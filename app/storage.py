import io
from pymongo import MongoClient
from gridfs import GridFS
import os
from dotenv import load_dotenv

load_dotenv()
MONGO_URL = os.environ.get("MONGO_URL") or os.environ.get("MONGO_URI")
if not MONGO_URL:
    raise RuntimeError("MONGO_URL env var is required")

client = MongoClient(MONGO_URL)
db = client.get_default_database()
fs = GridFS(db)

def store_asset(path: str, content: bytes, content_type: str = "application/octet-stream"):
    """
    Store asset bytes into GridFS and return the file id.
    If an asset with the same filename/path exists we still store new copy.
    """
    metadata = {"path": path, "content_type": content_type}
    fid = fs.put(content, filename=path, **metadata)
    return fid

def get_asset_bytes(file_id):
    grid_out = fs.get(file_id)
    return grid_out.read(), grid_out.content_type or "application/octet-stream"
