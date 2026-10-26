from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from .config import settings
from .database import AppSettings, Chunk, Document, Message, Trace
from .embeddings import chat_complete, count_tokens, llm_cost
from .keyword import keyword_search
from .postprocess import shape_results
from .retrieval import embed_query, fuse, rerank_step, vector_search
from .trace_utils import make_node

CITATION_RE = re.compile(r"\[p\.?\s*(\d+)\]", re.IGNORECASE)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def run_query(
    db: Session,
    document: Document,
    question: str,
    *,
    candidate_pool: int | None = None,
    final_k: int | None = None,
    reranker_enabled: bool | None = None,
    keyword_weight: float | None = None,
    diversity_enabled: bool | None = None,
    similarity_threshold: float | None = None,
    system_prompt: str | None = None,
    temperature: float | None = None,
    parent_trace_id: str | None = None,
) -> dict[str, Any]:
    app_settings = db.get(AppSettings, 1)
    candidate_pool = candidate_pool or (app_settings.candidate_pool if app_settings else 40)
    final_k = final_k or (app_settings.final_k if app_settings else 5)
    if reranker_enabled is None:
        reranker_enabled = app_settings.reranker_enabled if app_settings else True
    if keyword_weight is None:
        keyword_weight = app_settings.keyword_weight if app_settings else 0.5
    if diversity_enabled is None:
        diversity_enabled = app_settings.diversity_enabled if app_settings else False
    threshold = (
        similarity_threshold
        if similarity_threshold is not None
        else (app_settings.similarity_threshold if app_settings else 0.0)
    )
    temperature = (
        temperature if temperature is not None else (app_settings.temperature if app_settings else 0.2)
    )
    system_prompt = system_prompt or (
        app_settings.system_prompt if app_settings else "Answer using the provided excerpts."
    )

    nodes: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    total_cost = 0.0
    pipeline_error: str | None = None

    # 1. User Query
    nodes.append(
        make_node(
            "user_query",
            "user_query",
            "User Query",
            0,
            question[:80] + ("…" if len(question) > 80 else ""),
            None,
            {
                "question": question,
                "timestamp": _now().isoformat(),
                "document_id": document.id,
                "filename": document.filename,
            },
            slow_ms=1_000,
        )
    )

    # 2. Query Embedding
    embed_start = time.perf_counter()
    query_vec: list[float] = []
    embed_tokens = 0
    embed_error = None
    try:
        query_vec, embed_tokens, _ = embed_query(question)
    except Exception as exc:
        embed_error = str(exc)
        pipeline_error = embed_error
    embed_ms = (time.perf_counter() - embed_start) * 1000
    embed_cost = (embed_tokens / 1_000_000) * settings.embedding_usd_per_1m
    total_cost += embed_cost
    nodes.append(
        make_node(
            "query_embedding",
            "query_embedding",
            "Query Embedding",
            embed_ms,
            f"{settings.openai_embedding_model} · {embed_tokens} tokens",
            f"{embed_ms:.0f} ms",
            {
                "model": settings.openai_embedding_model,
                "tokens": embed_tokens,
                "latency_ms": round(embed_ms, 1),
                "cost_usd": round(embed_cost, 6),
                "vector_preview": [round(x, 6) for x in query_vec[:10]] if query_vec else [],
                "dimensions": settings.embedding_dimensions,
            },
            error=embed_error,
            slow_ms=1_500,
        )
    )

    # 3. Pinecone Search (wide candidate pool)
    search_start = time.perf_counter()
    matches: list[dict[str, Any]] = []
    search_error = None
    dropped_low_info = 0
    connect_ms = 0.0
    query_ms = 0.0
    if query_vec and not pipeline_error:
        try:
            found = vector_search(document.namespace, query_vec, candidate_pool)
            matches = found["matches"]
            dropped_low_info = found["dropped_low_info"]
            connect_ms = found["connect_ms"]
            query_ms = found["query_ms"]
        except Exception as exc:
            search_error = str(exc)
            pipeline_error = search_error
    elif not query_vec:
        search_error = "Skipped because query embedding failed"
    search_ms = (time.perf_counter() - search_start) * 1000
    nodes.append(
        make_node(
            "pinecone_search",
            "pinecone_search",
            "Pinecone Search",
            search_ms,
            f"pool={candidate_pool} · {len(matches)} candidates",
            f"{len(matches)} candidates",
            {
                "index_name": settings.pinecone_index_name,
                "namespace": document.namespace,
                "top_k": candidate_pool,
                "latency_ms": round(search_ms, 1),
                "raw_scores": [
                    {"id": m["id"], "score": round(m["score"], 6), "page_number": m["metadata"].get("page_number")}
                    for m in matches
                ],
                "deduped": True,
                "dropped_low_info": dropped_low_info,
                "connect_ms": round(connect_ms, 1),
                "query_ms": round(query_ms, 1),
            },
            error=search_error,
            slow_ms=1_500,
        )
    )

    # 3b. Keyword search (local BM25) + fusion with the semantic ranking
    keyword_hits: list[dict[str, Any]] = []
    keyword_terms: list[str] = []
    keyword_ms = 0.0
    keyword_error = None
    try:
        kw = keyword_search(document.id, question, candidate_pool)
        keyword_hits, keyword_terms, keyword_ms = kw["hits"], kw["query_terms"], kw["ms"]
    except Exception as exc:
        keyword_error = str(exc)
    candidates = fuse(matches, keyword_hits, keyword_weight, candidate_pool) if not search_error else []
    found_counts = {k: sum(1 for c in candidates if c["found_by"] == k) for k in ("both", "semantic", "keyword")}
    nodes.append(
        make_node(
            "keyword_search",
            "keyword_search",
            "Keyword Search",
            keyword_ms,
            f"BM25 · {len(keyword_hits)} hits · weight {keyword_weight:.2f}",
            f"{found_counts['both']} both · {found_counts['keyword']} kw-only",
            {
                "query_terms": keyword_terms,
                "keyword_weight": keyword_weight,
                "latency_ms": round(keyword_ms, 2),
                "hits": [
                    {
                        "id": h["id"],
                        "bm25": h["bm25"],
                        "page_number": h["metadata"].get("page_number"),
                        "matched_terms": h["matched_terms"],
                    }
                    for h in keyword_hits[:20]
                ],
                "fused_counts": found_counts,
            },
            error=keyword_error,
            slow_ms=500,
        )
    )

    # 4. Rerank the pool, then keep the best final_k for the LLM
    reranked = rerank_step(question, candidates, reranker_enabled and not pipeline_error)
    rerank_ms = reranked["ms"]
    ordered = reranked["ordered"]
    rerank_cost = llm_cost(reranked["tokens_in"], reranked["tokens_out"], reranked["model"]) if reranked["model"] else 0.0
    total_cost += rerank_cost
    if reranker_enabled:
        moved_up = sum(1 for c in ordered[:final_k] if c["vector_rank"] > final_k)
        nodes.append(
            make_node(
                "rerank",
                "rerank",
                "Rerank",
                rerank_ms or 0,
                f"{reranked['model'] or 'failed'} · {len(ordered)} → {min(final_k, len(ordered))}",
                f"{moved_up} promoted into top {final_k}",
                {
                    "model": reranked["model"],
                    "latency_ms": round(rerank_ms or 0, 1),
                    "candidates": len(ordered),
                    "final_k": final_k,
                    "tokens_in": reranked["tokens_in"],
                    "tokens_out": reranked["tokens_out"],
                    "cost_usd": round(rerank_cost, 6),
                    "fallback": "Reranker failed; using vector order" if reranked["error"] else None,
                    "moves": [
                        {
                            "page_number": c["metadata"].get("page_number"),
                            "vector_rank": c["vector_rank"],
                            "final_rank": c["final_rank"],
                            "found_by": c.get("found_by"),
                            "rerank_score": c["rerank_score"],
                        }
                        for c in ordered[: max(final_k, 10)]
                    ],
                },
                error=reranked["error"],
                slow_ms=3_000,
            )
        )

    # 4b. Merge same-page chunks into one result per page; optionally diversify
    shape_start = time.perf_counter()
    results = shape_results(ordered, diversity_enabled)
    shape_ms = (time.perf_counter() - shape_start) * 1000
    merged_pages = [r for r in results if r["merged_count"] > 1]
    top_pre = ordered[:final_k]
    repeats_before = len(top_pre) - len({c["metadata"].get("page_number") for c in top_pre})
    nodes.append(
        make_node(
            "merge_diversity",
            "merge_diversity",
            "Merge & Diversity",
            shape_ms,
            f"{len(ordered)} chunks → {len(results)} page results"
            + (" · diversity on" if diversity_enabled else ""),
            f"{repeats_before} repeat slot{'s' if repeats_before != 1 else ''} freed",
            {
                "chunks_in": len(ordered),
                "results_out": len(results),
                "diversity_enabled": diversity_enabled,
                "repeated_page_slots_before": repeats_before,
                "merged_pages": [
                    {
                        "page_number": r["metadata"].get("page_number"),
                        "chunks": r["merged_count"],
                        "chunk_indices": r["merged_chunk_indices"],
                    }
                    for r in merged_pages[:15]
                ],
                "final_pages": [
                    {
                        "page_number": r["metadata"].get("page_number"),
                        "result_rank": r["result_rank"],
                        "pre_diversity_rank": r.get("pre_diversity_rank"),
                        "redundancy": r.get("redundancy"),
                    }
                    for r in results[: max(final_k, 8)]
                ],
            },
            slow_ms=500,
        )
    )

    # 5. Retrieved Chunks (page results in final order; the first final_k go to the LLM)
    retrieved: list[dict[str, Any]] = []
    for m in results:
        meta = m["metadata"]
        chunk_index = meta.get("chunk_index")
        text = meta.get("text") or ""
        if not text and chunk_index is not None:
            row = (
                db.query(Chunk)
                .filter(Chunk.document_id == document.id, Chunk.chunk_index == int(chunk_index))
                .first()
            )
            if row:
                text = row.text
        retrieved.append(
            {
                "rank": m["result_rank"],
                "vector_rank": m["vector_rank"],
                "merged_count": m["merged_count"],
                "merged_chunk_indices": m["merged_chunk_indices"],
                "pre_diversity_rank": m.get("pre_diversity_rank"),
                "redundancy": m.get("redundancy"),
                "id": m["id"],
                "score": m["score"],
                "rerank_score": m["rerank_score"],
                "found_by": m.get("found_by"),
                "semantic_rank": m.get("semantic_rank"),
                "keyword_rank": m.get("keyword_rank"),
                "bm25": m.get("bm25"),
                "matched_terms": m.get("matched_terms") or [],
                "below_threshold": (m["score"] is not None and m["score"] < threshold) if threshold else False,
                "sent_to_llm": m["result_rank"] <= final_k,
                "chunk_index": chunk_index,
                "page_number": meta.get("page_number"),
                "heading": meta.get("heading") or None,
                "is_table": bool(meta.get("is_table")),
                "text": text,
            }
        )
    selected = [c for c in retrieved if c["sent_to_llm"]]

    nodes.append(
        make_node(
            "retrieved_chunks",
            "retrieved_chunks",
            "Retrieved Chunks",
            0,
            f"{len(selected)} of {len(retrieved)} sent to LLM"
            + (" · reranked" if reranker_enabled and not reranked["error"] else " · vector order"),
            f"{len(selected)} chunks",
            {
                "chunks": retrieved,
                "similarity_threshold": threshold,
                "final_k": final_k,
                "reranked": bool(reranker_enabled and not reranked["error"]),
            },
            slow_ms=1_000,
        )
    )

    # 6. Prompt Assembly
    included = [c for c in selected if not c["below_threshold"]]
    if not included:
        included = selected[: max(final_k, 1)]

    excerpt_blocks = []
    for c in included:
        heading = f" | {c['heading']}" if c.get("heading") else ""
        table_flag = " | TABLE" if c.get("is_table") else ""
        excerpt_blocks.append(
            f"[p.{c['page_number']} | chunk{'s' if len(c['merged_chunk_indices']) > 1 else ''} "
            f"{', '.join(str(i) for i in c['merged_chunk_indices'])}{heading}{table_flag}]\n{c['text']}"
        )
    excerpts = "\n\n".join(excerpt_blocks)
    user_prompt = (
        f"Report: {document.filename}\n\n"
        f"Excerpts:\n{excerpts}\n\n"
        f"Question: {question}\n\n"
        "Answer the question using only the excerpts. Cite pages as [p.N]."
    )
    prompt_tokens = count_tokens(system_prompt) + count_tokens(user_prompt)
    nodes.append(
        make_node(
            "prompt_assembly",
            "prompt_assembly",
            "Prompt Assembly",
            0,
            f"{prompt_tokens:,} tokens · {len(included)} chunks in prompt",
            f"{prompt_tokens:,} tokens",
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "final_prompt": f"SYSTEM:\n{system_prompt}\n\nUSER:\n{user_prompt}",
                "total_tokens": prompt_tokens,
                "included_chunk_indices": [c["chunk_index"] for c in included],
                "excluded_below_threshold": [
                    c["chunk_index"] for c in selected if c["below_threshold"]
                ],
            },
            slow_ms=1_000,
        )
    )

    # 6. LLM Call
    llm_start = time.perf_counter()
    answer = ""
    in_tok = 0
    out_tok = 0
    llm_error = None
    if not pipeline_error:
        try:
            answer, in_tok, out_tok = chat_complete(system_prompt, user_prompt)
        except Exception as exc:
            llm_error = str(exc)
            pipeline_error = llm_error
    llm_ms = (time.perf_counter() - llm_start) * 1000
    llm_cost_usd = llm_cost(in_tok, out_tok)
    total_cost += llm_cost_usd
    nodes.append(
        make_node(
            "llm_call",
            "llm_call",
            "LLM Call",
            llm_ms,
            f"{settings.openai_llm_model} · {in_tok}+{out_tok} tokens",
            f"{llm_ms:.0f} ms",
            {
                "model": settings.openai_llm_model,
                "temperature": temperature,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "latency_ms": round(llm_ms, 1),
                "cost_usd": round(llm_cost_usd, 6),
            },
            error=llm_error,
            slow_ms=8_000,
        )
    )

    # Latency breakdown, attached to the search node so it is visible where people look first.
    timings = {
        "query_embedding_ms": round(embed_ms, 1),
        "vector_search_ms": round(search_ms, 1),
        "vector_connect_ms": round(connect_ms, 1),
        "vector_query_ms": round(query_ms, 1),
        "keyword_ms": round(keyword_ms, 2),
        "rerank_ms": round(rerank_ms, 1) if rerank_ms is not None else None,
        "llm_ms": round(llm_ms, 1),
    }
    for node in nodes:
        if node["id"] == "pinecone_search":
            node["data"]["timings"] = timings

    # 7. Final Answer
    cited_pages = sorted({int(p) for p in CITATION_RE.findall(answer)})
    cited_chunks = []
    ignored_chunks = []
    for c in included:
        page = c.get("page_number")
        try:
            page_i = int(page) if page is not None else None
        except (TypeError, ValueError):
            page_i = None
        if page_i is not None and page_i in cited_pages:
            cited_chunks.append(c["chunk_index"])
        else:
            ignored_chunks.append(c["chunk_index"])

    citations = []
    for c in included:
        page = c.get("page_number")
        try:
            page_i = int(page) if page is not None else None
        except (TypeError, ValueError):
            page_i = None
        if page_i is None:
            continue
        if page_i in cited_pages:
            citations.append(
                {
                    "page": page_i,
                    "chunk_index": c["chunk_index"],
                    "score": c["rerank_score"] if c["rerank_score"] is not None else (c["score"] or 0.0),
                    "excerpt": (c["text"] or "")[:280],
                    "heading": c.get("heading"),
                }
            )
    # de-dupe by page, keep highest score
    best: dict[int, dict[str, Any]] = {}
    for cit in citations:
        prev = best.get(cit["page"])
        if prev is None or cit["score"] > prev["score"]:
            best[cit["page"]] = cit
    citations = [best[p] for p in sorted(best)]

    nodes.append(
        make_node(
            "final_answer",
            "final_answer",
            "Final Answer",
            0,
            (answer[:90] + "…") if len(answer) > 90 else (answer or (pipeline_error or "")),
            f"{len(cited_chunks)} cited",
            {
                "answer": answer,
                "cited_pages": cited_pages,
                "cited_chunk_indices": cited_chunks,
                "ignored_chunk_indices": ignored_chunks,
                "citations": citations,
            },
            error=pipeline_error if not answer else None,
            slow_ms=1_000,
        )
    )

    total_ms = (time.perf_counter() - t0) * 1000
    status = "error" if pipeline_error and not answer else "success" if answer else "error"
    if pipeline_error and not answer:
        status = "error"

    used_settings = {
        "candidate_pool": candidate_pool,
        "final_k": final_k,
        "reranker_enabled": reranker_enabled,
        "keyword_weight": keyword_weight,
        "diversity_enabled": diversity_enabled,
        "similarity_threshold": threshold,
        "temperature": temperature,
        "chunk_size": app_settings.chunk_size if app_settings else 1000,
        "chunk_overlap": app_settings.chunk_overlap if app_settings else 200,
        "timings": timings,
    }

    trace = Trace(
        id=str(uuid.uuid4()),
        type="query",
        document_id=document.id,
        query_text=question,
        parent_trace_id=parent_trace_id,
        created_at=_now(),
        total_latency_ms=round(total_ms, 1),
        total_cost_usd=round(total_cost, 6),
        status=status,
        nodes_json=json.dumps(nodes),
        settings_json=json.dumps(used_settings),
    )
    db.add(trace)

    user_msg = Message(
        id=str(uuid.uuid4()),
        document_id=document.id,
        role="user",
        content=question,
        citations_json=None,
        trace_id=trace.id,
        created_at=_now(),
    )
    assistant_msg = Message(
        id=str(uuid.uuid4()),
        document_id=document.id,
        role="assistant",
        content=answer or (pipeline_error or "The pipeline failed before an answer was produced."),
        citations_json=json.dumps(citations),
        trace_id=trace.id,
        created_at=_now(),
    )
    db.add(user_msg)
    db.add(assistant_msg)
    db.commit()
    db.refresh(trace)

    return {
        "trace_id": trace.id,
        "answer": assistant_msg.content,
        "citations": citations,
        "total_latency_ms": trace.total_latency_ms,
        "total_cost_usd": trace.total_cost_usd,
        "status": status,
        "trace": serialize_trace(trace),
        "user_message_id": user_msg.id,
        "assistant_message_id": assistant_msg.id,
    }


def serialize_trace(trace: Trace) -> dict[str, Any]:
    try:
        nodes = json.loads(trace.nodes_json or "[]")
    except json.JSONDecodeError:
        nodes = []
    try:
        used_settings = json.loads(trace.settings_json or "{}")
    except json.JSONDecodeError:
        used_settings = {}
    return {
        "id": trace.id,
        "type": trace.type,
        "document_id": trace.document_id,
        "query_text": trace.query_text,
        "parent_trace_id": trace.parent_trace_id,
        "created_at": trace.created_at.isoformat() if trace.created_at else None,
        "total_latency_ms": trace.total_latency_ms,
        "total_cost_usd": trace.total_cost_usd,
        "status": trace.status,
        "settings": used_settings,
        "nodes": nodes,
    }
