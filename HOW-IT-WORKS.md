# How this project works — in plain English

Written for someone taking this over. No jargon without an explanation.
Read top to bottom; each section builds on the last.

---

## 1. What the app does

Someone types where they're flying from, where they're going, their dates,
how many people, and a budget. A few minutes later they get a complete travel
plan: a day-by-day itinerary, places to stay, what to eat, the weather, and a
cost breakdown. They can download it as a PDF.

That's it. Everything below is *how* that happens.

---

## 2. The whole journey, start to end

When someone clicks **Plan my trip**, this happens in order:

```
1. Check the request        →  Are the dates sensible? Is the budget real?
2. Look things up           →  Search our travel guidebook for this city
3. Call outside services    →  Weather, hotel prices, flights
4. Work out the weather     →  What will it be like, what to pack
5. Plan the days            →  Day 1, Day 2, Day 3... activities and transport
6. Find places to stay      →  Budget / mid-range / family options
7. Work out the money       →  Flights + hotels + food + activities
8. Pick the food            →  Local dishes, restaurants
9. Check the work           →  Does the day count match the dates? Any problems?
10. Write it up             →  A human-readable summary of the whole thing
```

Steps 4 to 8 and step 10 each involve asking an AI model to do one job. Steps
1, 2, 3 and 9 are ordinary code.

**A step never crashes the whole thing.** If the weather step fails, you get a
plan with no weather section — plus a message explaining why. That's on
purpose. One broken piece shouldn't destroy a plan that's otherwise fine.

---

## 3. The agents, one at a time

An "agent" here just means: *a piece of code that asks the AI one specific
question and checks the answer*. Nothing more mysterious than that.

Each one gets a carefully written instruction (a "prompt"), sends it to the AI
along with the relevant facts, and gets back JSON — structured data, not prose.
If the JSON is malformed, we try to repair it. If it still fails, that section
comes back empty rather than wrong.

### RetrievalAgent — the librarian
Runs first. Searches our travel guidebook for three things about the
destination: general info, places to stay, and food. Hands what it finds to
everyone else. Doesn't use the AI at all — it's pure search.

### ToolAgent — the phone caller
Calls five outside services: weather, maps, hotels, restaurants, flights.
Also doesn't use the AI.

**Important:** if an API key is missing, that service returns *example data*
instead of failing. The app marks these clearly so nobody mistakes a sample
price for a real one. See section 7.

### WeatherAgent
Takes the raw weather data and turns it into something useful: what the
conditions will be, what to pack, any warnings.

### RouteAgent
The biggest job. Plans the actual trip — how to get there, and what to do on
each day. Runs *after* the weather agent so it can avoid planning a beach day
in the rain.

### HotelAgent
Suggests places to stay in three price brackets, and recommends which
neighbourhood to base yourself in.

### BudgetAgent
Adds up the money: flights, accommodation, food, local transport, activities.
Reads the route and hotel results first, so its numbers match the actual plan
rather than being invented separately.

### FoodAgent
Local dishes, restaurants, street food, and it respects dietary preferences.

### FinalPlannerAgent
Writes the summary you read at the top of the plan, scores its own confidence,
and flags contradictions ("the budget says 4 days but the itinerary has 5").

**One thing to know here:** this agent does *not* build the plan. The plan is
assembled by ordinary Python code from the other agents' results. The AI only
writes the summary. We tried letting it build the whole thing and it failed
every single time — the structure was too complicated to get right reliably.

### SupervisorAgent — ignore this one
It exists in the code and looks important. **Nothing calls it.** It's an
alternative design that was never wired up. Editing it changes nothing.

---

## 4. RAG — the guidebook

### What it is

RAG means "look something up before answering." We have a travel guidebook —
**8,161 pieces of text covering 53 cities**, pulled from Wikivoyage (a free
travel wiki). Before the agents plan anything, we search that guidebook and
give them the relevant pages.

### Why we need it when we already call APIs

They answer *different questions*.

| | Comes from |
|---|---|
| Today's temperature | **API** — changes daily |
| Tonight's hotel price | **API** — changes hourly |
| Which neighbourhood to stay in | **Guidebook** |
| What dish the city is famous for | **Guidebook** |
| Best months to visit | **Guidebook** |

