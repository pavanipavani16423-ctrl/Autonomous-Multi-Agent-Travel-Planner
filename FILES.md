# What's in this folder

A map of the project. Read `HOW-IT-WORKS.md` first for *what the system does*
— this is just *where things live*.

---

## Getting the latest code onto your laptop

**If you already have the project locally:**

```bash
cd "C:\Users\pavani\OneDrive\Desktop\Autonomous Multi-Agent Travel Planner"
git pull origin main
```

That's it. You should see a list of updated files.

**If git complains about local changes**, it means you edited something.
Either keep your edits:

```bash
git stash          # put your changes aside
git pull origin main
git stash pop      # bring them back
```

...or throw them away and take the server's version exactly:

```bash
git fetch origin
git reset --hard origin/main
```

> `reset --hard` **permanently deletes** any local changes you haven't
> committed. Only use it if you're sure you don't want them.

**If you don't have the project locally yet:**

```bash
git clone https://github.com/pavanipavani16423-ctrl/Autonomous-Multi-Agent-Travel-Planner.git
cd Autonomous-Multi-Agent-Travel-Planner
```

**Then, before running it:**

```bash
pip install -r requirements.txt
```

and create a file called `.env` in the project folder containing:

```
GROQ_API_KEY=your_key_from_console.groq.com
LLM_MODEL=openai/gpt-oss-120b
```

Then `streamlit run app.py`. The first start takes ~5 extra minutes building
the search index; after that it's fast.

---

## Read these first

| File | What it is |
|---|---|
| `README.md` | Front page. Live demo link, what the project does. |
| `HOW-IT-WORKS.md` | **The whole system in plain English.** Start here. |
| `CLAUDE.md` | Technical detail + the traps, for whoever edits the code. |
| `DEPLOY.md` | How to host it. |
| `docs/architecture.html` | The system diagram. Open in a browser. |

---

## The code that actually runs

Each folder holds one job. **The real code is inside the folders** — see the
warning at the bottom about the copies at the top level.

| Folder | What's inside |
|---|---|
| `agents/` | The nine agents. Each asks the AI one question and checks the answer. |
| `graph/` | The pipeline — what runs in what order, and how the plan is assembled. |
| `rag/` | The guidebook: searching it (`rag.py`) and building it (`ingest.py`). |
| `tools/` | The five outside services — weather, maps, hotels, restaurants, flights. |
| `prompts/` | The instructions each agent follows. Change behaviour here. |
| `models/` | The shapes data must take (Pydantic), and the AI connection. |
| `parsers/` | Turns the AI's text into structured data, repairing broken JSON. |
| `guardrails/` | The safety checks, before and after planning. |
| `memory/` | Plan history, the cache, and how quality is scored. |
| `eval/` | The quality gate (`harness.py`) and RAGAS scoring (`ragas_eval.py`). |
| `ui/` | The look of the app (`theme.py`) and the PDF export (`pdf.py`). |

| Root file | What it is |
|---|---|
| `app.py` | The web app. This is what Streamlit runs. |
| `main.py` | A command-line version of the same thing. |
| `config.py` | Every setting in one place. Reads `.env`. |
| `langfuse_setup.py` | Tracing — records what the AI did, for the dashboard. |
| `requirements.txt` | The Python packages needed. |
| `Dockerfile`, `docker-compose.yml`, `render.yaml` | For hosting elsewhere. |
| `.streamlit/` | Colours and settings for Streamlit Cloud. |

---

## Data (created, not written by hand)

| Path | What it is |
|---|---|
| `data/corpus.jsonl` | The guidebook — 8,161 passages, 53 cities. **In the repo**, so the app works immediately. |
| `chroma_db/` | The search index. Built automatically from the corpus on first run. Not in the repo. |
| `data/memory.db` | Your plan history and cache. Local to your machine, not shared. |
| `data/checkpoints.db` | Step-by-step state, so a crashed run can be inspected. Local. |

`.env` is **never** in the repo. It holds your API key, and secrets don't
belong in version control.

---

## Files that look important but are dead

These exist for historical reasons. **Editing them changes nothing** — the
live code is in the folders.

- `graph.py`, `prompts.py`, `guardrails.py`, `parser.py` at the top level
  — duplicates. Python loads the folder versions instead.
- A `config.py` inside every folder — eight identical copies of the real one
  at the top level.
- `evaluation.py` — an evaluation service nothing imports.
- `langfuse_config.py` — an abandoned second attempt at the tracing setup.

They can all be deleted safely; they're left alone only because deleting them
isn't urgent.

**If you edit a file and nothing changes, check you're editing the one inside
the folder.** This catches everyone once.
