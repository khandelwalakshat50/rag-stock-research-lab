from __future__ import annotations

import socket
import threading
import time
from typing import Any

from pinecone import Pinecone, ServerlessSpec

from .config import settings

_pc: Pinecone | None = None
_index = None
_index_info: dict[str, Any] | None = None
_lock = threading.Lock()
_diagnostics: dict[str, Any] = {"warmed_up": False}
_keepalive_started = False

# Idle keep-alive connections get dropped after ~60-90 s, after which a query pays a
# fresh TCP+TLS handshake (1.3-1.5 s from India to us-east-1 instead of ~300 ms).
# A free stats call every KEEPALIVE_S seconds keeps the connection open. (Measured:
# namespaces did not go cold within 3 min, so no read-unit-costing query pings.)
KEEPALIVE_S = 20


def get_pinecone() -> Pinecone:
    global _pc
    if _pc is None:
        if not settings.pinecone_api_key or settings.pinecone_api_key.startswith("your_"):
            raise RuntimeError("PINECONE_API_KEY is missing. Add it to the .env file.")
        _pc = Pinecone(api_key=settings.pinecone_api_key)
    return _pc


def ensure_index() -> dict[str, Any]:
    """Create the Pinecone index on first run if it does not exist."""
    pc = get_pinecone()
    name = settings.pinecone_index_name
    created = False
    if not pc.has_index(name):
        pc.create_index(
            name=name,
            dimension=settings.embedding_dimensions,
            metric="cosine",
            spec=ServerlessSpec(
                cloud=settings.pinecone_cloud,
                region=settings.pinecone_region,
            ),
        )
        created = True
        for _ in range(60):
            desc = pc.describe_index(name)
            ready = getattr(getattr(desc, "status", None), "ready", False)
            if ready:
                break
            time.sleep(2)
    desc = pc.describe_index(name)
    spec = getattr(desc, "spec", None)
    serverless = getattr(spec, "serverless", None) if spec is not None else None
    if serverless is None and isinstance(spec, dict):
        serverless = spec.get("serverless")
    get = (lambda k: serverless.get(k)) if isinstance(serverless, dict) else (lambda k: getattr(serverless, k, None))
    return {
        "name": name,
        "created_now": created,
        "dimension": settings.embedding_dimensions,
        "metric": "cosine",
        "host": getattr(desc, "host", None),
        "cloud": get("cloud") if serverless is not None else None,
        "region": get("region") if serverless is not None else None,
    }


def get_index():
    """Return one shared Index client. The control-plane lookup (has_index/describe_index)
    runs once per process instead of on every query, and the client's HTTP connection
    pool is reused so queries skip TCP/TLS setup."""
    global _index, _index_info
    if _index is not None:
        return _index
    with _lock:
        if _index is None:
            info = ensure_index()
            pc = get_pinecone()
            _index = pc.Index(host=info["host"]) if info.get("host") else pc.Index(info["name"])
            _index_info = info
    return _index


def measure_rtt(host: str, samples: int = 3) -> float | None:
    """Best-of-N TCP connect time to the index host: the pure network round trip."""
    best = None
    for _ in range(samples):
        try:
            start = time.perf_counter()
            sock = socket.create_connection((host, 443), timeout=5)
            elapsed = (time.perf_counter() - start) * 1000
            sock.close()
            best = elapsed if best is None else min(best, elapsed)
        except OSError:
            continue
    return round(best, 1) if best is not None else None


def _keepalive_loop() -> None:
    while True:
        time.sleep(KEEPALIVE_S)
        try:
            if _index is not None:
                _index.describe_index_stats()
        except Exception:
            pass


def _query_probe(namespace: str) -> float:
    probe = [0.0] * settings.embedding_dimensions
    probe[0] = 1.0
    start = time.perf_counter()
    get_index().query(vector=probe, top_k=1, namespace=namespace)
    return round((time.perf_counter() - start) * 1000, 1)


def warm_namespace(namespace: str) -> float:
    """Serverless indexes load a namespace into cache on first query (~500 ms extra),
    so touch it before a user asks. Returns the probe latency in ms."""
    return _query_probe(namespace)


def warmup(namespaces: list[str] | None = None) -> dict[str, Any]:
    """Open the Pinecone connection and prime the query path so the first user query
    does not pay for client setup, host lookup, the TLS handshake, or a cold namespace."""
    global _keepalive_started
    out: dict[str, Any] = {}
    start = time.perf_counter()
    index = get_index()
    out["connect_ms"] = round((time.perf_counter() - start) * 1000, 1)

    # One throwaway query opens the data-plane connection (empty namespace = no read cost).
    probe = [0.0] * settings.embedding_dimensions
    probe[0] = 1.0
    q_start = time.perf_counter()
    index.query(vector=probe, top_k=1, namespace="__warmup__")
    out["first_query_ms"] = round((time.perf_counter() - q_start) * 1000, 1)
    q_start = time.perf_counter()
    index.query(vector=probe, top_k=1, namespace="__warmup__")
    out["warm_query_ms"] = round((time.perf_counter() - q_start) * 1000, 1)

    out["namespaces_warmed"] = {ns: warm_namespace(ns) for ns in (namespaces or [])}

    info = _index_info or {}
    host = info.get("host")
    out["network_rtt_ms"] = measure_rtt(host) if host else None
    out.update({"index_host": host, "cloud": info.get("cloud"), "region": info.get("region")})
    out["warmed_up"] = True
    out["at"] = time.time()

    if not _keepalive_started:
        threading.Thread(target=_keepalive_loop, daemon=True, name="pinecone-keepalive").start()
        _keepalive_started = True
    out["keepalive_s"] = KEEPALIVE_S
    _diagnostics.update(out)
    return out


def diagnostics() -> dict[str, Any]:
    d = dict(_diagnostics)
    rtt = d.get("network_rtt_ms")
    if rtt is not None:
        # Rule of thumb: one query ≈ 1 network round trip + ~20-60 ms server time.
        d["region_far"] = rtt > 120
        d["floor_query_ms"] = round(rtt + 30)
    return d
