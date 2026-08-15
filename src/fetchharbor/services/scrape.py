import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, HttpUrl

from ..config import get_settings
from ..registry import ServiceDefinition

router = APIRouter()


class ScrapeRequest(BaseModel):
    url: HttpUrl


def _validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(400, "Only HTTP(S) URLs are supported")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443)
    except socket.gaierror as exc:
        raise HTTPException(400, "Hostname could not be resolved") from exc
    if any(
        ipaddress.ip_address(item[4][0]).is_private
        or ipaddress.ip_address(item[4][0]).is_loopback
        or ipaddress.ip_address(item[4][0]).is_link_local
        for item in addresses
    ):
        raise HTTPException(400, "Private and local network targets are blocked")


async def fetch_bytes(url: str) -> tuple[httpx.Response, bytes]:
    settings = get_settings()
    current_url = url
    try:
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=settings.request_timeout_seconds,
            proxy=settings.outbound_proxy_url or None,
            trust_env=False,
        ) as client:
            for _ in range(6):
                _validate_public_url(current_url)
                async with client.stream(
                    "GET", current_url, headers={"User-Agent": "FetchHarbor/0.1"}
                ) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise HTTPException(502, "Remote redirect has no location")
                        current_url = urljoin(str(response.url), location)
                        continue
                    if response.is_error:
                        raise HTTPException(
                            502, f"Remote server returned HTTP {response.status_code}"
                        )
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > settings.max_download_bytes:
                            raise HTTPException(413, "Remote response is too large")
                    break
            else:
                raise HTTPException(508, "Too many remote redirects")
    except httpx.TimeoutException as exc:
        raise HTTPException(504, "Remote request timed out") from exc
    except httpx.RequestError as exc:
        raise HTTPException(502, "Remote request failed") from exc
    return response, bytes(body)


async def fetch(url: str) -> dict:
    response, raw = await fetch_bytes(url)
    text = raw.decode(response.encoding or "utf-8", errors="replace")
    return {
        "status": "success",
        "url": str(response.url),
        "status_code": response.status_code,
        "content_type": response.headers.get("content-type"),
        "content": text,
    }


@router.get("/scrape")
async def scrape_get(url: str = Query()) -> dict:
    return await fetch(url)


@router.post("/scrape")
async def scrape_post(request: ScrapeRequest) -> dict:
    return await fetch(str(request.url))


definition = ServiceDefinition(
    name="scrape",
    path="/scrape",
    price_usdc="0.01",
    description="Fetch a public URL and return its content.",
    router=router,
    input_schema={
        "type": "object",
        "properties": {"url": {"type": "string", "format": "uri"}},
        "required": ["url"],
        "additionalProperties": False,
    },
    output_example={
        "status": "success",
        "url": "https://example.com",
        "status_code": 200,
        "content": "...",
    },
)
