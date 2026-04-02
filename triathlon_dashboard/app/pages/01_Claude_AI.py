"""Claude AI coach page — feed all Garmin data to Claude for analysis."""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import ANTHROPIC_API_KEY, GARMIN_EMAIL, GARMIN_PASSWORD
from app.claude_chat import format_garmin_context, send_message
from app.garmin_fetcher import fetch_all_garmin_data


def _apply_theme() -> None:
    st.markdown(
        """
        <style>
            .stApp { background-color: #0f1117; color: #e6e8ef; }
            .page-title {
                font-size: 1.6rem; font-weight: 700;
                letter-spacing: 0.02rem; margin-bottom: 0.25rem;
            }
            .page-subtitle {
                font-size: 0.9rem; color: #8892a4; margin-bottom: 1.5rem;
            }
            .stChatMessage { background-color: #1a1d27 !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _init_session_state() -> None:
    defaults = {
        "garmin_data": None,
        "garmin_context": None,
        "chat_history": [],
        "data_loaded": False,
        "data_error": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _render_sidebar() -> tuple[str, str, str, int, bool]:
    """Render sidebar controls and return (email, password, api_key, days, fetch_clicked)."""
    with st.sidebar:
        st.subheader("Garmin Credentials")
        email = st.text_input("Garmin Email", value=GARMIN_EMAIL)
        password_input = st.text_input("Garmin Password", type="password")
        password = password_input or GARMIN_PASSWORD

        st.subheader("Claude Settings")
        api_key_input = st.text_input(
            "Anthropic API Key",
            value=ANTHROPIC_API_KEY,
            type="password",
            help="Get your key at console.anthropic.com",
        )
        api_key = api_key_input or ANTHROPIC_API_KEY

        st.subheader("Date Range")
        days = st.selectbox("Days of history", options=[7, 14, 30], index=0)

        fetch_clicked = st.button("Load Garmin Data", type="primary", use_container_width=True)

        if st.session_state.data_loaded:
            st.success("Data loaded.")
            if st.button("Clear & Reset", use_container_width=True):
                st.session_state.garmin_data = None
                st.session_state.garmin_context = None
                st.session_state.chat_history = []
                st.session_state.data_loaded = False
                st.session_state.data_error = None
                st.rerun()

        if GARMIN_EMAIL:
            st.caption("GARMIN_EMAIL loaded from .env")
        if GARMIN_PASSWORD and not password_input:
            st.caption("GARMIN_PASSWORD loaded from .env")
        if ANTHROPIC_API_KEY and not api_key_input:
            st.caption("ANTHROPIC_API_KEY loaded from .env")

    return email, password, api_key, int(days), fetch_clicked


def _fetch_data(email: str, password: str, days: int) -> None:
    """Fetch Garmin data and store in session state."""
    with st.spinner(f"Connecting to Garmin Connect and fetching {days} days of data..."):
        try:
            raw = fetch_all_garmin_data(email=email, password=password, days=days)
            context = format_garmin_context(raw)
            st.session_state.garmin_data = raw
            st.session_state.garmin_context = context
            st.session_state.data_loaded = True
            st.session_state.data_error = None
            st.session_state.chat_history = []
        except Exception as exc:
            st.session_state.data_error = str(exc)
            st.session_state.data_loaded = False


def _render_data_summary() -> None:
    """Show a collapsible preview of the fetched data."""
    raw = st.session_state.garmin_data
    if not raw:
        return
    errors = raw.get("errors") or []
    dr = raw.get("date_range") or {}
    acts = raw.get("activities") or []

    col1, col2, col3 = st.columns(3)
    col1.metric("Date Range", f"{dr.get('start','')} → {dr.get('end','')}")
    col2.metric("Activities Found", len(acts))
    col3.metric("Endpoint Errors", len(errors))

    with st.expander("Raw data preview (JSON)", expanded=False):
        # Show a truncated view — full data goes to Claude via context
        import json
        preview = {
            k: v for k, v in raw.items()
            if k not in ("errors",) and v
        }
        st.code(json.dumps(preview, indent=2, default=str)[:8000] + "\n...", language="json")

    if errors:
        with st.expander(f"{len(errors)} endpoint(s) had no data (click to see)", expanded=False):
            for e in errors:
                st.caption(e)


def _render_chat(api_key: str) -> None:
    """Render the chat interface."""
    st.divider()
    st.markdown("### Chat with your AI coach")
    st.caption(
        "Ask anything about your training, recovery, sleep, or readiness. "
        "Claude has access to all your Garmin data above."
    )

    # Render existing history
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Chat input
    user_input = st.chat_input("Ask your AI coach...")
    if not user_input:
        return

    if not api_key.strip():
        st.error("Please enter your Anthropic API key in the sidebar.")
        return

    # Show user message immediately
    with st.chat_message("user"):
        st.markdown(user_input)

    # Get Claude response
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                response = send_message(
                    messages=st.session_state.chat_history,
                    garmin_context=st.session_state.garmin_context,
                    user_message=user_input,
                    api_key=api_key,
                )
                st.markdown(response)
                # Update history after successful response
                st.session_state.chat_history.append({"role": "user", "content": user_input})
                st.session_state.chat_history.append({"role": "assistant", "content": response})
            except Exception as exc:
                st.error(f"Claude API error: {exc}")


def main() -> None:
    st.set_page_config(page_title="Claude AI Coach", layout="wide", page_icon="🤖")
    _apply_theme()
    _init_session_state()

    st.markdown('<div class="page-title">Claude AI Coach</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="page-subtitle">'
        "Feed all your Garmin data to Claude for personalized training analysis."
        "</div>",
        unsafe_allow_html=True,
    )

    email, password, api_key, days, fetch_clicked = _render_sidebar()

    if fetch_clicked:
        if not email.strip() or not password:
            st.error("Garmin email and password are required.")
        else:
            _fetch_data(email, password, days)

    if st.session_state.data_error:
        st.error(f"Failed to load Garmin data: {st.session_state.data_error}")

    if not st.session_state.data_loaded:
        st.info(
            "Enter your Garmin credentials and Anthropic API key in the sidebar, "
            "then click **Load Garmin Data** to begin."
        )
        st.markdown(
            """
**What gets fetched:**
- Daily summaries (steps, calories, distance)
- Heart rate & HRV
- Sleep duration and quality scores
- Body Battery & stress levels
- SpO2 (blood oxygen) & respiration
- Training readiness & status
- All activities (runs, rides, swims, etc.)
- Body composition trends
- Personal records
            """
        )
        return

    _render_data_summary()
    _render_chat(api_key)


if __name__ == "__main__":
    main()
