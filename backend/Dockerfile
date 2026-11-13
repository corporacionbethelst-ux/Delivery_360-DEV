# syntax=docker/dockerfile:1
FROM python:3.11-slim AS dependencies
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN python -m venv /opt/venv
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt
COPY . .

FROM python:3.11-slim AS production
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH=/opt/venv/bin:$PATH
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client netcat-openbsd \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home app \
    && mkdir -p /app/uploads && chown app:app /app/uploads
WORKDIR /app
RUN --mount=type=bind,from=dependencies,source=/opt/venv,target=/tmp/runtime-venv \
    --mount=type=bind,from=dependencies,source=/app,target=/tmp/runtime-app \
    cp -a /tmp/runtime-venv /opt/venv \
    && cp -a /tmp/runtime-app/. /app/ \
    && chown -R app:app /app
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
