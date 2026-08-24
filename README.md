# Autonomous Multi-Agent Travel Planner

**[▶ Try the live app](https://autonomous-multi-agent-travel-planner-pnmjkcxhpddthjhxeu5nzc.streamlit.app/)**

Tell it where you're going, your dates and a budget. A few minutes later you
get a complete travel plan — a day-by-day itinerary, places to stay, what to
eat, the weather, and a costed budget — downloadable as a PDF.

Built with LangGraph, Groq, ChromaDB and Streamlit.

---

## What makes it different

Most LLM travel demos produce a confident plan and give you no way to tell
which parts are real. This one tells you.

**It knows when it doesn't know.** The knowledge base covers 53 cities. Ask
about one it doesn't cover and it says so, rather than quietly answering with
a *different* city's facts — which is exactly what a plain vector search does,
because it always returns its nearest matches and has no way to say "nothing
here is relevant."

> Measured: **18/18** covered cities correctly grounded · **18/18** uncovered
> cities correctly refused · **0** wrong-city facts leaked.

**It labels data it made up.** Without API keys the weather and price services
return sample figures. Every value is stamped `live`, `curated` or `mock`, and
that stamp follows it to the screen and into the PDF. If part of a plan is
illustrative, the plan says so and lowers its own confidence to match.

**Its quality is measured, not asserted.** Six automatic pass/fail checks run
on every plan and block a release if any fail. They have already caught two
bugs that had been silently broken for weeks.

---

## How it works

```
Trip request
   ↓
Is the request sane?  ──no──▶  stop, explain why
   ↓ yes
① Search the guidebook   8,161 passages · 53 cities
     hybrid search, then discard passages about other cities
   ↓
② Call live services     weather · maps · hotels · restaurants · flights
     each answer stamped live / curated / mock
   ↓
③ Five specialists       weather → route → hotels → budget → food
     one AI call each, in dependency order
   ↓
Check the work           days match dates? over budget? sections missing?
   ↓
Final planner            writes ONLY the summary + confidence
   ↓
Plan assembled in Python
   ↓
Itinerary on screen + PDF
```

A failed step becomes a missing section with an explanation — never a crash.

There's a full architecture diagram in
[`docs/architecture.html`](docs/architecture.html) (open it in a browser).

---

## Documentation

| Document | For |
|---|---|
| [`HOW-IT-WORKS.md`](HOW-IT-WORKS.md) | The whole system in plain English. Start here. |
| [`FILES.md`](FILES.md) | What every folder and file is, and how to pull the latest code. |
| [`CLAUDE.md`](CLAUDE.md) | Technical detail and the traps, for whoever edits the code. |
| [`DEPLOY.md`](DEPLOY.md) | Hosting notes. |

---

## Running it locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Create a `.env` file with one required line:

```
GROQ_API_KEY=your_key_from_console.groq.com
LLM_MODEL=openai/gpt-oss-120b
```

The first start takes ~5 extra minutes while it builds the search index from
`data/corpus.jsonl` (the 53 city guides, already in the repo). That happens
once and needs no internet. Every start after that is fast.

Weather, maps, hotel and flight keys are optional — without them those
sections use clearly-labelled sample data.

### Useful commands

```bash
python -m rag.ingest --list        # which cities are covered
python -m rag.ingest --cities X    # add a city (keeps the existing ones)
python -m rag.ingest --check       # prove the wrong-city filter works
python -m rag.ingest --backlog     # cities users wanted that we lack
python -m eval.harness             # the six checks — PASS or FAIL
python -m eval.harness --ragas     # plus RAGAS retrieval scoring
```

---

## Built with

**LangGraph** state machine · **Groq** (`openai/gpt-oss-120b`) ·
**ChromaDB** + **BM25** hybrid retrieval · **Wikivoyage** knowledge base ·
**Pydantic** schemas · **Langfuse** tracing · **RAGAS** evaluation ·
**Streamlit** UI · **ReportLab** PDF export · **SQLite** memory

---

## Known limits

Worth knowing before you try it:

- **A plan takes 3–5 minutes.** Seven AI calls run in sequence.
- **The free Groq tier allows roughly 10 plans a day.** Identical trips are
  cached and return instantly at no cost.
- **The hosted app forgets on restart.** Plan history and cache reset when the
  free instance sleeps.
- **Retrieval is stronger than generation.** The right passages are provably
  retrieved, but the agents lean more on the model's own knowledge than on
  them. Measured and documented in `HOW-IT-WORKS.md` — it's the next thing to
  improve.

---

## Author

**Pavani** — Artificial Intelligence, Multi-Agent Systems and Generative AI.

⭐ If you found this interesting, consider starring the repo.
