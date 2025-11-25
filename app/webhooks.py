"""
GitHub webhook receiver for repository -> notes sync.

Improvements and project-specific behavior:
- Verifies HMAC signature for both sha256 (X-Hub-Signature-256) and legacy sha1 (X-Hub-Signature).
- Validates the webhook's repository matches configured GITHUB_OWNER / GITHUB_REPO to avoid cross-repo triggers.
- Inspects push payload commits and only triggers a sync when files under the configured notes path (default "notes/") changed.
- Uses FastAPI BackgroundTasks to run sync_notes() asynchronously and logs failures.
- Adds a basic in-process cooldown per (repo, branch) to avoid repeated sync spam from multiple quick pushes.
- Returns appropriate HTTP statuses:
  - 202 Accepted when a background sync is scheduled
  - 200 OK when webhook received but no relevant changes found
  - 400/403/503 for errors
Notes:
- The cooldown is an in-memory heuristic (WEBHOOK_SYNC_COOLDOWN_SECONDS). In multi-worker deployments this won't coordinate across processes.
  For production, replace with a distributed lock (Redis or Mongo).
- sync_notes is invoked with ref=branch and path=notes_path; it still performs a repo-tree scan. If you later add an API to sync only specific files, adapt the call.
"""

import os
import hmac
import hashlib
import logging
import time
from typing import Optional, Iterable, List

from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, status
from fastapi.responses import JSONResponse

from app.github_sync import sync_notes

logger = logging.getLogger(__name__)
router = APIRouter()

# Configuration from environment
GITHUB_WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET")
GITHUB_OWNER = os.environ.get("GITHUB_OWNER")
GITHUB_REPO = os.environ.get("GITHUB_REPO")
NOTES_PATH = os.environ.get("NOTES_PATH", "notes/").lstrip("/")  # normalized to "notes/" or "some/path/"
WEBHOOK_SYNC_COOLDOWN_SECONDS = int(os.environ.get("WEBHOOK_SYNC_COOLDOWN_SECONDS", "10"))

# Simple in-process cooldown map: key -> last_scheduled_ts
# Note: not shared across processes/workers.
_LAST_SYNC: dict = {}


def _compute_hmac_hex(secret: bytes, body: bytes, algo: str) -> str:
    """
    Compute HMAC hex digest for the given algorithm ('sha1' or 'sha256').
    """
    if algo == "sha1":
        mac = hmac.new(secret, msg=body, digestmod=hashlib.sha1)
    else:
        mac = hmac.new(secret, msg=body, digestmod=hashlib.sha256)
    return mac.hexdigest()


def verify_github_signature(secret: str, body: bytes, signature_header: Optional[str]) -> bool:
    """
    Verify GitHub signature header. Accepts either "sha256=..." or "sha1=...".
    Uses hmac.compare_digest for timing-safe comparison.
    """
    if not secret:
        logger.error("No GITHUB_WEBHOOK_SECRET configured")
        return False
    if not signature_header:
        logger.warning("Missing signature header")
        return False
    try:
        prefix, hexsig = signature_header.split("=", 1)
    except Exception:
        logger.warning("Malformed signature header: %s", signature_header)
        return False
    algo = prefix.lower()
    if algo not in ("sha1", "sha256"):
        logger.warning("Unsupported signature algorithm: %s", algo)
        return False
    computed = _compute_hmac_hex(secret.encode("utf-8"), body, algo)
    try:
        return hmac.compare_digest(computed, hexsig)
    except Exception:
        return computed == hexsig


def _paths_intersect_notes(changed_paths: Iterable[str], notes_prefix: str) -> List[str]:
    """
    Return list of changed paths that fall under the notes_prefix (posix-style).
    Notes_prefix should be 'notes/' or 'folder/sub/' etc.
    This is a conservative check: we normalize and check startswith(notes_prefix).
    """
    hits = []
    # Ensure prefix ends with a slash for correct startswith checks
    prefix = notes_prefix if notes_prefix.endswith("/") else notes_prefix + "/"
    for p in changed_paths:
        if not p:
            continue
        norm = p.replace("\\", "/").lstrip("/")
        if norm.startswith(prefix) or prefix.startswith(norm):  # also catch case where prefix is file folder and p equals folder
            hits.append(norm)
    return hits


def _cooldown_allows(repo: str, branch: Optional[str]) -> bool:
    """
    Simple cooldown logic keyed by repo + branch to avoid scheduling syncs frequently.
    """
    key = f"{repo}:{branch or 'main'}"
    now = time.time()
    last = _LAST_SYNC.get(key)
    if last and (now - last) < WEBHOOK_SYNC_COOLDOWN_SECONDS:
        logger.info("Cooldown active for %s (last=%s, now=%s) skipping scheduling", key, last, now)
        return False
    _LAST_SYNC[key] = now
    return True


async def _background_sync(branch: Optional[str], path: str = NOTES_PATH):
    """
    Run sync_notes in background and capture exceptions for logging.
    """
    try:
        logger.info("Background sync starting for branch=%s path=%s", branch or "main", path)
        sync_notes(ref=branch or "main", path=path)
        logger.info("Background sync finished for branch=%s", branch or "main")
    except Exception as exc:
        logger.exception("Background sync failed for branch=%s: %s", branch or "main", exc)


