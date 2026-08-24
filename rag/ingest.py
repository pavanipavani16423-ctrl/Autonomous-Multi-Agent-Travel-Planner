# ============================================================
# rag/ingest.py — Build the travel knowledge base from Wikivoyage
# ============================================================
# PURPOSE:
#   Replaces the 12 hand-written synthetic chunks with a real, citable
#   corpus so that retrieval actually contributes facts instead of being
#   correctly-but-uselessly reported as "not grounded" for every city.
#
# WHY WIKIVOYAGE:
#   It is a travel guide, not an encyclopaedia — the content is already
#   the advice a planner needs (costs, neighbourhoods, transport, dishes).
#   It is free, needs no API key, and every article follows the same
#   section skeleton:
#
#       Understand / Get in / Get around / See / Do / Buy
#       Eat / Drink            → food
#       Sleep                  → hotel
#
#   That skeleton maps directly onto the three areas RetrievalAgent asks
#   about, so each chunk can be tagged with both its destination AND the
#   area it answers — which is exactly what the destination filter and the
#   grounding signal in rag.py need. Content is CC BY-SA; the source URL is
#   stored on every chunk.
#
# USAGE:
#   python -m rag.ingest                      # default destination list
#   python -m rag.ingest --cities Paris,Dubai # specific cities
#   python -m rag.ingest --list               # show what is indexed
#
# Re-running is idempotent: the store is rebuilt from scratch each time.
# ============================================================

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from typing import Dict, Iterable, List, Optional, Tuple

import requests
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from loguru import logger

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# A stock Windows console is cp1252 and raises UnicodeEncodeError on the
# arrows and dashes used below, killing the command mid-report. Force UTF-8
# and degrade anything unmappable rather than crashing.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

from config import rag_config
from rag.rag import GENERAL_KNOWLEDGE, _destination_key


WIKIVOYAGE_API = "https://en.wikivoyage.org/w/api.php"
USER_AGENT = (
    "AutonomousTravelPlanner/1.0 "
    "(https://github.com/; educational multi-agent RAG project)"
)

# Where the chunked corpus is written. Both Chroma and BM25 read this, so the
# dense and sparse halves of the hybrid always index the same text — before
# this, BM25 was rebuilt from freshly-chunked documents while Chroma loaded
# whatever was on disk, and the two could silently drift apart.
#
# Deliberately kept OUT of the Chroma persist directory: that directory gets
# deleted wholesale whenever the index is rebuilt or found incompatible, which
# would take the corpus with it and leave nothing to rebuild from.
CORPUS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
CORPUS_FILENAME = "corpus.jsonl"


# ── Section → retrieval area ─────────────────────────────────
# RetrievalAgent asks three questions (general / hotel / food). Tagging each
# chunk with the area it can answer keeps a "where do I sleep" query from
# being answered out of the "Stay safe" section.
SECTION_AREA: Dict[str, str] = {
    "understand": "general",
    "get in": "general",
    "get around": "general",
    "see": "general",
    "do": "general",
    "buy": "general",
    "itineraries": "general",
    "stay safe": "general",
    "stay healthy": "general",
    "respect": "general",
    "connect": "general",
    "cope": "general",
    "districts": "general",
    "eat": "food",
    "drink": "food",
    "sleep": "hotel",
}

# Sections that carry no planning value.
SKIP_SECTIONS = {"external links", "references", "see also", "nearby", "go next"}

