"""Retrieval steps shared by chat queries and the eval runner.

Each step returns its own timing so the UI and eval can show where latency goes.
"""
from __future__ import annotations

import re
import time
from typing import Any

from .chunking import is_low_info_chunk
from .database import Chunk, SessionLocal
from .embeddings import embed_texts
from .pinecone_client import get_index


def _ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000


def embed_query(question: str) -> tuple[list[float], int, float]:
    """Returns (vector, tokens, latency_ms)."""
    start = time.perf_counter()
    vecs, tokens, _ = embed_texts([question], batch_size=1)
    return vecs[0], tokens, _ms(start)


def _hydrate(index, namespace: str, ids: list[str]) -> dict[str, dict[str, Any]]:
    """Chunk metadata by vector id, from local SQLite (ids are "<document_id>:<chunk_index>").
    Falls back to a Pinecone fetch for any id SQLite does not know."""
    out: dict[str, dict[str, Any]] = {}
    db = SessionLocal()
    try:
        for row in db.query(Chunk).filter(Chunk.id.in_(ids)).all():
            out[row.id] = {
                "document_id": row.document_id,
                "chunk_index": row.chunk_index,
                "page_number": row.page_number,
                "heading": row.heading or "",
                "is_table": row.is_table,
                "text": row.text,
            }
    finally:
        db.close()
    missing = [i for i in ids if i not in out]
    if missing:
        fetched = index.fetch(ids=missing, namespace=namespace)
        for vid, vec in (getattr(fetched, "vectors", None) or {}).items():
            out[vid] = dict(getattr(vec, "metadata", None) or {})
    return out


def vector_search(namespace: str, query_vec: list[float], top_k: int) -> dict[str, Any]:
    """Query Pinecone, drop duplicate and low-info chunks, keep the first top_k (the
    candidate pool).

    Pinecone returns ids + scores only; chunk text comes from local SQLite. Asking Pinecone
    for metadata makes the response ~5x larger (~37 KB vs ~7 KB), which costs extra network
    round trips whenever the TCP window has shrunk after an idle gap (~250-500 ms from India).

    Returned timings split the step into getting an index handle (connect_ms), the query
    round trip (query_ms), and the local metadata lookup (hydrate_ms).
    """
    start = time.perf_counter()
    index = get_index()
    connect_ms = _ms(start)

    # Over-fetch a little so the pool is still full after dropping duplicates/boilerplate.
    fetch_k = top_k + max(10, top_k // 2)
    q_start = time.perf_counter()
    result = index.query(
        vector=query_vec,
        top_k=fetch_k,
        namespace=namespace,
        include_metadata=False,
    )
    query_ms = _ms(q_start)

    h_start = time.perf_counter()
    raw = getattr(result, "matches", None) or result.get("matches", [])
    scored = [
        (getattr(m, "id", None) or m.get("id"), float(getattr(m, "score", None) or m.get("score") or 0))
        for m in raw
    ]
    metadata = _hydrate(index, namespace, [vid for vid, _ in scored])
    hydrate_ms = _ms(h_start)

    matches: list[dict[str, Any]] = []
    seen_text: set[str] = set()
    dropped_low_info = 0
    for vid, score in scored:
        meta = metadata.get(vid) or {}
        text = str(meta.get("text") or "")
        text_key = re.sub(r"\s+", " ", text).strip().lower()
        if text_key and text_key in seen_text:
            continue
        if is_low_info_chunk(text, meta.get("heading"), bool(meta.get("is_table"))):
            dropped_low_info += 1
            continue
        if text_key:
            seen_text.add(text_key)
        matches.append({"id": vid, "score": score, "metadata": dict(meta)})
        if len(matches) >= top_k:
            break

    return {
        "matches": matches,
        "fetch_k": fetch_k,
        "dropped_low_info": dropped_low_info,
        "connect_ms": connect_ms,
        "query_ms": query_ms,
        "hydrate_ms": hydrate_ms,
        "total_ms": _ms(start),
    }


def match_page(match: dict[str, Any]) -> int | None:
    page = match.get("metadata", {}).get("page_number")
    try:
        return int(page) if page is not None else None
    except (TypeError, ValueError):
        return None


def rerank_step(question: str, candidates: list[dict[str, Any]], enabled: bool) -> dict[str, Any]:
    """Reorder the candidate pool by rerank score. Every candidate gets vector_rank,
    rerank_score (None when off/failed) and final_rank. A reranker failure falls back
    to vector order so the query still answers."""
    from .rerank import apply_rerank, rerank

    for i, c in enumerate(candidates):
        c["vector_rank"] = i + 1
        c["rerank_score"] = None
        c["final_rank"] = i + 1
    if not enabled or not candidates:
        return {"ordered": candidates, "ms": None, "error": None, "model": None, "tokens_in": 0, "tokens_out": 0}
    start = time.perf_counter()
    try:
        res = rerank(question, candidates)
    except Exception as exc:
        return {"ordered": candidates, "ms": _ms(start), "error": str(exc), "model": None, "tokens_in": 0, "tokens_out": 0}
    return {
        "ordered": apply_rerank(candidates, res["scores"]),
        "ms": _ms(start),
        "error": None,
        "model": res["model"],
        "tokens_in": res["tokens_in"],
        "tokens_out": res["tokens_out"],
    }


RRF_K = 60


def fuse(
    semantic: list[dict[str, Any]],
    keyword_hits: list[dict[str, Any]],
    weight: float,
    pool: int,
) -> list[dict[str, Any]]:
    """Weighted reciprocal-rank fusion of the semantic and keyword rankings.

    weight 0 = pure semantic, 1 = pure keyword. Ranks are fused rather than raw scores
    because cosine similarity (~0.3-0.6) and BM25 (unbounded) are not comparable.
    Each candidate records how it was found: "semantic", "keyword" or "both".
    Keyword-only hits have score=None (Pinecone never scored them).
    """
    by_id: dict[str, dict[str, Any]] = {}
    for rank, m in enumerate(semantic, start=1):
        by_id[m["id"]] = {
            **m,
            "semantic_rank": rank,
            "keyword_rank": None,
            "bm25": None,
            "matched_terms": [],
        }
    for rank, h in enumerate(keyword_hits, start=1):
        entry = by_id.get(h["id"])
        if entry is None:
            entry = {"id": h["id"], "score": None, "metadata": h["metadata"], "semantic_rank": None}
            by_id[h["id"]] = entry
        entry.update(keyword_rank=rank, bm25=h["bm25"], matched_terms=h["matched_terms"])

    for e in by_id.values():
        sem = (1 - weight) / (RRF_K + e["semantic_rank"]) if e["semantic_rank"] else 0.0
        kw = weight / (RRF_K + e["keyword_rank"]) if e.get("keyword_rank") else 0.0
        e["hybrid_score"] = sem + kw
        if e["semantic_rank"] and e.get("keyword_rank"):
            e["found_by"] = "both"
        else:
            e["found_by"] = "semantic" if e["semantic_rank"] else "keyword"

    ranked = sorted(
        (e for e in by_id.values() if e["hybrid_score"] > 0),
        key=lambda e: (-e["hybrid_score"], e["semantic_rank"] or 10_000),
    )
    return ranked[:pool]
