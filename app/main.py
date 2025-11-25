"""
Improved main FastAPI application wiring that matches the Mongo user shape you provided.

Key changes and goals:
- Registration accepts name / email / password / age / hobbies and stores them in Mongo.
- JWT "sub" uses the Mongo ObjectId (string) as canonical subject.
- Token decoding looks up users by _id (ObjectId) or by email fallback.
- get_current_user logic implemented here (instead of relying on an auth.get_current_user that assumed "username").
- Responses avoid returning password hashes.
- Notes endpoints reuse existing sync / delivery functionality but use the new token lookup behavior.
"""

import os
import io
import logging
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Header, Request, Depends
from fastapi.responses import PlainTextResponse, StreamingResponse, JSONResponse
from bson import ObjectId
from bson.errors import InvalidId

from app.models import UserCreate, UserPublic
from app.db import users, notes, subscriptions, init_db, health_check as db_health_check
from app.auth import hash_password, verify_password, create_jwt_token, decode_jwt_token, token_has_scope
from app.github_sync import sync_notes
from app.delivery import make_zip_for_note, generate_pdf_from_markdown
from app.payments import create_checkout_for_note, STRIPE_KEY, STRIPE_WEBHOOK_SECRET, handle_webhook
from app.webhooks import router as github_webhook_router
import stripe
import io as _io

logger = logging.getLogger("app.main")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

app = FastAPI(title="Notes API (Markdown only) - Improved User Model")

# Include the GitHub webhook router
app.include_router(github_webhook_router)


# ---- Health Check Endpoints ----
@app.get("/health")
def health():
    """Health check endpoint for deployment platforms."""
    return {"status": "ok"}


@app.get("/health/db")
def health_db():
    """Database health check endpoint."""
    if db_health_check():
        return {"status": "ok", "database": "connected"}
    return JSONResponse(
        status_code=503,
        content={"status": "error", "database": "disconnected"}
    )


# ---- Helper functions ----
def _user_doc_to_public(doc: dict) -> dict:
    return {
        "id": str(doc.get("_id")),
        "name": doc.get("name"),
        "email": doc.get("email"),
        "age": doc.get("age"),
        "hobbies": doc.get("hobbies") or [],
        "created_at": doc.get("created_at"),
    }

