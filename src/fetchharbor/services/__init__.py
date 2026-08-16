from ..config import Settings
from .chat import definition as chat
from .html_to_md import definition as html_to_md
from .pdf_parse import definition as pdf_parse
from .scrape import definition as scrape

BUILTIN_SERVICES = (scrape, html_to_md, pdf_parse)


def configured_services(settings: Settings):
    if settings.ollama_enabled:
        return (*BUILTIN_SERVICES, chat)
    return BUILTIN_SERVICES
