from __future__ import annotations

import asyncio
import base64
import logging
import os
import tempfile

import pandas as pd
import pymupdf4llm
from fastapi import HTTPException
from google.cloud import storage as gcs
from src.config.settings import settings

logger = logging.getLogger(__name__)

SUPPORTED_IMAGE_TYPES = {"jpg", "jpeg", "png", "webp"}
BUCKET_NAME = settings.GCS_BUCKET


def _download_from_gcs(storage_path: str, suffix: str | None = None) -> str:
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
        logger.exception("gcs_download_failed", extra={"path": storage_path})
        raise HTTPException(status_code=422, detail=f"Failed to download file from GCS: {e}") from e




def _extract_pages_from_pdf_sync(storage_path: str) -> list[str]:
    """Extract text per page from a PDF. Returns a list of non-empty page texts."""
    try:
        import pymupdf 

        doc = pymupdf.open(storage_path)
        pages = []
        for page in doc:
            md = pymupdf4llm.to_markdown(storage_path, pages=[page.number])
            if md and md.strip():
                pages.append(md.strip())
        doc.close()

        if not pages:
            raise HTTPException(
                status_code=422,
                detail="PDF appears to be empty or scanned. Only text-based PDFs are supported",
            )
        return pages
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("pdf_pages_extraction_failed", extra={"path": storage_path})
        raise HTTPException(status_code=422, detail="PDF extraction failed") from e


def _extract_from_image_sync(storage_path: str, file_type: str) -> dict:
    media_type_map = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp",
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
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"Image file not found: {storage_path}") from e
    except Exception as e:
        logger.exception("image_extraction_failed", extra={"path": storage_path})
        raise HTTPException(status_code=422, detail="Image extraction failed") from e


def _extract_from_csv_sync(storage_path: str) -> pd.DataFrame:
    try:
        df = pd.read_csv(storage_path)
        df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
        df = df.dropna(how="all")
        return df
    except Exception as e:
        logger.exception("csv_extraction_failed", extra={"path": storage_path})
        raise HTTPException(status_code=422, detail="CSV extraction failed") from e


def _extract_from_excel_sync(storage_path: str) -> pd.DataFrame:
    try:
        df = pd.read_excel(storage_path, engine="openpyxl")
        df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")
        df = df.dropna(how="all")
        return df
    except Exception as e:
        logger.exception("excel_extraction_failed", extra={"path": storage_path})
        raise HTTPException(status_code=422, detail="Excel extraction failed") from e


async def parse_text(storage_path: str, file_type: str, file_url: str | None = None):
    """
    Download the file from GCS then extract its content.
    CPU/IO-bound sync extractors are offloaded via asyncio.to_thread()
    so the event loop is never blocked.
    """
    file_type = file_type.lower()
    suffix = storage_path.rsplit(".", 1)[-1].lower()
    local_path = await asyncio.to_thread(_download_from_gcs, storage_path, suffix)

    if file_type == "pdf":
        return await asyncio.to_thread(_extract_pages_from_pdf_sync, local_path)
    elif file_type == "csv":
        return await asyncio.to_thread(_extract_from_csv_sync, local_path)
    elif file_type in ("xlsx", "xls"):
        return await asyncio.to_thread(_extract_from_excel_sync, local_path)
    elif file_type in SUPPORTED_IMAGE_TYPES:
        if not file_url:
            raise HTTPException(
                status_code=422, detail="Image URL is required but was not provided"
            )

        return await asyncio.to_thread(_extract_from_image_sync, local_path, file_type)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file_type}")