def _get_token_from_header(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            return None
        return token
    except Exception:
        return None

def get_user_by_token(token: str):
    """
    Decode token and return the user document (or raise HTTPException).
    Token 'sub' is expected to be the user's ObjectId (string).
    We also accept tokens that contain an 'email' claim and will attempt to find user by email.
    """
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    payload = decode_jwt_token(token)
    sub = payload.get("sub")
    email = payload.get("email")
    user_doc = None
    if sub:
        try:
            oid = ObjectId(sub)
            user_doc = users.find_one({"_id": oid})
        except (InvalidId, Exception):
            user_doc = None
    if not user_doc and email:
        user_doc = users.find_one({"email": email})
    if not user_doc:
        raise HTTPException(status_code=401, detail="User not found for token")
    return user_doc, payload

def require_user(authorization: Optional[str] = Header(None)):
    token = _get_token_from_header(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    user_doc, payload = get_user_by_token(token)
    return user_doc

# ---- Startup events ----
@app.on_event("startup")
def startup():
    # Initialize database connection
    try:
        init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.warning("Database initialization failed: %s (will retry on first request)", e)
    
    # Sync notes from GitHub if configured
    owner = os.environ.get("GITHUB_OWNER")
    repo = os.environ.get("GITHUB_REPO")
    if owner and repo:
        try:
            sync_notes()
        except Exception as e:
            logger.exception("Initial sync failed: %s", e)

# ---- Auth / user endpoints ----
@app.post("/register", status_code=201)
def register(user: UserCreate):
    """
    Register a new user. Stores:
      { name, email, password_hash, age, hobbies, created_at }
    """
    # Basic validation / unique email check
    if users.find_one({"email": user.email}):
        raise HTTPException(status_code=400, detail="Email already registered")

    password_hash = hash_password(user.password)
    doc = {
        "name": user.name,
        "email": user.email,
        "password_hash": password_hash,
        "age": user.age,
        "hobbies": user.hobbies or [],
        "created_at": datetime.utcnow(),
        # role / subscription flags can be added here
        "role": "user",
        "is_subscribed": False,
    }
    res = users.insert_one(doc)
    new_doc = users.find_one({"_id": res.inserted_id})
    return _user_doc_to_public(new_doc)

@app.post("/login")
def login(form: dict):
    """
    Login with {"email": "...", "password":"..."}
    Returns an access token whose `sub` is the user's ObjectId (string).
    """
    email = form.get("email")
    password = form.get("password")
    if not email or not password:
        raise HTTPException(status_code=400, detail="Email and password required")

    user_doc = users.find_one({"email": email})
    if not user_doc:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not verify_password(password, user_doc.get("password_hash")):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    subject = str(user_doc.get("_id"))
    # include email in token to support other token types that may set subject differently
    token = create_jwt_token(subject, scopes=["session"], expires_minutes=60 * 24 * 7)
    return {"access_token": token, "token_type": "bearer", "user": _user_doc_to_public(user_doc)}

@app.get("/me")
def me(current_user: dict = Depends(require_user)):
    return _user_doc_to_public(current_user)

# ---- Notes endpoints (simplified access control using token subject / scopes) ----
@app.get("/notes")
def list_notes():
    docs = list(notes.find({}, {"content": 0}))
    out = []
    for d in docs:
        out.append({
            "slug": d.get("slug"),
            "title": d.get("title"),
            "description": d.get("description"),
            "tags": d.get("tags", []),
            "public": bool(d.get("public", True)),
            "price_cents": int(d.get("price_cents", 0)),
            "updated_at": d.get("updated_at"),
        })
    return out

def _token_allows_access(payload: dict, slug: str) -> bool:
    # scoped token check
    if token_has_scope(payload, f"download:note:{slug}") or token_has_scope(payload, "subscribe:all"):
        return True
    return False

@app.get("/note/{slug}", response_class=PlainTextResponse)
def get_note(slug: str, authorization: Optional[str] = Header(None), access_token: Optional[str] = None):
    doc = notes.find_one({"slug": slug})
    if not doc:
        raise HTTPException(status_code=404, detail="Note not found")

    # Free & public
    if doc.get("public", True) and int(doc.get("price_cents", 0)) == 0:
        return PlainTextResponse(doc["content"], media_type="text/markdown")

    # Resolve token (from header or query)
    token = access_token or _get_token_from_header(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required for this note")

    try:
        payload = decode_jwt_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

    # scoped check
    if _token_allows_access(payload, slug):
        return PlainTextResponse(doc["content"], media_type="text/markdown")

    # session-based check: subject is ObjectId
    sub = payload.get("sub")
    if sub:
        try:
            user_doc = users.find_one({"_id": ObjectId(sub)})
            if user_doc and user_doc.get("is_subscribed"):
                return PlainTextResponse(doc["content"], media_type="text/markdown")
        except Exception:
            pass

    # If not allowed, but note has price, return checkout URL info (client should open it)
    price = int(doc.get("price_cents", 0))
    if price > 0 and STRIPE_KEY:
        # If we have a session token for a user, create a checkout session
        # Prefer using subject/email from payload to identify buyer
        buyer_email = payload.get("email")
        if not buyer_email and sub:
            # try to fetch user
            try:
                u = users.find_one({"_id": ObjectId(sub)})
                buyer_email = u.get("email") if u else None
            except Exception:
                buyer_email = None
        if not buyer_email:
            raise HTTPException(status_code=403, detail="Purchase requires authenticated user with email")
        session = create_checkout_for_note(user_email=buyer_email, note_slug=slug, price_cents=price)
        return JSONResponse({"checkout_url": session.url, "session_id": session.id})

    raise HTTPException(status_code=403, detail="Access denied")

@app.get("/note/{slug}/preview", response_class=PlainTextResponse)
def get_note_preview(slug: str):
    doc = notes.find_one({"slug": slug})
    if not doc:
        raise HTTPException(status_code=404, detail="Note not found")
    return PlainTextResponse(doc.get("preview", doc.get("content", "")[:400]), media_type="text/markdown")

@app.post("/note/{slug}/download_zip")
def download_zip(slug: str, authorization: Optional[str] = Header(None), access_token: Optional[str] = None):
    # Validate access with similar logic to get_note
    doc = notes.find_one({"slug": slug})
    if not doc:
        raise HTTPException(status_code=404, detail="Note not found")

    token = access_token or _get_token_from_header(authorization)
    allowed = False
    if token:
        try:
            payload = decode_jwt_token(token)
            if _token_allows_access(payload, slug):
                allowed = True
            else:
                sub = payload.get("sub")
                if sub:
                    u = users.find_one({"_id": ObjectId(sub)})
                    if u and u.get("is_subscribed"):
                        allowed = True
        except Exception:
            allowed = False
    if not allowed:
        raise HTTPException(status_code=403, detail="Access denied")

    zip_bytes = make_zip_for_note(slug)
    return StreamingResponse(_io.BytesIO(zip_bytes), media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{slug}.zip"'
    })

@app.get("/note/{slug}/pdf")
def note_pdf(slug: str, authorization: Optional[str] = Header(None), access_token: Optional[str] = None):
    token = access_token or _get_token_from_header(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        payload = decode_jwt_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
    # allow if scoped or subscribed
    if not (_token_allows_access(payload, slug) or (payload.get("sub") and users.find_one({"_id": ObjectId(payload.get("sub")), "is_subscribed": True} ))):
        raise HTTPException(status_code=403, detail="Access denied")
    pdf_bytes = generate_pdf_from_markdown(slug)
    return StreamingResponse(_io.BytesIO(pdf_bytes), media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{slug}.pdf"'
    })

# Stripe webhook endpoint (keeps behavior from payments.handle_webhook)
@app.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    if not STRIPE_KEY or not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Payments not configured")
    payload = await request.body()
    sig = request.headers.get("stripe-signature")
    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
        result = handle_webhook(event)
        return JSONResponse(result)
    except Exception as e:
        logger.exception("Stripe webhook handling error: %s", e)
        raise HTTPException(status_code=400, detail=f"Webhook error: {str(e)}")

# Admin sync route
@app.post("/admin/sync")
def admin_sync(secret: str = ""):
    if secret != os.environ.get("ADMIN_SYNC_SECRET"):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        sync_notes()
        return {"ok": True}
    except Exception as e:
        logger.exception("Manual sync failed: %s", e)
        raise HTTPException(status_code=500, detail="Sync failed")
