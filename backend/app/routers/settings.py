from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import DEFAULT_SYSTEM_PROMPT, AppSettings, get_db

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    chunk_size: int | None = Field(default=None, ge=200, le=4000)
    chunk_overlap: int | None = Field(default=None, ge=0, le=2000)
    top_k: int | None = Field(default=None, ge=1, le=50)
    similarity_threshold: float | None = Field(default=None, ge=0, le=1)
    show_threshold: bool | None = None
    system_prompt: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=1)
    candidate_pool: int | None = Field(default=None, ge=10, le=100)
    final_k: int | None = Field(default=None, ge=1, le=15)
    reranker_enabled: bool | None = None
    keyword_weight: float | None = Field(default=None, ge=0, le=1)
    diversity_enabled: bool | None = None


def _to_dict(row: AppSettings) -> dict:
    return {
        "chunk_size": row.chunk_size,
        "chunk_overlap": row.chunk_overlap,
        "top_k": row.top_k,
        "similarity_threshold": row.similarity_threshold,
        "show_threshold": row.show_threshold,
        "system_prompt": row.system_prompt or DEFAULT_SYSTEM_PROMPT,
        "temperature": row.temperature,
        "candidate_pool": row.candidate_pool,
        "final_k": row.final_k,
        "reranker_enabled": row.reranker_enabled,
        "keyword_weight": row.keyword_weight,
        "diversity_enabled": row.diversity_enabled,
    }


@router.get("")
def get_settings(db: Session = Depends(get_db)):
    row = db.get(AppSettings, 1)
    if not row:
        return {
            "chunk_size": 1000,
            "chunk_overlap": 200,
            "top_k": 10,
            "similarity_threshold": 0.0,
            "show_threshold": False,
            "system_prompt": DEFAULT_SYSTEM_PROMPT,
            "temperature": 0.2,
            "candidate_pool": 40,
            "final_k": 5,
            "reranker_enabled": True,
            "keyword_weight": 0.5,
            "diversity_enabled": False,
        }
    return _to_dict(row)


@router.put("")
def update_settings(body: SettingsUpdate, db: Session = Depends(get_db)):
    row = db.get(AppSettings, 1)
    if not row:
        row = AppSettings(id=1, system_prompt=DEFAULT_SYSTEM_PROMPT)
        db.add(row)
    data = body.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return _to_dict(row)
