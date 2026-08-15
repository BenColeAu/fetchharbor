FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN groupadd --system fetchharbor && useradd --system --gid fetchharbor --home /app fetchharbor
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir .
USER fetchharbor
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"
CMD ["uvicorn", "fetchharbor.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]

FROM runtime AS test
USER root
COPY tests ./tests
RUN pip install --no-cache-dir '.[test]'
CMD ["sh", "-c", "ruff check src tests && ruff format --check src tests && pytest -q"]
