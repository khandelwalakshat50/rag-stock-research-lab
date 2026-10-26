import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import Document, SessionLocal, init_db
from .embeddings import embed_texts
from .pinecone_client import diagnostics, warmup
from .routers.documents import router as documents_router
from .routers.evals import router as evals_router
from .routers.query import router as query_router
from .routers.settings import router as settings_router
from .routers.traces import router as traces_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    # Warm up in the background so the API is reachable immediately.
    threading.Thread(target=_warmup, daemon=True, name="warmup").start()
    yield


_openai_warmup: dict = {}


def _warmup() -> None:
    db = SessionLocal()
    try:
        recent = (
            db.query(Document)
            .filter(Document.status == "success")
            .order_by(Document.created_at.desc())
            .limit(3)
            .all()
        )
        namespaces = [d.namespace for d in recent]
    finally:
        db.close()
    try:
        info = warmup(namespaces)
        print(
            f"[startup] Pinecone warm: {info.get('cloud')}/{info.get('region')} "
            f"rtt={info.get('network_rtt_ms')}ms first_query={info.get('first_query_ms')}ms "
            f"warm_query={info.get('warm_query_ms')}ms"
        )
    except Exception as exc:
        # Allow the API to boot so the UI can show a clear error on first use.
        print(f"[startup] Pinecone index not ready: {exc}")
    try:
        start = time.perf_counter()
        embed_texts(["warmup"], batch_size=1)
        _openai_warmup["embedding_ms"] = round((time.perf_counter() - start) * 1000, 1)
    except Exception as exc:
        _openai_warmup["error"] = str(exc)


app = FastAPI(
    title="RAG Stock Research Lab",
    description="Inspectable RAG pipeline for equity research PDFs",
    version="1.0.0",
    lifespan=lifespan,
    redirect_slashes=False,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents_router)
app.include_router(query_router)
app.include_router(traces_router)
app.include_router(settings_router)
app.include_router(evals_router)


@app.get("/api/health")
def health():
    keys = {
        "pinecone": bool(settings.pinecone_api_key) and not settings.pinecone_api_key.startswith("your_"),
        "openai": bool(settings.openai_api_key) and not settings.openai_api_key.startswith("your_"),
    }
    return {
        "ok": all(keys.values()),
        "keys_configured": keys,
        "index_name": settings.pinecone_index_name,
        "embedding_model": settings.openai_embedding_model,
        "llm_model": settings.openai_llm_model,
    }


@app.get("/api/diagnostics")
def get_diagnostics():
    return {"pinecone": diagnostics(), "openai_warmup": _openai_warmup}
