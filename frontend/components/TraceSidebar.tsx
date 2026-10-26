import { useMemo } from "react";
import { Clock, Database, FileText } from "lucide-react";
import { useApp } from "./AppProvider";

export default function TraceSidebar() {
  const { traces, selectedTraceId, selectTrace, document } = useApp();

  const ingest = traces.filter((t) => t.type === "ingestion");
  const queries = traces.filter((t) => t.type === "query");

  const grouped = useMemo(() => {
    const byId = new Map(queries.map((q) => [q.id, q]));
    const rootOf = (q: (typeof queries)[number]) => {
      let cur = q;
      const seen = new Set<string>();
      while (cur.parent_trace_id && byId.has(cur.parent_trace_id) && !seen.has(cur.id)) {
        seen.add(cur.id);
        cur = byId.get(cur.parent_trace_id)!;
      }
      return cur;
    };
    const buckets = new Map<string, { root: (typeof queries)[number]; reruns: typeof queries }>();
    for (const q of queries) {
      const root = rootOf(q);
      const bucket = buckets.get(root.id) || { root, reruns: [] };
      if (q.id !== root.id) bucket.reruns.push(q);
      buckets.set(root.id, bucket);
    }
    return [...buckets.values()].map((b) => ({
      ...b,
      reruns: b.reruns.sort(
        (a, c) => Date.parse(a.created_at || "") - Date.parse(c.created_at || "")
      ),
    }));
  }, [queries]);

  return (
    <div className="flex h-full min-h-0 flex-col bg-white text-ink">
      <div className="border-b border-slate-200 px-3 py-3">
        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
          Pipeline runs
        </div>
        <div className="mt-1 truncate text-xs text-slate-500">
          {document?.filename || "No document"}
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-2 scroll-thin">
        <Section label="Ingestion">
          {ingest.length === 0 && <Empty text="Upload a PDF to create an ingestion graph." />}
          {ingest.map((t) => (
            <TraceButton
              key={t.id}
              active={t.id === selectedTraceId}
              icon={<Database size={13} />}
              title={document?.filename || "Document ingest"}
              meta={`${fmtMs(t.total_latency_ms)} · ${fmtUsd(t.total_cost_usd)}`}
              status={t.status}
              onClick={() => selectTrace(t.id)}
            />
          ))}
        </Section>
        <Section label="Queries">
          {grouped.length === 0 && <Empty text="Ask a question in Reader to inspect retrieval." />}
          {grouped.map(({ root, reruns }) => (
            <div key={root.id} className="mb-1">
              <TraceButton
                active={root.id === selectedTraceId}
                icon={<FileText size={13} />}
                title={root.query_text || "Query"}
                meta={`${fmtMs(root.total_latency_ms)} · ${fmtUsd(root.total_cost_usd)}`}
                status={root.status}
                onClick={() => selectTrace(root.id)}
              />
              {reruns.map((r, i) => (
                <TraceButton
                  key={r.id}
                  active={r.id === selectedTraceId}
                  icon={<Clock size={13} />}
                  title={`Re-run ${i + 1}: ${r.query_text || ""}`}
                  meta={`${fmtMs(r.total_latency_ms)} · ${fmtUsd(r.total_cost_usd)}`}
                  status={r.status}
                  nested
                  onClick={() => selectTrace(r.id)}
                />
              ))}
            </div>
          ))}
        </Section>
      </div>
    </div>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-4">
      <div className="px-2 pb-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
        {label}
      </div>
      {children}
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <p className="px-2 py-2 text-xs leading-5 text-slate-500">{text}</p>;
}

function TraceButton({
  active,
  icon,
  title,
  meta,
  status,
  nested,
  onClick,
}: {
  active: boolean;
  icon: React.ReactNode;
  title: string;
  meta: string;
  status: string;
  nested?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`mb-1 flex w-full items-start gap-2 rounded-xl px-2 py-2 text-left ${
        nested ? "ml-3 w-[calc(100%-0.75rem)]" : ""
      } ${active ? "bg-teal-50 text-ink" : "hover:bg-slate-50"}`}
    >
      <span className="mt-0.5 text-slate-400">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-xs font-medium">{title}</span>
        <span className="mt-0.5 flex items-center gap-2 font-mono text-[10px] text-slate-500">
          <StatusDot status={status} />
          {meta}
        </span>
      </span>
    </button>
  );
}

function StatusDot({ status }: { status: string }) {
  const color =
    status === "error" ? "bg-red-500" : status === "slow" ? "bg-amber-400" : "bg-emerald-500";
  return <span className={`inline-block h-1.5 w-1.5 rounded-full ${color}`} />;
}

function fmtMs(ms: number) {
  if (!ms) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
}

function fmtUsd(n: number) {
  return `$${(n || 0).toFixed(4)}`;
}
