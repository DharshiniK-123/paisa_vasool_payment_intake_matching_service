from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, NoReturn, cast

from fastapi import HTTPException
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field, ValidationError

from src.control.extraction.llm_client import get_llm, get_vision_llm
from src.control.extraction.prompts import INVOICE_EXTRACT_PROMPT, PAYMENT_EXTRACT_PROMPT

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS = 40_000
LLM_TIMEOUT_SECS = 120
MAX_RETRIES = 3


class InvoiceExtraction(BaseModel):
    mismatch: bool = Field(
        description="""true if this is NOT an invoice or 
                         critical data is unreadable, 
                         false if it is a valid invoice"""
    )
    detected_type: str | None = Field(
        default=None,
        description="""If mismatch=true: 
                                     what the document actually is — PAYMENT or UNKNOWN. 
                                     If mismatch=false: null""",
    )
    invoice_number: str | None = Field(
        default=None,
        description="""Invoice ID or number.
                                       null if mismatch=true""",
    )
    invoice_date: str | None = Field(
        default=None,
        description="""Invoice date in YYYY-MM-DD.
                                     null if mismatch=true""",
    )
    due_date: str | None = Field(
        default=None,
        description="""Due date in YYYY-MM-DD. 
                                If absent use invoice_date + 30 days. 
                                null if mismatch=true""",
    )
    total_amount: float | None = Field(
        default=None,
        description="""Final amount due as a number.
                                      null if mismatch=true""",
    )
    currency: str | None = Field(
        default=None,
        description="""3-letter code: INR, USD, EUR, GBP.
                                null if mismatch=true""",
    )
    customer_name: str | None = Field(default=None, description="Customer name or null")
    customer_email: str | None = Field(default=None, description="Customer email or null")
    gl_code: str | None = Field(default=None, description="GL code or null")


class PaymentExtraction(BaseModel):
    mismatch: bool = Field(
        description="""true if this is NOT a payment or 
                         critical data is unreadable, 
                         false if it is a valid payment"""
    )
    detected_type: str | None = Field(
        default=None,
        description="""If mismatch=true: 
                                  what the document actually is — INVOICE or UNKNOWN. 
                                  If mismatch=false: null""",
    )
    invoice_no: str | None = Field(
        default=None,
        description="""Invoice number(s) this payment is for. 
                               null if mismatch=true""",
    )
    payment_amount: float | None = Field(
        default=None,
        description="""Amount paid as a number.
                                       null if mismatch=true""",
    )
    paid_date: str | None = Field(
        default=None,
        description="""Payment date in YYYY-MM-DD. 
                                null if mismatch=true""",
    )
    payment_reference: str | None = Field(default=None, description="UTR/bank reference or null")
    currency: str | None = Field(
        default=None,
        description="""3-letter code: INR, USD, EUR, GBP. 
                             null if mismatch=true""",
    )
    customer_name: str | None = Field(default=None, description="Payer name or null")
    customer_email: str | None = Field(default=None, description="Payer email or null")


def _get_prompt_and_schema(document_type: str):
    if document_type == "INVOICE":
        return INVOICE_EXTRACT_PROMPT, InvoiceExtraction
    return PAYMENT_EXTRACT_PROMPT, PaymentExtraction


def _safe_json_parse(raw: str) -> dict | None:
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE)
    try:
        return cast(dict[Any, Any], json.loads(cleaned.strip()))
    except json.JSONDecodeError:
        return None


def _raise_mismatch(document_type: str, detected: str) -> None:
    raise HTTPException(
        status_code=422,
        detail=(
            f"Document mismatch: you selected '{document_type}' "
            f"but the file appears to be '{detected}'. "
            "Please re-upload the correct document."
        ),
    )


def _handle_llm_error(e: Exception, document_type: str) -> NoReturn:
    logger.error(
        "extraction_error",
        extra={
            "doc_type": document_type,
            "error_type": type(e).__name__,
            "detail": str(e),
        },
    )
    if isinstance(e, ValidationError):
        raise HTTPException(
            status_code=422,
            detail=f"""The uploaded {document_type.lower()} is missing required fields or 
            has invalid data.""",
        )
    if isinstance(e, (json.JSONDecodeError, ValueError)):
        raise HTTPException(
            status_code=422,
            detail="The document could not be parsed. Please verify the file and try again.",
        )
    raise HTTPException(
        status_code=500,
        detail="Document processing failed. Please try again.",
    )


