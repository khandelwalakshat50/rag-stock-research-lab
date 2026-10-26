from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import Document, Trace, get_db
from ..query import serialize_trace

router = APIRouter(prefix="/api/traces", tags=["traces"])


@router.get("")
def list_traces(document_id: str | None = None, db: Session = Depends(get_db)):
    q = db.query(Trace)
    if document_id:
        q = q.filter(Trace.document_id == document_id)
    rows = q.order_by(Trace.created_at.desc()).all()
    return [
        {
            "id": t.id,
            "type": t.type,
            "document_id": t.document_id,
            "query_text": t.query_text,
            "parent_trace_id": t.parent_trace_id,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "total_latency_ms": t.total_latency_ms,
            "total_cost_usd": t.total_cost_usd,
            "status": t.status,
        }
        for t in rows
    ]


@router.get("/{trace_id}")
def get_trace(trace_id: str, db: Session = Depends(get_db)):
    trace = db.get(Trace, trace_id)
    if not trace:
        raise HTTPException(404, "Trace not found")
    payload = serialize_trace(trace)
    doc = db.get(Document, trace.document_id)
    payload["filename"] = doc.filename if doc else None
    return payload
