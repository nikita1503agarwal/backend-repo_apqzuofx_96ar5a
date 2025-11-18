"""
Database Schemas

Define your MongoDB collection schemas here using Pydantic models.
These schemas are used for data validation in your application.

Each Pydantic model represents a collection in your database.
Model name is converted to lowercase for the collection name:
- User -> "user" collection
- Product -> "product" collection
- BlogPost -> "blogs" collection
"""

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Dict, Any

# Core user types
class User(BaseModel):
    name: str = Field(..., description="Full name")
    email: EmailStr = Field(..., description="Email address")
    role: str = Field("student", description="user | student | parent | admin")
    instagram: Optional[str] = None

class WaitlistEntry(BaseModel):
    name: str = Field(..., description="Full Name")
    email: EmailStr = Field(..., description="Gmail Address")
    instagram: Optional[str] = Field(None, description="Instagram ID")
    source: Optional[str] = Field("website", description="Where the user signed up from")

class ContactMessage(BaseModel):
    name: str
    email: EmailStr
    message: str

class AssessmentSubmission(BaseModel):
    academic_performance: str
    interests: List[str]
    skills: List[str]
    preferences: List[str]
    personality_answers: List[int] = Field(..., description="Array of 10–15 integers 1–5")
    uploaded_docs: Optional[List[str]] = Field(default=None, description="Filenames uploaded")
    language: str = Field("en", description="en | hi")

class CareerMatch(BaseModel):
    career: str
    match_percent: int
    why_match: List[str]
    strengths: List[str]
    skill_gap: List[str]
    salary_forecast: Dict[str, Any]
    demand_trends: Dict[str, Any]

class Roadmap(BaseModel):
    career: str
    summary: str
    required_skills: List[str]
    roadmap: Dict[str, List[str]]
    actions: List[str]

class CareerTemplate(BaseModel):
    career: str
    summary: str
    required_skills: List[str]
    roadmap: Dict[str, List[str]]
    default_actions: List[str]
    prompts: Optional[Dict[str, str]] = None