def _is_transient(e: Exception) -> bool:
    transient_phrases = (
        "rate limit",
        "timeout",
        "503",
        "502",
        "504",
        "connection",
        "overloaded",
        "server_error",
        "service_unavailable",
    )
    return any(p in str(e).lower() for p in transient_phrases)


async def _invoke_with_retry(chain, input_value, retries: int = MAX_RETRIES):
    last_exc: Exception = RuntimeError("unreachable")
    for attempt in range(retries + 1):
        try:
            return await asyncio.wait_for(
                chain.ainvoke(input_value),
                timeout=LLM_TIMEOUT_SECS,
            )
        except TimeoutError:
            last_exc = TimeoutError(f"LLM timed out after {LLM_TIMEOUT_SECS}s")
            logger.warning("llm_timeout", extra={"attempt": attempt})
        except Exception as e:
            if attempt < retries and _is_transient(e):
                wait = 2**attempt
                logger.warning("llm_retry", extra={"attempt": attempt, "wait_secs": wait})
                await asyncio.sleep(wait)
                last_exc = e
            else:
                logger.error("llm_max_retries_exceeded", extra={"error": str(e)})
                raise
    raise last_exc


async def _extract_from_text(raw_text: str, document_type: str) -> dict:
    if len(raw_text) > MAX_TEXT_CHARS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Document is too large ({len(raw_text):,} chars). "
                f"Maximum allowed is {MAX_TEXT_CHARS:,}."
            ),
        )
    try:
        prompt, schema = _get_prompt_and_schema(document_type)
        llm = get_llm()
        structured_llm = llm.with_structured_output(schema)
        result: InvoiceExtraction | PaymentExtraction = await _invoke_with_retry(
            structured_llm,
            prompt.format(raw_text=raw_text),
        )

        if result.mismatch:
            _raise_mismatch(document_type, result.detected_type or "UNKNOWN")

        return result.model_dump(exclude={"mismatch", "detected_type"})

    except HTTPException:
        raise
    except Exception as e:
        _handle_llm_error(e, document_type)


async def _extract_from_image(image_content: dict, document_type: str) -> dict:
    try:
        _, schema = _get_prompt_and_schema(document_type)
        llm = get_vision_llm()

        schema_fields = "\n".join(
            f"- {name}: {field.description}"
            for name, field in schema.model_fields.items()
            if name not in ("mismatch", "detected_type")
        )

        data_url = f"data:{image_content['media_type']};base64,{image_content['data']}"
        message = HumanMessage(
            content=[
                {
                    "type": "image_url",
                    "image_url": {"url": data_url},
                },
                {
                    "type": "text",
                    "text": (
                        f"STEP 1: Determine if this document is a {document_type}.\n\n"
                        f"STEP 2a: If it is NOT a {document_type}, return ONLY valid JSON:\n"
                        f'{{"mismatch": true, "detected_type": "<PAYMENT|INVOICE|UNKNOWN>"}}\n\n'
                        f"STEP 2b: If it IS a {document_type}, extract the fields below and "
                        "return ONLY valid JSON "
                        f"with mismatch=false. "
                        "Do NOT invent values — use null for any absent optional field:\n"
                        f"{schema_fields}"
                    ),
                },
            ]
        )

        response = await _invoke_with_retry(llm, [message])
        parsed = _safe_json_parse(response.content)

        if parsed is None:
            raise HTTPException(
                status_code=422,
                detail="Could not read the document. "
                "Please ensure the image is clear and try again.",
            )

        if parsed.get("mismatch"):
            _raise_mismatch(document_type, parsed.get("detected_type") or "UNKNOWN")

        try:
            validated = schema(**parsed)
        except ValidationError as exc:
            logger.warning(
                "image_validation_failed",
                extra={"doc_type": document_type, "errors": exc.errors()},
            )
            raise HTTPException(
                status_code=422,
                detail=(
                    f"""The {document_type.lower()} 
                    image is missing critical fields or has unreadable data. """
                    "Please check the image and re-upload."
                ),
            ) from exc

        return cast(dict[Any, Any], validated.model_dump(exclude={"mismatch", "detected_type"}))

    except HTTPException:
        raise
    except Exception as e:
        _handle_llm_error(e, document_type)


async def run_extraction(content: str | dict, document_type: str) -> dict:
    try:
        if isinstance(content, dict):
            return await _extract_from_image(content, document_type)
        return await _extract_from_text(content, document_type)
    except HTTPException:
        raise
    except Exception as e:
        _handle_llm_error(e, document_type)
