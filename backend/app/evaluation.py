"""Retrieval evaluation: run saved questions and score whether a correct page is retrieved.

The eval measures retrieval only (no LLM call), so runs are fast, cheap, and the
latency numbers isolate embedding + search (+ rerank once enabled).
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

from .database import AppSettings, Chunk, Document, EvalQuestion, EvalRun
from .keyword import keyword_search
from .postprocess import shape_results
from .retrieval import embed_query, fuse, match_page, rerank_step, vector_search

RECALL_K = 5
MRR_K = 10
TIMING_KEYS = [
    "query_embedding_ms",
    "vector_search_ms",
    "vector_connect_ms",
    "vector_query_ms",
    "keyword_ms",
    "rerank_ms",
]

ProgressCb = Callable[[dict[str, Any]], None]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def settings_snapshot(db: Session, document: Document) -> dict[str, Any]:
    row = db.get(AppSettings, 1)
    snap: dict[str, Any] = {}
    if row:
        for col in AppSettings.__table__.columns:
            if col.name in ("id", "system_prompt"):
                continue
            snap[col.name] = getattr(row, col.name)
    snap.pop("top_k", None)  # superseded by candidate_pool / final_k
    snap["chunk_count"] = db.query(Chunk).filter(Chunk.document_id == document.id).count()
    snap["ingest_trace_id"] = document.ingest_trace_id
    return snap


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    # SQLite drops tzinfo; values are written in UTC.
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).isoformat()


def question_to_dict(q: EvalQuestion) -> dict[str, Any]:
    return {
        "id": q.id,
        "document_id": q.document_id,
        "question": q.question,
        "expected_pages": json.loads(q.expected_pages_json or "[]"),
        "notes": q.notes,
        "created_at": _iso(q.created_at),
    }


def run_to_dict(run: EvalRun, include_results: bool = False) -> dict[str, Any]:
    out = {
        "id": run.id,
        "document_id": run.document_id,
        "label": run.label,
        "created_at": _iso(run.created_at),
        "settings": json.loads(run.settings_json or "{}"),
        "question_count": run.question_count,
        "recall_at_5": run.recall_at_5,
        "mrr_at_10": run.mrr_at_10,
        "avg_latency_ms": run.avg_latency_ms,
        "avg_timings": json.loads(run.avg_timings_json or "{}"),
    }
    if include_results:
        out["results"] = json.loads(run.results_json or "[]")
    return out


def _evaluate_one(
    document: Document,
    question: str,
    expected: set[int],
    pool: int,
    use_reranker: bool,
    keyword_weight: float,
    diversity: bool,
) -> dict[str, Any]:
    start = time.perf_counter()
    timings: dict[str, float | None] = {k: None for k in TIMING_KEYS}
    error = None
    warning = None
    ranked: list[dict[str, Any]] = []
    pre_merge: list[dict[str, Any]] = []
    try:
        vec, _tokens, embed_ms = embed_query(question)
        timings["query_embedding_ms"] = round(embed_ms, 1)
        found = vector_search(document.namespace, vec, max(pool, MRR_K))
        timings["vector_search_ms"] = round(found["total_ms"], 1)
        timings["vector_connect_ms"] = round(found["connect_ms"], 1)
        timings["vector_query_ms"] = round(found["query_ms"], 1)
        kw = keyword_search(document.id, question, max(pool, MRR_K))
        timings["keyword_ms"] = round(kw["ms"], 2)
        candidates = fuse(found["matches"], kw["hits"], keyword_weight, max(pool, MRR_K))
        reranked = rerank_step(question, candidates, use_reranker)
        if reranked["ms"] is not None:
            timings["rerank_ms"] = round(reranked["ms"], 1)
        if reranked["error"]:
            # Still scored (vector order), but flagged so it is not mistaken for a rerank result.
            warning = f"rerank failed, used vector order: {reranked['error']}"
        pre_merge = reranked["ordered"]
        ranked = shape_results(pre_merge, diversity)
    except Exception as exc:
        error = str(exc)
    latency_ms = (time.perf_counter() - start) * 1000

    pages = [match_page(m) for m in ranked[:MRR_K]]
    first_hit = next((i + 1 for i, p in enumerate(pages) if p in expected), None)
    return {
        "retrieved": [
            {
                "page": match_page(m),
                "score": round(m["score"], 4) if m["score"] is not None else None,
                "found_by": m.get("found_by"),
                "rerank_score": m.get("rerank_score"),
                "vector_rank": m.get("vector_rank"),
                "id": m["id"],
            }
            for m in ranked[:MRR_K]
        ],
        "first_hit_rank": first_hit,
        # Page repetition in the top 5 chunk slots before merging (merged results never repeat).
        "pre_merge_distinct_pages_top5": len({match_page(m) for m in pre_merge[:RECALL_K]}),
        "hit_at_5": first_hit is not None and first_hit <= RECALL_K,
        "latency_ms": round(latency_ms, 1),
        "timings": timings,
        "error": error,
        "warning": warning,
    }


def run_eval(
    db: Session,
    document: Document,
    label: str | None,
    progress: ProgressCb,
    pause_s: float = 0,
    limit: int | None = None,
) -> EvalRun:
    """pause_s spaces questions out to mimic a person asking (idle connections behave
    differently from back-to-back queries); limit runs only the first N questions."""
    questions = (
        db.query(EvalQuestion)
        .filter(EvalQuestion.document_id == document.id)
        .order_by(EvalQuestion.created_at.asc())
        .all()
    )
    if limit:
        questions = questions[:limit]
    snap = settings_snapshot(db, document)
    if pause_s:
        snap["eval_pause_s"] = pause_s
    pool = int(snap.get("candidate_pool") or 40)
    use_reranker = bool(snap.get("reranker_enabled", True))
    keyword_weight = float(snap.get("keyword_weight", 0.5))
    diversity = bool(snap.get("diversity_enabled", False))

    results: list[dict[str, Any]] = []
    for i, q in enumerate(questions, start=1):
        if pause_s and i > 1:
            time.sleep(pause_s)
        progress({"stage": "running", "done": i - 1, "total": len(questions), "message": q.question[:80]})
        expected = {int(p) for p in json.loads(q.expected_pages_json or "[]")}
        res = _evaluate_one(document, q.question, expected, pool, use_reranker, keyword_weight, diversity)
        res.update({"question_id": q.id, "question": q.question, "expected_pages": sorted(expected)})
        results.append(res)

    ok = [r for r in results if not r["error"]]
    n = len(ok)
    recall = sum(1 for r in ok if r["hit_at_5"]) / n if n else 0.0
    mrr = sum(1 / r["first_hit_rank"] for r in ok if r["first_hit_rank"]) / n if n else 0.0
    avg_latency = sum(r["latency_ms"] for r in ok) / n if n else 0.0
    avg_timings: dict[str, float | None] = {}
    for key in TIMING_KEYS:
        vals = [r["timings"][key] for r in ok if r["timings"].get(key) is not None]
        avg_timings[key] = round(sum(vals) / len(vals), 1) if vals else None
    # Median too: the first query after a restart can be an outlier.
    lat_sorted = sorted(r["latency_ms"] for r in ok)
    avg_timings["p50_latency_ms"] = lat_sorted[len(lat_sorted) // 2] if lat_sorted else None
    avg_timings["errors"] = len(results) - n
    avg_timings["rerank_fallbacks"] = sum(1 for r in results if r.get("warning"))
    # Not timings, but kept alongside so the comparison table can show them.
    avg_timings["distinct_pages_top5"] = (
        round(sum(len({x["page"] for x in r["retrieved"][:RECALL_K]}) for r in ok) / n, 2) if n else None
    )
    avg_timings["pre_merge_distinct_pages_top5"] = (
        round(sum(r["pre_merge_distinct_pages_top5"] for r in ok) / n, 2) if n else None
    )

    run = EvalRun(
        id=str(uuid.uuid4()),
        document_id=document.id,
        label=(label or "").strip() or None,
        created_at=_now(),
        settings_json=json.dumps(snap),
        question_count=len(results),
        recall_at_5=round(recall, 4),
        mrr_at_10=round(mrr, 4),
        avg_latency_ms=round(avg_latency, 1),
        avg_timings_json=json.dumps(avg_timings),
        results_json=json.dumps(results),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    progress({"stage": "done", "done": len(results), "total": len(results), "run_id": run.id})
    return run