APIs give you *numbers that change*. The guidebook gives you *judgement that
doesn't* — and no API sells you "stay in Le Marais, it's walkable to
everything." That's the gap RAG fills.

### How a search actually works

Say someone asks for Dubai. Step by step:

**Step 1 — two searches at once.**
One search matches by *meaning* (finds "affordable lodging" when you asked
about "cheap hotels"). The other matches by *exact words* (finds "Burj
Khalifa" reliably). Both have blind spots, so we run both and merge.

**Step 2 — throw away other cities. This is the important one.**

Search engines always return their closest matches. They have no way to say
"I've got nothing." Ask about a city we don't cover and you'll confidently get
passages about the nearest city we *do* cover.

This actually happened: a Dubai plan was quoting **Bali's dry season** as
fact.

So every piece of text is tagged with the city it's about. Anything about a
*different* city gets deleted before we look at scores. For a city we don't
cover, that leaves **zero** pieces — and we say so plainly instead of guessing.

**Step 3 — rank what's left**, keep the best few.

**Step 4 — be honest about the result.**

- Found city-specific text → the agents get it, and the plan says "grounded"
- Found nothing → the agents get told: *"We have no information about this
  place. Do NOT use facts about other cities. Use your own general knowledge."*

That last message matters. The AI genuinely knows a lot about most cities. The
danger was never "it knows nothing" — it was "it gets handed the wrong city's
facts and treats them as sources."

### Adding a new city

```bash
python -m rag.ingest --cities Hyderabad
```

Downloads that city's guide, adds it to the collection, keeps everything else.
Takes a few minutes.

To see which cities people asked for that we *don't* cover:

```bash
python -m rag.ingest --backlog
```

---

## 5. Memory — four kinds

"Memory" sounds grand. In practice it's four different things that need
remembering for different lengths of time.

### Working memory — during one plan
The notes passed from step to step while a plan is being built. The weather
result gets handed to the route planner, the route gets handed to the budget
calculator. Saved to a file so a crashed run can be inspected afterwards.

### Semantic memory — general knowledge
The guidebook from section 4. Facts about the world that stay true. Same for
every user.

### Episodic memory — what happened before
A record of every plan ever made: who asked for what, how long it took, how
good it was. Two uses:

- **Speed.** Ask for the same trip twice and the second one is instant instead
  of taking four minutes. (Measured: 219 seconds → 0.0 seconds.)
- **Improvement.** It tells us which cities people wanted that our guidebook
  doesn't cover — a to-do list built from real demand rather than guesswork.

### Procedural memory — how we do things
The instructions we give the AI are version-numbered (currently `v3`). Every
plan records which version produced it, so you can ask "did my prompt change
make things better or worse?" and get a real answer:

```bash
python -m eval.harness --compare
```

### One idea we deliberately did NOT build

A common design is: summarise past plans into "learned facts" and feed them
back into the guidebook. **We didn't, on purpose.**

The past plans were written by the AI, and some were built on example data.
Feeding them back means the AI's own guesses become "facts" it later looks up
and trusts. Errors compound quietly. Worse, it breaks the one guarantee we
have — that every piece of the guidebook traces back to a real source you can
check.

It becomes a good idea *if you add user accounts*. Then "this person always
picks budget hotels and is vegetarian" is genuinely worth remembering, and
exists nowhere else.

---

## 6. Guardrails — the safety checks

**Before planning** (can stop the whole thing): dates in the past, return
before departure, origin same as destination, silly budgets, banned words.

**After planning** (warns, never blocks): does the day count match the dates?
Is the budget over what they asked for? Are any sections missing?

Output problems become **warnings, not failures**. By that point we've spent
several minutes and real money on AI calls — throwing that away because one
number looks odd would be worse than showing it with a caution.

---

## 7. Being honest with the user

This is the part I'd most want kept if the project is changed later.

### "Some figures are examples"

Without API keys, the weather/hotel/flight services return **sample data**.
Before, a plan built entirely on fake numbers looked exactly like a real one.

Now every piece of data is stamped `live`, `curated`, or `mock`, and that
stamp follows it all the way to the screen and into the PDF. If part of the
plan is examples, the app says so, and the confidence score is reduced to
match.

Real example: a Dubai plan once showed **24°C and "pack a light jacket"** at
90% confidence. Dubai in October is about 35°C. The number came from a sample
fixture. Now that same plan says the weather is illustrative and drops to 44%.

### "This destination isn't in our guidebook"

If we have nothing about the place, the plan says so rather than sounding
equally confident either way.

Two different messages, because they have two different fixes: one needs API
keys, the other needs the city ingested.

---

## 8. RAGAS and the quality gate

Two separate systems. Don't confuse them.

### The gate — decides whether to release

Six checks, all plain code, no AI involved:

| Check | Passes when |
|---|---|
| A plan was produced | always required |
| All 5 sections present | all parsed successfully |
| Summary is real | not the fallback template |
| Itinerary matches dates | day count is right |
| No errors | zero |
| Not too slow | under 7 minutes |

```bash
python -m eval.harness
```

Exits with an error if anything fails. **This is what decides whether a change
is safe to ship.**

It has already caught two real bugs: the summary silently falling back to a
template on every run, and a prompt that was too large for the AI service to
accept.

### RAGAS — a second opinion, not a gate

RAGAS asks an AI to grade our AI. Two scores:

- **Faithfulness** — breaks our answer into individual claims and checks each
  one against the guidebook text we retrieved. *"Did you make this up?"*
- **Answer relevancy** — checks the answer actually addresses the question.

```bash
python -m eval.harness --ragas
```

**It has no thresholds and does not block anything.** Deliberately: it uses
the same AI model family that wrote the answer, so it shares the same blind
spots. A judge that thinks like the defendant shouldn't decide the verdict.

### What RAGAS told us — and it's uncomfortable

```
faithfulness      0.0
answer relevancy  0.57
```

Faithfulness near zero means **the agents mostly don't use the guidebook text
we retrieve.** They write from the AI's own knowledge and from the API data,
treating the guidebook as background reading.

Two things are true about that number:

1. **It's partly real.** The hotel names come from sample data, the restaurant
   names from a built-in list, the flight details from the AI's own knowledge.
   Very little is quoted from the guidebook.
2. **It's partly an unfair test.** One of the three checks compares a *flight
   plan* against a *city-overview page*. A guidebook page about Paris crowds
   can never support "the flight takes 9 hours." That test was set up to score
   zero regardless.

Neither is a reason to hide it. The retrieval provably works — 18 out of 18
covered cities found, 18 out of 18 uncovered cities correctly refused, zero
wrong-city leaks. What RAGAS shows is that the *writing* step under-uses what
retrieval found. That's a real, measurable gap and a sensible next thing to
improve.

**Note:** there are threshold numbers in `evaluation.py` (0.70, 0.60...).
**That file is dead — nothing imports it.** Ignore it or delete it.

---

## 9. Known rough edges

Nothing here is hidden; it's all worth knowing.

- **A plan takes 3–5 minutes.** The AI is called seven times in sequence.
- **The free AI tier allows about 10 plans per day.** Repeats are cached and
  free. For a live demo, generate the plans you'll show beforehand.
- **Deployed, the app forgets on restart.** History and cache reset. Fixing it
  properly needs an external database.
- **Duplicate files at the top level** — `graph.py`, `prompts.py`,
  `guardrails.py`, `parser.py` and eight copies of `config.py` are dead. The
  live code is in the folders. **Editing the top-level copies does nothing.**
- **`evaluation.py` and `langfuse_config.py` are dead too.**
- **Faithfulness is low** — see section 8.

---

## 10. Running it

```bash
pip install -r requirements.txt
streamlit run app.py
```

You need a `.env` file with one line:

```
GROQ_API_KEY=your_key_from_console.groq.com
```

First start takes ~5 extra minutes building the search index. After that it's
fast.

### Useful commands

```bash
python -m rag.ingest --list        # which cities we cover
python -m rag.ingest --check       # prove the wrong-city filter works
python -m rag.ingest --backlog     # cities people wanted that we lack
python -m eval.harness             # the release gate
python -m eval.harness --compare   # quality per prompt version
python -m eval.harness --history   # recent plans
```

`CLAUDE.md` is the technical companion to this document — same system, more
detail, aimed at whoever edits the code next.
