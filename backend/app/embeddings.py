from __future__ import annotations

import time
from typing import Callable

import httpx
import tiktoken
from openai import OpenAI, RateLimitError

from .config import settings

_client: OpenAI | None = None
_encoding = None


def get_openai() -> OpenAI:
    global _client
    if _client is None:
        if not settings.openai_api_key or settings.openai_api_key.startswith("your_"):
            raise RuntimeError("OPENAI_API_KEY is missing. Add it to the .env file.")
        # httpx drops idle connections after 5 s by default, so a question asked after a
        # pause paid a fresh TLS handshake. Keep connections for 2 minutes instead.
        _client = OpenAI(
            api_key=settings.openai_api_key,
            http_client=httpx.Client(
                limits=httpx.Limits(keepalive_expiry=120),
                timeout=httpx.Timeout(120.0, connect=10.0),
            ),
        )
    return _client


def encoding():
    global _encoding
    if _encoding is None:
        try:
            _encoding = tiktoken.encoding_for_model(settings.openai_embedding_model)
        except Exception:
            _encoding = tiktoken.get_encoding("cl100k_base")
    return _encoding


def count_tokens(text: str) -> int:
    return len(encoding().encode(text))


def embedding_cost(tokens: int) -> float:
    return (tokens / 1_000_000) * settings.embedding_usd_per_1m


# List prices (USD per 1M input, output tokens) for the small models used for reranking.
_MODEL_PRICES = {
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5-nano": (0.05, 0.40),
}


def llm_cost(input_tokens: int, output_tokens: int, model: str | None = None) -> float:
    in_price, out_price = _MODEL_PRICES.get(
        model or "", (settings.llm_input_usd_per_1m, settings.llm_output_usd_per_1m)
    )
    return (input_tokens / 1_000_000) * in_price + (output_tokens / 1_000_000) * out_price


def chat_complete(system_prompt: str, user_prompt: str) -> tuple[str, int, int]:
    """Answer with OpenAI GPT-5.6. Returns (text, input_tokens, output_tokens)."""
    client = get_openai()
    model = settings.openai_llm_model
    try:
        response = client.responses.create(
            model=model,
            instructions=system_prompt,
            input=user_prompt,
            reasoning={"effort": "low"},
        )
        answer = (getattr(response, "output_text", None) or "").strip()
        if not answer:
            parts: list[str] = []
            for item in getattr(response, "output", None) or []:
                for block in getattr(item, "content", None) or []:
                    text = getattr(block, "text", None)
                    if text:
                        parts.append(text)
            answer = "".join(parts).strip()
        usage = getattr(response, "usage", None)
        in_tok = int(getattr(usage, "input_tokens", 0) or 0)
        out_tok = int(getattr(usage, "output_tokens", 0) or 0)
        if answer:
            return answer, in_tok, out_tok
    except Exception:
        pass

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_completion_tokens=2048,
    )
    choice = response.choices[0] if response.choices else None
    answer = (choice.message.content or "").strip() if choice else ""
    usage = getattr(response, "usage", None)
    in_tok = int(getattr(usage, "prompt_tokens", 0) or 0)
    out_tok = int(getattr(usage, "completion_tokens", 0) or 0)
    return answer, in_tok, out_tok


def embed_texts(
    texts: list[str],
    progress_cb: Callable[[int, int], None] | None = None,
    batch_size: int = 64,
) -> tuple[list[list[float]], int, float]:
    client = get_openai()
    vectors: list[list[float]] = []
    total_tokens = 0
    started = time.perf_counter()
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        last_exc: Exception | None = None
        for attempt in range(5):
            try:
                response = client.embeddings.create(
                    model=settings.openai_embedding_model,
                    input=batch,
                    dimensions=settings.embedding_dimensions,
                )
                batch_vecs = [item.embedding for item in response.data]
                vectors.extend(batch_vecs)
                usage = getattr(response, "usage", None)
                if usage and getattr(usage, "total_tokens", None):
                    total_tokens += int(usage.total_tokens)
                else:
                    total_tokens += sum(count_tokens(t) for t in batch)
                last_exc = None
                break
            except RateLimitError as exc:
                last_exc = exc
                time.sleep(1.5 * (attempt + 1))
            except Exception as exc:
                last_exc = exc
                time.sleep(0.8 * (attempt + 1))
        if last_exc:
            raise last_exc
        if progress_cb:
            progress_cb(min(i + batch_size, len(texts)), len(texts))
    elapsed_ms = (time.perf_counter() - started) * 1000
    return vectors, total_tokens, elapsed_ms
