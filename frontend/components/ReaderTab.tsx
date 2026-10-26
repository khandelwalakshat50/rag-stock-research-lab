import { useRef, useState } from "react";
import { FileUp } from "lucide-react";
import { useApp } from "./AppProvider";
import ChatPanel from "./ChatPanel";
import IngestProgress from "./IngestProgress";
import PdfViewer from "./PdfViewer";

export default function ReaderTab() {
  const { document, upload, ingesting, page, setPage, highlight, error } = useApp();
  const inputRef = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);

  async function handleFile(file?: File | null) {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".pdf")) return;
    await upload(file);
  }

  if (!document && !ingesting) {
    return (
      <div className="flex h-full items-center justify-center p-8">
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDrag(false);
            handleFile(e.dataTransfer.files?.[0]);
          }}
          className={`w-full max-w-xl rounded-3xl border-2 border-dashed bg-white p-12 text-center shadow-panel ${
            drag ? "border-accent bg-teal-50" : "border-slate-200"
          }`}
        >
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-teal-50 text-accent">
            <FileUp />
          </div>
          <h2 className="text-xl font-semibold tracking-tight">Upload an equity research PDF</h2>
          <p className="mt-2 text-sm leading-6 text-slate-500">
            Built for long reports (150+ pages). You will see parsing, chunking, embedding, and
            Pinecone upload as they happen, then ask questions with page citations.
          </p>
          <button
            onClick={() => inputRef.current?.click()}
            className="mt-6 rounded-full bg-ink px-5 py-2.5 text-sm font-medium text-white"
          >
            Choose PDF
          </button>
          <input
            ref={inputRef}
            type="file"
            accept="application/pdf"
            hidden
            onChange={(e) => handleFile(e.target.files?.[0])}
          />
          {error ? <p className="mt-4 text-sm text-red-600">{error}</p> : null}
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <IngestProgress />
      {error ? (
        <div className="border-b border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          {error}
        </div>
      ) : null}
      {document?.status === "error" && !ingesting ? (
        <div className="border-b border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-900">
          Ingestion stopped before the index was ready. Add API keys to <span className="font-mono">.env</span>,
          restart the backend, then re-ingest from Pipeline Inspector → Controls.
        </div>
      ) : null}
      <div className="grid min-h-0 flex-1 grid-cols-2 overflow-hidden">
        <div className="min-h-0 h-full border-r border-slate-200 overflow-hidden">
          {document ? (
            <PdfViewer
              documentId={document.id}
              page={page}
              onPage={setPage}
              pageCountHint={document.page_count}
              highlight={highlight}
            />
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-slate-400">
              Waiting for PDF…
            </div>
          )}
        </div>
        <ChatPanel />
      </div>
    </div>
  );
}
