# app/storage.py (replace existing)
from typing import Tuple
from bson import ObjectId
from app.db import get_gridfs  # or import fs from app.db after init_db
fs = get_gridfs()

def store_asset(path: str, content: bytes, content_type: str = "application/octet-stream"):
    fid = fs.put(content, filename=path, metadata={"path": path, "content_type": content_type})
    return fid

def get_asset_bytes(file_id) -> Tuple[bytes, str]:
    grid_out = fs.get(file_id)
    ctype = None
    if getattr(grid_out, "metadata", None):
        ctype = grid_out.metadata.get("content_type")
    return grid_out.read(), ctype or "application/octet-stream"
