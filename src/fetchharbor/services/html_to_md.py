from fastapi import APIRouter, Query
from markdownify import markdownify
from pydantic import BaseModel, Field

from ..registry import ServiceDefinition

router = APIRouter()


class HtmlRequest(BaseModel):
    html: str = Field(max_length=2_000_000)


def convert(html: str) -> dict:
    result = markdownify(html, heading_style="ATX").strip()
    return {
        "status": "success",
        "markdown": result,
        "character_count": len(result),
        "truncated": False,
    }


@router.get("/html-to-md", summary="html-to-md (GET)", operation_id="html_to_md_get")
async def html_to_md_get(html: str = Query(max_length=2_000_000)) -> dict:
    return convert(html)


@router.post("/html-to-md", summary="html-to-md (POST)", operation_id="html_to_md_post")
async def html_to_md_post(request: HtmlRequest) -> dict:
    return convert(request.html)


definition = ServiceDefinition(
    name="html-to-md",
    path="/html-to-md",
    price_usdc="0.005",
    description="Convert HTML into cleaned Markdown.",
    router=router,
    input_schema={
        "type": "object",
        "properties": {"html": {"type": "string"}},
        "required": ["html"],
        "additionalProperties": False,
    },
    input_example={"html": "<h1>Hello</h1>"},
    output_example={
        "status": "success",
        "markdown": "# Hello",
        "character_count": 7,
        "truncated": False,
    },
)
