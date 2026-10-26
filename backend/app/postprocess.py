"""Post-rerank result shaping: merge same-page chunks, optionally diversify.

merge_by_page: several chunks from one page used to fill several of the few slots sent
to the LLM (e.g. p.60 three times in the top 10). They are merged into one result per
page, in reading order, with the overlap between neighbouring chunks removed.

diversify: statements like these repeat content on different pages (every standalone
note has a near-identical consolidated twin). Maximal marginal relevance picks results
that are relevant but add new content, instead of five near-copies.
"""
from __future__ import annotations

from typing import Any

from .keyword import tokenize

MAX_MERGED_CHARS = 4000
MIN_OVERLAP = 25
DIVERSITY_LAMBDA = 0.7  # 1.0 = pure relevance, 0.0 = pure novelty
# Measured on the Aeroflex report (token Jaccard between pages): standalone/consolidated
# twins overlap 0.24-0.82, same-topic pages with different content <= 0.21, unrelated
# ~0.05-0.08. Only overlap above this floor counts as redundancy, so diversity pushes
# down near-copies without penalising related pages that add new facts.
REDUNDANCY_FLOOR = 0.22


def _strip_overlap(prev: str, nxt: str) -> str:
    """Chunking repeats text from the end of the previous chunk (up to ~200 chars, and not
    always its very last characters) at the start of the next. Drop that repeated prefix."""
    tail = prev[-600:]
    for k in range(min(len(nxt), len(tail)), MIN_OVERLAP - 1, -1):
        if nxt[:k] in tail:
            return nxt[k:].lstrip()
    return nxt


def _chunk_index(c: dict[str, Any]) -> int:
    try:
        return int(c["metadata"].get("chunk_index"))
    except (TypeError, ValueError):
        return 0


def merge_by_page(ordered: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse candidates (already in final relevance order) into one result per page.
    The result keeps the position of its best chunk and the best scores of its members."""
    groups: dict[Any, list[dict[str, Any]]] = {}
    order: list[Any] = []
    for c in ordered:
        meta = c.get("metadata", {})
        key = (meta.get("document_id"), meta.get("page_number"))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(c)

    results: list[dict[str, Any]] = []
    for key in order:
        members = groups[key]
        best = members[0]
        # Keep the most relevant members that fit, then restore reading order.
        kept, total = [], 0
        for m in members:
            n = len(m["metadata"].get("text") or "")
            if kept and total + n > MAX_MERGED_CHARS:
                continue
            kept.append(m)
            total += n
        kept.sort(key=_chunk_index)
        parts: list[str] = []
        prev_idx, prev_text = None, ""
        for m in kept:
            text = str(m["metadata"].get("text") or "").strip()
            idx = _chunk_index(m)
            if prev_idx is not None and idx == prev_idx + 1:
                text = _strip_overlap(prev_text, text)
            if text:
                parts.append(text)
            prev_idx, prev_text = idx, str(m["metadata"].get("text") or "").strip()

        sims = [m["score"] for m in members if m.get("score") is not None]
        reranks = [m["rerank_score"] for m in members if m.get("rerank_score") is not None]
        found = {m.get("found_by") for m in members if m.get("found_by")}
        terms: list[str] = []
        for m in members:
            for t in m.get("matched_terms") or []:
                if t not in terms:
                    terms.append(t)
        sem_ranks = [m["semantic_rank"] for m in members if m.get("semantic_rank")]
        kw_ranks = [m["keyword_rank"] for m in members if m.get("keyword_rank")]
        bm25s = [m["bm25"] for m in members if m.get("bm25") is not None]

        results.append(
            {
                **best,
                "score": max(sims) if sims else None,
                "rerank_score": max(reranks) if reranks else best.get("rerank_score"),
                "found_by": "both" if ("both" in found or {"semantic", "keyword"} <= found) else (found.pop() if found else None),
                "semantic_rank": min(sem_ranks) if sem_ranks else None,
                "keyword_rank": min(kw_ranks) if kw_ranks else None,
                "bm25": max(bm25s) if bm25s else None,
                "matched_terms": terms,
                "merged_count": len(members),
                "merged_chunk_indices": [_chunk_index(m) for m in kept],
                "dropped_for_length": len(members) - len(kept),
                "metadata": {
                    **best["metadata"],
                    "text": "\n\n".join(parts),
                    "is_table": any(m["metadata"].get("is_table") for m in members),
                },
            }
        )
    return results


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def diversify(results: list[dict[str, Any]], lam: float = DIVERSITY_LAMBDA) -> list[dict[str, Any]]:
    """Reorder by maximal marginal relevance. Relevance is the rerank score when present,
    otherwise the fused hybrid score. Records each result's redundancy (max content
    overlap with anything picked before it) and its rank before diversity."""
    n = len(results)
    if n <= 1:
        return results
    if all(r.get("rerank_score") is not None for r in results):
        rel = [r["rerank_score"] for r in results]
    else:
        # Reranker off: use the fused hybrid score, scaled to 0-1.
        raw = [r.get("hybrid_score") or 0.0 for r in results]
        hi, lo = max(raw), min(raw)
        rel = [(x - lo) / (hi - lo) if hi > lo else 1.0 for x in raw]
    toks = [set(tokenize(r["metadata"].get("text") or "")) for r in results]

    remaining = list(range(n))
    picked: list[int] = []
    while remaining:
        best_i, best_val = remaining[0], None
        for i in remaining:
            red = max((_jaccard(toks[i], toks[j]) for j in picked), default=0.0)
            excess = max(0.0, red - REDUNDANCY_FLOOR) / (1 - REDUNDANCY_FLOOR)
            val = lam * rel[i] - (1 - lam) * excess
            if best_val is None or val > best_val:
                best_i, best_val = i, val
        picked.append(best_i)
        remaining.remove(best_i)

    out = []
    for pos, i in enumerate(picked):
        r = dict(results[i])
        r["redundancy"] = round(max((_jaccard(toks[i], toks[j]) for j in picked[:pos]), default=0.0), 3)
        r["pre_diversity_rank"] = i + 1
        out.append(r)
    return out


def shape_results(ordered: list[dict[str, Any]], diversity: bool) -> list[dict[str, Any]]:
    """Merge by page, optionally diversify, and assign final result ranks."""
    results = merge_by_page(ordered)
    if diversity:
        results = diversify(results)
    for i, r in enumerate(results):
        r["result_rank"] = i + 1
    return results
