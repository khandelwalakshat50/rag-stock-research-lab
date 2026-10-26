import { useApp } from "./AppProvider";

const STAGES = [
  { id: "parsing", label: "Parsing" },
  { id: "chunking", label: "Chunking" },
  { id: "embedding", label: "Embedding" },
  { id: "uploading", label: "Uploading" },
];

function stageIndex(stage: string) {
  if (stage === "done") return STAGES.length;
  if (stage === "error") return -1;
  const i = STAGES.findIndex((s) => s.id === stage);
  return i < 0 ? 0 : i;
}

export default function IngestProgress() {
  const { progress, ingesting } = useApp();
  if (!ingesting && !progress) return null;
  if (progress?.stage === "done" && !ingesting) return null;

  const pct = Math.round((progress?.progress || 0) * 100);
  const idx = stageIndex(progress?.stage || "parsing");
  const failed = progress?.stage === "error";

  return (
    <div className="border-b border-slate-200 bg-white px-4 py-3">
      <div className="mb-2 flex items-center justify-between text-xs">
        <span className={failed ? "font-medium text-red-700" : "text-slate-600"}>
          {progress?.message || "Starting ingestion…"}
        </span>
        <span className="font-mono text-slate-500">{pct}%</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-slate-100">
        <div
          className={`h-full rounded-full transition-all ${failed ? "bg-red-500" : "bg-accent"}`}
          style={{ width: `${Math.min(100, Math.max(2, pct))}%` }}
        />
      </div>
      <div className="mt-2 flex gap-4 text-[11px] uppercase tracking-wide">
        {STAGES.map((s, i) => {
          const active = i === idx;
          const done = i < idx;
          return (
            <span
              key={s.id}
              className={
                failed
                  ? "text-red-400"
                  : active
                    ? "font-semibold text-accent"
                    : done
                      ? "text-teal-700"
                      : "text-slate-400"
              }
            >
              {s.label}
            </span>
          );
        })}
      </div>
    </div>
  );
}
