# ============================================================
# ui/theme.py — Design system for the travel planner
# ============================================================
# One place for every colour, radius and type rule, so the app reads as a
# product rather than as a pile of inline styles.
#
# Design intent: a calm, editorial travel site. The previous UI advertised
# its own architecture — agent counts, model sizes, framework badges. None of
# that is a reason for someone to plan a trip, so none of it appears here.
# ============================================================

# ── Palette ──────────────────────────────────────────────────
# Deep neutral ground with a single warm accent. One accent keeps emphasis
# meaningful; the old neon multi-hue scheme made everything shout equally.
INK = "#0B0E14"        # page
SURFACE = "#12161F"    # cards
SURFACE_2 = "#171C27"  # raised
BORDER = "#232A38"
BORDER_STRONG = "#303A4D"

TEXT = "#E8EBF0"       # primary copy
TEXT_MUTED = "#9AA5B8" # secondary copy
TEXT_FAINT = "#6B7789" # captions

ACCENT = "#E0A458"       # warm sand — the single emphasis colour
ACCENT_SOFT = "#F0C68B"
ACCENT_DIM = "rgba(224,164,88,0.12)"

OK = "#5FB88A"
WARN = "#D9A441"
INFO = "#6E9BD1"
DANGER = "#CC6B6B"


CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Fraunces:opsz,wght@9..144,500;9..144,600&display=swap');

/* ── Ground ───────────────────────────────────────────── */
.stApp {{
    background: {INK};
    color: {TEXT};
}}
html, body, [class*="css"], .stMarkdown, p, span, div, label {{
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    color: {TEXT};
}}

/* Streamlit chrome we do not want in a product UI */
#MainMenu, footer, header {{ visibility: hidden; }}
.block-container {{ padding-top: 2.2rem; padding-bottom: 4rem; max-width: 1120px; }}

/* ── Type ─────────────────────────────────────────────── */
h1, h2, h3 {{
    font-family: 'Fraunces', Georgia, serif;
    color: {TEXT};
    letter-spacing: -0.01em;
    font-weight: 600;
}}
h1 {{ font-size: 2.9rem; line-height: 1.12; margin: 0 0 0.6rem; }}
h2 {{ font-size: 1.5rem; margin: 0 0 0.6rem; }}
h3 {{ font-size: 1.1rem; margin: 0 0 0.4rem; }}

.lede {{
    color: {TEXT_MUTED};
    font-size: 1.06rem;
    line-height: 1.6;
    max-width: 34rem;
}}
.eyebrow {{
    color: {ACCENT};
    font-size: 0.76rem;
    font-weight: 600;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    margin-bottom: 0.7rem;
}}
.caption {{ color: {TEXT_FAINT}; font-size: 0.83rem; }}

/* ── Cards ────────────────────────────────────────────── */
.card {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 14px;
    padding: 1.4rem 1.5rem;
    margin-bottom: 1rem;
}}
.card-tight {{ padding: 1rem 1.15rem; }}

/* ── Form controls ────────────────────────────────────── */
.stTextInput input, .stNumberInput input, .stDateInput input, .stTextArea textarea {{
    background: {SURFACE_2} !important;
    color: {TEXT} !important;
    border: 1px solid {BORDER_STRONG} !important;
    border-radius: 9px !important;
    font-size: 0.95rem !important;
    padding: 0.55rem 0.75rem !important;
}}
.stTextInput input:focus, .stNumberInput input:focus, .stTextArea textarea:focus {{
    border-color: {ACCENT} !important;
    box-shadow: 0 0 0 3px {ACCENT_DIM} !important;
}}
.stTextInput input::placeholder, .stTextArea textarea::placeholder {{ color: {TEXT_FAINT} !important; }}

div[data-baseweb="select"] > div {{
    background: {SURFACE_2} !important;
    border: 1px solid {BORDER_STRONG} !important;
    border-radius: 9px !important;
    color: {TEXT} !important;
}}
div[data-baseweb="popover"] li {{ background: {SURFACE_2} !important; color: {TEXT} !important; }}
div[data-baseweb="popover"] li:hover {{ background: {BORDER} !important; }}

