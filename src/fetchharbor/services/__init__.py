from ..config import Settings
from .chat import definition as chat
from .html_to_md import definition as html_to_md
from .media import MEDIA_SERVICES, summary_definition
from .pdf_parse import definition as pdf_parse
from .scrape import definition as scrape

BUILTIN_SERVICES = (scrape, html_to_md, pdf_parse)


def configured_services(settings: Settings):
    services = list(BUILTIN_SERVICES)
    if settings.ollama_enabled:
        services.append(chat)
    if settings.media_enabled:
        services.extend(MEDIA_SERVICES)
        if settings.ollama_enabled:
            services.append(summary_definition)
    return tuple(services)
