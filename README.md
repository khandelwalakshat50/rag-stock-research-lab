# RAG Stock Research Lab

A learning-first RAG app for equity research PDFs. Every pipeline step is visible: what was extracted, how it was chunked, the embedding vectors, Pinecone scores, the exact prompt sent to the LLM, token counts, latency, and estimated cost.

The UI has two tabs:

- **Reader** — upload a report, watch ingestion, read the PDF, ask questions, jump to cited pages.
- **Pipeline Inspector** — node graphs for the ingestion run and every query, plus controls to change chunking, candidate pool, final chunks, and the reranker, then re-run.

## What is not in this repository

Do **not** commit secrets or local data. `.gitignore` already excludes:

| Path | Why |
| --- | --- |
| `.env` | Pinecone and OpenAI API keys |
| `backend/uploads/` | PDFs you uploaded |
| `backend/data/` | SQLite traces, chat history, eval runs |
| `.venv/`, `node_modules/` | Installed dependencies |

Use `.env.example` as the template. Copy it locally:

```bash
cp .env.example .env
```

Fill in real keys in `.env` only. That file stays on your machine.

## Architecture

```
PDF → PyMuPDF extract → table-aware chunking → OpenAI text-embedding-3-small
    → Pinecone upsert (auto-created index)
Query → embed → Pinecone semantic pool ┐
      → local BM25 keyword pool ────────┴→ weighted rank fusion
      → LLM rerank (gpt-4.1-mini) → merge same-page chunks → GPT-5.6 → cited answer
Every stage is stored as JSON nodes in local SQLite so graphs survive restart.
```

## Prerequisites

- Python 3.9+ (3.11 recommended)
- Node.js 20+
- API keys: Pinecone, OpenAI

## 1. Keys

```bash
cp .env.example .env
```

Edit `.env`:

```
PINECONE_API_KEY=...
PINECONE_INDEX_NAME=rag-stock-reports
OPENAI_API_KEY=...
```

Optional: `PINECONE_CLOUD` (default `aws`), `PINECONE_REGION` (default `us-east-1`), `OPENAI_LLM_MODEL` (default `gpt-5.6`).

The Pinecone index is created automatically on first backend start if it does not exist (1536 dimensions, cosine, serverless).

## 2. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --reload-dir app --host 0.0.0.0 --port 8006
```

Check: [http://127.0.0.1:8006/api/health](http://127.0.0.1:8006/api/health)

Local extraction/chunking smoke test (no API keys):

```bash
cd backend
source .venv/bin/activate
python -m tests.test_extract_chunk
```

## 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5181](http://localhost:5181).

Or from the repo root, after both venvs/deps are installed:

```bash
./start.sh
```

## How to use it as a learning tool

1. Upload a 10-K, initiation, or sell-side PDF (150+ pages is expected).
2. Watch the progress bar: **Parsing → Chunking → Embedding → Uploading**.
3. Ask a question in the Reader. Click `[p.12]` citations to jump and highlight.
4. Switch to **Pipeline Inspector**. Select the ingestion run, then any query.
5. Click nodes. Open **Controls** to change `chunk_size`, overlap, candidate pool, final chunks, the reranker, score threshold, or the system prompt.
6. **Re-run query** writes a sibling graph so you can compare retrieval and cost. **Re-ingest** rebuilds chunks after size/overlap changes.

Node colors: green = success, yellow = slow, red = error. Edge labels are step latency. The graph header shows end-to-end time and estimated USD cost.

## Project layout

```
backend/app/          FastAPI, extract, chunk, embed, query, traces
backend/data/         SQLite database (gitignored)
backend/uploads/      Stored PDFs (gitignored)
frontend/            Vite + React UI (port 5181)
frontend/components/ Reader, Inspector, React Flow, PDF viewer
```

## Retrieval quality

- **Evaluation tab**: save test questions with their correct pages, press *Run eval*, compare runs side by side (recall@5, MRR@10, per-stage latency, settings used). The eval runs retrieval only (no answer LLM).
- **Candidate pool → rerank → final chunks**: vector search fetches a wide pool (Learning Controls → *Candidate pool*, default 40); `gpt-4.1-mini` scores every candidate against the question; only the best *Final chunks sent to LLM* (default 5) go into the prompt. Toggle *Reranker* off to compare against plain vector order. If the reranker errors or takes over 10 s, the query falls back to vector order.
- **Hybrid search**: a BM25 keyword index over the chunks (built in memory from SQLite, rebuilt after re-ingest) runs alongside vector search, so exact tokens like tickers, `FY26E`, `EBITDA`, loan numbers and figures (`12,97,82,239` matches `129782239`) are found reliably. *Keyword vs semantic weight* (0 = pure semantic, 1 = pure keyword, default 0.5) sets how the two rankings are merged (weighted reciprocal-rank fusion). Each result is labelled *semantic*, *keyword* or *both*; keyword-only hits have no similarity score.
- **One result per page**: after reranking, candidates from the same page are merged into a single result (reading order, overlapping text between neighbouring chunks removed, capped at 4,000 chars), so a page can't take several of the few LLM slots. **Diversity** (Learning Controls, default off) additionally moves down results that mostly repeat one already picked, e.g. the consolidated copy of a standalone note (maximal marginal relevance; only token overlap above 0.22 counts, which separates near-copies from related pages in this report).
- Why an LLM reranker: local MS-MARCO cross-encoders and Pinecone's free hosted rerankers were tested on the eval set and ranked financial-statement notes *worse* than plain vector search.

## Latency notes

- One shared Pinecone `Index` client per process: the index host is looked up once, and HTTP connections are reused.
- On startup the backend warms up in the background: opens the Pinecone connection, primes the 3 most recent document namespaces, and makes one embedding call. Selecting a document in the UI and finishing an ingest also warm that namespace.
- A free `describe_index_stats` call every 20 s keeps the connection from being dropped when idle.
- `GET /api/diagnostics` shows the index cloud/region and the measured network round trip. A vector search can't be faster than one round trip. From India, `us-east-1` is ~265 ms away; `ap-southeast-1` (Singapore, paid plans) is ~65 ms.

## Notes

- Chunk metadata always includes `page_number`. Detected headings and `is_table` are stored too.
- Tables are kept as atomic chunks (split only if they are huge, retaining the header row).
- Chat history and traces persist in SQLite across restarts.
- Cost figures are estimates from published per-token list prices, not invoices.
