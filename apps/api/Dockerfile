# Voyager API. Build from the repo root (needs data/corpus.jsonl):
#   docker build -f apps/api/Dockerfile -t voyager-api .
#
# The fastembed models are downloaded and the embedded Qdrant index is built from the corpus
# at BUILD time, so a cold start only opens files (no 9k-passage embedding on a tiny instance).
# Set BUILD_INDEX=0 when the API will use a Qdrant server (QDRANT_URL) instead.

FROM python:3.11-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    VOYAGER_DATA_DIR=/app/data FASTEMBED_CACHE_PATH=/app/models \
    PATH="/app/api/.venv/bin:$PATH"
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
WORKDIR /app/api

# dependencies first (cached layer); no dev tools, no Ragas in the runtime image
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY apps/api/voyager ./voyager
RUN uv sync --frozen --no-dev

COPY data/corpus.jsonl /app/data/corpus.jsonl
# the sample trip the web app replays at /trip/demo, so the assistant can answer about it too
COPY docs/sample-plan.json /app/data/sample-plan.json

# models + index baked into the image
ARG BUILD_INDEX=1
RUN python -c "from voyager.rag.embeddings import warm; warm()" \
 && if [ "$BUILD_INDEX" = "1" ]; then python -m voyager.rag.ingest; fi \
 && rm -f /app/data/*.db

RUN useradd --create-home --uid 10001 voyager && chown -R voyager /app
USER voyager

ENV PORT=8000 VOYAGER_EMBED_THREADS=2
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health')"
CMD ["sh", "-c", "uvicorn voyager.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
