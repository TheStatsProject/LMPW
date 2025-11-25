import os
from datetime import datetime, timedelta
from passlib.context import CryptContext
from jose import jwt, JWTError
from fastapi import HTTPException, Header
from app.db import users, db
from pymongo.errors import DuplicateKeyError

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
JWT_SECRET = os.environ.get("SESSION_SECRET_KEY") or "dev-secret"
JWT_ALGO = "HS256"

# token lifetimes
SESSION_EXPIRES_MIN = 60*24*7  # 7 days for login tokens
ACCESS_EXPIRES_MIN = 60*24*14  # 14 days for purchased-resource tokens

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_user(user):
    doc = {
        "username": user.username,
        "email": user.email,
        "password_hash": hash_password(user.password),
        "created_at": datetime.utcnow(),
        "role": "user",
        "is_subscribed": False,
    }
    try:
        users.create_index("username", unique=True)
        users.create_index("email", unique=True)
        users.insert_one(doc)
        del doc["password_hash"]
        return doc
    except DuplicateKeyError:
        raise HTTPException(status_code=400, detail="User or email already exists")

def authenticate_user(username_or_email: str, password: str):
    doc = users.find_one({"$or": [{"username": username_or_email}, {"email": username_or_email}]})
    if not doc:
        return None
    if not verify_password(password, doc["password_hash"]):
        return None
    return doc

def create_jwt_token(subject: str, scopes: list = None, expires_minutes: int = ACCESS_EXPIRES_MIN):
    now = datetime.utcnow()
    payload = {"sub": subject, "scopes": scopes or [], "iat": now, "exp": now + timedelta(minutes=expires_minutes)}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)

def decode_jwt_token(token: str):
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

def get_current_user(authorization: str = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    try:
        scheme, token = authorization.split()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Authorization header")
    if scheme.lower() != "bearer":
        raise HTTPException(status_code=400, detail="Invalid scheme")
    payload = decode_jwt_token(token)
    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    u = users.find_one({"username": username})
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    return u

def token_has_scope(token_payload: dict, required_scope: str):
    scopes = token_payload.get("scopes") or []
    return required_scope in scopes
