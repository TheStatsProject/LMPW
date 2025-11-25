import os
from fastapi import HTTPException
import stripe
from app.db import subscriptions, users, notes
from app.auth import create_jwt_token
from app.delivery import make_zip_for_note, send_bytes_via_email
from datetime import datetime, timedelta

STRIPE_KEY = os.environ.get("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
DOMAIN = os.environ.get("PAYMENT_SUCCESS_RETURN_URL") or "https://example.com/payment-success"
EMAIL_ON_PURCHASE = os.environ.get("EMAIL_ON_PURCHASE", "true").lower() in ("1", "true", "yes")

if STRIPE_KEY:
    stripe.api_key = STRIPE_KEY
else:
    stripe = None

def create_checkout_for_note(user_email: str, note_slug: str, price_cents: int, success_url=None, cancel_url=None):
    if stripe is None:
        raise HTTPException(status_code=503, detail="Payments not configured")
    success_url = success_url or f"{DOMAIN}?status=success&session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = cancel_url or f"{DOMAIN}?status=cancel"
    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {"name": f"Access to note {note_slug}"},
                "unit_amount": price_cents,
            },
            "quantity": 1,
        }],
        mode="payment",
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"note_slug": note_slug, "buyer_email": user_email},
    )
    return session

def _create_access_token_for_purchase(email: str, note_slug: str, expires_days=14):
    subject = email
    scopes = [f"download:note:{note_slug}"]
    token = create_jwt_token(subject, scopes=scopes, expires_minutes=expires_days * 24 * 60)
    return token

def handle_webhook(event):
    if event["type"] == "checkout.session.completed":
        sess = event["data"]["object"]
        buyer_email = sess.get("customer_details", {}).get("email") or sess.get("metadata", {}).get("buyer_email")
        note_slug = sess.get("metadata", {}).get("note_slug")
        subscriptions.insert_one({
            "email": buyer_email,
            "note_slug": note_slug,
            "stripe_session_id": sess.get("id"),
            "status": "paid",
            "purchased_at": datetime.utcnow()
        })
        if buyer_email:
            users.update_one({"email": buyer_email}, {"$set": {"is_subscribed": True}})
        # create an access token specific to this purchase
        token = _create_access_token_for_purchase(buyer_email, note_slug)
        # Optionally deliver a ZIP by email
        if EMAIL_ON_PURCHASE:
            try:
                zip_bytes = make_zip_for_note(note_slug)
                send_bytes_via_email(buyer_email, f"Your purchase: {note_slug}", "Attached is your purchased content.", zip_bytes, f"{note_slug}.zip", mime_type="application/zip")
            except Exception:
                # best-effort: don't fail webhook
                pass
        return {"token": token}
    return {}
