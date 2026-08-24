# ============================================================
# ui/pdf.py — Render a TravelPlan as a printable itinerary
# ============================================================
# The JSON download was only useful to someone who could read JSON, which is
# nobody the app is actually for. This produces the thing a traveller wants:
# a document they can print, forward, or open on a phone at the airport.
#
# Print-first choices:
#   • Dark text on white — the app's dark theme is unreadable on paper.
#   • The provenance note travels WITH the document. A printed page outlives
#     the browser session, so a page that omits "these prices are examples"
#     is the version that gets acted on.
# ============================================================

from __future__ import annotations

import io
from datetime import date
from typing import Any, List, Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, KeepTogether, PageBreak, PageTemplate,
    Paragraph, Spacer, Table, TableStyle,
)

# Print palette — the on-screen sand accent, darkened enough to stay legible
# on white at small sizes.
ACCENT = colors.HexColor("#B0762A")
INK = colors.HexColor("#1A1D23")
MUTED = colors.HexColor("#5A6474")
FAINT = colors.HexColor("#8A93A3")
RULE = colors.HexColor("#DDE1E8")
WARN_BG = colors.HexColor("#FDF6E7")
WARN_EDGE = colors.HexColor("#E0B968")

SOURCE_LABEL = {
    "weather": "weather", "maps": "travel times", "hotel": "hotel prices",
    "restaurant": "restaurants", "flight": "flight prices",
}


def _styles() -> dict:
    base = getSampleStyleSheet()
    body = base["BodyText"]
    return {
        "title": ParagraphStyle(
            "title", parent=body, fontName="Helvetica-Bold", fontSize=24,
            leading=28, textColor=INK, spaceAfter=2,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=body, fontName="Helvetica", fontSize=10.5,
            leading=15, textColor=MUTED, spaceAfter=14,
        ),
        "h2": ParagraphStyle(
            "h2", parent=body, fontName="Helvetica-Bold", fontSize=13.5,
            leading=17, textColor=INK, spaceBefore=16, spaceAfter=7,
        ),
        "h3": ParagraphStyle(
            "h3", parent=body, fontName="Helvetica-Bold", fontSize=10.5,
            leading=14, textColor=ACCENT, spaceBefore=9, spaceAfter=3,
        ),
        "body": ParagraphStyle(
            "body", parent=body, fontName="Helvetica", fontSize=9.8,
            leading=14.5, textColor=INK, alignment=TA_LEFT, spaceAfter=4,
        ),
        "muted": ParagraphStyle(
            "muted", parent=body, fontName="Helvetica", fontSize=8.8,
            leading=12.5, textColor=MUTED, spaceAfter=3,
        ),
        "bullet": ParagraphStyle(
            "bullet", parent=body, fontName="Helvetica", fontSize=9.8,
            leading=14.5, textColor=INK, leftIndent=10, bulletIndent=2,
            spaceAfter=1.5,
        ),
        "summary": ParagraphStyle(
            "summary", parent=body, fontName="Helvetica-Oblique", fontSize=10.5,
            leading=16, textColor=INK, leftIndent=8, borderPadding=0,
            spaceBefore=6, spaceAfter=10,
        ),
        "note": ParagraphStyle(
            "note", parent=body, fontName="Helvetica", fontSize=8.8,
            leading=12.5, textColor=INK, spaceAfter=2,
        ),
    }


# The model writes typographically — non-breaking hyphens, en dashes, curly
# quotes, ≈. The base-14 PDF fonts are WinAnsi and have no glyph for most of
# them, so they render as a black box (“6■day”). Fold them to ASCII before
# they reach the canvas.
_TYPOGRAPHIC = {
    "‑": "-", "‐": "-", "‒": "-", "–": "-", "—": "-",
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"',
    "…": "...", "≈": "~", "≠": "!=",
    " ": " ", " ": " ", " ": " ", "​": "",
    "→": "->", "←": "<-", "•": "-",
}


