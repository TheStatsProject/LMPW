from pydantic import BaseModel, field_validator
from typing import List, Optional
from datetime import datetime
import re

# Email validation regex pattern
EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')

class UserCreate(BaseModel):
    """
    Payload used when registering a new user.

    Fields intentionally match the MongoDB document structure you showed:
    - name: full name
    - email: contact email (unique)
    - password: plaintext (will be hashed before storing)
    - age: optional integer
    - hobbies: optional list of strings
    """
    name: str
    email: str
    password: str
    age: Optional[int] = None
    hobbies: Optional[List[str]] = None

    @field_validator('email')
    @classmethod
    def validate_email(cls, v: str) -> str:
        if not EMAIL_REGEX.match(v):
            raise ValueError('Invalid email address')
        return v.lower()

class UserPublic(BaseModel):
    """
    Public user representation returned by the API (no password hash).
    """
    id: str
    name: str
    email: str
    age: Optional[int] = None
    hobbies: Optional[List[str]] = None
    created_at: Optional[datetime] = None
