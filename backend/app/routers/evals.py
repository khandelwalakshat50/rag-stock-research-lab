from __future__ import annotations

import json
import queue
import threading
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import Document, EvalQuestion, EvalRun, SessionLocal, get_db
from ..evaluation import question_to_dict, run_eval, run_to_dict

router = APIRouter(prefix="/api/evals", tags=["evals"])


class QuestionCreate(BaseModel):
    document_id: str
    question: str = Field(..., min_length=1)
    expected_pages: list[int] = Field(..., min_length=1)
    notes: str | None = None


class QuestionUpdate(BaseModel):
    question: str | None = Field(default=None, min_length=1)
    expected_pages: list[int] | None = Field(default=None, min_length=1)
    notes: str | None = None


class RunRequest(BaseModel):
    document_id: str
    label: str | None = None
    pause_s: float = Field(default=0, ge=0, le=300)
    limit: int | None = Field(default=None, ge=1)


@router.get("/questions")
def list_questions(document_id: str, db: Session = Depends(get_db)):
    rows = (
        db.query(EvalQuestion)
        .filter(EvalQuestion.document_id == document_id)
        .order_by(EvalQuestion.created_at.asc())
        .all()
    )
    return [question_to_dict(r) for r in rows]


@router.post("/questions")
def create_question(body: QuestionCreate, db: Session = Depends(get_db)):
    if not db.get(Document, body.document_id):
        raise HTTPException(404, "Document not found")
    row = EvalQuestion(
        id=str(uuid.uuid4()),
        document_id=body.document_id,
        question=body.question.strip(),
        expected_pages_json=json.dumps(sorted(set(body.expected_pages))),
        notes=body.notes,
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    return question_to_dict(row)


@router.patch("/questions/{question_id}")
def update_question(question_id: str, body: QuestionUpdate, db: Session = Depends(get_db)):
    row = db.get(EvalQuestion, question_id)
    if not row:
        raise HTTPException(404, "Question not found")
    if body.question is not None:
        row.question = body.question.strip()
    if body.expected_pages is not None:
        row.expected_pages_json = json.dumps(sorted(set(body.expected_pages)))
    if body.notes is not None:
        row.notes = body.notes
    db.commit()
    return question_to_dict(row)


@router.delete("/questions/{question_id}")
def delete_question(question_id: str, db: Session = Depends(get_db)):
    row = db.get(EvalQuestion, question_id)
    if not row:
        raise HTTPException(404, "Question not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/runs")
def list_runs(document_id: str, db: Session = Depends(get_db)):
    rows = (
        db.query(EvalRun)
        .filter(EvalRun.document_id == document_id)
        .order_by(EvalRun.created_at.desc())
        .all()
    )
    return [run_to_dict(r) for r in rows]


@router.get("/runs/{run_id}")
def get_run(run_id: str, db: Session = Depends(get_db)):
    row = db.get(EvalRun, run_id)
    if not row:
        raise HTTPException(404, "Run not found")
    return run_to_dict(row, include_results=True)


@router.delete("/runs/{run_id}")
def delete_run(run_id: str, db: Session = Depends(get_db)):
    row = db.get(EvalRun, run_id)
    if not row:
        raise HTTPException(404, "Run not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.post("/run")
def start_run(body: RunRequest, db: Session = Depends(get_db)):
    doc = db.get(Document, body.document_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    if doc.status != "success":
        raise HTTPException(400, "Document is not ready. Finish ingestion first.")
    count = db.query(EvalQuestion).filter(EvalQuestion.document_id == doc.id).count()
    if count == 0:
        raise HTTPException(400, "Save at least one test question first.")

    events: queue.Queue = queue.Queue()

    def worker() -> None:
        session = SessionLocal()
        try:
            document = session.get(Document, body.document_id)
            run_eval(session, document, body.label, events.put, body.pause_s, body.limit)
        except Exception as exc:
            events.put({"stage": "error", "message": str(exc)})
        finally:
            session.close()
            events.put(None)

    def stream():
        threading.Thread(target=worker, daemon=True).start()
        while True:
            event = events.get()
            if event is None:
                break
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