def _ascii_safe(text: str) -> str:
    """Replace glyphs the PDF core fonts cannot draw."""
    for bad, good in _TYPOGRAPHIC.items():
        text = text.replace(bad, good)
    # Anything still outside Latin-1 has no glyph either; drop it rather than
    # printing a box.
    return text.encode("latin-1", "ignore").decode("latin-1")


def _esc(value: Any) -> str:
    """Escape for reportlab's mini-HTML; plan text is model-authored."""
    text = str(value if value is not None else "")
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return _ascii_safe(text)


def _place(name: Any) -> str:
    """
    Present a place name properly.

    Someone typing "dubai" should not get a document headed "mumbai to dubai".
    Only touches all-lowercase input so "New York City" and "Rio de Janeiro"
    keep their own capitalisation.
    """
    raw = str(name or "").strip()
    return _esc(raw.title() if raw.islower() else raw)


def _rule(width: float = 170 * mm) -> Table:
    t = Table([[""]], colWidths=[width], rowHeights=[0.6])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), RULE)]))
    return t


def _notice(text: str, styles: dict, width: float = 170 * mm) -> Table:
    """A boxed caution — used for the 'these are examples' provenance note."""
    t = Table([[Paragraph(text, styles["note"])]], colWidths=[width])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), WARN_BG),
        ("BOX", (0, 0), (-1, -1), 0.6, WARN_EDGE),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return t


