import os
import uuid
import aiofiles
from fastapi import UploadFile

UPLOAD_DIR = "uploads"
BASE_URL = os.getenv("BASE_URL", "http://localhost")

async def save_file_locally(file: UploadFile, document_type: str) -> tuple[str, str]:
    folder = os.path.join(UPLOAD_DIR, document_type)
    os.makedirs(folder, exist_ok=True)
    original_name = file.filename or "unknown"
    extension = original_name.rsplit(".", 1)[-1].lower()
    unique_name = f"{uuid.uuid4().hex}.{extension}"
    storage_path = os.path.join(folder, unique_name)

    async with aiofiles.open(storage_path, "wb") as f:
        content = await file.read()
        await f.write(content)
    file_url = f"{BASE_URL}/uploads/{document_type}/{unique_name}"
    return storage_path, extension,file_url