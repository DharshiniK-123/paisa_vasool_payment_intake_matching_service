import hashlib

from google.cloud import storage
from src.config.settings import settings

client = storage.Client()

BUCKET_NAME = settings.GCS_BUCKET
BASE_FOLDER = settings.GCS_FOLDER


async def save_file(file, document_type) -> tuple[str, str, str, str]:
    if not BUCKET_NAME:
        raise ValueError("GCS_BUCKET not configured")

    doc_type_str = document_type.value.lower() if hasattr(document_type, "value") else str(document_type).lower()

    if doc_type_str == "invoice":
        folder = "invoices"
    elif doc_type_str == "payment":
        folder = "payments"
    else:
        folder = "pending" 
        
    filename = file.filename or "file"
    ext = filename.split(".")[-1] if "." in filename else "bin"

    content = await file.read()
    file_hash = hashlib.md5(content).hexdigest()

    file_path = f"{BASE_FOLDER}/{folder}/{file_hash}.{ext}"
    file_url = f"https://storage.googleapis.com/{BUCKET_NAME}/{file_path}"

    bucket = client.bucket(BUCKET_NAME)
    blob = bucket.blob(file_path)
    try:
        if not blob.exists():
            blob.upload_from_string(
                content,
                content_type=file.content_type or "application/octet-stream",
            )
    except Exception as e:
        raise

    return file_path, ext, file_url, file_hash