def _footer(canvas, doc):
    """Destination, page number and the honesty line on every page."""
    canvas.saveState()
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.5)
    canvas.line(20 * mm, 15 * mm, 190 * mm, 15 * mm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(FAINT)
    canvas.drawString(20 * mm, 10.5 * mm, getattr(doc, "footer_left", ""))
    canvas.drawRightString(190 * mm, 10.5 * mm, f"Page {doc.page}")
    canvas.restoreState()


def build_itinerary_pdf(plan: Any, request: Any) -> bytes:
    """
    Render the plan to PDF bytes.

    Sections with no data are skipped rather than printed empty — a heading
    with nothing under it reads as a broken document.
    """
    styles = _styles()
    buf = io.BytesIO()

    doc = BaseDocTemplate(
        buf, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=22 * mm,
        title=f"{_place(request.destination)} itinerary",
        author="Voyager - AI Travel Planner",
    )
    doc.footer_left = _ascii_safe(
        f"{_place(request.origin)} to {_place(request.destination)} "
        f"| {request.departure_date}"
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=_footer)])

    story: List[Any] = []
    S = story.append

    try:
        nights = (date.fromisoformat(request.return_date)
                  - date.fromisoformat(request.departure_date)).days
    except (ValueError, TypeError):
        nights = 0

    # ── Header ────────────────────────────────────────────
    S(Paragraph(
        f"{_place(request.origin)} &rarr; {_place(request.destination)}", styles["title"]))
    S(Paragraph(
        f"{_esc(request.departure_date)} – {_esc(request.return_date)} &nbsp;·&nbsp; "
        f"{nights} nights &nbsp;·&nbsp; {request.travellers} traveller(s) "
        f"&nbsp;·&nbsp; {_esc(str(request.travel_purpose).title())}",
        styles["subtitle"]))
    S(_rule())

    if plan.executive_summary:
        S(Paragraph(_esc(plan.executive_summary), styles["summary"]))

    # ── Provenance ────────────────────────────────────────
    mocked = getattr(plan, "mocked_sources", []) or []
    if mocked:
        names = ", ".join(SOURCE_LABEL.get(m, m) for m in mocked)
        S(_notice(
            f"<b>Some figures in this document are examples, not live data.</b><br/>"
            f"The {_esc(names)} shown here come from sample data. Treat them as a "
            f"guide to what to expect rather than prices to book on.",
            styles))
        S(Spacer(1, 8))

    if plan.budget:
        b = plan.budget
        S(_money_summary(b, request, styles))

    # ── Itinerary ─────────────────────────────────────────
    if plan.route and plan.route.day_wise_itinerary:
        S(Paragraph("Your itinerary", styles["h2"]))
        if plan.route.best_route_summary:
            S(Paragraph(_esc(plan.route.best_route_summary), styles["muted"]))
            S(Spacer(1, 6))
        for day in plan.route.day_wise_itinerary:
            S(KeepTogether(_day_block(day, styles)))

    # ── Stay ──────────────────────────────────────────────
    if plan.hotels:
        h = plan.hotels
        blocks: List[Any] = [Paragraph("Where to stay", styles["h2"])]
        if h.recommended_area:
            blocks.append(Paragraph(
                f"Best area to base yourself: <b>{_esc(h.recommended_area)}</b>",
                styles["muted"]))
        S(KeepTogether(blocks))
        for label, group in [("Good value", h.budget_hotels),
                             ("A step up", h.premium_hotels),
                             ("Good for families", h.family_hotels)]:
            if not group:
                continue
            S(Paragraph(label, styles["h3"]))
            for hotel in group:
                S(KeepTogether(_hotel_block(hotel, styles)))

    # ── Food ──────────────────────────────────────────────
    if plan.food:
        f = plan.food
        S(Paragraph("Food &amp; drink", styles["h2"]))
        if f.average_meal_cost_usd:
            S(Paragraph(
                f"Typical meal: <b>${f.average_meal_cost_usd:,.0f}</b> per person",
                styles["muted"]))
        for label, items in [
            ("Don't leave without trying", f.local_specialties),
            ("Vegetarian", f.vegetarian_dishes),
            ("Meat &amp; seafood", f.non_vegetarian_dishes),
            ("Street food", f.street_food_recommendations),
        ]:
            if items:
                S(Paragraph(label, styles["h3"]))
                S(Paragraph(_esc(", ".join(items)), styles["body"]))
        if f.restaurant_suggestions:
            S(Paragraph("Where to eat", styles["h3"]))
            for r in f.restaurant_suggestions:
                S(Paragraph(
                    f"<b>{_esc(r.name)}</b> &nbsp;{_esc(r.price_range)} &nbsp;"
                    f"{r.rating:g}/5<br/>"
                    f"<font color='#5A6474'>{_esc(r.cuisine_type)} — try the "
                    f"{_esc(r.must_try_dish)}. {_esc(r.location_hint)}</font>",
                    styles["body"]))

    # ── Weather ───────────────────────────────────────────
    if plan.weather:
        w = plan.weather
        S(Paragraph("Weather", styles["h2"]))
        S(Paragraph(
            f"<b>{_esc(w.condition)}</b> &nbsp;·&nbsp; {w.current_temp_celsius:g}°C "
            f"&nbsp;·&nbsp; humidity {w.humidity_percent}% "
            f"&nbsp;·&nbsp; wind {w.wind_speed_kmh:.0f} km/h", styles["body"]))
        for warn in (w.travel_warnings or []):
            S(Paragraph(f"<b>Note:</b> {_esc(warn)}", styles["muted"]))
        if w.clothing_suggestions:
            S(Paragraph("What to pack", styles["h3"]))
            for item in w.clothing_suggestions:
                S(Paragraph(_esc(item), styles["bullet"], bulletText="·"))

    # ── Budget ────────────────────────────────────────────
    if plan.budget:
        S(Paragraph("Budget", styles["h2"]))
        S(_budget_table(plan.budget, styles))
        if plan.budget.saving_tips:
            S(Paragraph("Ways to spend less", styles["h3"]))
            for tip in plan.budget.saving_tips:
                S(Paragraph(_esc(tip), styles["bullet"], bulletText="·"))

    # ── Worth checking ────────────────────────────────────
    checks = [w for w in (plan.warnings or []) if not w.startswith("[DataSources]")]
    if checks:
        S(Paragraph("Worth checking before you book", styles["h2"]))
        for w in checks:
            clean = w.split("] ", 1)[-1] if w.startswith("[") else w
            S(Paragraph(_esc(clean), styles["bullet"], bulletText="·"))

    S(Spacer(1, 14))
    S(_rule())
    S(Paragraph(
        f"Plan {_esc(plan.plan_id)} · generated {_esc(str(plan.created_at)[:10])} · "
        "Confirm opening times, prices and visa requirements before booking.",
        styles["muted"]))

    doc.build(story)
    return buf.getvalue()


