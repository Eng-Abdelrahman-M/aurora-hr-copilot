"""Policy corpus ingestion + retrieval.

Chunking is heading-aware: every `## section` (md), `<h2>` (html) or numbered
ALL-CAPS heading (txt) becomes one chunk, carrying doc_id / title / section
metadata so answers can cite their sources. Chunk ids are deterministic
(doc_id::index), so re-ingestion is idempotent.

Embeddings: Chroma's default local ONNX MiniLM model — free, no API key.
"""
import re
from html.parser import HTMLParser
from pathlib import Path

import chromadb

ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT / "corpus"
CHROMA_DIR = ROOT / ".chroma"
COLLECTION = "policies"

_client = None
_collection = None


# ── parsing ──────────────────────────────────────────────────────────────────

class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self._h2 = False

    def handle_starttag(self, tag, attrs):
        if tag == "h2":
            self._h2 = True

    def handle_endtag(self, tag):
        if tag == "h2":
            self._h2 = False

    def handle_data(self, data):
        if data.strip():
            self.parts.append(("h2" if self._h2 else "text", data.strip()))


def _doc_meta(text, fallback_title):
    m = re.search(r"Document ID:\s*(POL-[A-Z]+-\d+)", text)
    return m.group(1) if m else fallback_title


def _sections_md(text):
    title = next((l[2:].strip() for l in text.splitlines() if l.startswith("# ")), "")
    parts = re.split(r"^## ", text, flags=re.M)
    intro, rest = parts[0], parts[1:]
    out = [("Overview", intro)] if len(rest) == 0 else []
    for p in rest:
        heading, _, body = p.partition("\n")
        out.append((heading.strip(), body.strip()))
    return title, out


def _sections_html(text):
    parser = _TextExtractor()
    parser.feed(text)
    title, sections, current, buf = "", [], "Overview", []
    for kind, data in parser.parts:
        if not title and kind == "text":
            title = data
        if kind == "h2":
            if buf:
                sections.append((current, "\n".join(buf)))
            current, buf = data, []
        else:
            buf.append(data)
    if buf:
        sections.append((current, "\n".join(buf)))
    return title, sections


def _sections_txt(text):
    lines = text.splitlines()
    title = lines[0].strip()
    sections, current, buf = [], "Overview", []
    for line in lines[1:]:
        if re.match(r"^\d+\.\s+[A-Z]", line):
            if buf and any(s.strip() for s in buf):
                sections.append((current, "\n".join(buf).strip()))
            current, buf = line.strip(), []
        else:
            buf.append(line)
    if buf and any(s.strip() for s in buf):
        sections.append((current, "\n".join(buf).strip()))
    return title, sections


def parse_corpus():
    """Yield chunk dicts for every section of every corpus document."""
    chunks = []
    for path in sorted(CORPUS_DIR.iterdir()):
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".md":
            title, sections = _sections_md(text)
        elif path.suffix == ".html":
            title, sections = _sections_html(text)
        elif path.suffix == ".txt":
            title, sections = _sections_txt(text)
        else:
            continue
        doc_id = _doc_meta(text, path.stem)
        for i, (section, body) in enumerate(sections):
            if not body.strip():
                continue
            chunks.append({
                "id": f"{doc_id}::{i}",
                "text": f"{title} — {section}\n{body}",
                "metadata": {
                    "doc_id": doc_id,
                    "title": title,
                    "section": section,
                    "source_file": path.name,
                },
            })
    return chunks


# ── index ────────────────────────────────────────────────────────────────────

def get_collection():
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        _collection = _client.get_or_create_collection(
            COLLECTION, metadata={"hnsw:space": "cosine"})
    return _collection


def ingest(force=False):
    """Build the index if missing or stale. Idempotent."""
    col = get_collection()
    chunks = parse_corpus()
    if not force and col.count() == len(chunks):
        return col.count()
    if col.count():
        global _collection
        _client.delete_collection(COLLECTION)
        _collection = None
        col = get_collection()
    col.add(
        ids=[c["id"] for c in chunks],
        documents=[c["text"] for c in chunks],
        metadatas=[c["metadata"] for c in chunks],
    )
    return col.count()


def search(query, k=4):
    """Top-k semantic search. Returns citation-ready hits.
    RAG_K env var overrides k (used by the evaluation ablation)."""
    import os
    k = int(os.environ.get("RAG_K", k))
    col = get_collection()
    res = col.query(query_texts=[query], n_results=min(k, max(col.count(), 1)))
    hits = []
    for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
        hits.append({
            "doc_id": meta["doc_id"],
            "title": meta["title"],
            "section": meta["section"],
            "source_file": meta["source_file"],
            "snippet": doc[:800],
            "relevance": round(1 - dist, 3),
        })
    return hits


def get_section(doc_id, section_query=""):
    """Return full sections of one document, optionally filtered by section name."""
    col = get_collection()
    res = col.get(where={"doc_id": doc_id})
    out = []
    for doc, meta in zip(res["documents"], res["metadatas"]):
        if section_query and section_query.lower() not in meta["section"].lower():
            continue
        out.append({"doc_id": doc_id, "title": meta["title"],
                    "section": meta["section"], "text": doc})
    return out


if __name__ == "__main__":
    n = ingest(force=True)
    print(f"indexed {n} chunks")
    for h in search("how many vacation days carry over?", k=3):
        print(f"  {h['relevance']:.2f} {h['doc_id']} / {h['section']}")
    assert n > 30, "expected 30+ chunks"
    top = search("how many vacation days carry over?", k=1)[0]
    assert top["doc_id"] == "POL-PTO-001", f"expected PTO policy, got {top['doc_id']}"
    print("rag self-check OK")
