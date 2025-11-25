from pydantic import BaseModel, EmailStr
from typing import List, Optional
from datetime import datetime

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
    email: EmailStr
    password: str
    age: Optional[int] = None
    hobbies: Optional[List[str]] = None

class UserPublic(BaseModel):
    """
    Public user representation returned by the API (no password hash).
    """
    id: str
    name: str
    email: EmailStr
    age: Optional[int] = None
    hobbies: Optional[List[str]] = None
    created_at: Optional[datetime] = None
