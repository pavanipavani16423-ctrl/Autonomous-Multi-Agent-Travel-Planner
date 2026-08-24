FROM python:3.11-slim

LABEL description="Autonomous Multi-Agent Travel Planner"
LABEL version="2.0.0"

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV APP_HOME=/app

# Keep the model cache inside the image so the first request does not pay for
# a ~170 MB download (and so the container works on hosts with no egress).
ENV HF_HOME=/app/.cache/huggingface
ENV SENTENCE_TRANSFORMERS_HOME=/app/.cache/huggingface
ENV TOKENIZERS_PARALLELISM=false

ENV STREAMLIT_SERVER_HEADLESS=true
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
ENV STREAMLIT_SERVER_ENABLE_CORS=false
ENV STREAMLIT_SERVER_ENABLE_XSRF_PROTECTION=false

WORKDIR $APP_HOME

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ── torch, CPU-only ─────────────────────────────────────────
# This MUST come before requirements.txt. The default PyPI wheel for torch
# bundles CUDA and is ~2.5 GB, which blows past most hosts' build limits and
# image size caps. This box has no GPU, so the CPU wheel (~200 MB) is both
# smaller and functionally identical here.
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir torch==2.5.1 \
        --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Bake the embedding + rerank models ──────────────────────
# Downloaded at build time, not first request: a cold Streamlit request that
# also has to pull two models will exceed most platform health-check windows.
RUN python -c "\
from sentence_transformers import SentenceTransformer, CrossEncoder; \
SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2'); \
CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2', max_length=512); \
print('models cached')"

COPY . .

# ── Bake the vector index ───────────────────────────────────
# data/corpus.jsonl is committed, so this needs no network and is
# reproducible. Embedding 8k chunks takes minutes — doing it at boot would
# time out the health check on every deploy and every restart.
RUN mkdir -p data chroma_db && \
    python -c "\
from rag.rag import get_retriever; \
r = get_retriever(); \
print('index ready:', r.vector_store._collection.count(), 'vectors')"

# Render/Railway/Fly inject $PORT. Default to 8501 for plain `docker run`.
ENV PORT=8501
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD curl -fs "http://localhost:${PORT}/_stcore/health" || exit 1

# Shell form so ${PORT} is expanded at runtime rather than baked in.
CMD streamlit run app.py \
    --server.port=${PORT} \
    --server.address=0.0.0.0 \
    --server.headless=true
