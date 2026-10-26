from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import Document, get_db
from ..query import run_query

router = APIRouter(prefix="/api/query", tags=["query"])


class QueryRequest(BaseModel):
    document_id: str
    question: str = Field(..., min_length=1)
    candidate_pool: int | None = Field(default=None, ge=10, le=100)
    final_k: int | None = Field(default=None, ge=1, le=15)
    reranker_enabled: bool | None = None
    keyword_weight: float | None = Field(default=None, ge=0, le=1)
    diversity_enabled: bool | None = None
    similarity_threshold: float | None = Field(default=None, ge=0, le=1)
    system_prompt: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=1)
    parent_trace_id: str | None = None


@router.post("")
def query_document(body: QueryRequest, db: Session = Depends(get_db)):
    doc = db.get(Document, body.document_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    if doc.status != "success":
        raise HTTPException(400, "Document is not ready. Finish ingestion first.")
    try:
        return run_query(
            db,
            doc,
            body.question.strip(),
            candidate_pool=body.candidate_pool,
            final_k=body.final_k,
            reranker_enabled=body.reranker_enabled,
            keyword_weight=body.keyword_weight,
            diversity_enabled=body.diversity_enabled,
            similarity_threshold=body.similarity_threshold,
            system_prompt=body.system_prompt,
            temperature=body.temperature,
            parent_trace_id=body.parent_trace_id,
        )
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc
