# What's in this project

A guide to the folder. Plain English, no jargon.

---

## If you only open five files, open these

**`README.md`** — the front page. What the project is, and the link to the
live app.

**`HOW-IT-WORKS.md`** — the whole system explained simply. How a plan gets
made, what each agent does, why there's a guidebook. **Read this one first.**

**`app.py`** — the actual web app. Everything you see on screen is here.

**`agents/agents.py`** — the nine agents. This is where the real work happens.

**`prompts/prompts.py`** — the instructions given to the AI. Change a sentence
here and every plan changes.

---

## The folders, one by one

Each folder does one job.

### `agents/`
The nine agents. An agent is just a piece of code that asks the AI one
question and checks the answer. One plans the route, one does the weather, one
picks hotels, and so on.

### `graph/`
The order things happen in. Check the request, look things up, call the
services, run the five agents, check the work, write the plan. If you want to
change *what runs when*, it's here.

### `rag/`
The guidebook — 8,161 pieces of text about 53 cities.

- `rag.py` searches it
- `ingest.py` builds it (downloads city guides from Wikivoyage)

### `tools/`
The five outside services: weather, maps, hotels, restaurants, flights. If a
key is missing, these return clearly-labelled sample data instead of failing.

### `prompts/`
What each agent is told to do — its role, the steps it should follow, the
rules it must obey, and examples of good answers.

### `models/`
The shape every piece of data must take. If the AI returns something that
doesn't fit the shape, it gets rejected rather than passed along broken.

### `parsers/`
Turns the AI's text into proper data, and repairs it when the AI sends
slightly-broken JSON (which happens often).

### `guardrails/`
The safety checks. Before planning: are the dates sensible, is the budget
real. After planning: does the day count match the dates, is it over budget.

### `memory/`
What the app remembers. Past plans, the cache that makes a repeated trip
instant, and how each plan's quality is scored.

### `eval/`
Testing.

- `harness.py` — the six checks that say PASS or FAIL
- `ragas_eval.py` — scores whether the guidebook is actually being used

### `ui/`
How it looks.

- `theme.py` — colours and styling
- `pdf.py` — the downloadable PDF itinerary

---

## Other files worth knowing

**`config.py`** — every setting in one place. Reads your `.env` file.

**`main.py`** — a command-line version, if you'd rather not use the browser.

**`requirements.txt`** — the list of Python packages to install.

**`langfuse_setup.py`** — records what the AI did, so you can inspect runs
later in a dashboard.

**`docs/architecture.html`** — a diagram of the whole system. Open it in a
browser.

**`Dockerfile`, `render.yaml`, `DEPLOY.md`** — only needed if you host the app
somewhere else.

---

## Files that are created, not written

You don't edit these — the app makes them.

**`data/corpus.jsonl`** — the guidebook text. This one *is* in the repo, so
the app works straight away without downloading anything.

**`chroma_db/`** — the search index, built automatically the first time you
run the app. Takes about 5 minutes, once.

**`data/memory.db`** — your own plan history and cache. Stays on your machine.

**`.env`** — your API key. Never goes into the repo, because secrets don't
belong in shared code.

---

## Careful: some files look important but do nothing

There are leftover copies at the top level of the folder:

`graph.py` · `prompts.py` · `guardrails.py` · `parser.py`

and a `config.py` inside every single folder.

**Python ignores all of these.** The real code is the one *inside* the folder
— `graph/graph.py`, `prompts/prompts.py`, and so on.

`evaluation.py` and `langfuse_config.py` are dead too. Nothing uses them.

> **If you change something and nothing happens, check you edited the file
> inside the folder.** This catches everybody once.

---

## Getting the latest code

If you already have the project:

```bash
git pull origin main
```

If you don't have it yet:

```bash
git clone https://github.com/pavanipavani16423-ctrl/Autonomous-Multi-Agent-Travel-Planner.git
```

Then, to run it:

```bash
pip install -r requirements.txt
streamlit run app.py
```

You need a file called `.env` with your key in it:

```
GROQ_API_KEY=your_key_from_console.groq.com
LLM_MODEL=openai/gpt-oss-120b
```

The first run takes about 5 extra minutes while it builds the search index.
After that it starts quickly.
