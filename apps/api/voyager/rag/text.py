"""Text helpers shared by ingest and retrieval: destination keys, Wikivoyage section parsing, chunking.

Ported from v1 `rag/ingest.py` (section skeleton -> area mapping, heading parser, 120-char floor,
"City — Section:" prefix that keeps the city and topic inside the embedded text).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
import uuid

GENERAL_KNOWLEDGE = "__general__"

# Wikivoyage's article skeleton -> the retrieval area each section answers
SECTION_AREA: dict[str, str] = {
    "understand": "general", "get in": "general", "get around": "general", "see": "general",
    "do": "general", "buy": "general", "itineraries": "general", "stay safe": "general",
    "stay healthy": "general", "respect": "general", "connect": "general", "cope": "general",
    "districts": "general", "learn": "general", "talk": "general", "work": "general",
    "eat": "food", "drink": "food", "sleep": "hotel",
}
SKIP_SECTIONS = {"external links", "references", "see also", "nearby", "go next"}
MIN_CHUNK_CHARS = 120
CHUNK_SIZE = 900
CHUNK_OVERLAP = 120

_HEADING_RE = re.compile(r"^(={2,4})\s*(.+?)\s*\1\s*$", re.M)


def destination_key(name: str) -> str:
    """'Zürich, Switzerland' -> 'zurich'. Diacritics stripped so typed ASCII matches the wiki title."""
    base = (name or "").split(",")[0].strip().lower()
    decomposed = unicodedata.normalize("NFKD", base)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def split_sections(text: str) -> list[tuple[str, str]]:
    """Split a plaintext Wikivoyage article into (top-level heading, body). Sub-headings stay inside
    their parent so a price list keeps its 'Sleep' context."""
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return [("Understand", text)]
    sections: list[tuple[str, str]] = []
    lead = text[: matches[0].start()].strip()
    if lead:
        sections.append(("Understand", lead))
    heading: str | None = None
    start = 0
    for m in matches:
        if len(m.group(1)) == 2:
            if heading is not None:
                sections.append((heading, text[start:m.start()].strip()))
            heading, start = m.group(2), m.end()
    if heading is not None:
        sections.append((heading, text[start:].strip()))
    return [(h, b) for h, b in sections if b]


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Recursive-ish splitter: paragraphs, then sentences, then hard cut; with overlap."""
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    pieces: list[str] = []
    for para in re.split(r"\n\s*\n|\n", text):
        para = para.strip()
        if not para:
            continue
        if len(para) <= size:
            pieces.append(para)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", para)
        for s in sentences:
            while len(s) > size:
                pieces.append(s[:size])
                s = s[size - overlap:]
            if s:
                pieces.append(s)
    chunks: list[str] = []
    current = ""
    for p in pieces:
        if len(current) + len(p) + 1 <= size:
            current = f"{current}\n{p}" if current else p
        else:
            if current:
                chunks.append(current)
            tail = current[-overlap:] if overlap and current else ""
            current = (tail + " " + p).strip() if tail and len(tail) + len(p) + 1 <= size else p
    if current:
        chunks.append(current)
    return chunks


def article_records(name: str, text: str, url: str, alias: str = "", country: str = "") -> list[dict]:
    """One Wikivoyage article -> corpus records (same shape as data/corpus.jsonl)."""
    key = destination_key(name)
    records = []
    for heading, body in split_sections(text):
        if heading.strip().lower() in SKIP_SECTIONS:
            continue
        area = SECTION_AREA.get(heading.strip().lower(), "general")
        for chunk in chunk_text(body):
            chunk = chunk.strip()
            if len(chunk) < MIN_CHUNK_CHARS:
                continue
            records.append({
                "page_content": f"{name} — {heading}: {chunk}",
                "metadata": {"source": "wikivoyage", "destination": key, "destination_name": name,
                             "destination_alias": destination_key(alias) if alias else "",
                             "area": area, "section": heading, "url": url, "country": country},
            })
    return records


def point_id(text: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, text))


def citation_id(text: str) -> str:
    """Stable short id for a guidebook passage, used as the citation id across the plan."""
    return "wv-" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())
