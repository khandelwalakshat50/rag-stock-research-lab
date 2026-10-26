import { useCallback, useEffect, useRef, useState } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import { ChevronLeft, ChevronRight } from "lucide-react";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";
import { documentFileUrl } from "@/lib/api";

pdfjs.GlobalWorkerOptions.workerSrc = `https://unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

type Props = {
  documentId: string;
  page: number;
  onPage: (n: number) => void;
  pageCountHint?: number;
  highlight?: string | null;
};

export default function PdfViewer({
  documentId,
  page,
  onPage,
  pageCountHint,
  highlight,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(520);
  const [numPages, setNumPages] = useState(pageCountHint || 0);
  const [input, setInput] = useState(String(page));

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const obs = new ResizeObserver(() => {
      setWidth(Math.max(280, el.clientWidth - 24));
    });
    obs.observe(el);
    setWidth(Math.max(280, el.clientWidth - 24));
    return () => obs.disconnect();
  }, []);

  useEffect(() => setInput(String(page)), [page]);

  const onLoad = useCallback(
    ({ numPages: n }: { numPages: number }) => {
      setNumPages(n);
      if (page > n) onPage(n);
    },
    [onPage, page]
  );

  const needle = (highlight || "").replace(/\s+/g, " ").trim().slice(0, 48);

  const customTextRenderer = useCallback(
    ({ str }: { str: string }) => {
      if (!needle) return str;
      const lower = str.toLowerCase();
      const n = needle.toLowerCase();
      const idx = lower.indexOf(n);
      if (idx === -1) return str;
      const before = str.slice(0, idx);
      const mid = str.slice(idx, idx + needle.length);
      const after = str.slice(idx + needle.length);
      return `${escapeHtml(before)}<mark class="pdf-hl">${escapeHtml(mid)}</mark>${escapeHtml(after)}`;
    },
    [needle]
  );

  const maxPage = numPages || pageCountHint || 1;

  return (
    <div className="flex h-full min-h-0 flex-col bg-[#ece8e1]">
      <div className="flex items-center justify-between gap-3 border-b border-stone-200 bg-white/80 px-3 py-2 text-sm">
        <button
          className="rounded-md p-1 text-slate-600 hover:bg-slate-100 disabled:opacity-30"
          onClick={() => onPage(Math.max(1, page - 1))}
          disabled={page <= 1}
          aria-label="Previous page"
        >
          <ChevronLeft size={18} />
        </button>
        <form
          className="flex items-center gap-2 font-mono text-xs text-slate-600"
          onSubmit={(e) => {
            e.preventDefault();
            const n = Number(input);
            if (Number.isFinite(n)) onPage(Math.min(maxPage, Math.max(1, Math.floor(n))));
          }}
        >
          <span>Page</span>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            className="w-14 rounded border border-slate-200 bg-white px-2 py-1 text-center text-ink"
          />
          <span>/ {maxPage}</span>
        </form>
        <button
          className="rounded-md p-1 text-slate-600 hover:bg-slate-100 disabled:opacity-30"
          onClick={() => onPage(Math.min(maxPage, page + 1))}
          disabled={page >= maxPage}
          aria-label="Next page"
        >
          <ChevronRight size={18} />
        </button>
      </div>
      {highlight ? (
        <div className="border-b border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
          Highlighting cited excerpt on this page. Scroll if the mark is off-screen.
        </div>
      ) : null}
      <div ref={containerRef} className="min-h-0 flex-1 overflow-auto p-3">
        <div className="mx-auto w-fit shadow-panel">
          <Document
            file={documentFileUrl(documentId)}
            onLoadSuccess={onLoad}
            loading={
              <div className="w-[520px] bg-white p-10 text-center text-sm text-slate-500">
                Loading PDF…
              </div>
            }
            error={
              <div className="w-[520px] bg-white p-10 text-center text-sm text-red-600">
                Could not load the PDF. Check that the backend is running.
              </div>
            }
          >
            <Page
              pageNumber={page}
              width={width}
              renderAnnotationLayer
              renderTextLayer
              customTextRenderer={needle ? customTextRenderer : undefined}
              loading={
                <div className="flex h-[720px] items-center justify-center bg-white text-sm text-slate-400">
                  Rendering page {page}…
                </div>
              }
            />
          </Document>
        </div>
      </div>
    </div>
  );
}

function escapeHtml(s: string) {
  return s
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}