# A broad, deliberately mainstream default set — the destinations a demo is
# most likely to be asked about. Extend with --cities rather than editing.
DEFAULT_DESTINATIONS: List[str] = [
    "Paris", "London", "Rome", "Barcelona", "Amsterdam", "Berlin", "Prague",
    "Vienna", "Lisbon", "Istanbul", "Athens", "Venice", "Florence",
    "Tokyo", "Kyoto", "Seoul", "Beijing", "Shanghai", "Hong Kong",
    "Singapore", "Bangkok", "Bali", "Hanoi", "Kuala Lumpur",
    "Dubai", "Abu Dhabi", "Doha", "Cairo", "Marrakesh", "Cape Town",
    "New York City", "Los Angeles", "San Francisco", "Chicago", "Toronto",
    "Mexico City", "Rio de Janeiro", "Buenos Aires", "Lima",
    "Sydney", "Melbourne", "Auckland",
    "Delhi", "Mumbai", "Jaipur", "Goa",
    "Reykjavik", "Oslo", "Stockholm", "Copenhagen", "Zurich", "Edinburgh",
]


# ══════════════════════════════════════════════════════════════
# SECTION 1 — Fetch
# ══════════════════════════════════════════════════════════════

# MediaWiki's prop=extracts only honours `exlimit` when `exintro` is set —
# for FULL article text the server silently returns one extract per request
# and blanks the rest. So this fetches one article per request by necessity,
# and stays polite through backoff rather than through batching.
MIN_ARTICLE_CHARS = 500


def _api_get(session: requests.Session, params: dict, max_retries: int = 4) -> Optional[dict]:
    """
    GET the MediaWiki API, honouring 429 backoff.

    `maxlag` asks the server to reject us rather than add load when it is
    already struggling — standard etiquette for the Wikimedia APIs.
    """
    params = {**params, "format": "json", "maxlag": "5"}
    delay = 1.0
    for attempt in range(1, max_retries + 1):
        try:
            resp = session.get(
                WIKIVOYAGE_API, params=params,
                headers={"User-Agent": USER_AGENT}, timeout=45,
            )
            if resp.status_code == 429:
                wait = float(resp.headers.get("Retry-After", delay))
                logger.warning(
                    f"[Ingest] Rate limited (429), waiting {wait:.0f}s "
                    f"[attempt {attempt}/{max_retries}]"
                )
                time.sleep(wait)
                delay = min(delay * 2, 30)
                continue
            resp.raise_for_status()
            data = resp.json()
            if "error" in data and data["error"].get("code") == "maxlag":
                logger.warning(f"[Ingest] Server lagged, retrying in {delay:.0f}s")
                time.sleep(delay)
                delay = min(delay * 2, 30)
                continue
            return data
        except Exception as e:
            logger.warning(f"[Ingest] Request failed ({e}) [attempt {attempt}/{max_retries}]")
            time.sleep(delay)
            delay = min(delay * 2, 30)
    return None


def fetch_articles(
    titles: List[str], session: Optional[requests.Session] = None, delay_s: float = 1.0
) -> Dict[str, Tuple[str, str, str, str]]:
    """
    Fetch Wikivoyage articles as plain text.

    Returns {resolved_title: (resolved_title, text, url, requested_title)}.
    The API resolves redirects, so "Marrakesh" comes back as "Marrakech" and
    "NYC" as "New York City". Keeping the requested title alongside is what
    lets either spelling match at query time.
    """
    sess = session or requests.Session()
    found: Dict[str, Tuple[str, str, str]] = {}

    for i, title in enumerate(titles, 1):
        logger.info(f"[Ingest] ({i}/{len(titles)}) {title}")
        data = _api_get(sess, {
            "action": "query",
            "prop": "extracts",
            "explaintext": 1,
            "redirects": 1,
            "titles": title,
        })
        if not data:
            logger.error(f"[Ingest] Gave up on '{title}'")
            continue

        for _, page in data.get("query", {}).get("pages", {}).items():
            resolved = page.get("title", title)
            if "missing" in page:
                logger.warning(f"[Ingest] No article for '{resolved}'")
                continue
            text = page.get("extract", "") or ""
            if len(text) < MIN_ARTICLE_CHARS:
                logger.warning(f"[Ingest] '{resolved}' too short ({len(text)} chars) — skipped")
                continue
            url = f"https://en.wikivoyage.org/wiki/{resolved.replace(' ', '_')}"
            found[resolved] = (resolved, text, url, title)

        if i < len(titles):
            time.sleep(delay_s)

    return found


