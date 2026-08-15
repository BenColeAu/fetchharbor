from .html_to_md import definition as html_to_md
from .pdf_parse import definition as pdf_parse
from .scrape import definition as scrape

BUILTIN_SERVICES = (scrape, html_to_md, pdf_parse)
