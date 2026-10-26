"""BM25 keyword search over a document's chunks (from local SQLite).

Semantic search blurs exact tokens: "FY26E", "EBITDA", a loan number or "12,97,82,239"
embed close to many similar-looking chunks. BM25 matches the literal tokens instead.
The index is built in memory per document (a few ms for ~1000 chunks) and rebuilt
whenever the document is re-ingested.
"""
from __future__ import annotations

import math
import re
import threading
import time
from collections import Counter, defaultdict
from typing import Any

from .chunking import is_low_info_chunk
from .database import Chunk, Document, SessionLocal

# Order matters: alphanumeric codes (FY26E, LCV2996785) before plain numbers and words.
TOKEN_RE = re.compile(
    r"[A-Za-z]+[0-9][A-Za-z0-9]*"            # FY26E, Q3FY26, LCV2996785
    r"|[0-9][0-9,]*(?:\.[0-9]+)?%?[A-Za-z]*"  # 41,247.20  12,97,82,239  25.168%  2026E
    r"|[A-Za-z]+"                            # words
)
STOPWORDS = set(
    "a an and are as at be by did do does for from had has have how in is it its of on or "
    "our than that the their them there these they this those to was were what when where "
    "which who whom why will with would can could should much many any about into during "
    "company report".split()
)
K1 = 1.2
B = 0.75


def tokenize(text: str) -> list[str]:
    out: list[str] = []
    for raw in TOKEN_RE.findall(text or ""):
        tok = raw.lower()
        if tok[0].isdigit():
            tok = tok.replace(",", "")  # Indian and Western digit grouping both match
            out.append(tok)
            if "." in tok:
                out.append(tok.split(".", 1)[0])  # "41247.20" also matches "41247"
            if tok.endswith("%"):
                out.append(tok[:-1])
            continue
        if tok in STOPWORDS or len(tok) < 2:
            continue
        out.append(tok)
    return out


class _Index:
    def __init__(self, rows: list[Chunk]) -> None:
        self.rows: list[dict[str, Any]] = []
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        lengths: list[int] = []
        for row in rows:
            if is_low_info_chunk(row.text, row.heading, row.is_table):
                continue
            toks = tokenize(f"{row.heading or ''}\n{row.text}")
            if not toks:
                continue
            i = len(self.rows)
            self.rows.append(
                {
                    "id": row.id,
                    "metadata": {
                        "document_id": row.document_id,
                        "chunk_index": row.chunk_index,
                        "page_number": row.page_number,
                        "heading": row.heading or "",
                        "is_table": row.is_table,
                        "text": row.text,
                    },
                }
            )
            lengths.append(len(toks))
            for tok, tf in Counter(toks).items():
                self.postings[tok].append((i, tf))
        self.lengths = lengths
        self.avgdl = (sum(lengths) / len(lengths)) if lengths else 1.0
        n = len(self.rows)
        self.idf = {
            tok: math.log(1 + (n - len(p) + 0.5) / (len(p) + 0.5)) for tok, p in self.postings.items()
        }

    def search(self, query: str, top_k: int) -> list[dict[str, Any]]:
        q_toks = list(dict.fromkeys(tokenize(query)))
        scores: dict[int, float] = defaultdict(float)
        matched: dict[int, list[str]] = defaultdict(list)
        for tok in q_toks:
            idf = self.idf.get(tok)
            if idf is None:
                continue
            for i, tf in self.postings[tok]:
                dl = self.lengths[i]
                scores[i] += idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * dl / self.avgdl))
                matched[i].append(tok)
        best = sorted(scores.items(), key=lambda kv: -kv[1])[:top_k]
        return [
            {
                "id": self.rows[i]["id"],
                "bm25": round(score, 4),
                "matched_terms": matched[i],
                "metadata": dict(self.rows[i]["metadata"]),
            }
            for i, score in best
        ]


_cache: dict[str, tuple[str | None, int, _Index]] = {}
_lock = threading.Lock()


def _get_index(document_id: str) -> _Index:
    db = SessionLocal()
    try:
        doc = db.get(Document, document_id)
        signature = doc.ingest_trace_id if doc else None
        count = db.query(Chunk).filter(Chunk.document_id == document_id).count()
        cached = _cache.get(document_id)
        if cached and cached[0] == signature and cached[1] == count:
            return cached[2]
        with _lock:
            rows = db.query(Chunk).filter(Chunk.document_id == document_id).all()
            index = _Index(rows)
            _cache[document_id] = (signature, count, index)
            return index
    finally:
        db.close()


def keyword_search(document_id: str, query: str, top_k: int) -> dict[str, Any]:
    start = time.perf_counter()
    hits = _get_index(document_id).search(query, top_k)
    return {
        "hits": hits,
        "query_terms": list(dict.fromkeys(tokenize(query))),
        "ms": (time.perf_counter() - start) * 1000,
    }
