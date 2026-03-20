import pandas as pd
import pymupdf4llm
from fastapi import HTTPException
import base64
from google.cloud import storage
import tempfile
import os
from google.cloud import storage as gcs

SUPPORTED_IMAGE_TYPES = {"jpg", "jpeg", "png", "gif", "webp"}
BUCKET_NAME = os.getenv("GCS_BUCKET")
 
def _download_from_gcs(storage_path: str, suffix: str = None) -> str:
    if suffix is None:
        suffix = storage_path.rsplit(".", 1)[-1].lower()
    
    try:
        client = gcs.Client()
        bucket = client.bucket(BUCKET_NAME)
        blob = bucket.blob(storage_path)

        tmp = tempfile.NamedTemporaryFile(suffix=f".{suffix}", delete=False)
        blob.download_to_file(tmp)
        tmp.flush()
        tmp.close()
        
        return tmp.name
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Failed to download file from GCS: {str(e)}")

def extract_from_pdf(storage_path: str) -> str:
    try:
        text = pymupdf4llm.to_markdown(storage_path)
        if not text or not text.strip():
            raise HTTPException(status_code=422, detail="PDF appears to be empty or scanned. Only text-based PDFs are supported")
        return text
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"PDF extraction failed")


def extract_from_image(storage_path: str, file_type: str, file_url: str = None) -> dict:
    media_type_map = {
        "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "png": "image/png", "gif": "image/gif", "webp": "image/webp",
    }
    try:
        with open(storage_path, "rb") as f:
            encoded = base64.standard_b64encode(f.read()).decode("utf-8")
        if not encoded:
            raise HTTPException(status_code=422, detail="Image file appears to be empty")
        return {
            "type": "base64",
            "media_type": media_type_map[file_type.lower()],
            "data": encoded,
        }
    except HTTPException:
        raise
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Image file not found: {storage_path}")
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Image extraction failed")
    
    
def extract_from_csv(storage_path: str) -> pd.DataFrame:
    try:
        df = pd.read_csv(storage_path)
        df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
        df = df.dropna(how="all")
        return df
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"CSV extraction failed")


def extract_from_excel(storage_path: str) -> pd.DataFrame:
    try:
        df = pd.read_excel(storage_path, engine="openpyxl")
        df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
        df = df.dropna(how="all")
        return df
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Excel extraction failed")


def extract_text(storage_path: str, file_type: str, file_url: str = None) -> dict:
    file_type = file_type.lower()
    suffix = storage_path.rsplit(".", 1)[-1].lower()
    local_path = _download_from_gcs(storage_path,suffix)
    if file_type == "pdf":
        return extract_from_pdf(local_path)
    elif file_type == "csv":
        return extract_from_csv(local_path)
    elif file_type in ("xlsx", "xls"):
        return extract_from_excel(local_path)
    elif file_type in SUPPORTED_IMAGE_TYPES:
        if not file_url:
            raise HTTPException(status_code=422, detail="Image URL is required but was not provided")
        return extract_from_image(local_path, file_type, file_url)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file_type}")