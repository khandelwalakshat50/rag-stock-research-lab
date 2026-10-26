from __future__ import annotations

import json
import queue
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import fitz
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..database import Chunk, Document, Message, SessionLocal, Trace, get_db
from ..ingest import ingest_document
from ..pinecone_client import get_index, warm_namespace

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _ingest_stream(document_id: str, start_message: str):
    events: queue.Queue = queue.Queue()

    def progress(event: dict) -> None:
        events.put(event)

    def worker() -> None:
        db = SessionLocal()
        try:
            document = db.get(Document, document_id)
            if document is None:
                events.put(
                    {
                        "stage": "error",
                        "progress": 1.0,
                        "message": "Document disappeared before ingest",
                        "document_id": document_id,
                        "status": "error",
                    }
                )
                return
            ingest_document(db, document, progress)
        except Exception as exc:
            events.put(
                {
                    "stage": "error",
                    "progress": 1.0,
                    "message": str(exc),
                    "document_id": document_id,
                    "status": "error",
                }
            )
            failed = db.get(Document, document_id)
            if failed:
                failed.status = "error"
                db.commit()
        finally:
            db.close()
            events.put(None)

    yield _sse(
        {
            "stage": "parsing",
            "progress": 0.01,
            "message": start_message,
            "document_id": document_id,
        }
    )
    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    while True:
        event = events.get()
        if event is None:
            break
        yield _sse(event)


@router.get("")
def list_documents(db: Session = Depends(get_db)):
    docs = db.query(Document).order_by(Document.created_at.desc()).all()
    return [
        {
            "id": d.id,
            "filename": d.filename,
            "size_bytes": d.size_bytes,
            "page_count": d.page_count,
            "status": d.status,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "ingest_trace_id": d.ingest_trace_id,
        }
        for d in docs
    ]


@router.get("/{document_id}")
def get_document(document_id: str, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    chunk_count = db.query(Chunk).filter(Chunk.document_id == document_id).count()
    return {
        "id": doc.id,
        "filename": doc.filename,
        "size_bytes": doc.size_bytes,
        "page_count": doc.page_count,
        "status": doc.status,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "ingest_trace_id": doc.ingest_trace_id,
        "chunk_count": chunk_count,
        "file_url": f"/api/documents/{doc.id}/file",
    }


@router.get("/{document_id}/file")
def get_document_file(document_id: str, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc or not Path(doc.file_path).exists():
        raise HTTPException(404, "PDF not found")
    return FileResponse(doc.file_path, media_type="application/pdf", filename=doc.filename)


@router.get("/{document_id}/chunks")
def list_chunks(document_id: str, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    rows = (
        db.query(Chunk)
        .filter(Chunk.document_id == document_id)
        .order_by(Chunk.chunk_index.asc())
        .all()
    )
    return [
        {
            "chunk_index": r.chunk_index,
            "page_number": r.page_number,
            "heading": r.heading,
            "is_table": r.is_table,
            "char_length": r.char_length,
            "text": r.text,
        }
        for r in rows
    ]


@router.get("/{document_id}/messages")
def list_messages(document_id: str, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    rows = (
        db.query(Message)
        .filter(Message.document_id == document_id)
        .order_by(Message.created_at.asc())
        .all()
    )
    out = []
    for r in rows:
        try:
            citations = json.loads(r.citations_json) if r.citations_json else []
        except json.JSONDecodeError:
            citations = []
        out.append(
            {
                "id": r.id,
                "role": r.role,
                "content": r.content,
                "citations": citations,
                "trace_id": r.trace_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )
    return out


@router.post("/upload")
async def upload_and_ingest(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Please upload a PDF file")

    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")

    doc_id = str(uuid.uuid4())
    dest = settings.uploads_dir / f"{doc_id}.pdf"
    dest.write_bytes(data)

    try:
        pdf = fitz.open(stream=data, filetype="pdf")
        page_count = pdf.page_count
        pdf.close()
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, f"Could not open PDF: {exc}") from exc

    document = Document(
        id=doc_id,
        filename=file.filename,
        size_bytes=len(data),
        page_count=page_count,
        namespace=doc_id,
        file_path=str(dest),
        created_at=_now(),
        status="running",
    )
    db.add(document)
    db.commit()

    return StreamingResponse(
        _ingest_stream(doc_id, f"Saved {file.filename} ({page_count} pages)"),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{document_id}/warm")
def warm_document(document_id: str, db: Session = Depends(get_db)):
    """Prime the document's Pinecone namespace so the next question skips the cold start."""
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    try:
        return {"ok": True, "probe_ms": warm_namespace(doc.namespace)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@router.post("/{document_id}/reingest")
def reingest(document_id: str, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(404, "Document not found")

    return StreamingResponse(
        _ingest_stream(document_id, "Re-ingesting with current chunk settings"),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete("/{document_id}")
def delete_document(document_id: str, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    try:
        index = get_index()
        index.delete(delete_all=True, namespace=doc.namespace)
    except Exception:
        pass
    db.query(Chunk).filter(Chunk.document_id == document_id).delete()
    db.query(Message).filter(Message.document_id == document_id).delete()
    db.query(Trace).filter(Trace.document_id == document_id).delete()
    Path(doc.file_path).unlink(missing_ok=True)
    db.delete(doc)
    db.commit()
    return {"ok": True}
