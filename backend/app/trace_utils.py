from __future__ import annotations

from typing import Any


def node_status(latency_ms: float, error: str | None = None, slow_ms: float = 3000) -> str:
    if error:
        return "error"
    if latency_ms >= slow_ms:
        return "slow"
    return "success"


def make_node(
    node_id: str,
    node_type: str,
    label: str,
    latency_ms: float,
    summary: str,
    key_metric: str | None,
    data: dict[str, Any],
    error: str | None = None,
    slow_ms: float = 3000,
) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": node_type,
        "label": label,
        "status": node_status(latency_ms, error, slow_ms),
        "latency_ms": round(latency_ms, 1),
        "summary": summary,
        "key_metric": key_metric,
        "error": error,
        "data": data,
    }
