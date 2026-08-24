# Deploying

## Vercel will not work

Not a configuration problem — three hard limits:

| | Vercel | This app |
|---|---|---|
| Bundle size | 250 MB unzipped | `torch` alone is 474 MB |
| Function timeout | 10–60 s | a plan takes ~250 s |
| Process model | stateless functions | Streamlit is a long-lived WebSocket server |
| Filesystem | ephemeral, read-only except `/tmp` | needs a 77 MB vector index |

Vercel targets Next.js/static sites plus short serverless functions. Use a
container host instead.

## What it actually needs

- **~1.5 GB RAM.** torch + a 384-dim embedding model + the cross-encoder
  reranker + an 8k-vector Chroma index, all resident.
- **Docker.** The image bakes both models and the vector index at build time
  so the first request is fast and the container needs no egress to start.
- **No persistent disk.** The index is rebuilt into every image from the
  committed `data/corpus.jsonl`. Deploys are reproducible and stateless.
- **A `GROQ_API_KEY`.** Everything else is optional.

Build takes ~10–15 minutes (torch, two model downloads, embedding 8k chunks)
and produces a ~2.5 GB image.

---

## Option A — Hugging Face Spaces (free, recommended)

The free tier gives 16 GB RAM and 2 vCPU with native Docker support, which is
more headroom than a paid Render instance. For a portfolio project this is
the better deal.

1. Create a Space → SDK **Docker** → Blank.
2. Push this repo to it.
3. Space settings → **Variables and secrets** → add `GROQ_API_KEY`
   (and the Langfuse keys if you want tracing).
4. Add this to the top of `README.md` so the Space knows which port to serve:

   ```yaml
   ---
   title: Autonomous Multi-Agent Travel Planner
   sdk: docker
   app_port: 8501
   ---
   ```

The `Dockerfile` already reads `$PORT` and defaults to 8501, so nothing else
changes.

## Option B — Render

`render.yaml` is a ready Blueprint.

1. Push to GitHub.
2. Render → **New** → **Blueprint** → select the repo.
3. Set `GROQ_API_KEY` in the dashboard when prompted (it is marked
   `sync: false`, so it is never read from git).

**Pick the `standard` plan (2 GB).** The 512 MB Starter instance is
OOM-killed part-way through a plan — the blueprint already specifies
`standard` for this reason. If cost is the constraint, use Hugging Face
Spaces rather than dropping to Starter.

## Option C — Railway / Fly.io

Both run the same `Dockerfile` unchanged. Set `GROQ_API_KEY` and give the
service at least 2 GB.

---

## Local

```bash
docker compose up --build      # reads GROQ_API_KEY from your environment/.env
```

Or without Docker:

```bash
pip install -r requirements.txt
python -m rag.ingest           # build the knowledge base first
streamlit run app.py
```

---

## Before you hand it over

- [ ] `GROQ_API_KEY` set as a platform secret, not committed.
- [ ] `.env` is gitignored and **not** in the repo. If the keys currently in
      it were ever pushed, rotate them — Groq and Langfuse both let you
      revoke and reissue.
- [ ] `git rm -r --cached chroma_db` — it is still tracked from the first
      commit despite now being a gitignored build artefact. A stale committed
      index is unreadable by a different chromadb version and silently
      disables dense retrieval.
- [ ] `data/corpus.jsonl` **is** committed. That is deliberate: it is what
      lets the image build its index offline.

## Cutting cost or memory

`RERANK_ENABLED=false` drops the cross-encoder and roughly 400 MB of RAM.

Be aware of what that costs you: the reranker is what powers the grounding
gate. Without it the retriever falls back to fusion order with no relevance
floor, so a destination the corpus does not cover gets the least-bad passages
instead of an honest "no knowledge" signal. Prefer paying for the RAM.