def fetch_article(title: str, session: Optional[requests.Session] = None) -> Optional[Tuple[str, str, str]]:
    """Single-article convenience wrapper; drops the requested-title element."""
    result = fetch_articles([title], session=session)
    first = next(iter(result.values()), None)
    return (first[0], first[1], first[2]) if first else None


# ══════════════════════════════════════════════════════════════
# SECTION 2 — Parse & chunk
# ══════════════════════════════════════════════════════════════

_HEADING_RE = re.compile(r"^(={2,4})\s*(.+?)\s*\1\s*$", re.M)


def split_sections(text: str) -> List[Tuple[str, str]]:
    """
    Split a plaintext Wikivoyage article into (top_level_heading, body) pairs.

    Sub-headings (=== ... ===) stay inside their parent's body so a chunk keeps
    the context of which section it came from — a price list is far less useful
    once separated from the "Sleep" heading above it.
    """
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return [("Understand", text)]

    sections: List[Tuple[str, str]] = []
    lead = text[: matches[0].start()].strip()
    if lead:
        sections.append(("Understand", lead))

    current_heading: Optional[str] = None
    current_start = 0
    for m in matches:
        level = len(m.group(1))
        if level == 2:  # a new top-level section
            if current_heading is not None:
                sections.append((current_heading, text[current_start:m.start()].strip()))
            current_heading = m.group(2)
            current_start = m.end()
    if current_heading is not None:
        sections.append((current_heading, text[current_start:].strip()))

    return [(h, b) for h, b in sections if b]


def article_to_documents(
    destination: str, text: str, url: str, splitter: RecursiveCharacterTextSplitter,
    alias: Optional[str] = None,
) -> List[Document]:
    """
    Turn one article into tagged, retrieval-ready chunks.

    Every chunk carries `destination` (so the wrong city can be filtered out)
    and `area` (general/hotel/food), plus the source URL for attribution.
    """
    dest_key = _destination_key(destination)
    docs: List[Document] = []

    for heading, body in split_sections(text):
        key = heading.strip().lower()
        if key in SKIP_SECTIONS:
            continue
        area = SECTION_AREA.get(key, "general")

        for chunk in splitter.split_text(body):
            chunk = chunk.strip()
            if len(chunk) < 120:      # fragments carry no usable advice
                continue
            docs.append(
                Document(
                    # Prefixing keeps the city and topic inside the embedded
                    # text, which measurably helps both BM25 and the reranker
                    # when a chunk's body never repeats the city name.
                    page_content=f"{destination} — {heading}: {chunk}",
                    metadata={
                        "source": "wikivoyage",
                        "destination": dest_key,
                        "destination_name": destination,
                        # Set when the wiki redirected us (Marrakesh ->
                        # Marrakech) so the requested spelling still matches.
                        "destination_alias": alias or "",
                        "area": area,
                        "section": heading,
                        "url": url,
                    },
                )
            )
    return docs


# ══════════════════════════════════════════════════════════════
# SECTION 3 — Corpus persistence
# ══════════════════════════════════════════════════════════════

def corpus_path() -> str:
    return os.path.join(CORPUS_DIR, CORPUS_FILENAME)


def save_corpus(documents: List[Document]) -> str:
    """Write chunks to JSONL so dense and sparse retrieval share one source."""
    os.makedirs(CORPUS_DIR, exist_ok=True)
    path = corpus_path()
    with open(path, "w", encoding="utf-8") as f:
        for d in documents:
            f.write(json.dumps(
                {"page_content": d.page_content, "metadata": d.metadata},
                ensure_ascii=False,
            ) + "\n")
    logger.info(f"[Ingest] Wrote {len(documents)} chunks to {path}")
    return path


