import io
import zipfile
import os
import smtplib
from email.message import EmailMessage
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from app.storage import get_asset_bytes  # get_asset_bytes is defined in storage.py
from app.db import notes, subscriptions, users
from gridfs import GridFS
from pymongo import MongoClient
import markdown2

# Email settings (configure in env)
EMAIL_HOST = os.environ.get("EMAIL_HOST")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT") or 587)
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASS = os.environ.get("EMAIL_PASS")
EMAIL_FROM = os.environ.get("EMAIL_FROM") or EMAIL_USER

def make_zip_for_note(slug: str):
    doc = notes.find_one({"slug": slug})
    if not doc:
        raise FileNotFoundError("Note not found")
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        mdname = f"{slug}.md"
        zf.writestr(mdname, doc["content"])
        # write assets
        for repo_path, fid in (doc.get("asset_map") or {}).items():
            try:
                asset_bytes, ctype = get_asset_bytes(fid)
                filename = os.path.basename(repo_path)
                zf.writestr(filename, asset_bytes)
            except Exception:
                continue
    mem.seek(0)
    return mem.read()

def send_bytes_via_email(to_email: str, subject: str, body: str, attachment_bytes: bytes, attachment_name: str, mime_type="application/zip"):
    if not EMAIL_HOST or not EMAIL_USER or not EMAIL_PASS:
        raise RuntimeError("Email not configured")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = to_email
    msg.set_content(body)
    msg.add_attachment(attachment_bytes, maintype=mime_type.split("/")[0], subtype=mime_type.split("/")[1], filename=attachment_name)
    with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as s:
        s.starttls()
        s.login(EMAIL_USER, EMAIL_PASS)
        s.send_message(msg)
    return True

def generate_pdf_from_markdown(slug: str):
    """
    Basic PDF generator using ReportLab.
    This is a simple converter: it converts markdown to text and writes paragraphs.
    For richer layout you can replace with a HTML->PDF pipeline if you accept extra system deps.
    """
    doc = notes.find_one({"slug": slug})
    if not doc:
        raise FileNotFoundError("Note not found")
    text = markdown2.markdown(doc["content"], extras=["fenced-code-blocks", "strike", "tables"])
    # Convert markdown2 output to plain text by stripping tags roughly
    # (This is intentionally simple to avoid HTML rendering in this prototype)
    import re
    plain = re.sub(r'<[^>]+>', '', text)
    # Create PDF in memory
    packet = io.BytesIO()
    c = canvas.Canvas(packet, pagesize=letter)
    width, height = letter
    margin = 40
    y = height - margin
    lines = plain.splitlines()
    for line in lines:
        if y < margin + 20:
            c.showPage()
            y = height - margin
        # naive wrapping
        for chunk in [line[i:i+90] for i in range(0, len(line), 90)]:
            c.drawString(margin, y, chunk)
            y -= 12
    c.save()
    packet.seek(0)
    return packet.read()
