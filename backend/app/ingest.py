from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session

from .chunking import chunk_histogram, chunk_pages
from .config import settings
from .database import AppSettings, Chunk, Document, Trace
from .embeddings import embed_texts, embedding_cost
from .pdf_extract import extract_pdf
from .pinecone_client import get_index, warm_namespace
from .trace_utils import make_node

ProgressCb = Callable[[dict[str, Any]], None]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def ingest_document(db: Session, document: Document, progress: ProgressCb) -> Trace:
    app_settings = db.get(AppSettings, 1)
    chunk_size = app_settings.chunk_size if app_settings else 1000
    overlap = app_settings.chunk_overlap if app_settings else 200

    nodes: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    total_cost = 0.0
    ingest_error: str | None = None

    progress(
        {
            "stage": "parsing",
            "progress": 0.02,
            "message": f"Opening {document.filename}",
        }
    )

    # --- 1. PDF Upload ---
    upload_node = make_node(
        "pdf_upload",
        "pdf_upload",
        "PDF Upload",
        0,
        f"{document.page_count} pages · {_fmt_bytes(document.size_bytes)}",
        f"{document.page_count} pages",
        {
            "filename": document.filename,
            "size_bytes": document.size_bytes,
            "size_human": _fmt_bytes(document.size_bytes),
            "page_count": document.page_count,
            "document_id": document.id,
        },
        slow_ms=10_000,
    )
    nodes.append(upload_node)

    # --- 2. Text Extraction ---
    extract_start = time.perf_counter()
    pages = []
    extract_error = None
    try:

        def extract_progress(stage: str, frac: float, message: str) -> None:
            progress({"stage": stage, "progress": 0.05 + frac * 0.25, "message": message})

        pages = extract_pdf(document.file_path, extract_progress)
    except Exception as exc:
        extract_error = str(exc)
        ingest_error = extract_error

    extract_ms = (time.perf_counter() - extract_start) * 1000
    page_summaries = [
        {
            "page": p.page_number,
            "chars": p.char_count,
            "has_table": p.has_table,
            "table_count": p.table_count,
            "empty": p.empty,
            "failed": p.failed,
            "error": p.error,
            "headings": p.headings,
        }
        for p in pages
    ]
    nodes.append(
        make_node(
            "text_extraction",
            "text_extraction",
            "Text Extraction",
            extract_ms,
            f"{sum(p.char_count for p in pages):,} chars · {sum(1 for p in pages if p.has_table)} tables",
            f"{sum(p.char_count for p in pages):,} chars",
            {
                "pages": page_summaries,
                "total_characters": sum(p.char_count for p in pages),
                "pages_with_tables": sum(1 for p in pages if p.has_table),
                "table_count": sum(p.table_count for p in pages),
                "empty_pages": [p.page_number for p in pages if p.empty],
                "failed_pages": [p.page_number for p in pages if p.failed],
            },
            error=extract_error,
            slow_ms=8_000,
        )
    )

    # --- 3. Chunking ---
    chunk_start = time.perf_counter()
    text_chunks = []
    chunk_error = None
    if not extract_error:
        try:
            progress({"stage": "chunking", "progress": 0.35, "message": "Splitting into chunks"})
            text_chunks = chunk_pages(pages, chunk_size=chunk_size, overlap=overlap)
            db.query(Chunk).filter(Chunk.document_id == document.id).delete()
            for ch in text_chunks:
                db.add(
                    Chunk(
                        id=f"{document.id}:{ch.chunk_index}",
                        document_id=document.id,
                        chunk_index=ch.chunk_index,
                        page_number=ch.page_number,
                        heading=ch.heading,
                        is_table=ch.is_table,
                        text=ch.text,
                        char_length=ch.char_length,
                    )
                )
            db.commit()
        except Exception as exc:
            chunk_error = str(exc)
            ingest_error = chunk_error
            db.rollback()
    chunk_ms = (time.perf_counter() - chunk_start) * 1000
    lengths = [c.char_length for c in text_chunks]
    nodes.append(
        make_node(
            "chunking",
            "chunking",
            "Chunking",
            chunk_ms,
            f"{len(text_chunks)} chunks · size {chunk_size}/{overlap}",
            f"{len(text_chunks)} chunks",
            {
                "chunk_size": chunk_size,
                "overlap": overlap,
                "total_chunks": len(text_chunks),
                "min_length": min(lengths) if lengths else 0,
                "avg_length": round(sum(lengths) / len(lengths), 1) if lengths else 0,
                "max_length": max(lengths) if lengths else 0,
                "table_chunks": sum(1 for c in text_chunks if c.is_table),
                "histogram": chunk_histogram(text_chunks),
                "chunks": [
                    {
                        "chunk_index": c.chunk_index,
                        "page_number": c.page_number,
                        "heading": c.heading,
                        "is_table": c.is_table,
                        "char_length": c.char_length,
                        "text": c.text,
                    }
                    for c in text_chunks
                ],
            },
            error=chunk_error,
            slow_ms=5_000,
        )
    )

    # --- 4. Embedding ---
    embed_start = time.perf_counter()
    vectors: list[list[float]] = []
    embed_tokens = 0
    embed_error = None
    sample_vector: list[float] = []
    if text_chunks and not ingest_error:
        try:
            def embed_progress(done: int, total: int) -> None:
                frac = done / max(total, 1)
                progress(
                    {
                        "stage": "embedding",
                        "progress": 0.4 + frac * 0.4,
                        "message": f"Embedding {done}/{total} chunks",
                    }
                )

            vectors, embed_tokens, _embed_ms = embed_texts(
                [c.text for c in text_chunks], embed_progress
            )
            if vectors:
                sample_vector = [round(x, 6) for x in vectors[0][:10]]
        except Exception as exc:
            embed_error = str(exc)
            ingest_error = embed_error
    embed_ms = (time.perf_counter() - embed_start) * 1000
    embed_cost = embedding_cost(embed_tokens)
    total_cost += embed_cost
    nodes.append(
        make_node(
            "embedding",
            "embedding",
            "Embedding",
            embed_ms,
            f"{settings.openai_embedding_model} · {embed_tokens:,} tokens",
            f"{embed_tokens:,} tokens",
            {
                "model": settings.openai_embedding_model,
                "dimensions": settings.embedding_dimensions,
                "total_tokens": embed_tokens,
                "cost_usd": round(embed_cost, 6),
                "time_ms": round(embed_ms, 1),
                "vectors_created": len(vectors),
                "sample_vector_preview": sample_vector,
                "sample_from_chunk_index": 0 if vectors else None,
            },
            error=embed_error,
            slow_ms=10_000,
        )
    )

    # --- 5. Pinecone Upsert ---
    upsert_start = time.perf_counter()
    upserted = 0
    upsert_error = None
    metadata_keys = [
        "document_id",
        "chunk_index",
        "page_number",
        "heading",
        "is_table",
        "filename",
        "text",
    ]
    if vectors and not ingest_error:
        try:
            progress({"stage": "uploading", "progress": 0.85, "message": "Uploading vectors to Pinecone"})
            index = get_index()
            # Replace previous vectors for this document
            try:
                index.delete(delete_all=True, namespace=document.namespace)
            except Exception:
                pass
            batch_size = 100
            for i in range(0, len(vectors), batch_size):
                batch_chunks = text_chunks[i : i + batch_size]
                batch_vecs = vectors[i : i + batch_size]
                payload = []
                for ch, vec in zip(batch_chunks, batch_vecs):
                    payload.append(
                        {
                            "id": f"{document.id}:{ch.chunk_index}",
                            "values": vec,
                            "metadata": {
                                "document_id": document.id,
                                "chunk_index": ch.chunk_index,
                                "page_number": ch.page_number,
                                "heading": ch.heading or "",
                                "is_table": ch.is_table,
                                "filename": document.filename,
                                "text": ch.text[:35000],
                            },
                        }
                    )
                index.upsert(vectors=payload, namespace=document.namespace)
                upserted += len(payload)
                frac = upserted / max(len(vectors), 1)
                progress(
                    {
                        "stage": "uploading",
                        "progress": 0.85 + frac * 0.12,
                        "message": f"Uploaded {upserted}/{len(vectors)} vectors",
                    }
                )
        except Exception as exc:
            upsert_error = str(exc)
            ingest_error = upsert_error
    elif not vectors:
        upsert_error = "Skipped because no vectors were produced"
    upsert_ms = (time.perf_counter() - upsert_start) * 1000
    nodes.append(
        make_node(
            "pinecone_upsert",
            "pinecone_upsert",
            "Pinecone Upsert",
            upsert_ms,
            f"{upserted} vectors → {settings.pinecone_index_name}",
            f"{upserted} vectors",
            {
                "index_name": settings.pinecone_index_name,
                "namespace": document.namespace,
                "vectors_uploaded": upserted,
                "metadata_keys": metadata_keys,
                "time_ms": round(upsert_ms, 1),
            },
            error=upsert_error,
            slow_ms=8_000,
        )
    )

    total_ms = (time.perf_counter() - t0) * 1000
    status = "error" if ingest_error else "success"
    if status == "success":
        try:
            warm_namespace(document.namespace)
        except Exception:
            pass
    trace = Trace(
        id=str(uuid.uuid4()),
        type="ingestion",
        document_id=document.id,
        query_text=None,
        parent_trace_id=None,
        created_at=_now(),
        total_latency_ms=round(total_ms, 1),
        total_cost_usd=round(total_cost, 6),
        status=status,
        nodes_json=json.dumps(nodes),
        settings_json=json.dumps({"chunk_size": chunk_size, "chunk_overlap": overlap}),
    )
    db.add(trace)
    document.ingest_trace_id = trace.id
    document.status = status
    db.commit()
    db.refresh(trace)

    progress(
        {
            "stage": "done" if status == "success" else "error",
            "progress": 1.0,
            "message": "Ingestion complete" if status == "success" else ingest_error,
            "document_id": document.id,
            "trace_id": trace.id,
            "status": status,
        }
    )
    return trace


def _fmt_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f" {n / 1024:.1f} KB".strip()
    return f"{n / (1024 * 1024):.1f} MB"
