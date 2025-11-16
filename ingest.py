import os
from pathlib import Path

from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

INPUT_MD = Path("data/yelp_businesses.md")
INDEX_DIR = "index"

def load_md(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}. Put your .md file at data/knowledge.md")
    text = path.read_text(encoding="utf-8", errors="ignore")
    return [Document(page_content=text, metadata={"source": str(path)})]

if __name__ == "__main__":
    # 1) Load
    docs = load_md(INPUT_MD)

    # 2) Split into chunks
    splitter = RecursiveCharacterTextSplitter(chunk_size=1200, chunk_overlap=150)
    chunks = splitter.split_documents(docs)

    # 3) Embed + build FAISS
    embeddings = GoogleGenerativeAIEmbeddings(model="text-embedding-004")
    vs = FAISS.from_documents(chunks, embeddings)

    # 4) Persist
    os.makedirs(INDEX_DIR, exist_ok=True)
    vs.save_local(INDEX_DIR)
    print(f"Indexed {len(chunks)} chunks into ./{INDEX_DIR}")