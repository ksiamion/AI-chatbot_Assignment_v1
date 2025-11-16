import streamlit as st
from google import genai
from uuid import uuid4          # <-- add this line
from datetime import datetime
import json, re
import requests
import html

# ---- Importing System Prompt ----
from prompt import SYSTEM_PROMPT

# ---- Secure client ----
client = genai.Client(api_key=st.secrets['GEMINI_API_KEY'])
MODEL_NAME = "gemini-2.5-flash"
chat_client = client.chats.create(model=MODEL_NAME)

st.title("Wireless Support Bot")

# Session state init
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
if "user_input" not in st.session_state:
    st.session_state.user_input = ""
if "chat_closed" not in st.session_state:
    st.session_state.chat_closed = False
if "bootstrapped" not in st.session_state:
    st.session_state.bootstrapped = False
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid4())
if "started_at" not in st.session_state:
    st.session_state.started_at = datetime.utcnow().isoformat() + "Z"
if "prolific_id" not in st.session_state:
    st.session_state.prolific_id = ""
if "saved_once" not in st.session_state:
    st.session_state.saved_once = False

END_TOKEN = "[END_OF_CHAT]"
# =========================
# HELPERS
# =========================
def _compact_newlines(text: str) -> str:
    # normalize newlines
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    # drop whitespace-only lines
    t = re.sub(r"[ \t]+\n", "\n", t)
    # collapse 3+ consecutive line breaks to just one blank line
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()

# ---- Colored chat bubbles (helper) ----
def render_bubble(role: str, text: str):
    # Colors
    if role == "assistant":
        label = "Assistant"
        bg = "#E8F5FF"   # light blue
        border = "#B3E0FF"
        justify = "flex-start"
    else:
        label = "You"
        bg = "#FFF4E5"   # light orange
        border = "#FFD8A8"
        justify = "flex-end"

    # Compact spacing and escape HTML
    compact = _compact_newlines(text)
    safe = html.escape(compact).replace("\n", "<br>")

    st.markdown(
        f"""
        <div style="display:flex; justify-content:{justify}; margin:6px 0;">
          <div style="
              max-width: 85%;
              padding: 10px 12px;
              background: {bg};
              border: 1px solid {border};
              border-radius: 14px;
              line-height: 1.35;
              white-space: normal;">
            <strong>{label}:</strong><br>{safe}
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

def _messages_without_system():
    return [m for m in st.session_state.messages if m["role"] != "system"]

def _payload(include_system: bool = False):
    msgs = st.session_state.messages if include_system else _messages_without_system()
    return {
        "session_id": st.session_state.session_id,
        "started_at": st.session_state.started_at,
        "ended_at": datetime.utcnow().isoformat() + "Z" if st.session_state.chat_closed else None,
        "prolific_id": st.session_state.prolific_id or None,
        "messages": msgs,
    }

def _maybe_capture_prolific_id(text: str):
    # Best-effort: first user message is treated as an ID, otherwise find an alphanumeric 12+ token.
    if not st.session_state.prolific_id:
        if sum(1 for m in st.session_state.messages if m["role"] == "user") == 0:
            st.session_state.prolific_id = text.strip()
            return
        m = re.search(r"\b([A-Za-z0-9]{12,})\b", text)
        if m:
            st.session_state.prolific_id = m.group(1)

def _save_to_drive_once():
    """POST the full transcript to your Apps Script Web App once (no links shown to users)."""
    if st.session_state.saved_once:
        return
    try:
        base = st.secrets["WEBHOOK_URL"].rstrip("?")
        # Optional token support: if WEBHOOK_TOKEN is provided, append it; else just use base.
        token = st.secrets.get("WEBHOOK_TOKEN")
        url = f"{base}?token={token}" if token else base

        r = requests.post(url, json=_payload(False), timeout=10)
        if r.status_code == 200 and (r.text or "").strip().startswith("OK"):
            st.session_state.saved_once = True
        else:
            st.sidebar.warning(f"Admin note: webhook save failed ({r.status_code}): {r.text[:200]}")
    except Exception as e:
        st.sidebar.warning(f"Admin note: webhook error: {e}")

def _append_assistant_reply_from_model():
    response = chat_client.send_message(st.session_state.messages)
    raw = response.text
    if END_TOKEN in raw:
        visible = raw.split(END_TOKEN)[0].rstrip()
        st.session_state.chat_closed = True
    else:
        visible = raw

    st.session_state.messages.append({"role": "assistant", "content": visible})

    # If the chat ended this turn, save logs to Drive (admin-only, silent)
    if st.session_state.chat_closed:
        _save_to_drive_once()

# =========================
# AUTO-START (assistant speaks first)
# =========================

if not st.session_state.bootstrapped:
    if len(st.session_state.messages) == 1:
        _append_assistant_reply_from_model()
    st.session_state.bootstrapped = True

# =========================
# RENDER HISTORY
# =========================

#replaced
#for msg in st.session_state.messages[1:]:
#    st.write(f"**{msg['role'].capitalize()}:** {msg['content']}")
# ---- Render history (skip system prompt) ----

for msg in st.session_state.messages[1:]:
    render_bubble(msg["role"], msg["content"])
# =========================
# INPUT HANDLING
# =========================

def send_message():
    if st.session_state.chat_closed:
        return
    text = st.session_state.user_input.strip()
    if not text:
        return
    _maybe_capture_prolific_id(text)
    st.session_state.messages.append({"role": "user", "content": text})
    _append_assistant_reply_from_model()
    st.session_state.user_input = ""
    # No st.rerun() in callbacks (no-op); Streamlit auto-reruns.

if st.session_state.chat_closed:
    st.info("🔒 End of chat. Thank you! Please return to the survey to complete all questions.")
    if st.button("Start a new chat"):
        sid = str(uuid4())
        st.session_state.clear()
        st.session_state.session_id = sid
else:
    st.text_input(
        "You:",
        key="user_input",
        placeholder="Type your message… (press Enter to send)",
        on_change=send_message,
    )
