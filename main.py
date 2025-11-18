import os
import io
from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse

from pydantic import BaseModel

from database import db, create_document, get_documents
from schemas import (
    WaitlistEntry, ContactMessage, AssessmentSubmission,
    CareerMatch, Roadmap, CareerTemplate, User
)

# Optional Google Sheets integration
GSPREAD_AVAILABLE = False
try:
    import gspread  # type: ignore
    from google.oauth2.service_account import Credentials  # type: ignore
    GSPREAD_AVAILABLE = True
except Exception:
    GSPREAD_AVAILABLE = False

# Optional PDF generation (ReportLab)
REPORTLAB_AVAILABLE = False
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import cm
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False

app = FastAPI(title="Pathify AI Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------- Helpers -----------------------------

def sheets_client():
    if not GSPREAD_AVAILABLE:
        return None
    service_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    if not service_json or not sheet_id:
        return None
    try:
        import json
        info = json.loads(service_json)
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_info(info, scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(sheet_id)
        return sh
    except Exception:
        return None


def append_waitlist_to_sheet(entry: WaitlistEntry) -> bool:
    sh = sheets_client()
    if not sh:
        return False
    try:
        ws = sh.sheet1
        ws.append_row([
            entry.name,
            entry.email,
            entry.instagram or "",
            entry.source or "website",
            datetime.utcnow().isoformat()
        ])
        return True
    except Exception:
        return False


# ----------------------------- Routes -----------------------------

@app.get("/")
def root():
    return {"app": "Pathify AI Backend", "status": "ok"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available" if db is None else "✅ Connected",
        "sheets": "✅ Enabled" if sheets_client() else "❌ Not Configured",
    }
    try:
        if db:
            response["collections"] = db.list_collection_names()
    except Exception as e:
        response["database"] = f"⚠️ {str(e)[:80]}"
    return response


# ---- Waitlist ----
@app.post("/api/waitlist")
def add_waitlist(entry: WaitlistEntry):
    doc_id = create_document("waitlistentry", entry)
    appended = append_waitlist_to_sheet(entry)
    return {"id": doc_id, "sheet": appended}


@app.get("/api/waitlist/stats")
def waitlist_stats():
    items = get_documents("waitlistentry", {}, limit=50)
    total = db["waitlistentry"].count_documents({}) if db else len(items)
    names = [i.get("name") for i in items][-10:][::-1]
    return {"total": total, "recent": names}


# ---- Contact ----
@app.post("/api/contact")
def contact(msg: ContactMessage):
    doc_id = create_document("contactmessage", msg)
    # Optional: also send to Google Sheets second tab
    sh = sheets_client()
    if sh:
        try:
            ws = sh.worksheet("Contact") if "Contact" in [w.title for w in sh.worksheets()] else sh.add_worksheet("Contact", 100, 10)
            ws.append_row([msg.name, msg.email, msg.message, datetime.utcnow().isoformat()])
        except Exception:
            pass
    return {"id": doc_id}


# ---- Assessment & AI Results ----

class AssessmentResult(BaseModel):
    matches: List[CareerMatch]
    preview_summary: Dict[str, Any]


CAREER_LIBRARY: Dict[str, Dict[str, Any]] = {
    "Software Engineer": {
        "skills": ["Data Structures", "Algorithms", "Python", "Git", "System Design"],
        "why": ["Strong analytical thinking", "Enjoys building things", "High demand across industries"],
    },
    "Data Scientist": {
        "skills": ["Statistics", "Python", "Pandas", "Machine Learning", "Visualization"],
        "why": ["Enjoys working with data", "Curiosity for patterns", "Growing AI ecosystem"],
    },
    "UI/UX Designer": {
        "skills": ["Figma", "User Research", "Prototyping", "Visual Design", "Accessibility"],
        "why": ["Creative problem solving", "Empathy for users", "Portfolio-driven growth"],
    },
    "Cybersecurity Analyst": {
        "skills": ["Network Basics", "Linux", "Threat Modeling", "SIEM", "Security+"],
        "why": ["Detail-oriented", "Protective mindset", "Rising threats -> demand"],
    },
    "Product Manager": {
        "skills": ["Communication", "Roadmapping", "User Stories", "Analytics", "Leadership"],
        "why": ["Cross-functional", "User + business focus", "High leverage role"],
    },
}


def score_careers(payload: AssessmentSubmission) -> List[CareerMatch]:
    # Simple heuristic for demo purposes
    interests = set([s.lower() for s in payload.interests])
    skills = set([s.lower() for s in payload.skills])
    personality = sum(payload.personality_answers) / max(len(payload.personality_answers), 1)

    results: List[CareerMatch] = []
    for career, meta in CAREER_LIBRARY.items():
        base = 50
        # interest-based boosts
        if "code" in interests or "programming" in interests or "software" in interests:
            if career == "Software Engineer":
                base += 25
        if "design" in interests:
            if career == "UI/UX Designer":
                base += 22
        if "data" in interests or "math" in interests:
            if career == "Data Scientist":
                base += 24
        if "security" in interests or "network" in interests:
            if career == "Cybersecurity Analyst":
                base += 20
        if "lead" in interests or "business" in interests:
            if career == "Product Manager":
                base += 18

        # skills overlap
        overlap = len(set([s.lower() for s in meta["skills"]]).intersection(skills))
        base += min(overlap * 6, 18)

        # personality tilt
        base += int((personality - 3) * 4)  # -8..+8 approx
        base = max(1, min(97, base))

        # build outputs
        gap = [s for s in meta["skills"] if s.lower() not in skills]
        salary = {"entry": 4.0, "mid": 12.0, "senior": 30.0}  # LPA example
        demand = {"current_index": base, "trend_6m": "+12%", "regions": ["India", "US", "Remote"]}

        match = CareerMatch(
            career=career,
            match_percent=base,
            why_match=meta["why"],
            strengths=list(skills)[:5],
            skill_gap=gap,
            salary_forecast=salary,
            demand_trends=demand,
        )
        results.append(match)

    results.sort(key=lambda m: m.match_percent, reverse=True)
    return results[:5]


@app.post("/api/assessment", response_model=AssessmentResult)
def run_assessment(payload: AssessmentSubmission):
    matches = score_careers(payload)
    summary = {
        "language": payload.language,
        "overview": "Assessment complete. Top matches generated based on interests, skills, and personality alignment.",
        "highlights": [
            f"Top Career: {matches[0].career}",
            f"Skill Gap Focus: {', '.join(matches[0].skill_gap[:5]) if matches[0].skill_gap else 'Minimal'}",
            "Steady market demand with positive 6M trend",
        ],
    }
    create_document("assessmentsubmission", payload)
    return AssessmentResult(matches=matches, preview_summary=summary)


# ---- Roadmap ----
@app.post("/api/roadmap", response_model=Roadmap)
def generate_roadmap(data: Dict[str, Any]):
    career = data.get("career", "Software Engineer")
    template = db["careertemplate"].find_one({"career": career}) if db else None

    if template:
        required = template.get("required_skills", [])
        roadmap = template.get("roadmap", {})
        summary = template.get("summary", f"Roadmap for {career}")
        actions = template.get("default_actions", [])
    else:
        required = CAREER_LIBRARY.get(career, CAREER_LIBRARY["Software Engineer"]) ["skills"]
        roadmap = {
            "Classes 8–10": ["Math foundations", "Intro to CS", "Logic puzzles", "Build small projects"],
            "Classes 11–12": ["Choose PCM", "Python + DSA basics", "Hackathons", "Git + GitHub"],
            "Graduation": ["Data Structures & Algorithms", "Internship", "System Design basics", "Open Source"],
            "Certifications": ["Coursera Specialization", "AWS Cloud Practitioner", "Security basics"],
            "Portfolio": ["3-5 polished projects", "README docs", "Case studies", "Personal website"],
        }
        summary = f"A clear, stage-wise pathway to become a {career}."
        actions = ["Complete DSA 150", "Build 2 real-world projects", "Internship hunt", "Leetcode 100"]

    return Roadmap(career=career, summary=summary, required_skills=required, roadmap=roadmap, actions=actions)


# ---- PDF ----
@app.post("/api/pdf")
def create_pdf(data: Dict[str, Any]):
    if not REPORTLAB_AVAILABLE:
        raise HTTPException(status_code=500, detail="PDF engine not available on server")

    career = data.get("career", "Career Roadmap")
    language = data.get("language", "en")
    roadmap: Dict[str, List[str]] = data.get("roadmap", {})
    summary: str = data.get("summary", "")

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # Header
    c.setFillColorRGB(0.14, 0.29, 1)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(2*cm, height - 2*cm, f"Pathify AI — {career} Roadmap ({'English' if language=='en' else 'Hindi'})")

    c.setFillColorRGB(0,0,0)
    c.setFont("Helvetica", 11)
    text = c.beginText(2*cm, height - 3.2*cm)
    text.textLines(summary[:600])
    c.drawText(text)

    y = height - 5*cm
    for section, items in roadmap.items():
        if y < 4*cm:
            c.showPage(); y = height - 3*cm
        c.setFont("Helvetica-Bold", 13)
        c.setFillColorRGB(0.26, 0.56, 0.44)  # green tint
        c.drawString(2*cm, y, section)
        y -= 0.6*cm
        c.setFont("Helvetica", 11)
        c.setFillColorRGB(0,0,0)
        for it in items:
            if y < 3*cm:
                c.showPage(); y = height - 3*cm
            c.drawString(2.5*cm, y, f"• {it}")
            y -= 0.5*cm
        y -= 0.4*cm

    c.showPage()
    c.save()
    buffer.seek(0)
    headers = {"Content-Disposition": f"attachment; filename={career.replace(' ', '_')}_roadmap.pdf"}
    return StreamingResponse(buffer, media_type="application/pdf", headers=headers)


# ---- Admin minimal ----
@app.post("/api/admin/templates")
def upsert_template(tpl: CareerTemplate):
    db["careertemplate"].update_one({"career": tpl.career}, {"$set": tpl.model_dump()}, upsert=True)
    return {"ok": True}

@app.get("/api/admin/templates")
def list_templates():
    return [
        {"career": d.get("career"), "summary": d.get("summary")}
        for d in get_documents("careertemplate")
    ]


# ---- Dashboards ----
@app.get("/api/student/{email}/overview")
def student_overview(email: str):
    saved = list(db["careertemplate"].find({}, {"career": 1, "_id": 0}))[:5] if db else []
    tasks = [
        {"title": "Complete DSA 50", "done": False},
        {"title": "Publish 1 project", "done": True},
        {"title": "Apply to 3 internships", "done": False},
    ]
    skills = [
        {"name": "Python", "level": 80},
        {"name": "DSA", "level": 60},
        {"name": "System Design", "level": 30},
    ]
    courses = [
        {"title": "Python for Everyone", "provider": "Coursera"},
        {"title": "Algo & DS", "provider": "Stanford"},
    ]
    return {"saved": saved, "tasks": tasks, "skills": skills, "courses": courses}


@app.get("/api/parent/{email}/overview")
def parent_overview(email: str):
    return {
        "student": email,
        "recommended": ["Software Engineer", "Data Scientist"],
        "progress": {"overall": 62, "last_week": "+6%"},
        "summaries": [
            {"career": "Software Engineer", "summary": "Strong fit with growing skills."},
            {"career": "Data Scientist", "summary": "Good analytical base; build statistics."},
        ]
    }


@app.get("/schema")
def schema_list():
    # For viewers/tools to introspect schemas
    return {
        "collections": [
            "user", "waitlistentry", "contactmessage", "assessmentsubmission", "careertemplate"
        ]
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