.stForm label, .stTextInput label, .stNumberInput label,
.stDateInput label, .stSelectbox label, .stTextArea label {{
    color: {TEXT_MUTED} !important;
    font-size: 0.84rem !important;
    font-weight: 500 !important;
    letter-spacing: 0.01em;
}}
[data-testid="stForm"] {{ border: none; padding: 0; }}

/* ── Buttons ──────────────────────────────────────────── */
.stButton > button, .stFormSubmitButton > button, .stDownloadButton > button {{
    background: {ACCENT};
    color: #1A1206;
    border: none;
    border-radius: 9px;
    font-weight: 600;
    font-size: 0.95rem;
    padding: 0.62rem 1.4rem;
    transition: background 0.15s ease;
}}
.stButton > button:hover, .stFormSubmitButton > button:hover, .stDownloadButton > button:hover {{
    background: {ACCENT_SOFT};
    color: #1A1206;
}}
.stButton > button[kind="secondary"] {{
    background: transparent;
    color: {TEXT_MUTED};
    border: 1px solid {BORDER_STRONG};
}}

/* ── Tabs ─────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {{
    gap: 0.4rem;
    border-bottom: 1px solid {BORDER};
    margin-bottom: 1.2rem;
}}
.stTabs [data-baseweb="tab"] {{
    background: transparent;
    color: {TEXT_MUTED};
    font-weight: 500;
    font-size: 0.92rem;
    padding: 0.55rem 0.9rem;
    border-radius: 8px 8px 0 0;
}}
.stTabs [aria-selected="true"] {{
    color: {TEXT} !important;
    border-bottom: 2px solid {ACCENT};
}}

/* ── Trip header ──────────────────────────────────────── */
.trip-head {{
    border-bottom: 1px solid {BORDER};
    padding-bottom: 1.3rem;
    margin-bottom: 1.5rem;
}}
.trip-route {{
    font-family: 'Fraunces', Georgia, serif;
    font-size: 2.3rem;
    font-weight: 600;
    line-height: 1.15;
}}
.trip-meta {{ color: {TEXT_MUTED}; font-size: 0.95rem; margin-top: 0.35rem; }}
.trip-summary {{
    color: {TEXT};
    font-size: 1.02rem;
    line-height: 1.65;
    margin-top: 1.1rem;
    padding-left: 1rem;
    border-left: 2px solid {ACCENT};
}}

/* ── Day cards ────────────────────────────────────────── */
.day {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 1.1rem 1.3rem;
    margin-bottom: 0.7rem;
}}
.day-head {{ display: flex; align-items: baseline; gap: 0.75rem; margin-bottom: 0.7rem; }}
.day-n {{
    color: {ACCENT};
    font-weight: 600;
    font-size: 0.78rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
}}
.day-date {{ color: {TEXT_FAINT}; font-size: 0.85rem; }}
.day-cost {{ margin-left: auto; color: {TEXT_MUTED}; font-size: 0.88rem; font-weight: 500; }}
.act {{ color: {TEXT}; font-size: 0.94rem; line-height: 1.75; padding-left: 1rem; position: relative; }}
.act:before {{ content: "·"; position: absolute; left: 0.25rem; color: {ACCENT}; font-weight: 700; }}
.day-foot {{
    margin-top: 0.7rem; padding-top: 0.65rem;
    border-top: 1px solid {BORDER};
    color: {TEXT_FAINT}; font-size: 0.84rem;
    display: flex; gap: 1.3rem; flex-wrap: wrap;
}}

/* ── Listing rows (hotels, restaurants) ───────────────── */
.listing {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 11px;
    padding: 1rem 1.15rem;
    margin-bottom: 0.6rem;
}}
.listing-top {{ display: flex; align-items: baseline; gap: 0.6rem; }}
.listing-name {{ font-weight: 600; font-size: 1rem; }}
.listing-price {{ margin-left: auto; color: {ACCENT}; font-weight: 600; }}
.listing-sub {{ color: {TEXT_MUTED}; font-size: 0.88rem; margin-top: 0.3rem; line-height: 1.55; }}
.listing-tags {{ margin-top: 0.5rem; }}
.tag {{
    display: inline-block; background: {SURFACE_2}; border: 1px solid {BORDER};
    border-radius: 6px; padding: 0.15rem 0.5rem; margin: 0.15rem 0.3rem 0.15rem 0;
    color: {TEXT_MUTED}; font-size: 0.78rem;
}}

