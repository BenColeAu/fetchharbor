from io import BytesIO

import httpx
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, HttpUrl
from pypdf import PdfReader

from ..config import get_settings
from ..registry import ServiceDefinition
from .scrape import _validate_public_url

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
    return {"status": "success", "text": text, "page_count": len(pages), "character_count": len(text)}


async def download(url: str) -> bytes:
    _validate_public_url(url)
    settings = get_settings()
    async with httpx.AsyncClient(follow_redirects=True, timeout=settings.request_timeout_seconds) as client:
        response = await client.get(url)
        response.raise_for_status()
    if len(response.content) > settings.max_download_bytes:
        raise HTTPException(413, "PDF is too large")
    return response.content


@router.get("/pdf-parse")
async def pdf_get(url: str = Query()) -> dict:
    return parse_pdf(await download(url))


@router.post("/pdf-parse")
async def pdf_post(url: str | None = Query(default=None), file: UploadFile | None = File(default=None)) -> dict:
    if url:
        return parse_pdf(await download(url))
    if file:
        data = await file.read(get_settings().max_download_bytes + 1)
        if len(data) > get_settings().max_download_bytes:
            raise HTTPException(413, "PDF is too large")
        return parse_pdf(data)
    raise HTTPException(400, "Provide either url or file")


definition = ServiceDefinition(
    name="pdf-parse", path="/pdf-parse", price_usdc="0.01", description="Extract text from a PDF URL or upload.", router=router,
    input_schema={"type": "object", "properties": {"url": {"type": "string", "format": "uri"}}},
    output_example={"status": "success", "text": "...", "page_count": 1, "character_count": 3},
)

