import hashlib
import os

from google.cloud import storage
from src.config.settings import settings
client = storage.Client()

BUCKET_NAME = settings.GCS_BUCKET
BASE_FOLDER = settings.GCS_FOLDER


async def save_file(file, document_type: str):
    if not BUCKET_NAME:
        raise ValueError("GCS_BUCKET not configured")

    doc_type = document_type.lower()
    if doc_type == "invoice":
        doc_type = "invoices"
    elif doc_type == "payment":
        doc_type = "payments"
    else:
        raise ValueError(f"Invalid document_type: {document_type}")

    filename = file.filename or "file"
    ext = filename.split(".")[-1] if "." in filename else "bin"

    content = await file.read()
    file_hash = hashlib.md5(content).hexdigest()

    file_path = f"{BASE_FOLDER}/{doc_type}/{file_hash}.{ext}"
    file_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{file_path}"

    bucket = client.bucket(BUCKET_NAME)
    blob = bucket.blob(file_path)

    if not blob.exists():
        blob.upload_from_string(
            content,
            content_type=file.content_type or "application/octet-stream",
        )

    return file_path, ext, file_url, file_hash