FROM python:3.12-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
RUN apt-get update \
    && apt-get upgrade --yes --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd --system fetchharbor \
    && useradd --system --gid fetchharbor --home /app fetchharbor \
    && install -d -o fetchharbor -g fetchharbor /app/data
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m pip install --no-cache-dir --upgrade 'pip>=26.1.2,<27' 'setuptools>=78.1.1' \
    && pip install --no-cache-dir . \
    && rm -rf \
        /usr/local/lib/python3.12/site-packages/msgpack-1.1.2.dist-info \
        /usr/local/lib/python3.12/site-packages/setuptools-70.3.0.dist-info \
    && pip uninstall --yes pip setuptools
USER fetchharbor
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD python -c "import os, urllib.request; host=os.environ.get('FETCHHARBOR_ALLOWED_HOSTS','localhost').split(',')[0].strip(); request=urllib.request.Request('http://127.0.0.1:8080/health/ready', headers={'Host':host}); urllib.request.urlopen(request, timeout=3)"
CMD ["uvicorn", "fetchharbor.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]

FROM runtime AS test
USER root
COPY tests ./tests
COPY compose.production.yaml ./compose.production.yaml
COPY deploy/egress-proxy/squid.conf ./deploy/egress-proxy/squid.conf
RUN find src tests -type f -exec chmod a-x {} +
RUN python -m ensurepip --upgrade \
    && python -m pip install --no-cache-dir --upgrade 'pip>=26.1.2,<27' 'setuptools>=78.1.1' \
    && pip install --no-cache-dir '.[test]'
CMD ["sh", "-c", "ruff check src tests && ruff format --check src tests && pytest -q"]
