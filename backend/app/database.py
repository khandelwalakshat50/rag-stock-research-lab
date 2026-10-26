from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import settings

engine = create_engine(
    f"sqlite:///{settings.sqlite_path}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True)
    filename = Column(String, nullable=False)
    size_bytes = Column(Integer, nullable=False, default=0)
    page_count = Column(Integer, nullable=False, default=0)
    namespace = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False)
    ingest_trace_id = Column(String, nullable=True)
    status = Column(String, nullable=False, default="pending")


class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(String, primary_key=True)
    document_id = Column(String, index=True, nullable=False)
    chunk_index = Column(Integer, nullable=False)
    page_number = Column(Integer, nullable=False)
    heading = Column(String, nullable=True)
    is_table = Column(Boolean, nullable=False, default=False)
    text = Column(Text, nullable=False)
    char_length = Column(Integer, nullable=False)


class Trace(Base):
    __tablename__ = "traces"

    id = Column(String, primary_key=True)
    type = Column(String, nullable=False)
    document_id = Column(String, index=True, nullable=False)
    query_text = Column(Text, nullable=True)
    parent_trace_id = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False)
    total_latency_ms = Column(Float, nullable=False, default=0)
    total_cost_usd = Column(Float, nullable=False, default=0)
    status = Column(String, nullable=False, default="running")
    nodes_json = Column(Text, nullable=False, default="[]")
    settings_json = Column(Text, nullable=True)


class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True)
    document_id = Column(String, index=True, nullable=False)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    citations_json = Column(Text, nullable=True)
    trace_id = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False)


class EvalQuestion(Base):
    __tablename__ = "eval_questions"

    id = Column(String, primary_key=True)
    document_id = Column(String, index=True, nullable=False)
    question = Column(Text, nullable=False)
    expected_pages_json = Column(Text, nullable=False, default="[]")
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False)


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id = Column(String, primary_key=True)
    document_id = Column(String, index=True, nullable=False)
    label = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False)
    settings_json = Column(Text, nullable=False, default="{}")
    question_count = Column(Integer, nullable=False, default=0)
    recall_at_5 = Column(Float, nullable=False, default=0)
    mrr_at_10 = Column(Float, nullable=False, default=0)
    avg_latency_ms = Column(Float, nullable=False, default=0)
    avg_timings_json = Column(Text, nullable=False, default="{}")
    results_json = Column(Text, nullable=False, default="[]")


class AppSettings(Base):
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True)
    chunk_size = Column(Integer, nullable=False, default=1000)
    chunk_overlap = Column(Integer, nullable=False, default=200)
    top_k = Column(Integer, nullable=False, default=10)
    similarity_threshold = Column(Float, nullable=False, default=0.0)
    show_threshold = Column(Boolean, nullable=False, default=False)
    system_prompt = Column(Text, nullable=False)
    temperature = Column(Float, nullable=False, default=0.2)
    candidate_pool = Column(Integer, nullable=False, default=40)
    final_k = Column(Integer, nullable=False, default=5)
    reranker_enabled = Column(Boolean, nullable=False, default=True)
    keyword_weight = Column(Float, nullable=False, default=0.5)
    diversity_enabled = Column(Boolean, nullable=False, default=False)


DEFAULT_SYSTEM_PROMPT = """You are a financial research assistant helping a student learn from equity research reports.

Rules:
- Answer ONLY using the provided report excerpts.
- Cite sources inline with page markers like [p.12].
- If multiple excerpts support a point, cite each relevant page.
- If the excerpts do not contain the answer, say so clearly and do not invent numbers.
- Preserve numbers, dates, ticker symbols, and table figures exactly as written.
- Be concise but complete: lead with the direct answer, then supporting evidence."""


# Columns added after the first release. create_all() never alters existing tables,
# so add any that are missing (SQLite supports ADD COLUMN with a constant default).
_ADDED_COLUMNS = {
    "app_settings": {
        "candidate_pool": "INTEGER NOT NULL DEFAULT 40",
        "final_k": "INTEGER NOT NULL DEFAULT 5",
        "reranker_enabled": "BOOLEAN NOT NULL DEFAULT 1",
        "keyword_weight": "FLOAT NOT NULL DEFAULT 0.5",
        "diversity_enabled": "BOOLEAN NOT NULL DEFAULT 0",
    },
}


def _migrate() -> None:
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, cols in _ADDED_COLUMNS.items():
            if table not in insp.get_table_names():
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in cols.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _migrate()
    db = SessionLocal()
    try:
        row = db.get(AppSettings, 1)
        if row is None:
            db.add(
                AppSettings(
                    id=1,
                    chunk_size=1000,
                    chunk_overlap=200,
                    top_k=10,
                    similarity_threshold=0.0,
                    show_threshold=False,
                    system_prompt=DEFAULT_SYSTEM_PROMPT,
                    temperature=0.2,
                )
            )
            db.commit()
    finally:
        db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
