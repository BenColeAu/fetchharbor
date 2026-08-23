from io import BytesIO
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, HttpUrl
from pypdf import PdfReader

from ..config import get_settings
from ..registry import ServiceDefinition
from .scrape import fetch_bytes

router = APIRouter()


class PdfRequest(BaseModel):
    url: HttpUrl


def parse_pdf(data: bytes) -> dict:
    try:
        reader = PdfReader(BytesIO(data))
        pages = [(page.extract_text() or "") for page in reader.pages]
    except Exception as exc:
        raise HTTPException(422, "Invalid or unsupported PDF") from exc
    text = "\n\n".join(pages)
    return {
        "status": "success",
        "text": text,
        "page_count": len(pages),
        "character_count": len(text),
    }


async def download(url: str) -> bytes:
    _, data = await fetch_bytes(url)
    return data


PDF_ERRORS = {
    400: {"description": "No PDF URL or file was supplied."},
    402: {"description": "A valid x402 payment is required."},
    413: {"description": "The PDF exceeds the configured download limit."},
    422: {"description": "The PDF is invalid, encrypted, or unsupported."},
    502: {"description": "The remote PDF could not be retrieved."},
    504: {"description": "The remote PDF request timed out."},
}


@router.get(
    "/pdf-parse",
    summary="pdf-parse (GET)",
    operation_id="pdf_parse_get",
    responses=PDF_ERRORS,
)
async def pdf_get(url: str = Query()) -> dict:
    return parse_pdf(await download(url))


@router.post(
    "/pdf-parse",
    summary="pdf-parse (POST)",
    operation_id="pdf_parse_post",
    responses=PDF_ERRORS,
)
async def pdf_post(
    url: Annotated[str | None, Query()] = None,
    form_url: Annotated[str | None, Form(alias="url")] = None,
    file: Annotated[UploadFile | None, File()] = None,
) -> dict:
    selected_url = url or form_url
    if selected_url:
        return parse_pdf(await download(selected_url))
    if file:
        data = await file.read(get_settings().max_download_bytes + 1)
        if len(data) > get_settings().max_download_bytes:
            raise HTTPException(413, "PDF is too large")
        return parse_pdf(data)
    raise HTTPException(400, "Provide either url or file")


definition = ServiceDefinition(
    name="pdf-parse",
    path="/pdf-parse",
    price_usdc="0.01",
    description=(
        "Extract embedded text from a public PDF URL or multipart upload for "
        "research and retrieval pipelines. Returns text, page count, and character "
        "count; scanned-image OCR is not included. Remote and uploaded PDFs are "
        "limited to the operator-configured maximum size."
    ),
    router=router,
    input_schema={
        "type": "object",
        "properties": {"url": {"type": "string", "format": "uri"}},
    },
    input_example={"url": "https://example.com/document.pdf"},
    method_input_schemas={
        "GET": {
            "type": "object",
            "properties": {"url": {"type": "string", "format": "uri"}},
            "required": ["url"],
            "additionalProperties": False,
        },
        "POST": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "format": "uri"},
                "file": {"type": "string", "format": "binary"},
            },
            "anyOf": [{"required": ["url"]}, {"required": ["file"]}],
            "additionalProperties": False,
        },
    },
    body_types={"POST": "form-data"},
    output_example={
        "status": "success",
        "text": "...",
        "page_count": 1,
        "character_count": 3,
    },
    output_schema={
        "type": "object",
        "properties": {
            "status": {"type": "string", "const": "success"},
            "text": {"type": "string"},
            "page_count": {"type": "integer", "minimum": 0},
            "character_count": {"type": "integer", "minimum": 0},
        },
        "required": ["status", "text", "page_count", "character_count"],
        "additionalProperties": False,
    },
)
