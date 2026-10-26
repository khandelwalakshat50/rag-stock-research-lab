"""LLM reranker: a small, fast OpenAI model reads the question with every candidate chunk
and scores how well each one answers it.

Why an LLM instead of a cross-encoder: the MS-MARCO cross-encoders available locally
(FlashRank) and Pinecone's free hosted rerankers were tested on this app's eval set and
ranked financial-statement notes worse than plain vector search (and were 1-3 s slower).
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from .embeddings import get_openai

RERANK_MODEL = "gpt-4.1-mini"
MAX_CHARS_PER_CHUNK = 900
# A stuck call must not hang the chat; on timeout the caller falls back to vector order.
RERANK_TIMEOUT_S = 10

SYSTEM = """You rank excerpts from a company report by how useful they are for answering a question.

Score each excerpt from 0 to 10:
10 = directly contains the answer (the figure, name, or statement asked for)
6-9 = clearly about the asked topic and helpful
1-5 = loosely related
0 = unrelated, boilerplate, or only mentions the company name

Judge by substance, not by shared words: every excerpt mentions the company, so the company
name alone is never evidence of relevance. Prefer excerpts with the specific numbers asked for.

Return JSON only: {"scores": [[excerpt_number, score], ...]} listing every excerpt that scores
1 or more, best first. Omit excerpts that score 0."""


def _excerpt(i: int, c: dict[str, Any]) -> str:
    meta = c.get("metadata", {})
    text = re.sub(r"[ \t]+", " ", str(meta.get("text") or "")).strip()
    if len(text) > MAX_CHARS_PER_CHUNK:
        text = text[:MAX_CHARS_PER_CHUNK] + " …"
    head = f"[{i}] p.{meta.get('page_number')}"
    if meta.get("heading"):
        head += f" | {meta.get('heading')}"
    if meta.get("is_table"):
        head += " | TABLE"
    return f"{head}\n{text}"


def rerank(question: str, candidates: list[dict[str, Any]], model: str = RERANK_MODEL) -> dict[str, Any]:
    """Returns {"scores": [float 0-1 per candidate], "latency_ms", "model", "tokens_in", "tokens_out"}.
    Candidates the model omits score 0."""
    start = time.perf_counter()
    scores = [0.0] * len(candidates)
    if not candidates:
        return {"scores": scores, "latency_ms": 0.0, "model": model, "tokens_in": 0, "tokens_out": 0}

    user = (
        f"Question: {question}\n\nExcerpts:\n\n"
        + "\n\n".join(_excerpt(i, c) for i, c in enumerate(candidates))
    )
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        "response_format": {"type": "json_object"},
    }
    if model.startswith("gpt-5"):
        kwargs["reasoning_effort"] = "minimal" if model.startswith("gpt-5-") else "none"
    else:
        kwargs["temperature"] = 0
    client = get_openai().with_options(timeout=RERANK_TIMEOUT_S, max_retries=1)
    response = client.chat.completions.create(**kwargs)
    content = response.choices[0].message.content or "{}"
    try:
        pairs = json.loads(content).get("scores", [])
    except json.JSONDecodeError:
        pairs = []
    for pair in pairs:
        try:
            idx, score = int(pair[0]), float(pair[1])
        except (TypeError, ValueError, IndexError):
            continue
        if 0 <= idx < len(scores):
            scores[idx] = max(0.0, min(score, 10.0)) / 10.0

    usage = getattr(response, "usage", None)
    return {
        "scores": scores,
        "latency_ms": (time.perf_counter() - start) * 1000,
        "model": model,
        "tokens_in": int(getattr(usage, "prompt_tokens", 0) or 0),
        "tokens_out": int(getattr(usage, "completion_tokens", 0) or 0),
    }


def apply_rerank(candidates: list[dict[str, Any]], scores: list[float]) -> list[dict[str, Any]]:
    """Sort by rerank score (ties keep vector order) and record each chunk's movement."""
    for i, c in enumerate(candidates):
        c["vector_rank"] = i + 1
        c["rerank_score"] = scores[i]
    ordered = sorted(candidates, key=lambda c: (-c["rerank_score"], c["vector_rank"]))
    for i, c in enumerate(ordered):
        c["final_rank"] = i + 1
    return ordered
