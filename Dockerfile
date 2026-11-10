# --- Stage 1: build the console UI ---------------------------------------------
FROM node:22-alpine AS ui
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
# vite outDir is ../app/static, i.e. /src/app/static
RUN npm run build

# --- Stage 2: the API, serving the built console from the same origin ----------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATABASE_PATH=/data/executions.db

RUN useradd --create-home --uid 10001 app && mkdir /data && chown app:app /data
WORKDIR /srv

COPY pyproject.toml README.md ./
COPY app ./app
COPY --from=ui /src/app/static ./app/static
RUN pip install .

USER app
EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"

# --proxy-headers so client IPs are right behind a platform proxy (pair with TRUST_PROXY=true)
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
