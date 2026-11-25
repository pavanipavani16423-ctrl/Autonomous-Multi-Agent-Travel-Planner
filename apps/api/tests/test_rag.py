from __future__ import annotations

import pytest

from voyager.rag import text
from voyager.rag.ingest import expand_city
from voyager.rag.store import Guidebook


def test_destination_key_strips_diacritics() -> None:
    assert text.destination_key("Zürich, Switzerland") == "zurich"
    assert text.destination_key("  Kyoto ") == "kyoto"


def test_split_sections_keeps_subheadings_inside_parent() -> None:
    article = "Lead text here.\n== See ==\nTemple A.\n=== Museums ===\nMuseum B.\n== Eat ==\nNoodles."
    secs = dict(text.split_sections(article))
    assert secs["Understand"] == "Lead text here."
    assert "Museum B" in secs["See"] and "Museums" in secs["See"]
    assert secs["Eat"] == "Noodles."


def test_chunk_text_respects_size_and_overlap() -> None:
    body = " ".join(f"Sentence number {i} about the city." for i in range(200))
    chunks = text.chunk_text(body, size=300, overlap=50)
    assert all(len(c) <= 300 for c in chunks)
    assert len(chunks) > 5


def test_citation_ids_are_stable() -> None:
    assert text.citation_id("abc") == text.citation_id("abc")
    assert text.citation_id("abc").startswith("wv-")


def test_coverage_and_destination_prefilter(guidebook: Guidebook) -> None:
    assert guidebook.is_covered("Kyoto")
    res = guidebook.search("famous temples and shrines", "Kyoto", k=6)
    assert res.covered and res.passages
    assert all(p.destination == "kyoto" for p in res.passages), "payload filter must exclude other cities"
    assert 0 < res.top_score <= 1


def test_section_filter(guidebook: Guidebook) -> None:
    res = guidebook.search("where to stay hotels ryokan", "Kyoto", sections=["Sleep"], k=4)
    assert res.passages and all(p.section == "Sleep" for p in res.passages)


def test_grounding_gate_uncovered_city(guidebook: Guidebook) -> None:
    res = guidebook.search("top sights", "Atlantis", k=5)
    assert not res.covered and res.passages == []
    assert not guidebook.is_covered("Atlantis")


def test_thin_city_is_not_covered(guidebook: Guidebook) -> None:
    # tokyo has 20 passages in the tiny corpus (>= 15) but paris 25; both covered. A city with 0 isn't.
    assert guidebook.passages_for("tokyo") == 20
    assert guidebook.is_covered("Tokyo")


@pytest.mark.anyio
async def test_on_demand_expansion(guidebook: Guidebook) -> None:
    assert not guidebook.is_covered("Ljubljana")
    out = await expand_city("Ljubljana", "Slovenia", book=guidebook)
    assert out["status"] == "expanded" and out["passages"] >= 5
    res = guidebook.search("castle funicular old town", "Ljubljana", k=3)
    assert res.passages and res.passages[0].destination == "ljubljana"
    assert "Ljubljana Castle" in " ".join(p.text for p in res.passages)


@pytest.mark.anyio
async def test_expansion_without_article_returns_none(guidebook: Guidebook) -> None:
    out = await expand_city("Nowhereville", "Atlantis", book=guidebook)
    assert out["status"] == "none" and out["passages"] == 0
