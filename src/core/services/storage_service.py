from google.cloud import storage
import uuid
import os

client = storage.Client()

BUCKET_NAME = os.getenv("GCS_BUCKET")
BASE_FOLDER = os.getenv("GCS_FOLDER", "paisavasool")

async def save_file(file, document_type: str):
    try:

        if not BUCKET_NAME:
            raise ValueError("GCS_BUCKET not configured")

        doc_type = document_type.lower()

        if doc_type == "invoice":
            doc_type = "invoices"
        elif doc_type == "payment":
            doc_type = "payments"
        else:
            raise ValueError(f"Invalid document_type: {document_type}")


        bucket = client.bucket(BUCKET_NAME)

        filename = file.filename or "file"
        ext = filename.split(".")[-1] if "." in filename else "bin"

        file_path = f"{BASE_FOLDER}/{doc_type}/{uuid.uuid4().hex}.{ext}"

        blob = bucket.blob(file_path)

        content = await file.read()

        blob.upload_from_string(
            content,
            content_type=file.content_type or "application/octet-stream"
        )

        return file_path, ext, f"https://storage.googleapis.com/{BUCKET_NAME}/{file_path}"

    except Exception as e:
        raise
