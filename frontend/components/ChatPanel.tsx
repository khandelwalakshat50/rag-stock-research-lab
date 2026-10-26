import { FormEvent, useEffect, useRef, useState } from "react";
import { ArrowUp, LoaderCircle } from "lucide-react";
import { useApp } from "./AppProvider";

export default function ChatPanel() {
  const { messages, ask, asking, jumpTo, document, ingesting } = useApp();
  const [text, setText] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, asking]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const q = text.trim();
    if (!q || asking || ingesting || document?.status !== "success") return;
    setText("");
    await ask(q);
  }

  const ready = document?.status === "success" && !ingesting;

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-white">
      <div className="border-b border-slate-200 px-4 py-3">
        <div className="text-sm font-semibold tracking-tight">Ask the report</div>
        <div className="text-xs text-slate-500">
          Answers cite pages. Click a citation to jump in the PDF.
        </div>
      </div>
      <div className="min-h-0 flex-1 space-y-4 overflow-auto px-4 py-4 scroll-thin">
        {messages.length === 0 && (
          <div className="rounded-xl border border-dashed border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">
            Try questions like:
            <ul className="mt-2 list-disc space-y-1 pl-5 text-slate-500">
              <li>What is the price target and rating?</li>
              <li>Which risks does the analyst emphasize?</li>
              <li>How is valuation constructed?</li>
            </ul>
          </div>
        )}
        {messages.map((m) => (
          <div
            key={m.id}
            className={
              m.role === "user"
                ? "ml-8 rounded-2xl bg-ink px-4 py-3 text-sm text-white"
                : "mr-4 rounded-2xl border border-slate-200 bg-paper px-4 py-3 text-sm leading-6 text-slate-800"
            }
          >
            <div className="whitespace-pre-wrap">{m.content}</div>
            {m.role === "assistant" && m.citations?.length ? (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {m.citations.map((c) => (
                  <button
                    key={`${m.id}-${c.page}-${c.chunk_index}`}
                    onClick={() => jumpTo({ page: c.page, excerpt: c.excerpt })}
                    className="rounded-full border border-teal-200 bg-teal-50 px-2 py-0.5 font-mono text-[11px] text-teal-800 hover:bg-teal-100"
                    title={c.excerpt}
                  >
                    p.{c.page}
                    {c.heading ? ` · ${c.heading.slice(0, 28)}` : ""}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        ))}
        {asking && (
          <div className="flex items-center gap-2 text-sm text-slate-500">
            <LoaderCircle className="animate-spin" size={16} />
            Retrieving chunks and calling the model…
          </div>
        )}
        <div ref={bottomRef} />
      </div>
      <form onSubmit={onSubmit} className="border-t border-slate-200 p-3">
        <div className="flex items-end gap-2 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                onSubmit(e);
              }
            }}
            rows={2}
            placeholder={
              ready
                ? "Ask about this report…"
                : ingesting
                  ? "Ingestion in progress…"
                  : document
                    ? "Finish ingestion before asking questions"
                    : "Upload a report to start asking questions"
            }
            disabled={!ready || asking}
            className="min-h-[52px] flex-1 resize-none bg-transparent text-sm outline-none placeholder:text-slate-400"
          />
          <button
            type="submit"
            disabled={!ready || asking || !text.trim()}
            className="flex h-9 w-9 items-center justify-center rounded-full bg-accent text-white disabled:opacity-40"
            aria-label="Send"
          >
            <ArrowUp size={16} />
          </button>
        </div>
      </form>
    </div>
  );
}