def load_corpus() -> Optional[List[Document]]:
    """Read the persisted corpus, or None when it has not been built yet."""
    path = corpus_path()
    if not os.path.exists(path):
        return None
    docs: List[Document] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rec = json.loads(line)
                    docs.append(Document(
                        page_content=rec["page_content"],
                        metadata=rec.get("metadata", {}),
                    ))
    except Exception as e:
        logger.warning(f"[Ingest] Corpus at {path} unreadable ({e}) — ignoring it")
        return None
    return docs or None


def corpus_destinations() -> List[str]:
    """Destinations currently covered, for reporting and coverage checks."""
    docs = load_corpus()
    if not docs:
        return []
    return sorted({
        d.metadata.get("destination_name") or d.metadata.get("destination", "")
        for d in docs
        if d.metadata.get("destination") not in (None, GENERAL_KNOWLEDGE)
    } - {""})


# ══════════════════════════════════════════════════════════════
# SECTION 4 — Ingest
# ══════════════════════════════════════════════════════════════

def ingest(
    destinations: Iterable[str],
    rebuild_index: bool = True,
    delay_s: float = 1.0,
    merge: bool = False,
) -> List[Document]:
    """
    Fetch, chunk and index destinations. Returns the resulting corpus.

    merge=True keeps everything already indexed and adds these destinations to
    it — the behaviour you want for `--cities Tashkent`, which should extend
    the guidebook rather than reduce it to one city. Re-ingesting a
    destination that is already present replaces just that destination's
    chunks, so the command stays idempotent.

    `delay_s` spaces out requests; Wikivoyage is a donated service and this is
    a handful of reads, not a crawl.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=rag_config.chunk_size,
        chunk_overlap=rag_config.chunk_overlap,
        separators=["\n\n", "\n", ". ", "! ", "? ", " ", ""],
    )

    session = requests.Session()
    all_docs: List[Document] = []
    ok, failed = [], []

    destinations = list(destinations)
    articles = fetch_articles(destinations, session=session, delay_s=delay_s)

    for resolved, (_, text, url, requested) in sorted(articles.items()):
        # Only a genuine redirect needs an alias (Marrakesh -> Marrakech);
        # when the names already normalise the same, one tag is enough.
        alias = (
            requested
            if _destination_key(requested) != _destination_key(resolved)
            else None
        )
        if alias:
            logger.info(f"[Ingest]   '{requested}' redirected to '{resolved}' — aliased")
        docs = article_to_documents(resolved, text, url, splitter, alias=alias)
        if not docs:
            failed.append(resolved)
            continue
        all_docs.extend(docs)
        ok.append(resolved)
        logger.info(f"[Ingest]   {resolved}: {len(docs)} chunks from {len(text):,} chars")

    # Anything asked for that never came back (missing page, stub) is reported
    # rather than silently lost. Compared against the REQUESTED titles, not the
    # resolved ones, so a redirect (Marrakesh -> Marrakech) counts as a success.
    got = {_destination_key(req) for (_, _, _, req) in articles.values()}
    failed.extend(d for d in destinations if _destination_key(d) not in got)

    if merge:
        existing = load_corpus() or []
        fresh_keys = {_destination_key(name) for name in ok}
        carried = [
            d for d in existing
            if d.metadata.get("destination") != GENERAL_KNOWLEDGE
            and _destination_key(d.metadata.get("destination", "")) not in fresh_keys
        ]
        logger.info(
            f"[Ingest] Merging: kept {len(carried)} existing chunks, "
            f"adding {len(all_docs)} new"
        )
        all_docs = carried + all_docs

    # Keep the hand-written general advice: it is destination-agnostic and
    # covers practicalities (insurance, packing, booking timing) that
    # city articles assume you already know.
    all_docs.extend(_general_advice_documents())

    if not ok:
        logger.error("[Ingest] Nothing was fetched — leaving the existing store alone")
        return all_docs

    if rebuild_index:
        _rebuild_vector_store(all_docs)
    save_corpus(all_docs)

    logger.info(
        f"[Ingest] Done | {len(ok)} destinations, {len(all_docs)} chunks"
        + (f" | failed: {', '.join(failed)}" if failed else "")
    )
    return all_docs


def _general_advice_documents() -> List[Document]:
    """Destination-agnostic practicalities, tagged GENERAL_KNOWLEDGE."""
    texts = [
        "Travel insurance is strongly recommended for international trips. "
        "Always carry a photocopy of your passport. Check visa requirements 3 months "
        "in advance. Travel adapters are needed for different outlet types globally. "
        "Notify your bank of travel dates to prevent card blocks.",

        "Budget travel tips: Book flights 6-8 weeks in advance for the best prices. "
        "Travel on Tuesdays and Wednesdays for cheaper airfares. Use flight price "
        "tracking. Hostels and guesthouses save 60-70% versus hotels. Cooking at "
        "accommodation with a kitchen cuts food costs substantially.",

        "Packing essentials: lightweight layers, a universal adapter, a portable "
        "charger, offline maps downloaded in advance, a translation app, a small "
        "first aid kit, rehydration salts, and photocopies of all documents stored "
        "in email or cloud storage.",
    ]
    return [
        Document(
            page_content=t,
            metadata={
                "source": "curated_general_advice",
                "destination": GENERAL_KNOWLEDGE,
                "destination_name": "General",
                "area": "general",
                "section": "General travel advice",
                "url": "",
            },
        )
        for t in texts
    ]


def _rebuild_vector_store(documents: List[Document]) -> None:
    """Drop and rebuild the Chroma index so it matches the new corpus."""
    # Imported here so `--list` and the corpus helpers stay import-light.
    from rag.rag import build_vector_store, _discard_persist_dir

    logger.info("[Ingest] Rebuilding vector store…")
    _discard_persist_dir(rag_config.persist_dir)
    build_vector_store(documents)
    logger.info("[Ingest] Vector store rebuilt")


# ══════════════════════════════════════════════════════════════
# SECTION 5 — CLI
# ══════════════════════════════════════════════════════════════

def check_grounding(sample: int = 6) -> int:
    """
    Verify the grounding gate against the corpus that is actually indexed.

    Indexed destinations should come back grounded; destinations that were
    never ingested should be gated. This is what `rerank_min_score` is tuned
    against — re-run it after changing the corpus, the reranker or the floor
    instead of guessing whether the threshold still separates the two.
    """
    from rag.rag import get_retriever

    covered = corpus_destinations()
    if not covered:
        print("No corpus built yet. Run: python -m rag.ingest")
        return 1

    indexed = covered[:sample]

    # Derive the negatives from the corpus rather than hardcoding them.
    # A fixed list rots the moment someone ingests one of those cities, and
    # then the harness fails for a correct system - which is worse than no
    # harness, because it trains you to ignore it.
    candidates = ["Asuncion", "Windhoek", "Chisinau", "Tirana", "Ulaanbaatar",
                  "Podgorica", "Gaborone", "Paramaribo", "Bishkek", "Nouakchott"]
    covered_keys = {_destination_key(c) for c in covered}
    absent = [c for c in candidates if _destination_key(c) not in covered_keys][:sample]
    if len(absent) < 2:
        print("Warning: too few un-ingested cities left to test gating.")

    queries = {
        "general": "What should a traveller know about visiting {c}?",
        "hotel": "Where should I stay in {c} and what do hotels cost?",
        "food": "What food and restaurants is {c} known for?",
    }

    retriever = get_retriever()
    print(f"\n{'destination':22} {'state':9} " + " ".join(f"{k:>9}" for k in queries))
    print("-" * 62)

    hits = misses = gated = leaked = 0
    for city, state in [(c, "indexed") for c in indexed] + [(c, "absent") for c in absent]:
        cells = []
        for tmpl in queries.values():
            res = retriever.retrieve(tmpl.format(c=city), destination=city)
            cells.append(f"{'YES' if res.grounded else 'no':>9}")
            if state == "indexed":
                hits += res.grounded
                misses += not res.grounded
            else:
                leaked += res.grounded
                gated += not res.grounded
        print(f"{city:22} {state:9} " + " ".join(cells))

    total_idx, total_abs = hits + misses, gated + leaked
    print(f"\nindexed grounded : {hits}/{total_idx}")
    print(f"absent gated     : {gated}/{total_abs}   false grounding = {leaked}")
    if leaked:
        print("\nFAIL — an un-ingested destination was reported as grounded.")
        return 1
    print("\nPASS — no destination was grounded on knowledge the corpus lacks.")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the travel knowledge base from Wikivoyage."
    )
    parser.add_argument(
        "--cities",
        help="Comma-separated destinations to ADD to the existing corpus. "
             "Without this, the built-in list is (re)built from scratch.",
    )
    parser.add_argument(
        "--replace", action="store_true",
        help="With --cities, replace the whole corpus instead of adding to it.",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="Show which destinations are currently indexed, then exit.",
    )
    parser.add_argument(
        "--backlog", action="store_true",
        help="Show destinations users asked for that the corpus cannot answer, "
             "ranked by demand. Add --ingest to fetch them.",
    )
    parser.add_argument(
        "--ingest", action="store_true",
        help="With --backlog, ingest every destination in the backlog.",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Verify the grounding gate against the indexed corpus, then exit.",
    )
    parser.add_argument(
        "--delay", type=float, default=1.0,
        help="Seconds between API batches (default 1.0).",
    )
    args = parser.parse_args(argv)

    if args.backlog:
        # Episodic memory -> a concrete improvement to semantic memory.
        # What gets distilled is observed demand, not generated content, so
        # nothing the model invented can end up in the retrieval corpus.
        from memory.store import ungrounded_demand

        gaps = ungrounded_demand()
        if not gaps:
            print("No gaps: every destination asked for so far is covered.")
            return 0

        print(f"\n{len(gaps)} destination(s) asked for but missing from the guidebook:\n")
        print(f"  {'destination':24}{'requests':>9}   last asked")
        print("  " + "-" * 52)
        for g in gaps:
            print(f"  {g['destination']:24}{g['requests']:>9}   {g['last_asked'][:10]}")

        if not args.ingest:
            print("\nAdd them with:  python -m rag.ingest --backlog --ingest")
            return 0

        names = [g["destination"] for g in gaps]
        print(f"\nIngesting {len(names)} destination(s)...")
        ingest(names, delay_s=args.delay, merge=True)
        print("Done. Verify with: python -m rag.ingest --check")
        return 0

    if args.check:
        return check_grounding()

    if args.list:
        covered = corpus_destinations()
        docs = load_corpus()
        if not covered:
            print("No corpus built yet. Run: python -m rag.ingest")
            return 1
        print(f"{len(docs)} chunks covering {len(covered)} destinations:\n")
        for name in covered:
            n = sum(1 for d in docs if d.metadata.get("destination_name") == name)
            print(f"  {name:22} {n:4} chunks")
        return 0

    adding = bool(args.cities) and not args.replace
    cities = (
        [c.strip() for c in args.cities.split(",") if c.strip()]
        if args.cities else DEFAULT_DESTINATIONS
    )
    already = len(corpus_destinations())
    print(f"{'Adding' if adding else 'Ingesting'} {len(cities)} destination(s) "
          f"from Wikivoyage"
          + (f" (keeping the {already} already indexed)" if adding else "") + "…")
    docs = ingest(cities, delay_s=args.delay, merge=adding)
    print(f"\nDone — {len(docs)} chunks indexed.")
    print("Check coverage with: python -m rag.ingest --list")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