/* ── Stat row ─────────────────────────────────────────── */
.stats {{ display: flex; gap: 2.4rem; flex-wrap: wrap; margin: 0.2rem 0 0.4rem; }}
.stat-k {{ color: {TEXT_FAINT}; font-size: 0.76rem; letter-spacing: 0.08em; text-transform: uppercase; }}
.stat-v {{ font-size: 1.35rem; font-weight: 600; margin-top: 0.15rem; }}

/* ── Notices ──────────────────────────────────────────── */
.notice {{
    border-radius: 11px; padding: 0.85rem 1.1rem; margin-bottom: 0.9rem;
    font-size: 0.9rem; line-height: 1.6; border: 1px solid;
}}
.notice-warn {{ background: rgba(217,164,65,0.07); border-color: rgba(217,164,65,0.3); color: {TEXT}; }}
.notice-ok   {{ background: rgba(95,184,138,0.07); border-color: rgba(95,184,138,0.28); color: {TEXT}; }}
.notice-info {{ background: rgba(110,155,209,0.07); border-color: rgba(110,155,209,0.28); color: {TEXT}; }}
.notice b {{ font-weight: 600; }}

/* ── Progress ─────────────────────────────────────────── */
.stProgress > div > div > div > div {{ background: {ACCENT}; }}
.step {{
    display: flex; align-items: center; gap: 0.7rem;
    color: {TEXT_MUTED}; font-size: 0.95rem;
    padding: 0.7rem 0;
}}
.step-dot {{ width: 7px; height: 7px; border-radius: 50%; background: {ACCENT}; flex: none; }}
.step-time {{ margin-left: auto; color: {TEXT_FAINT}; font-size: 0.83rem; }}

hr {{ border-color: {BORDER}; }}
[data-testid="stExpander"] {{
    background: {SURFACE};
    border: 1px solid {BORDER} !important;
    border-radius: 11px;
}}
[data-testid="stExpander"] summary {{ color: {TEXT_MUTED}; font-size: 0.9rem; }}

/* ── Brand ────────────────────────────────────────────── */
.brand {{ display:flex; align-items:baseline; gap:0.55rem; margin-bottom:1.5rem; }}
.brand-mark {{ color:{ACCENT}; font-size:1.15rem; }}
.brand-name {{
    font-family:'Fraunces',Georgia,serif; font-size:1.3rem; font-weight:600;
    letter-spacing:-0.01em; color:{TEXT};
}}
.brand-sub {{
    color:{TEXT_FAINT}; font-size:0.74rem; font-weight:500;
    letter-spacing:0.13em; text-transform:uppercase;
    padding-left:0.55rem; border-left:1px solid {BORDER_STRONG};
}}
.h1-accent {{ color:{ACCENT}; }}

/* ── Hero credibility strip ───────────────────────────── */
.hero-facts {{
    display:flex; gap:2rem; flex-wrap:wrap; margin-top:1.6rem;
    padding-top:1.2rem; border-top:1px solid {BORDER};
}}
.hero-facts span {{ color:{TEXT_FAINT}; font-size:0.85rem; }}
.hero-facts b {{ color:{TEXT}; font-weight:600; }}

/* ── Empty / failed section ───────────────────────────── */
/* Deliberately looks like a message, not like a styled blank: an empty tab
   with a grey caption reads as "nothing here" when the truth is "a call
   failed and we did not tell you". */
.empty {{
    background:{SURFACE}; border:1px solid {BORDER};
    border-left:2px solid {WARN};
    border-radius:11px; padding:1.15rem 1.3rem; margin:0.4rem 0 1rem;
}}
.empty-title {{ font-weight:600; font-size:0.98rem; margin-bottom:0.35rem; }}
.empty-body {{ color:{TEXT_MUTED}; font-size:0.89rem; line-height:1.6; }}
</style>
"""
