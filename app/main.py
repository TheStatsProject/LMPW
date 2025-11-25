import os
from fastapi import FastAPI, HTTPException, Depends, Request, Header, Response
from fastapi.responses import PlainTextResponse, StreamingResponse, JSONResponse
from app.models import UserCreate
from app.auth import create_user, authenticate_user, create_jwt_token, get_current_user, decode_jwt_token, token_has_scope
from app.github_sync import sync_notes
from app.db import notes
from app.payments import create_checkout_for_note, STRIPE_KEY, STRIPE_WEBHOOK_SECRET, handle_webhook
from app.delivery import make_zip_for_note, generate_pdf_from_markdown
import stripe
import io

app = FastAPI(title="Notes API (Markdown only) - Enhanced")

@app.on_event("startup")
def startup_sync():
    owner = os.environ.get("GITHUB_OWNER")
    repo = os.environ.get("GITHUB_REPO")
    if owner and repo:
        try:
            sync_notes()
        except Exception:
            pass

@app.post("/register")
def register(user: UserCreate):
    create_user(user)
    return {"status": "ok"}

@app.post("/login")
def login(form: dict):
    username = form.get("username")
    password = form.get("password")
    user = authenticate_user(username, password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_jwt_token(user["username"], scopes=["session"], expires_minutes=60*24*7)
    return {"access_token": token, "token_type": "bearer"}

@app.get("/notes")
def list_notes():
    # list public notes (for unauthenticated) + metadata
    docs = list(notes.find({}, {"content": 0, "preview": 0}))
    for d in docs:
        d["_id"] = str(d["_id"])
    return docs

@app.get("/note/{slug}", response_class=PlainTextResponse)
def get_note(slug: str, authorization: str = Header(None), access_token: str = None):
    """
    Returns full markdown if user authorized (subscription or purchase).
    Accepts:
     - Authorization: Bearer <session-token> (user with is_subscribed True)
     - Authorization: Bearer <scoped-token> (scoped download token)
     - or ?access_token=<token> as query param
    """
    doc = notes.find_one({"slug": slug})
    if not doc:
        raise HTTPException(404, "Not found")
    # free public note
    if doc.get("public", True) and doc.get("price_cents", 0) == 0:
        return PlainTextResponse(doc["content"], media_type="text/markdown")
    # check tokens
    token = None
    if access_token:
        token = access_token
    elif authorization:
        try:
            scheme, tok = authorization.split()
            token = tok
        except Exception:
            token = None
    if token:
        payload = None
        try:
            payload = decode_jwt_token(token)
        except Exception:
            pass
        if payload:
            # check if scope matches download:note:<slug> or global subscriber
            if token_has_scope(payload, f"download:note:{slug}") or token_has_scope(payload, "subscribe:all"):
                return PlainTextResponse(doc["content"], media_type="text/markdown")
            # try session scenario: subject is username; check DB
            subject = payload.get("sub")
            if subject:
                from app.db import users
                u = users.find_one({"username": subject})
                if u and u.get("is_subscribed"):
                    return PlainTextResponse(doc["content"], media_type="text/markdown")
    raise HTTPException(403, "Access denied")

@app.get("/note/{slug}/preview", response_class=PlainTextResponse)
def get_note_preview(slug: str):
    doc = notes.find_one({"slug": slug})
    if not doc:
        raise HTTPException(404, "Not found")
    return PlainTextResponse(doc.get("preview", doc["content"][:400]), media_type="text/markdown")

@app.post("/note/{slug}/download_zip")
def download_zip(slug: str, authorization: str = Header(None), access_token: str = None):
    # Guard similar to get_note; only allow for authorized tokens
    # Return a streaming zip file
    # Accept either session token (subscribed) or scoped token
    # The token handling reuses previous logic
    from app.main import get_note  # avoid circular import in some contexts
    # reuse get_note to validate access -- but we will not fetch content there; instead replicate token check:
    doc = notes.find_one({"slug": slug})
    if not doc:
        raise HTTPException(404, "Not found")
    token = None
    if access_token:
        token = access_token
    elif authorization:
        try:
            scheme, tok = authorization.split()
            token = tok
        except Exception:
            token = None
    allowed = False
    if token:
        try:
            payload = decode_jwt_token(token)
            if token_has_scope(payload, f"download:note:{slug}") or token_has_scope(payload, "subscribe:all"):
                allowed = True
            else:
                # maybe session user
                subject = payload.get("sub")
                if subject:
                    from app.db import users
                    u = users.find_one({"username": subject})
                    if u and u.get("is_subscribed"):
                        allowed = True
        except Exception:
            allowed = False
    if not allowed:
        raise HTTPException(403, "Access denied")
    zip_bytes = make_zip_for_note(slug)
    return StreamingResponse(io.BytesIO(zip_bytes), media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{slug}.zip"'
    })

@app.get("/note/{slug}/pdf")
def note_pdf(slug: str, authorization: str = Header(None), access_token: str = None):
    # Similar access checks
    token = access_token
    if authorization and not token:
        try:
            _, token = authorization.split()
        except Exception:
            token = None
    if not token:
        raise HTTPException(401, "Missing token")
    try:
        payload = decode_jwt_token(token)
    except Exception:
        raise HTTPException(401, "Invalid token")
    if not (token_has_scope(payload, f"download:note:{slug}") or token_has_scope(payload, "subscribe:all")):
        # try session
        subject = payload.get("sub")
        if subject:
            from app.db import users
            u = users.find_one({"username": subject})
            if not (u and u.get("is_subscribed")):
                raise HTTPException(403, "Access denied")
        else:
            raise HTTPException(403, "Access denied")
    pdf_bytes = generate_pdf_from_markdown(slug)
    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{slug}.pdf"'
    })

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
        raise HTTPException(status_code=400, detail=f"Webhook error: {str(e)}")

# admin sync
@app.post("/admin/sync")
def admin_sync(secret: str = ""):
    if secret != os.environ.get("ADMIN_SYNC_SECRET"):
        raise HTTPException(403, "Forbidden")
    sync_notes()
    return {"ok": True}
