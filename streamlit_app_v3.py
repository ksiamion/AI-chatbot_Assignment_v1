import os
import re
import glob
import html
import hashlib
from uuid import uuid4
from datetime import datetime
from pathlib import Path

import streamlit as st

from prompt import SYSTEM_PROMPT

# LangChain / Gemini / FAISS
from langchain_google_genai import (
    ChatGoogleGenerativeAI,
    GoogleGenerativeAIEmbeddings,
)
from langchain_community.vectorstores import FAISS
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableWithMessageHistory
from langchain_core.messages import AIMessage, HumanMessage
from langchain_community.chat_message_histories import StreamlitChatMessageHistory


# =========================
# CONFIG
# =========================
st.set_page_config(page_title="Yelp Bot (RAG)", page_icon="📡")
st.title("Yelp Bot")

GOOGLE_API_KEY = st.secrets.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
if not GOOGLE_API_KEY:
    st.error("Missing GEMINI_API_KEY (set it in Streamlit secrets).")
    st.stop()

MODEL_NAME = "gemini-2.5-flash"
DATA_DIR = Path("data")
K = 4  # top-k chunks for retrieval


# =========================
# UI HELPERS (bubbles)
# =========================
def _compact_newlines(text: str) -> str:
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def render_bubble(role: str, text: str):
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


def _load_md_documents(folder: Path):
    docs = []
    for path in sorted(glob.glob(str(folder / "**/*.md"), recursive=True)):
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
        docs.append(Document(page_content=text, metadata={"source": path}))
    return docs


@st.cache_resource(show_spinner=True)
def _build_retriever():
    """Builds FAISS from all .md files and returns a retriever. Cached by fingerprint."""
    docs = _load_md_documents(DATA_DIR)
    if not docs:
        raise RuntimeError(f"No .md files found in {DATA_DIR}/ (add at least one).")

    splitter = RecursiveCharacterTextSplitter(chunk_size=1200, chunk_overlap=150)
    chunks = splitter.split_documents(docs)

    embeddings = GoogleGenerativeAIEmbeddings(model="text-embedding-004", api_key=GOOGLE_API_KEY)
    vs = FAISS.from_documents(chunks, embeddings)

    # Optional: persist within container lifetime (not relied upon on Cloud)
    try:
        Path("index").mkdir(parents=True, exist_ok=True)
        vs.save_local("index")
    except Exception:
        pass

    return vs.as_retriever(search_kwargs={"k": K})


def get_retriever():
    return _build_retriever()


# =========================
# RAG CHAIN
# =========================
def format_docs_with_markers(docs):
    """Add bracket markers [1], [2], ... and include source in each chunk."""
    out = []
    for i, d in enumerate(docs, 1):
        src = d.metadata.get("source", "source.md")
        out.append(f"[{i}] Source: {src}\n{d.page_content}")
    return "\n\n".join(out)


def make_chain(retriever):
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        MessagesPlaceholder("history"),
        ("human", "Question: {question}\n\nUse the context below.\n\n{context}"),
    ])

    llm = ChatGoogleGenerativeAI(
        model=MODEL_NAME,
        api_key=GOOGLE_API_KEY,
    )

    def retrieve_context(x):
        docs = retriever.get_relevant_documents(x["question"])
        return format_docs_with_markers(docs)

    chain = (
        {
            "question": lambda x: x["question"],
            "context": retrieve_context,
            "history": lambda x: x["history"],
        }
        | prompt
        | llm
        | StrOutputParser()
    )
    return chain


# =========================
# SESSION INIT
# =========================
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid4())
if "started_at" not in st.session_state:
    st.session_state.started_at = datetime.utcnow().isoformat() + "Z"

# Build retriever (cached) and chain
retriever = get_retriever()
base_chain = make_chain(retriever)

history = StreamlitChatMessageHistory(key="chat_history")
rag_with_history = RunnableWithMessageHistory(
    base_chain,
    lambda sid: history,
    input_messages_key="question",
    history_messages_key="history",
)

# First assistant message (optional)
if len(history.messages) == 0:
    history.add_ai_message("Hi! I’m your Yelp Bot. Ask me anything about any business in Tucson.")

# Sidebar controls
with st.sidebar:
    st.subheader("Knowledge")
    st.caption("All `.md` files under `data/` are indexed at startup.")
    if st.button("🔁 Rebuild index"):
        _build_retriever.clear()  # clear cache; next access rebuilds
        st.success("Index cache cleared. It will rebuild on the next message.")

# Render chat history with bubbles
for m in history.messages:
    role = "assistant" if isinstance(m, AIMessage) else "user"
    render_bubble(role, m.content)

# Input (chat style)
user_text = st.chat_input("Type your message…")
if user_text:
    render_bubble("user", user_text)

    response = rag_with_history.invoke(
        {"question": user_text},
        config={"configurable": {"session_id": st.session_state.session_id}},
    )

    render_bubble("assistant", response)