def _money_summary(b: Any, request: Any, styles: dict) -> Table:
    over = b.total_trip_cost_usd > request.budget_usd
    delta = abs(b.total_trip_cost_usd - request.budget_usd)
    verdict = (f"${delta:,.0f} over budget" if over else f"${delta:,.0f} to spare")

    data = [[
        Paragraph("<font size=7.5 color='#8A93A3'>ESTIMATED COST</font><br/>"
                  f"<font size=15><b>${b.total_trip_cost_usd:,.0f}</b></font>", styles["body"]),
        Paragraph("<font size=7.5 color='#8A93A3'>YOUR BUDGET</font><br/>"
                  f"<font size=15><b>${request.budget_usd:,.0f}</b></font>", styles["body"]),
        Paragraph("<font size=7.5 color='#8A93A3'>DIFFERENCE</font><br/>"
                  f"<font size=15 color='{'#B03A3A' if over else '#3A7D52'}'>"
                  f"<b>{verdict}</b></font>", styles["body"]),
    ]]
    t = Table(data, colWidths=[56 * mm, 56 * mm, 58 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (0, -1), 0),
    ]))
    return t


def _day_block(day: Any, styles: dict) -> List[Any]:
    out = [Paragraph(
        f"<font color='#B0762A'><b>DAY {day.day}</b></font> &nbsp; "
        f"<font color='#8A93A3'>{_esc(day.date)}</font> &nbsp; "
        f"<font color='#5A6474'>· ${day.estimated_cost_usd:,.0f}</font>",
        styles["h3"])]
    for act in day.activities:
        out.append(Paragraph(_esc(act), styles["bullet"], bulletText="·"))
    out.append(Paragraph(
        f"<font color='#5A6474'>Getting around: {_esc(day.transportation)} &nbsp;·&nbsp; "
        f"Staying: {_esc(day.accommodation)}</font>", styles["muted"]))
    out.append(Spacer(1, 7))
    return out


def _hotel_block(h: Any, styles: dict) -> List[Any]:
    amenities = ", ".join((h.amenities or [])[:6])
    return [
        Paragraph(
            f"<b>{_esc(h.name)}</b> &nbsp; "
            f"<font color='#B0762A'><b>${h.price_per_night_usd:,.0f}</b></font>"
            f"<font color='#8A93A3'> / night &nbsp; · &nbsp; {h.rating:g}/5</font>",
            styles["body"]),
        Paragraph(
            f"<font color='#5A6474'>{_esc(h.location_description)}"
            + (f"<br/>{_esc(amenities)}" if amenities else "")
            + (f"<br/><i>{_esc(h.booking_tip)}</i>" if h.booking_tip else "")
            + "</font>", styles["muted"]),
        Spacer(1, 6),
    ]


def _budget_table(b: Any, styles: dict) -> Table:
    bd = b.per_person_breakdown
    rows = [["", "Per person", "Total"]]
    for label, value in [
        ("Flights", bd.flights_usd), ("Accommodation", bd.accommodation_usd),
        ("Food", bd.food_usd), ("Local transport", bd.local_transport_usd),
        ("Activities", bd.activities_usd), ("Other", bd.miscellaneous_usd),
    ]:
        share = (value / bd.total_usd * b.total_trip_cost_usd) if bd.total_usd else 0
        rows.append([label, f"${value:,.0f}", f"${share:,.0f}"])
    rows.append(["Total", f"${bd.total_usd:,.0f}", f"${b.total_trip_cost_usd:,.0f}"])

    t = Table(rows, colWidths=[100 * mm, 35 * mm, 35 * mm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), FAINT),
        ("TEXTCOLOR", (0, 1), (-1, -2), INK),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, RULE),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, INK),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#FAFBFC")]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


__all__ = ["build_itinerary_pdf"]
