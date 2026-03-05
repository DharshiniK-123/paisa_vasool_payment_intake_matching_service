import json
import logging
import re
from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError
from typing import Optional
from langchain_core.messages import HumanMessage
from src.control.extraction.llm_client import get_llm, get_vision_llm
from src.control.extraction.prompts import INVOICE_EXTRACT_PROMPT, PAYMENT_EXTRACT_PROMPT



class InvoiceExtraction(BaseModel):
    invoice_number: str           = Field(description="Invoice ID or number")
    invoice_date:   str           = Field(description="Invoice date in YYYY-MM-DD format")
    due_date:       str           = Field(description="Due date in YYYY-MM-DD. If missing, invoice_date + 30 days")
    total_amount:   float         = Field(description="Final amount due as a number")
    currency:       str           = Field(description="3-letter currency code: INR, USD, EUR, GBP")
    customer_name:  Optional[str] = Field(default=None, description="Customer name or null")
    customer_email: Optional[str] = Field(default=None, description="Customer email or null")
    gl_code:        Optional[str] = Field(default=None, description="GL code or null")


class PaymentExtraction(BaseModel):
    invoice_no:        str           = Field(description="Invoice number this payment is for")
    payment_amount:    float         = Field(description="Amount paid as a number")
    paid_date:         str           = Field(description="Payment date in YYYY-MM-DD format")
    payment_reference: Optional[str] = Field(default=None, description="UTR/bank reference or null")
    currency:          str           = Field(description="3-letter currency code: INR, USD, EUR, GBP")
    customer_name:     Optional[str] = Field(default=None, description="Payer name or null")
    customer_email:    Optional[str] = Field(default=None, description="Payer email or null")


def _get_prompt_and_schema(document_type: str):
    if document_type == "INVOICE":
        return INVOICE_EXTRACT_PROMPT, InvoiceExtraction
    return PAYMENT_EXTRACT_PROMPT, PaymentExtraction


def _check_mismatch(parsed: dict, document_type: str) -> None:
    if parsed and parsed.get("mismatch"):
        detected = parsed.get("detected_type", "UNKNOWN")
        raise HTTPException(
            status_code=422,
            detail=f"Document mismatch. You selected '{document_type}' "
                   f"but uploaded file appears to be '{detected}'. "
                   f"Please re-upload the correct document."
        )


def _handle_llm_error(e: Exception, document_type: str) -> None:
    logging.error(f"{document_type} extraction error: {repr(e)}")

    if isinstance(e, ValidationError):
        raise HTTPException(
            status_code=422,
            detail=f"The uploaded {document_type.lower()} is missing required fields or contains invalid data."
        )

    if isinstance(e, json.JSONDecodeError):
        raise HTTPException(
            status_code=422,
            detail="The document could not be parsed properly. Please check the file and try again."
        )

    if isinstance(e, ValueError):
        raise HTTPException(
            status_code=422,
            detail="The document contains invalid values. Please verify the data and try again."
        )

    raise HTTPException(
        status_code=500,
        detail="Document processing failed. Please try again."
    )

async def _extract_from_text(raw_text: str, document_type: str) -> dict:
    try:
        llm = get_llm()
        prompt, schema = _get_prompt_and_schema(document_type)
        response = await llm.ainvoke(prompt.format(raw_text=raw_text))
        try:
            raw    = response.content.strip().strip("```json").strip("```").strip()
            parsed = json.loads(raw)
        except Exception:
            parsed = None
        _check_mismatch(parsed, document_type)
        structured_llm = llm.with_structured_output(schema)
        result = await structured_llm.ainvoke(prompt.format(raw_text=raw_text))
        return result.model_dump()

    except HTTPException:
        raise
    except Exception as e:
        _handle_llm_error(e, document_type)


async def _extract_from_image(image_content: dict, document_type: str) -> dict:
    try:
        llm = get_vision_llm()
        _, schema = _get_prompt_and_schema(document_type)

        schema_fields = "\n".join(
            f"- {name}: {field.description}"
            for name, field in schema.model_fields.items()
        )
        data_url = f"data:{image_content['media_type']};base64,{image_content['data']}"
        message = HumanMessage(content=[
            {
                "type": "image_url",
                "image_url": {"url": data_url},
            },
            {
                "type": "text",
                "text": (
                    f"STEP 1: Check if this is a {document_type}. "
                    f"If NOT, return ONLY: {{\"mismatch\": true, \"detected_type\": \"<actual type>\"}}\n\n"
                    f"STEP 2: If it IS a {document_type}, extract these fields "
                    f"and return ONLY valid JSON, no explanation:\n{schema_fields}"
                ),
            }
        ])
        response = await llm.ainvoke([message])
        try:
            raw    = response.content.strip().strip("```json").strip("```").strip()
            parsed = json.loads(raw)
        except Exception:
            raise HTTPException(status_code=422,detail="Could not read the document. ""Please ensure the image is clear and try again.")
        _check_mismatch(parsed, document_type)
        try:
            validated = schema(**parsed)
            return validated.model_dump()
        except Exception:
            raise HTTPException(status_code=422,detail=f"The uploaded {document_type.lower()} image is missing critical fields or contains unreadable data. "f"Please check the image and re-upload.")
    except HTTPException:
        raise
    except Exception as e:
        _handle_llm_error(e, document_type)


async def run_extraction(content: str | dict, document_type: str) -> dict:
    try:
        if isinstance(content, dict):
            return await _extract_from_image(content, document_type)
        else:
            return await _extract_from_text(content, document_type)
    except HTTPException:
        raise
    except Exception as e:
        _handle_llm_error(e, document_type)


async def run_extraction_batch(text: str, document_type: str) -> list[dict]:
    try:
        llm = get_llm()
        prompt = f"""
            Extract ALL rows from this {document_type} data and return a JSON array.
            Each element should have the same fields as a single {document_type} record.
            Return ONLY a JSON array, no explanation.
            Data:
            {text}
            """
        response = await llm.ainvoke(prompt)
        try:
            clean  = re.sub(r"```json|```", "", response.content).strip()
            parsed = json.loads(clean)
        except json.JSONDecodeError:
            raise HTTPException(status_code=422,detail="Could not parse the batch document. ""Please check the file format and try again.")
        if not isinstance(parsed, list):
            raise HTTPException(status_code=422,detail="Unexpected format in batch document. ""Please ensure each row is a valid record and try again.")
        if not parsed:
            raise HTTPException(status_code=422,detail="No records could be extracted from the document. ""Please check the file content and try again.")
        return parsed
    except HTTPException:
        raise
    except Exception as e:
        _handle_llm_error(e, document_type)