@router.post("/github/webhook")
async def github_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    GitHub webhook endpoint (push events).

    - Verifies signature (X-Hub-Signature-256 or X-Hub-Signature)
    - Validates repository matches configured GITHUB_OWNER/GITHUB_REPO (if configured)
    - Inspects commit file lists and triggers background sync only if files under NOTES_PATH changed
    - Applies a short in-process cooldown to avoid repeated syncs
    """
    if not GITHUB_WEBHOOK_SECRET:
        logger.error("GITHUB_WEBHOOK_SECRET not configured")
        raise HTTPException(status_code=503, detail="Webhook secret not configured")

    body = await request.body()

    # Accept either header; be case-insensitive by using get()
    signature = request.headers.get("X-Hub-Signature-256") or request.headers.get("X-Hub-Signature")
    if not signature:
        logger.warning("No signature header present")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing signature header")

    if not verify_github_signature(GITHUB_WEBHOOK_SECRET, body, signature):
        logger.warning("Signature verification failed")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid signature")

    # Parse payload as JSON
    try:
        payload = await request.json()
    except Exception as exc:
        logger.warning("Failed to parse JSON payload: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON payload")

    event = request.headers.get("X-GitHub-Event", "unknown")
    delivery = request.headers.get("X-GitHub-Delivery")
    logger.info("Received GitHub event=%s delivery=%s", event, delivery)

    # Validate repository, if configured
    repo_full_name = payload.get("repository", {}).get("full_name") if isinstance(payload.get("repository"), dict) else None
    if GITHUB_OWNER and GITHUB_REPO:
        expected = f"{GITHUB_OWNER}/{GITHUB_REPO}"
        if repo_full_name and repo_full_name.lower() != expected.lower():
            logger.warning("Repository mismatch in webhook: got=%s expected=%s", repo_full_name, expected)
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Repository mismatch")

    # Handle push events: inspect changed files and schedule sync only if notes files changed
    if event == "push":
        commits = payload.get("commits", [])
        changed = set()
        for c in commits:
            for k in ("added", "modified", "removed"):
                entries = c.get(k, [])
                for p in entries:
                    changed.add(p.replace("\\", "/").lstrip("/"))

        # If no commits (rare), fall back to scheduling a full sync for the branch
        if not changed:
            ref = payload.get("ref")
            branch = None
            if ref:
                ref = ref
                # compute branch name like "main" from "refs/heads/main"
                if isinstance(ref, str) and ref.startswith("refs/heads/"):
                    branch = ref.split("refs/heads/", 1)[1]
            # Respect cooldown
            repo_id = repo_full_name or f"{GITHUB_OWNER}/{GITHUB_REPO}"
            if not _cooldown_allows(repo_id, branch):
                return JSONResponse({"ok": True, "event": event, "scheduled": False, "reason": "cooldown"}, status_code=status.HTTP_200_OK)
            background_tasks.add_task(_background_sync, branch, NOTES_PATH)
            logger.info("Scheduled background sync (no commit paths available) for branch=%s", branch or "main")
            return JSONResponse({"ok": True, "event": event, "scheduled": True, "branch": branch}, status_code=status.HTTP_202_ACCEPTED)

        # Filter changed paths for notes path
        touched = _paths_intersect_notes(changed, NOTES_PATH)
        if not touched:
            logger.info("Push did not change notes (changed_files_count=%d). No sync scheduled.", len(changed))
            return JSONResponse({"ok": True, "event": event, "scheduled": False, "changed_files": len(changed)}, status_code=status.HTTP_200_OK)

        # Extract branch from ref
        ref = payload.get("ref")
        branch = None
        if isinstance(ref, str) and ref.startswith("refs/heads/"):
            branch = ref.split("refs/heads/", 1)[1]

        repo_id = repo_full_name or f"{GITHUB_OWNER}/{GITHUB_REPO}"
        if not _cooldown_allows(repo_id, branch):
            logger.info("Cooldown prevented scheduling sync for branch=%s", branch or "main")
            return JSONResponse({"ok": True, "event": event, "scheduled": False, "reason": "cooldown"}, status_code=status.HTTP_200_OK)

        # Schedule background sync
        logger.info("Scheduling background sync for branch=%s path=%s touched_files=%s", branch or "main", NOTES_PATH, touched)
        background_tasks.add_task(_background_sync, branch, NOTES_PATH)
        return JSONResponse({"ok": True, "event": event, "scheduled": True, "branch": branch, "touched_files": touched}, status_code=status.HTTP_202_ACCEPTED)

    # Respond to ping so setup testers succeed
    if event == "ping":
        logger.info("Received ping for repo=%s", repo_full_name)
        return JSONResponse({"ok": True, "event": "ping"}, status_code=status.HTTP_200_OK)

    # Other events: acknowledge but no action
    logger.info("Received unsupported event %s; no action taken", event)
    return JSONResponse({"ok": True, "event": event, "scheduled": False}, status_code=status.HTTP_200_OK)
