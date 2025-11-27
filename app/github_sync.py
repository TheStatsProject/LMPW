import os
import re
import httpx
import yaml
from pathlib import Path
from datetime import datetime
from app.db import notes
from app.storage import store_asset

GITHUB_OWNER = os.environ.get("GITHUB_OWNER")
GITHUB_REPO = os.environ.get("GITHUB_REPO")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")  # optional but recommended
BASE_API = "https://api.github.com"

headers = {}
if GITHUB_TOKEN:
    headers["Authorization"] = f"token {GITHUB_TOKEN}"

ASSET_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf", ".zip", ".csv", ".mp4", ".mp3"}

class GitHubSyncError(Exception):
    """Custom exception for GitHub sync errors with actionable guidance."""
    pass


def _get_repo_tree(ref="main", path="notes"):
    url = f"{BASE_API}/repos/{GITHUB_OWNER}/{GITHUB_REPO}/git/trees/{ref}?recursive=1"
    try:
        r = httpx.get(url, headers=headers, timeout=30)
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        status_code = e.response.status_code
        if status_code == 401:
            raise GitHubSyncError(
                f"GitHub API returned 401 Unauthorized. "
                f"Please check that GITHUB_TOKEN is set and valid. "
                f"Ensure the token has 'repo' scope for private repositories."
            ) from e
        elif status_code == 403:
            owner_val = GITHUB_OWNER or "(not set)"
            repo_val = GITHUB_REPO or "(not set)"
            raise GitHubSyncError(
                f"GitHub API returned 403 Forbidden. "
                f"This may indicate rate limiting or insufficient permissions. "
                f"Check that GITHUB_TOKEN has appropriate scopes, or verify "
                f"the repository '{owner_val}/{repo_val}' is accessible."
            ) from e
        elif status_code == 404:
            owner_val = GITHUB_OWNER or "(not set)"
            repo_val = GITHUB_REPO or "(not set)"
            raise GitHubSyncError(
                f"GitHub API returned 404 Not Found. "
                f"Verify that GITHUB_OWNER ('{owner_val}') and "
                f"GITHUB_REPO ('{repo_val}') are correct, and that "
                f"the repository exists and is accessible with your token."
            ) from e
        else:
            raise GitHubSyncError(
                f"GitHub API request failed with status {status_code}: {e.response.text}"
            ) from e
    data = r.json()
    files = [item for item in data.get("tree", []) if item["type"] == "blob" and item["path"].startswith(path)]
    return files

def _fetch_raw(path, ref="main", as_bytes=False):
    raw_url = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{ref}/{path}"
    r = httpx.get(raw_url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.content if as_bytes else r.text

def parse_front_matter(text):
    if text.startswith("---"):
        try:
            parts = text.split("---", 2)
            _, yaml_block, content = parts
            meta = yaml.safe_load(yaml_block) or {}
            return meta, content.lstrip("\n")
        except Exception:
            return {}, text
    return {}, text

# find asset references like ![alt](assets/img.png) or [file](assets/data.csv)
ASSET_REF_RE = re.compile(r'!\[.*?\]\((?P<path>[^\)]+)\)|\[[^\]]+\]\((?P<path2>[^\)]+)\)')

def _collect_asset_paths(markdown_text, note_base_path):
    paths = set()
    for m in ASSET_REF_RE.finditer(markdown_text):
        path = m.group("path") or m.group("path2")
        if not path:
            continue
        # Only consider relative paths (no http://) or same-repo references
        if path.startswith("http://") or path.startswith("https://"):
            continue
        # Normalize to repo path
        normalized = str(Path(note_base_path) / Path(path)).replace("\\", "/")
        paths.add(normalized)
    return list(paths)

def compute_preview(content: str, meta: dict):
    # If preview_marker is provided, cut there
    marker = meta.get("preview_marker")
    if marker and marker in content:
        preview = content.split(marker, 1)[0].strip()
        return preview
    # Otherwise use preview_length (chars) if provided
    length = meta.get("preview_length")
    if length:
        try:
            n = int(length)
            return content[:n].rsplit("\n", 1)[0]  # don't cut right in the middle of line
        except Exception:
            pass
    # Default: first 400 chars
    return content[:400]

def sync_notes(ref="main", path="notes"):
    files = _get_repo_tree(ref=ref, path=path)
    for f in files:
        if not f["path"].lower().endswith(".md"):
            continue
        raw = _fetch_raw(f["path"], ref=ref)
        meta, content = parse_front_matter(raw)
        slug = meta.get("slug") or Path(f["path"]).stem
        note_base = str(Path(f["path"]).parent)
        # collect asset paths relative to the note's folder
        asset_paths = _collect_asset_paths(content, note_base)
        asset_map = {}
        for ap in asset_paths:
            # fetch asset as bytes and store in GridFS
            try:
                b = _fetch_raw(ap, ref=ref, as_bytes=True)
                fid = store_asset(ap, b)
                asset_map[ap] = fid
            except Exception:
                # skip missing asset but continue
                continue
        preview = compute_preview(content, meta)
        doc = {
            "slug": slug,
            "title": meta.get("title") or slug,
            "description": meta.get("description") or "",
            "tags": meta.get("tags") or [],
            "public": bool(meta.get("public", True)),
            "price_cents": int(meta.get("price_cents", 0)),
            "content": content,
            "preview": preview,
            "asset_map": asset_map,   # mapping repo/path -> gridfs id
            "path": f["path"],
            "updated_at": datetime.utcnow(),
        }
        notes.update_one({"slug": slug}, {"$set": doc}, upsert=True)
    return True
