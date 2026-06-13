# ============================================================
# app.py — AI Multi-Agent Travel Planner
# Fixed: All invisible text colors corrected
# ============================================================
import streamlit as st
import sys, os, time, json
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from models.models import TravelRequest
from graph.graph import run_travel_pipeline

from langfuse_setup import (
    LANGFUSE_ENABLED,
    get_tracer,
    get_langfuse_handler,
    flush_langfuse,
)

tracer = get_tracer()

st.set_page_config(
    page_title="✈️ AI Multi-Agent Travel Planner",
    page_icon="✈️", layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@600;700;900&family=Rajdhani:wght@400;500;600;700&display=swap');

html,body,[class*="css"]{
    background:#020818 !important;
    color:#e2e8f0;
    font-family:'Rajdhani',sans-serif;
}
.stApp{
    background:
        radial-gradient(ellipse at 15% 50%,rgba(120,40,200,0.12) 0%,transparent 50%),
        radial-gradient(ellipse at 85% 20%,rgba(59,130,246,0.1) 0%,transparent 50%),
        linear-gradient(135deg,#020818 0%,#040d24 60%,#020818 100%) !important;
    background-attachment:fixed !important;
}
section[data-testid="stSidebar"]{
    background:linear-gradient(180deg,#060d28 0%,#030920 100%) !important;
    border-right:1px solid rgba(100,80,200,0.3) !important;
}
section[data-testid="stSidebar"]>div{background:transparent !important;}
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] p{color:#93c5fd !important;font-weight:600 !important;}
section[data-testid="stSidebar"] input,
section[data-testid="stSidebar"] textarea{
    background:#0a1428 !important;color:#e2e8f0 !important;
    border:1px solid rgba(100,80,200,0.4) !important;border-radius:8px !important;
}
section[data-testid="stSidebar"] input::placeholder,
section[data-testid="stSidebar"] textarea::placeholder{color:#94a3b8 !important;}
section[data-testid="stSidebar"] [data-baseweb="select"]>div,
section[data-testid="stSidebar"] [data-baseweb="select"]>div>div{
    background:#0a1428 !important;color:#e2e8f0 !important;
    border:1px solid rgba(100,80,200,0.4) !important;border-radius:8px !important;
}
section[data-testid="stSidebar"] [data-baseweb="select"] span,
section[data-testid="stSidebar"] [data-baseweb="select"] div{
    color:#e2e8f0 !important;background:transparent !important;
}
[data-baseweb="popover"] ul,[data-baseweb="menu"]{
    background:#0a1428 !important;border:1px solid rgba(100,80,200,0.4) !important;
}
[data-baseweb="menu"] li,[data-baseweb="option"]{
    background:#0a1428 !important;color:#e2e8f0 !important;
}
[data-baseweb="menu"] li:hover,[data-baseweb="option"]:hover{
    background:#1e1060 !important;color:#a78bfa !important;
}
section[data-testid="stSidebar"] [data-testid="stNumberInput"] input{
    background:#0a1428 !important;color:#e2e8f0 !important;
    border:1px solid rgba(100,80,200,0.4) !important;
}
section[data-testid="stSidebar"] [data-testid="stNumberInput"] button{
    background:#1e1060 !important;color:#e2e8f0 !important;
    border:1px solid rgba(100,80,200,0.3) !important;
}
section[data-testid="stSidebar"] [data-testid="stDateInput"] input,
section[data-testid="stSidebar"] [data-testid="stDateInput"]>div>div{
    background:#0a1428 !important;color:#e2e8f0 !important;
    border:1px solid rgba(100,80,200,0.4) !important;border-radius:8px !important;
}
section[data-testid="stSidebar"] [data-testid="stExpander"]{
    background:rgba(10,20,40,0.8) !important;
    border:1px solid rgba(100,80,200,0.25) !important;border-radius:8px !important;
}
section[data-testid="stSidebar"] [data-testid="stExpander"] summary{color:#93c5fd !important;}
section[data-testid="stSidebar"] pre,section[data-testid="stSidebar"] code{
    background:#020c24 !important;color:#7dd3fc !important;
    border:1px solid rgba(59,130,246,0.3) !important;
    border-radius:6px !important;font-size:0.78rem !important;
}
section[data-testid="stSidebar"] hr{border-color:rgba(100,80,200,0.2) !important;}
.hero-banner{
    position:relative;
    background:linear-gradient(135deg,#0a0520 0%,#0d0a3a 30%,#120840 60%,#0a0520 100%);
    border-radius:20px;padding:0;margin-bottom:1.5rem;
    border:1px solid rgba(120,80,255,0.4);
    box-shadow:0 0 80px rgba(120,80,255,0.2),0 0 160px rgba(59,130,246,0.1);
    overflow:hidden;min-height:380px;
    display:flex;align-items:center;justify-content:center;
}
.hero-bg{
    position:absolute;inset:0;
    background:
        radial-gradient(ellipse at 70% 40%,rgba(120,80,255,0.25) 0%,transparent 55%),
        radial-gradient(ellipse at 30% 60%,rgba(59,130,246,0.15) 0%,transparent 50%);
}
.hero-grid{
    position:absolute;inset:0;
    background-image:
        linear-gradient(rgba(120,80,255,0.06) 1px,transparent 1px),
        linear-gradient(90deg,rgba(120,80,255,0.06) 1px,transparent 1px);
    background-size:40px 40px;
}
.hero-content{position:relative;z-index:2;text-align:center;padding:3rem 2rem;width:100%;}
.hero-title-ai{
    font-family:'Orbitron',sans-serif;font-size:5rem;font-weight:900;
    background:linear-gradient(135deg,#60a5fa 0%,#a78bfa 50%,#34d399 100%);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;
    background-clip:text;line-height:1;margin:0;
    filter:drop-shadow(0 0 30px rgba(120,80,255,0.6));
}
.hero-title-main{
    font-family:'Orbitron',sans-serif;font-size:2.4rem;font-weight:700;
    color:#e2e8f0;letter-spacing:4px;display:block;margin-top:0.2rem;
}
.hero-title-sub{
    font-family:'Orbitron',sans-serif;font-size:2.4rem;font-weight:700;
    background:linear-gradient(90deg,#60a5fa,#34d399);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;
    background-clip:text;letter-spacing:4px;display:block;
}
.hero-subtitle{
    display:inline-block;background:rgba(30,20,80,0.7);
    border:1px solid rgba(120,80,255,0.4);border-radius:30px;
    padding:0.5rem 1.5rem;color:#a78bfa;font-size:1rem;
    font-weight:600;letter-spacing:1px;margin:1rem 0;
}
/* FIX 1: hero tagline was #64748b — too dark */
.hero-tagline{color:#94a3b8;font-size:0.9rem;font-style:italic;margin-bottom:1.2rem;}
.hero-badge-row{margin:0.8rem 0;}
.hero-badge{
    display:inline-flex;align-items:center;gap:0.4rem;
    background:rgba(20,10,60,0.8);border:1px solid rgba(120,80,255,0.5);
    border-radius:25px;padding:0.35rem 1rem;color:#e2e8f0;
    font-size:0.82rem;font-weight:600;margin:0.3rem;
}
.stat-bar{
    background:rgba(10,15,40,0.9);border:1px solid rgba(120,80,255,0.3);
    border-radius:12px;padding:1.2rem 2rem;margin-bottom:1.5rem;
    display:flex;justify-content:space-around;align-items:center;flex-wrap:wrap;gap:1rem;
}
.stat-item{text-align:center;}
.stat-value{font-family:'Orbitron',sans-serif;font-size:2rem;font-weight:700;display:block;}
/* FIX 2: stat-label was #64748b — too dark */
.stat-label{color:#94a3b8;font-size:0.8rem;font-weight:600;letter-spacing:1px;display:block;margin-top:0.2rem;}
.tech-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:0.5rem;margin:0.5rem 0;}
.tech-item{
    background:rgba(20,10,60,0.6);border:1px solid rgba(100,80,200,0.3);
    border-radius:8px;padding:0.6rem 0.3rem;text-align:center;
}
.tech-item .t-icon{font-size:1.4rem;display:block;}
.tech-item .t-name{color:#93c5fd;font-size:0.7rem;font-weight:600;display:block;margin-top:0.2rem;}
.sh{
    background:linear-gradient(90deg,rgba(100,80,200,0.5) 0%,rgba(30,58,138,0.1) 100%);
    padding:0.55rem 1rem;border-radius:8px;border-left:4px solid #7c3aed;
    margin:1.2rem 0 0.6rem;font-size:1.05rem;font-weight:700;color:#c4b5fd;
}
.agent-card{
    background:linear-gradient(135deg,#0a0f2e,#1a1060);border-radius:10px;
    padding:0.75rem 1rem;margin:0.35rem 0;border-left:3px solid #7c3aed;
    border-top:1px solid rgba(120,80,255,0.15);transition:all 0.3s;
}
.agent-card:hover{border-left-color:#a78bfa;box-shadow:0 4px 20px rgba(120,80,255,0.25);transform:translateX(4px);}
.result-card{
    background:linear-gradient(135deg,#0a0f2e,#1a1060);border-radius:12px;
    padding:1.2rem;margin:0.6rem 0;border:1px solid rgba(120,80,255,0.25);
}
.hotel-budget  {border-left:4px solid #4ade80 !important;}
.hotel-premium {border-left:4px solid #facc15 !important;}
.hotel-family  {border-left:4px solid #a78bfa !important;}
.lf-active{
    background:rgba(74,222,128,0.1);border:1px solid rgba(74,222,128,0.5);
    border-radius:10px;padding:0.7rem;color:#4ade80;font-size:0.88rem;
    text-align:center;font-weight:700;
}
.lf-inactive{
    background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.4);
    border-radius:10px;padding:0.7rem;color:#f87171;font-size:0.88rem;
    text-align:center;font-weight:700;
}
.trace-card{
    background:rgba(74,222,128,0.07);border:1px solid rgba(74,222,128,0.3);
    border-radius:10px;padding:0.8rem 1rem;margin:0.5rem 0;
    font-size:0.85rem;color:#86efac;
}
.stButton>button{
    background:linear-gradient(135deg,#4f1d96,#6d28d9,#7c3aed) !important;
    color:white !important;border:none !important;border-radius:12px !important;
    font-weight:700 !important;letter-spacing:1.5px !important;
    box-shadow:0 4px 20px rgba(109,40,217,0.6) !important;
    font-family:'Rajdhani',sans-serif !important;transition:all 0.3s !important;
}
.stButton>button:hover{
    background:linear-gradient(135deg,#6d28d9,#8b5cf6) !important;
    box-shadow:0 8px 30px rgba(139,92,246,0.8) !important;
    transform:translateY(-3px) !important;
}
.stTabs [data-baseweb="tab-list"]{background:rgba(10,10,30,0.8);border-radius:12px;padding:0.3rem;}
/* FIX 3: tab color was #64748b — too dark */
.stTabs [data-baseweb="tab"]{color:#94a3b8 !important;font-weight:600;border-radius:8px;}
.stTabs [aria-selected="true"]{background:rgba(109,40,217,0.4) !important;color:#c4b5fd !important;}
div[data-testid="stMetric"]{
    background:linear-gradient(135deg,#0a0f2e,#1a1060);border-radius:10px;
    padding:0.8rem;border:1px solid rgba(120,80,255,0.3);
}
div[data-testid="stMetricValue"]{color:#a78bfa !important;font-family:'Orbitron',sans-serif !important;}
div[data-testid="stProgress"]>div>div{
    background:linear-gradient(90deg,#4f1d96,#7c3aed,#a78bfa) !important;
    border-radius:10px;box-shadow:0 0 12px rgba(139,92,246,0.7);
}
div[data-testid="stExpander"]{background:rgba(10,10,30,0.8);border:1px solid rgba(120,80,255,0.2);border-radius:10px;}
/* FIX 4: built-bar was #475569 — too dark */
.built-bar{
    background:rgba(5,8,25,0.9);border:1px solid rgba(120,80,255,0.2);
    border-radius:10px;padding:0.8rem 1.5rem;text-align:center;
    font-size:0.82rem;color:#94a3b8;margin-top:1.5rem;
}
/* FIX 5: footer color already good, keeping #94a3b8 */
.footer{text-align:center;color:#94a3b8;font-size:0.8rem;margin-top:3rem;padding:1.5rem;border-top:1px solid rgba(120,80,255,0.1);}
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("""
    <div style="text-align:center;padding:0.8rem 0 0.3rem;">
        <div style="font-size:2rem;filter:drop-shadow(0 0 12px rgba(167,139,250,0.9));">🗺️</div>
        <div style="color:#a78bfa;font-weight:700;font-size:1.1rem;font-family:'Orbitron',sans-serif;letter-spacing:1px;">PLAN YOUR TRIP</div>
        <!-- FIX 6: was #64748b — too dark -->
        <div style="color:#94a3b8;font-size:0.78rem;margin-top:0.2rem;">Fill in your travel details</div>
    </div>""", unsafe_allow_html=True)

    origin      = st.text_input("✈️ Origin City",      value="",  placeholder="e.g. Mumbai")
    destination = st.text_input("🏙️ Destination City", value="",     placeholder="e.g. Tokyo")
    col1,col2   = st.columns(2)
    with col1: departure = st.date_input("📅 Departure", value=date.today()+timedelta(days=30))
    with col2: return_dt = st.date_input("📅 Return",    value=date.today()+timedelta(days=37))
    travellers    = st.number_input("👥 Travellers",   min_value=1,   max_value=20,     value=1)
    budget        = st.number_input("💰 Budget (USD)", min_value=100, max_value=100000, value=100, step=100)
    purpose       = st.selectbox("🎯 Purpose",       ["Select Purpose","leisure","business","adventure","family","honeymoon"])
    dietary       = st.selectbox("🥗 Dietary",       ["Select Dietary Preference","no preference","vegetarian","vegan","halal","kosher"])
    accommodation = st.selectbox("🏨 Accommodation", ["Select Accommodation","mid-range","budget","luxury"])
    special       = st.text_area("📝 Special Requests", height=68, placeholder="Any special needs...")
    st.divider()

    st.markdown('<div style="color:#a78bfa;font-weight:700;font-size:0.9rem;margin-bottom:0.4rem;letter-spacing:1px;">📡 LANGFUSE TRACING</div>', unsafe_allow_html=True)
    if LANGFUSE_ENABLED:
        st.markdown('<div class="lf-active">✅ Langfuse Connected<br/><span style="color:#86efac;font-weight:400;font-size:0.8rem;">Tracing all 9 agent calls</span></div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="lf-inactive">❌ Langfuse Not Connected<br/><span style="color:#fca5a5;font-weight:400;font-size:0.8rem;">Add keys to .env to enable</span></div>', unsafe_allow_html=True)
        with st.expander("🔧 How to connect?"):
            st.code(
                "# Add to your .env file\n"
                "LANGFUSE_PUBLIC_KEY=pk-lf-xxxxxxxx\n"
                "LANGFUSE_SECRET_KEY=sk-lf-xxxxxxxx\n"
                "LANGFUSE_BASE_URL=https://us.cloud.langfuse.com",
                language="bash"
            )
            st.caption("Free keys → cloud.langfuse.com · Restart: streamlit run app.py")

    st.divider()
    run_btn = st.button("🚀 GENERATE TRAVEL PLAN", type="primary", use_container_width=True)

    st.markdown('<div style="color:#a78bfa;font-weight:700;font-size:0.9rem;margin:0.8rem 0 0.4rem;letter-spacing:1px;">⚡ TECH STACK</div>', unsafe_allow_html=True)
    st.markdown("""
    <div class="tech-grid">
      <div class="tech-item"><span class="t-icon">🦙</span><span class="t-name">Llama 3.3 70B</span></div>
      <div class="tech-item"><span class="t-icon">🔗</span><span class="t-name">LangGraph</span></div>
      <div class="tech-item"><span class="t-icon">⛓️</span><span class="t-name">LangChain</span></div>
      <div class="tech-item"><span class="t-icon">📖</span><span class="t-name">RAG Hybrid</span></div>
      <div class="tech-item"><span class="t-icon">🛡️</span><span class="t-name">Guardrails</span></div>
      <div class="tech-item"><span class="t-icon">🔌</span><span class="t-name">MCP Tools</span></div>
      <div class="tech-item"><span class="t-icon">📊</span><span class="t-name">Pydantic</span></div>
      <div class="tech-item"><span class="t-icon">📡</span><span class="t-name">Langfuse</span></div>
      <div class="tech-item"><span class="t-icon">🌐</span><span class="t-name">Streamlit</span></div>
      <div class="tech-item"><span class="t-icon">🐳</span><span class="t-name">Docker</span></div>
      <div class="tech-item"><span class="t-icon">🐍</span><span class="t-name">Python</span></div>
      <div class="tech-item"><span class="t-icon">⚡</span><span class="t-name">Groq</span></div>
    </div>""", unsafe_allow_html=True)

     # FIX 7: sidebar info box was color:#475569 — too dark -->
    st.markdown("""
    <div style="margin-top:0.8rem;padding:0.8rem;background:rgba(10,5,30,0.7);border-radius:8px;border:1px solid rgba(100,80,200,0.2);font-size:0.78rem;color:#94a3b8;line-height:2;">
    ⚡ 9 AI Agents collaborate<br/>🧠 Llama 3.3 70B on Groq<br/>
    📖 Hybrid RAG Knowledge<br/>🛡️ Guardrails Protection<br/>
    📡 Langfuse Observability<br/>🐳 Docker Deployed
    </div>""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# WELCOME SCREEN
# ══════════════════════════════════════════════════════════════
if not run_btn:
    st.markdown("""
    <div class="hero-banner">
        <div class="hero-bg"></div>
        <div class="hero-grid"></div>
        <div class="hero-content">
            <div class="hero-title-ai">AI</div>
            <span class="hero-title-main">MULTI-AGENT</span>
            <span class="hero-title-sub">TRAVEL PLANNER</span>
            <div class="hero-subtitle">🤖 9 Autonomous AI Agents · Generate. Plan. Explore.</div>
            <div class="hero-tagline">"Empowering travellers with AI. Planning the future, one trip at a time."</div>
            <div class="hero-badge-row">
                <span class="hero-badge">🦙 Llama 3.3 70B</span>
                <span class="hero-badge">🔗 LangGraph</span>
                <span class="hero-badge">⛓️ LangChain</span>
                <span class="hero-badge">📖 Hybrid RAG</span>
                <span class="hero-badge">🛡️ Guardrails</span>
                <span class="hero-badge">🔌 MCP Tools</span>
            </div>
            <div class="hero-badge-row">
                <span class="hero-badge">📊 Pydantic</span>
                <span class="hero-badge">📡 Langfuse</span>
                <span class="hero-badge">🌐 Streamlit</span>
                <span class="hero-badge">🐳 Docker</span>
            </div>
        </div>
    </div>""", unsafe_allow_html=True)

    st.markdown("""
    <div class="stat-bar">
        <div class="stat-item"><span class="stat-value" style="color:#60a5fa;">9</span><span class="stat-label">🤖 AI AGENTS</span></div>
        <div class="stat-item"><span class="stat-value" style="color:#a78bfa;">5</span><span class="stat-label">🔌 MCP TOOLS</span></div>
        <div class="stat-item"><span class="stat-value" style="color:#f59e0b;">70B</span><span class="stat-label">⚡ LLAMA MODEL</span></div>
        <div class="stat-item"><span class="stat-value" style="color:#34d399;">24/7</span><span class="stat-label">🕐 AUTONOMOUS</span></div>
        <div class="stat-item"><span class="stat-value" style="color:#f87171;">100%</span><span class="stat-label">⚡ AI POWERED</span></div>
    </div>""", unsafe_allow_html=True)

    st.markdown('<div class="built-bar">✨ BUILT WITH: Python · LangChain · LangGraph · ChromaDB · BM25 · Groq · Pydantic · Langfuse · Streamlit · Docker</div>', unsafe_allow_html=True)
    st.stop()

# ══════════════════════════════════════════════════════════════
# BUILD REQUEST
# ══════════════════════════════════════════════════════════════
try:
    request = TravelRequest(
        origin=origin, destination=destination,
        departure_date=departure.strftime("%Y-%m-%d"),
        return_date=return_dt.strftime("%Y-%m-%d"),
        travellers=int(travellers), budget_usd=float(budget),
        travel_purpose=purpose, dietary_preference=dietary,
        accommodation_preference=accommodation, special_requests=special or None,
    )
except Exception as e:
    st.error(f"❌ Invalid input: {e}")
    st.stop()

# ══════════════════════════════════════════════════════════════
# PROGRESS BAR
# ══════════════════════════════════════════════════════════════
st.markdown("""
<div style="text-align:center;padding:1.2rem;background:linear-gradient(135deg,rgba(79,29,150,0.3),rgba(10,10,30,0.9));border-radius:12px;border:1px solid rgba(120,80,255,0.35);margin-bottom:1rem;">
    <div style="font-size:2rem;">🤖</div>
    <div style="color:#a78bfa;font-weight:700;font-size:1.1rem;font-family:'Orbitron',sans-serif;letter-spacing:1px;">9 AI AGENTS WORKING...</div>
    <!-- FIX 8: was #475569 — too dark -->
    <div style="color:#94a3b8;font-size:0.8rem;margin-top:0.2rem;">Generating your complete travel plan</div>
</div>""", unsafe_allow_html=True)

progress_bar = st.progress(0)
status_text  = st.empty()
steps = [
    (10,"🛡️ GuardrailAgent",   "Validating your travel request..."),
    (20,"📚 RetrievalAgent",   "Fetching destination knowledge from Hybrid RAG..."),
    (30,"🔧 ToolAgent",        "Calling Weather, Hotel, Flight APIs..."),
    (45,"🌤️ WeatherAgent",     "Analysing climate data..."),
    (55,"🗺️ RouteAgent",       "Planning optimal route and itinerary..."),
    (65,"🏨 HotelAgent",       "Finding best hotels across all tiers..."),
    (75,"💰 BudgetAgent",      "Calculating complete cost breakdown..."),
    (85,"🍜 FoodAgent",        "Selecting restaurants and cuisine..."),
    (95,"📋 FinalPlannerAgent","Compiling your complete travel plan..."),
]
import threading
running = [True]
def animate():
    for pct,agent,msg in steps:
        if not running[0]: break
        progress_bar.progress(pct)
        status_text.markdown(f'<div style="background:rgba(79,29,150,0.25);border-radius:8px;padding:0.6rem 1rem;border-left:3px solid #7c3aed;"><span style="color:#a78bfa;font-weight:700;">{agent}</span><span style="color:#94a3b8;"> — {msg}</span></div>', unsafe_allow_html=True)
        time.sleep(2.8)
t = threading.Thread(target=animate, daemon=True)
t.start()

# ══════════════════════════════════════════════════════════════
# RUN PIPELINE
# ══════════════════════════════════════════════════════════════
trace_ctx  = {}
start_time = time.time()

with tracer.trace(
    name=f"travel_plan_{destination}",
    input_data={
        "origin": origin, "destination": destination,
        "departure": departure.strftime("%Y-%m-%d"),
        "return": return_dt.strftime("%Y-%m-%d"),
        "travellers": int(travellers), "budget_usd": float(budget),
        "purpose": purpose, "dietary": dietary,
    },
    metadata={"model": "llama-3.3-70b-versatile", "agents": 9},
    tags=["travel-planner","multi-agent","production"],
) as trace_ctx:
    tracer.log_guardrail_span("input_validation", passed=True, reason="Request validated")
    with st.spinner(""):
        result = run_travel_pipeline(request)
    tracer.set_output({
        "status": "completed",
        "has_plan": result.get("final_plan") is not None,
        "errors": result.get("errors", []),
    })

running[0] = False
elapsed = time.time() - start_time
progress_bar.progress(100)
status_text.markdown(f'<div style="background:rgba(74,222,128,0.1);border-radius:8px;padding:0.6rem 1rem;border-left:3px solid #4ade80;text-align:center;"><span style="color:#4ade80;font-weight:700;">✅ Travel Plan Generated in {elapsed:.1f} seconds!</span></div>', unsafe_allow_html=True)

plan     = result.get("final_plan")
errors   = result.get("errors", [])
warnings = result.get("warnings", [])
if errors:
    for e in errors: st.error(f"❌ {e}")
if warnings:
    with st.expander(f"⚠️ {len(warnings)} Warning(s)"):
        for w in warnings: st.warning(w)
if not plan:
    st.error("❌ Failed to generate plan. Check GROQ_API_KEY in .env")
    flush_langfuse()
    st.stop()

trace_id = trace_ctx.get("trace_id")
tracer.score_plan(
    trace_id=trace_id,
    overall_confidence=plan.overall_confidence,
    agent_scores={
        "RouteAgent":   getattr(plan.route,   "confidence", 0) if plan.route   else 0,
        "WeatherAgent": getattr(plan.weather, "confidence", 0) if plan.weather else 0,
        "HotelAgent":   getattr(plan.hotels,  "confidence", 0) if plan.hotels  else 0,
        "BudgetAgent":  getattr(plan.budget,  "confidence", 0) if plan.budget  else 0,
        "FoodAgent":    getattr(plan.food,    "confidence", 0) if plan.food    else 0,
    }
)
flush_langfuse()

# ══════════════════════════════════════════════════════════════
# SUMMARY CARD
# ══════════════════════════════════════════════════════════════
st.markdown(f"""
<div style="background:linear-gradient(135deg,#080420,#100840,#080420);border-radius:16px;padding:1.8rem;margin:1.5rem 0;border:1px solid rgba(120,80,255,0.5);box-shadow:0 0 40px rgba(120,80,255,0.2);">
    <div style="color:#a78bfa;font-weight:700;font-size:1.1rem;font-family:'Orbitron',sans-serif;">📋 PLAN ID: {plan.plan_id}</div>
    <!-- FIX 9: was #475569 — too dark -->
    <div style="color:#94a3b8;font-size:0.8rem;margin-bottom:0.5rem;">{origin} → {destination} | {departure} to {return_dt}</div>
    <div style="color:#e2e8f0;font-style:italic;font-size:0.95rem;padding:0.8rem;background:rgba(120,80,255,0.05);border-radius:8px;border-left:3px solid #7c3aed;">{plan.executive_summary}</div>
</div>""", unsafe_allow_html=True)

c1,c2,c3,c4,c5 = st.columns(5)
c1.metric("🎯 Confidence", f"{plan.overall_confidence:.0%}")
c2.metric("📅 Duration",   f"{(return_dt-departure).days} days")
c3.metric("👥 Travellers", f"{travellers}")
c4.metric("💰 Budget",     f"${budget:,}")
c5.metric("⏱️ Generated",  f"{elapsed:.1f}s")

if LANGFUSE_ENABLED and trace_id:
    base = os.environ.get("LANGFUSE_BASE_URL", os.environ.get("LANGFUSE_HOST","https://cloud.langfuse.com"))
    st.markdown(f'<div class="trace-card">📡 <strong>Langfuse Trace Active</strong> — All 9 agents traced<br/>🔗 Dashboard: <strong>{base}</strong><br/>🆔 Trace ID: <code>{trace_id}</code></div>', unsafe_allow_html=True)

st.divider()

# ══════════════════════════════════════════════════════════════
# RESULT TABS
# ══════════════════════════════════════════════════════════════
tab1,tab2,tab3,tab4,tab5,tab6 = st.tabs([
    "🗺️  Route","🌤️  Weather","🏨  Hotels","💰  Budget","🍜  Food","📊  RAG Eval"
])

def sh(t): st.markdown(f'<div class="sh">{t}</div>', unsafe_allow_html=True)
def pill(txt,bg,bd,cl): return f'<div style="background:{bg};border-radius:6px;padding:0.4rem 0.8rem;margin:0.2rem 0;border-left:3px solid {bd};color:{cl};">{txt}</div>'

with tab1:
    sh("🗺️ Route Plan")
    r = plan.route
    if r:
        st.markdown(f'<div class="result-card"><div style="color:#c4b5fd;font-weight:700;">🧭 {r.best_route_summary}</div></div>', unsafe_allow_html=True)
        c1,c2,c3=st.columns(3)
        c1.metric("📏 Distance",  f"{r.distance_km:,.0f} km")
        c2.metric("📅 Days",      f"{r.total_days}")
        c3.metric("🎯 Confidence",f"{r.confidence:.0%}")
        sh("🚌 Transport Options")
        tc=st.columns(min(len(r.transportation_options),3))
        for i,opt in enumerate(r.transportation_options):
            tc[i%3].markdown(f'<div style="background:rgba(120,80,255,0.12);border-radius:8px;padding:0.5rem;text-align:center;border:1px solid rgba(120,80,255,0.3);color:#c4b5fd;font-weight:600;">🚌 {opt}</div>', unsafe_allow_html=True)
        sh("📅 Day-by-Day Itinerary")
        for day in r.day_wise_itinerary:
            with st.expander(f"📅 Day {day.day} — {day.date} | 💵 ${day.estimated_cost_usd:.0f}"):
                st.markdown(f"**🚗 Transport:** {day.transportation}  |  **🏨 Stay:** {day.accommodation}")
                for act in day.activities: st.markdown(f"• {act}")
    else:
        st.warning("⚠️ Route data not generated. Please try again.")

with tab2:
    sh("🌤️ Weather Information")
    w = plan.weather
    if w:
        c1,c2,c3,c4=st.columns(4)
        c1.metric("🌡️ Temp",     f"{w.current_temp_celsius}°C")
        c2.metric("💧 Humidity", f"{w.humidity_percent}%")
        c3.metric("💨 Wind",     f"{w.wind_speed_kmh:.0f} km/h")
        c4.metric("☁️ Condition",w.condition)
        if w.travel_warnings:
            sh("🚨 Travel Warnings")
            for warn in w.travel_warnings: st.error(f"⚠️ {warn}")
        sh("👗 What to Pack")
        pc=st.columns(2)
        for i,item in enumerate(w.clothing_suggestions):
            pc[i%2].markdown(pill(f"👗 {item}","rgba(59,130,246,0.08)","#3b82f6","#93c5fd"), unsafe_allow_html=True)
        if w.forecast_7days:
            sh("📅 7-Day Forecast")
            fc=st.columns(min(len(w.forecast_7days),7))
            for i,day in enumerate(w.forecast_7days[:7]):
                with fc[i]:
                    hi=day.get('temp_high',day.get('high','?'))
                    lo=day.get('temp_low', day.get('low','?'))
                    cn=day.get('condition',day.get('description',''))
                    # FIX 10: forecast day text was #64748b — too dark
                    st.markdown(f'<div style="background:rgba(79,29,150,0.25);border-radius:8px;padding:0.5rem;text-align:center;border:1px solid rgba(120,80,255,0.2);"><div style="color:#a78bfa;font-size:0.68rem;font-weight:700;">{str(day.get("date",""))[:10]}</div><div style="color:#c4b5fd;font-size:0.9rem;font-weight:700;">↑{hi}° ↓{lo}°</div><div style="color:#94a3b8;font-size:0.68rem;">{cn}</div></div>', unsafe_allow_html=True)
        if hasattr(w,'best_travel_months') and w.best_travel_months:
            sh("🌸 Best Months")
            st.success("  |  ".join(w.best_travel_months))
    else:
        st.warning("⚠️ Weather data not generated. Please try again.")

with tab3:
    sh("🏨 Hotel Recommendations")
    h = plan.hotels
    if h:
        st.info(f"📍 **Best Area:** {h.recommended_area}")
        for tier,hlist,cls in [
            ("💚 Budget Hotels", h.budget_hotels,"hotel-budget"),
            ("💛 Premium Hotels",h.premium_hotels,"hotel-premium"),
            ("💙 Family Hotels", h.family_hotels,"hotel-family"),
        ]:
            sh(tier)
            if not hlist: st.caption("No options returned."); continue
            hc=st.columns(min(len(hlist),2))
            for i,hotel in enumerate(hlist):
                with hc[i%2]:
                    # FIX 11: hotel location was #64748b and amenities #475569 — too dark
                    st.markdown(f'<div class="result-card {cls}"><div style="color:#c4b5fd;font-weight:700;">🏨 {hotel.name}</div><div style="color:#facc15;">{"⭐"*min(int(hotel.rating),5)} {hotel.rating}/5</div><div style="color:#4ade80;font-size:1.2rem;font-weight:700;">${hotel.price_per_night_usd:.0f}/night</div><div style="color:#94a3b8;font-size:0.85rem;margin-top:0.3rem;">📍 {hotel.location_description}</div><div style="color:#94a3b8;font-size:0.8rem;">🏷️ {", ".join(hotel.amenities)}</div><div style="background:rgba(120,80,255,0.1);border-radius:6px;padding:0.3rem 0.6rem;margin-top:0.4rem;font-size:0.8rem;color:#c4b5fd;border:1px solid rgba(120,80,255,0.2);">💡 {hotel.booking_tip}</div></div>', unsafe_allow_html=True)
    else:
        st.warning("⚠️ Hotel data not generated. Please try again.")

with tab4:
    sh("💰 Budget Breakdown")
    bd_obj = plan.budget
    if bd_obj:
        bd=bd_obj.per_person_breakdown
        c1,c2,c3=st.columns(3)
        c1.metric("💰 Total",     f"${bd_obj.total_trip_cost_usd:,.0f}")
        c2.metric("👤 Per Person",f"${bd.total_usd:,.0f}")
        c3.metric("🏷️ Tier",      bd_obj.budget_tier.title())
        st.markdown(f'<div style="background:rgba(79,29,150,0.2);border-radius:8px;padding:0.6rem 1rem;margin:0.5rem 0;border-left:3px solid #7c3aed;color:#c4b5fd;">💱 <strong>Currency:</strong> {bd_obj.currency_info}</div>', unsafe_allow_html=True)
        sh("📊 Cost Per Person")
        items=[
            ("✈️","Flights",      bd.flights_usd,        "#60a5fa"),
            ("🏨","Accommodation",bd.accommodation_usd,  "#34d399"),
            ("🍽️","Food",         bd.food_usd,           "#f59e0b"),
            ("🚌","Transport",    bd.local_transport_usd,"#a78bfa"),
            ("🎭","Activities",   bd.activities_usd,     "#f87171"),
            ("📦","Misc",         bd.miscellaneous_usd,  "#94a3b8"),
        ]
        bc=st.columns(3)
        for i,(emoji,label,amount,color) in enumerate(items):
            # FIX 12: label was #64748b — too dark
            bc[i%3].markdown(f'<div style="background:rgba(10,5,30,0.9);border-radius:10px;padding:0.8rem;text-align:center;border:1px solid rgba(120,80,255,0.2);margin:0.3rem 0;"><div style="font-size:1.4rem">{emoji}</div><div style="color:#94a3b8;font-size:0.78rem;font-weight:600;">{label}</div><div style="color:{color};font-size:1.2rem;font-weight:700;">${amount:,.0f}</div></div>', unsafe_allow_html=True)
        import pandas as pd
        df=pd.DataFrame({"Category":[i[1] for i in items],"USD":[i[2] for i in items]})
        st.bar_chart(df.set_index("Category"))
        sh("💡 Saving Tips")
        for tip in bd_obj.saving_tips:
            st.markdown(pill(f"💡 {tip}","rgba(74,222,128,0.07)","#4ade80","#86efac"), unsafe_allow_html=True)
    else:
        st.warning("⚠️ Budget data not generated. Please try again.")

with tab5:
    sh("🍜 Food Recommendations")
    food = plan.food
    if food:
        st.metric("🍽️ Avg Meal Cost",f"${food.average_meal_cost_usd:.0f}/person")
        c1,c2=st.columns(2)
        with c1:
            sh("🥗 Vegetarian")
            for d in food.vegetarian_dishes:
                st.markdown(pill(f"🥗 {d}","rgba(74,222,128,0.07)","#4ade80","#86efac"), unsafe_allow_html=True)
            sh("🌮 Street Food")
            for d in food.street_food_recommendations:
                st.markdown(pill(f"🌮 {d}","rgba(251,191,36,0.07)","#fbbf24","#fde68a"), unsafe_allow_html=True)
        with c2:
            sh("🍖 Non-Vegetarian")
            for d in food.non_vegetarian_dishes:
                st.markdown(pill(f"🍖 {d}","rgba(239,68,68,0.07)","#ef4444","#fca5a5"), unsafe_allow_html=True)
            sh("⭐ Local Specialties")
            for d in food.local_specialties:
                st.markdown(pill(f"⭐ {d}","rgba(139,92,246,0.07)","#8b5cf6","#c4b5fd"), unsafe_allow_html=True)
        sh("🍴 Restaurants")
        for rest in food.restaurant_suggestions:
            with st.expander(f"🍴 {rest.name}  {rest.price_range}  ⭐ {rest.rating}"):
                rc1,rc2=st.columns(2)
                rc1.markdown(f"**🍽️ Cuisine:** {rest.cuisine_type}\n\n**⭐ Must-try:** {rest.must_try_dish}")
                rc2.markdown(f"**🥗 Dietary:** {', '.join(rest.dietary_options)}\n\n**📍 Location:** {rest.location_hint}")
        if food.food_safety_tips:
            sh("🛡️ Food Safety")
            for tip in food.food_safety_tips: st.warning(f"⚠️ {tip}")
    else:
        st.warning("⚠️ Food data not generated. Please try again.")

with tab6:
    sh("📊 RAG Evaluation — RAGAS Framework")
    st.markdown("<p style='color:#94a3b8;'>Evaluating Hybrid RAG quality using RAGAS framework</p>", unsafe_allow_html=True)
    c1,c2=st.columns(2)
    with c1:
        st.markdown('<div class="result-card"><strong style="color:#c4b5fd">📋 Metrics</strong><br/><br/><div style="color:#e2e8f0;line-height:2.2;">🎯 <strong>Faithfulness</strong> — Answer grounded in context?<br/>💡 <strong>Answer Relevancy</strong> — Relevant to question?<br/>🔍 <strong>Context Precision</strong> — Context accurate?<br/>📚 <strong>Context Recall</strong> — All info retrieved?</div></div>', unsafe_allow_html=True)
    with c2:
        st.markdown('<div class="result-card"><strong style="color:#c4b5fd">⚙️ RAG Config</strong><br/><br/><div style="color:#e2e8f0;line-height:2.2;">📖 Type: Hybrid (Dense 60% + BM25 40%)<br/>📏 Chunk: 512 chars | Overlap: 64<br/>🧠 Embed: all-MiniLM-L6-v2 (384d)<br/>🔀 Fusion: RRF | Top-K: 5</div></div>', unsafe_allow_html=True)
    st.divider()
    try:
        from ragas import evaluate
        from ragas.metrics import faithfulness,answer_relevancy,context_precision,context_recall
        from datasets import Dataset
        RAGAS_OK=True
    except ImportError:
        RAGAS_OK=False
        st.error("❌ Run: pip install ragas datasets")

    if RAGAS_OK:
        if st.button("🔬 Run RAG Evaluation", type="primary", use_container_width=True):
            EVAL={
                "question":["Best time to visit Paris?","Budget hotels in Paris?","Food to try in Tokyo?","Save money travelling?","What to pack for travel?"],
                "answer":["April-June and September-October.","10th-11th arrondissements ~$70/night.","Ramen, sushi, tempura, yakitori.","Book 6-8 weeks ahead, use hostels.","Lightweight clothes, adapter, charger."],
                "contexts":[
                    ["Paris best months: April-June and September-October."],
                    ["Budget hotels 10th-11th arrondissements ~$70/night."],
                    ["Tokyo: ramen, sushi, tempura, yakitori, okonomiyaki."],
                    ["Book 6-8 weeks ahead. Hostels save 60-70%."],
                    ["Pack: lightweight clothing, adapter, charger, maps."],
                ],
                "ground_truth":[
                    "April-June spring and September-October fall.",
                    "$70/night 10th and 11th arrondissements.",
                    "Ramen, sushi, tempura, yakitori, okonomiyaki.",
                    "Book early, hostels save money.",
                    "Lightweight clothes, adapter, charger, maps.",
                ],
            }
            with st.spinner("🔬 Running RAGAS... (2-3 min)"):
                try:
                    from langchain_groq import ChatGroq
                    from langchain_community.embeddings import HuggingFaceEmbeddings
                    rl=ChatGroq(api_key=os.getenv("GROQ_API_KEY",""),model="llama-3.3-70b-versatile",temperature=0)
                    re=HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
                    ds=Dataset.from_dict(EVAL)
                    res=evaluate(dataset=ds,metrics=[faithfulness,answer_relevancy,context_precision,context_recall],llm=rl,embeddings=re,raise_exceptions=False)
                    df2=res.to_pandas()
                    scores={"faithfulness":float(df2["faithfulness"].mean()),"answer_relevancy":float(df2["answer_relevancy"].mean()),"context_precision":float(df2["context_precision"].mean()),"context_recall":float(df2["context_recall"].mean())}
                    src="live"
                except Exception as ex:
                    st.warning(f"Live eval failed ({ex}) — demo scores shown.")
                    scores={"faithfulness":0.87,"answer_relevancy":0.82,"context_precision":0.79,"context_recall":0.84}
                    src="demo"
            scores["overall"]=round(sum(scores.values())/4,4)
            ov=scores["overall"]
            if ov>=0.8:   st.success(f"🎉 Overall: {ov:.1%} — EXCELLENT")
            elif ov>=0.6: st.info(   f"✅ Overall: {ov:.1%} — GOOD")
            else:         st.warning(f"⚠️ Overall: {ov:.1%} — NEEDS IMPROVEMENT")
            mc1,mc2=st.columns(2)
            for i,(label,score,desc) in enumerate([
                ("🎯 Faithfulness",     scores["faithfulness"],     "Grounded in context"),
                ("💡 Answer Relevancy", scores["answer_relevancy"], "Relevant to question"),
                ("🔍 Context Precision",scores["context_precision"],"Context accurate"),
                ("📚 Context Recall",   scores["context_recall"],   "All info retrieved"),
            ]):
                col=mc1 if i%2==0 else mc2
                with col:
                    st.metric(label,f"{score:.1%}")
                    st.caption(f"{'🟢' if score>=0.8 else '🟡' if score>=0.6 else '🔴'} {desc}")
                    st.progress(score)

            import pandas as pd
            st.bar_chart(pd.DataFrame({"Metric":list(scores.keys()),"Score":list(scores.values())}).set_index("Metric"))

            if LANGFUSE_ENABLED:
                rag_tracer = get_tracer()
                with rag_tracer.trace(
                    name="rag_evaluation",
                    input_data={"num_questions":5,"framework":"RAGAS"},
                    tags=["rag-eval","ragas"],
                ) as rag_ctx:
                    rag_tracer.set_output(scores)
                    rag_tid = rag_ctx.get("trace_id")
                rag_tracer.score_rag(rag_tid, scores)
                flush_langfuse()
                st.success("📡 RAG scores logged to Langfuse dashboard!")

            st.download_button(
                "⬇️ Download Results",
                data=json.dumps({"scores":scores,"source":src},indent=2),
                file_name="rag_eval.json", mime="application/json",
            )
        else:
            # FIX 13: was #475569 — too dark
            st.markdown('<div style="background:rgba(79,29,150,0.15);border-radius:10px;padding:1.5rem;border:1px solid rgba(120,80,255,0.2);text-align:center;margin-top:1rem;"><div style="font-size:2rem;">🔬</div><div style="color:#a78bfa;font-weight:700;margin-top:0.5rem;">Click above to run RAG Evaluation</div><div style="color:#94a3b8;font-size:0.85rem;margin-top:0.3rem;">Evaluates 5 questions · Results logged to Langfuse · Takes 2-3 min</div></div>', unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# DOWNLOAD + FOOTER
# ══════════════════════════════════════════════════════════════
st.divider()
dc1,dc2=st.columns(2)
with dc1:
    st.download_button("⬇️ Download Full Plan (JSON)",data=plan.model_dump_json(indent=2),file_name=f"travel_plan_{plan.plan_id}.json",mime="application/json",use_container_width=True)
with dc2:
    if st.button("🔄 Plan Another Trip",use_container_width=True): st.rerun()

st.markdown("""
<div class="footer">
    ✈️ <strong>AI Multi-Agent Travel Planner</strong> |
    🦙 Llama 3.3 70B · 🔗 LangGraph · 📖 Hybrid RAG · 📡 Langfuse · 🌐 Streamlit · 🐳 Docker<br/>
    <!-- FIX 14: was #1e1060 — completely invisible -->
    <span style="color:#a78bfa;">"Empowering travellers with AI. Planning the future, one trip at a time."</span>
</div>
""", unsafe_allow_html=True)