import time

import streamlit as st

from agent import run_agent

st.set_page_config(page_title="Smart Trip Planner Agent", page_icon="🧭", layout="wide")

# How long each tool's "calling..." state stays visible, so the agent's steps are
# clearly watchable on camera instead of flashing by.
STEP_PAUSE_SECONDS = 0.9
TOTAL_TOOLS = 5

TOOL_LABELS = {
    "search_flights": "Searching flights",
    "search_hotels": "Finding your stay",
    "get_weather": "Checking the weather",
    "estimate_local_costs": "Estimating food, transport & activities",
    "calculate_budget": "Balancing your budget",
}

# ---------------------------------------------------------------- styling
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .stApp {
        background: radial-gradient(1200px 600px at 15% -10%, #eef4ff 0%, #f7f9fc 45%, #f7f9fc 100%);
    }

    .hero h1 {
        font-size: 2.2rem; font-weight: 800; letter-spacing: -0.02em; margin-bottom: 2px;
        background: linear-gradient(90deg, #4f46e5, #06b6d4);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    }
    .hero p { color: #5b6472; font-size: 0.98rem; margin-top: 0; }

    .section-title {
        font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.08em;
        color: #8a93a3; font-weight: 700; margin-bottom: 6px;
    }

    .status {
        display: flex; align-items: center; gap: 10px;
        background: #ffffff; border: 1px solid #e3e8f2; border-radius: 14px;
        padding: 13px 16px; box-shadow: 0 4px 14px rgba(30,41,59,0.06);
        font-weight: 600; color: #2b3242; margin: 4px 0 8px 0;
    }
    .dot { width: 11px; height: 11px; border-radius: 50%; background: #4f46e5;
        box-shadow: 0 0 0 0 rgba(79,70,229,0.5); animation: pulse 1.2s infinite; }
    .dot.done { background: #10b981; animation: none; }
    @keyframes pulse {
        0% { box-shadow: 0 0 0 0 rgba(79,70,229,0.5); }
        70% { box-shadow: 0 0 0 10px rgba(79,70,229,0); }
        100% { box-shadow: 0 0 0 0 rgba(79,70,229,0); }
    }

    .feed-step { border-left: 2px solid #e3e8f2; padding: 7px 0 7px 14px;
        margin-left: 4px; color: #3a4252; }
    .feed-step.active { border-left-color: #4f46e5; }
    .feed-step.done { border-left-color: #10b981; }
    .feed-label { font-weight: 600; font-size: 0.95rem; }
    .feed-sub { font-size: 0.78rem; color: #8a93a3; font-family: monospace;
        margin-top: 2px; word-break: break-all; }

    .stButton>button {
        background: linear-gradient(90deg, #4f46e5, #06b6d4); color: #fff;
        border: none; border-radius: 12px; padding: 10px 22px; font-weight: 700;
        box-shadow: 0 6px 16px rgba(79,70,229,0.25); transition: all .15s ease;
    }
    .stButton>button:hover { filter: brightness(1.06); transform: translateY(-1px); }
    .stProgress > div > div > div { background: linear-gradient(90deg,#4f46e5,#06b6d4); }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero">
      <h1>🧭 Smart Trip Planner Agent</h1>
      <p>An agentic AI that plans your trip by deciding which tools to call —
         flights, stay, weather, on-ground costs, and a full budget check.</p>
    </div>
    """,
    unsafe_allow_html=True,
)
st.write("")

if "itinerary" not in st.session_state:
    st.session_state.itinerary = None

left, right = st.columns([1.25, 1], gap="large")

with left:
    user_input = st.text_input(
        "Describe your trip",
        placeholder="Plan 3 days in Goa from Hyderabad for 2 people under Rs 25000",
    )
    run_clicked = st.button("Plan my trip ✨")
    status_slot = st.empty()
    progress_slot = st.empty()
    itinerary_slot = st.empty()

with right:
    st.markdown('<div class="section-title">🧠 Agent Activity</div>', unsafe_allow_html=True)
    activity_slot = st.empty()


def render_left_status(phase_text, pct, done=False):
    dot_class = "dot done" if done else "dot"
    status_slot.markdown(
        f'<div class="status"><span class="{dot_class}"></span>{phase_text}</div>',
        unsafe_allow_html=True,
    )
    progress_slot.progress(min(1.0, pct))


def render_feed(steps, writing=False, idle=False):
    if idle:
        activity_slot.markdown(
            '<span style="color:#8a93a3;">Waiting for your trip request…</span>',
            unsafe_allow_html=True,
        )
        return
    html = []
    for s in steps:
        label = TOOL_LABELS.get(s["tool"], s["tool"])
        if s["status"] == "calling":
            args = ", ".join(f"{k}={v}" for k, v in s["args"].items())
            html.append(
                f'<div class="feed-step active"><div class="feed-label">⏳ {label}…</div>'
                f'<div class="feed-sub">{s["tool"]}({args})</div></div>'
            )
        else:
            html.append(
                f'<div class="feed-step done"><div class="feed-label">✅ {label}</div></div>'
            )
    if writing:
        html.append(
            '<div class="feed-step active"><div class="feed-label">✍️ Writing your itinerary…</div></div>'
        )
    activity_slot.markdown("".join(html), unsafe_allow_html=True)


def show_itinerary(text):
    with itinerary_slot.container(border=True):
        st.markdown("#### 🗺️ Your Itinerary")
        st.markdown(text)


# ---------------------------------------------------------------- run / idle
if run_clicked and user_input:
    steps = []
    completed = {"n": 0}
    render_left_status("Understanding your request…", 0.08)
    render_feed(steps)

    def log_callback(event):
        if event["type"] == "tool_call":
            steps.append(
                {"tool": event["tool"], "args": event["args"], "status": "calling"}
            )
            render_feed(steps)
            render_left_status(
                f"{TOOL_LABELS.get(event['tool'], event['tool'])}…",
                0.1 + 0.72 * (completed["n"] / TOTAL_TOOLS),
            )
            time.sleep(STEP_PAUSE_SECONDS)
        elif event["type"] == "tool_result":
            steps[-1]["status"] = "done"
            completed["n"] += 1
            render_feed(steps)
            render_left_status(
                "Gathering details…", 0.1 + 0.72 * (completed["n"] / TOTAL_TOOLS)
            )
        elif event["type"] == "final_output":
            render_feed(steps, writing=True)
            render_left_status("Writing your itinerary…", 0.9)

    result = run_agent(user_input, log_callback=log_callback)

    st.session_state.itinerary = result
    render_feed(steps)
    render_left_status("Your trip is ready ✅", 1.0, done=True)
    show_itinerary(result)

elif st.session_state.itinerary:
    render_feed([], idle=True)
    show_itinerary(st.session_state.itinerary)
else:
    render_feed([], idle=True)
