import { useCallback, useEffect, useMemo, useState } from "react";
import { Check, LoaderCircle, Pencil, Play, Trash2, X } from "lucide-react";
import {
  createEvalQuestion,
  deleteEvalQuestion,
  deleteEvalRun,
  getEvalRun,
  listEvalQuestions,
  listEvalRuns,
  runEval,
  updateEvalQuestion,
} from "@/lib/api";
import type { EvalProgress, EvalQuestion, EvalRun, EvalRunDetail } from "@/lib/types";
import { regionNote, useDiagnostics } from "@/lib/useDiagnostics";
import { useApp } from "./AppProvider";

export default function EvalTab() {
  const { document, jumpTo } = useApp();
  const [questions, setQuestions] = useState<EvalQuestion[]>([]);
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [details, setDetails] = useState<Record<string, EvalRunDetail>>({});
  const [selected, setSelected] = useState<string[]>([]);
  const [label, setLabel] = useState("");
  const [progress, setProgress] = useState<EvalProgress | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const docId = document?.id;
  const note = regionNote(useDiagnostics());

  const load = useCallback(async () => {
    if (!docId) return;
    try {
      const [qs, rs] = await Promise.all([listEvalQuestions(docId), listEvalRuns(docId)]);
      setQuestions(qs);
      setRuns(rs);
      return rs;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load eval data");
    }
  }, [docId]);

  useEffect(() => {
    setSelected([]);
    setDetails({});
    load().then((rs) => {
      if (rs) setSelected(rs.slice(0, 2).map((r) => r.id));
    });
  }, [load]);

  // Fetch per-question results for the selected runs, plus the latest run (for question badges).
  useEffect(() => {
    const wanted = runs[0] ? [...selected, runs[0].id] : selected;
    const missing = [...new Set(wanted)].filter((id) => !details[id]);
    if (!missing.length) return;
    Promise.all(missing.map(getEvalRun))
      .then((rows) =>
        setDetails((prev) => {
          const next = { ...prev };
          for (const r of rows) next[r.id] = r;
          return next;
        })
      )
      .catch(() => undefined);
  }, [selected, details, runs]);

  async function startRun() {
    if (!docId || running) return;
    setRunning(true);
    setError(null);
    setProgress({ stage: "running", done: 0, total: questions.length });
    try {
      const last = await runEval(docId, label, setProgress);
      if (last?.stage === "error") throw new Error(last.message || "Eval failed");
      const rs = await load();
      if (last?.run_id && rs) {
        // Compare the new run against the previous one by default.
        const prev = rs.find((r) => r.id !== last.run_id);
        setSelected(prev ? [last.run_id, prev.id] : [last.run_id]);
      }
      setLabel("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Eval failed");
    } finally {
      setRunning(false);
      setProgress(null);
    }
  }

  if (!document) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-slate-500">
        Upload a report first. Test questions are saved per document.
      </div>
    );
  }

  const latestDetail = runs[0] ? details[runs[0].id] : undefined;

  return (
    <div className="flex h-full min-h-0 overflow-hidden bg-paper text-ink">
      <aside className="flex w-[400px] shrink-0 flex-col border-r border-slate-200 bg-white">
        <QuestionEditor
          documentId={document.id}
          onSaved={(q) => setQuestions((prev) => [...prev, q])}
        />
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2">
          <Label>Test questions ({questions.length})</Label>
          {latestDetail ? (
            <span className="font-mono text-[10px] text-slate-400">status from latest run</span>
          ) : null}
        </div>
        <div className="min-h-0 flex-1 overflow-auto p-2 scroll-thin">
          {questions.length === 0 ? (
            <p className="px-2 py-3 text-xs leading-5 text-slate-500">
              Add questions whose answer you know, with the page(s) where it appears. The eval then
              checks whether retrieval surfaces a correct page in the top 5.
            </p>
          ) : null}
          {questions.map((q) => (
            <QuestionRow
              key={q.id}
              q={q}
              result={latestDetail?.results.find((r) => r.question_id === q.id)}
              onJump={(page) => jumpTo({ page })}
              onChange={(next) => setQuestions((prev) => prev.map((p) => (p.id === next.id ? next : p)))}
              onDelete={async () => {
                await deleteEvalQuestion(q.id);
                setQuestions((prev) => prev.filter((p) => p.id !== q.id));
              }}
            />
          ))}
        </div>
      </aside>

      <section className="min-w-0 flex-1 overflow-auto scroll-thin">
        <div className="border-b border-slate-200 bg-white px-4 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="mr-auto">
              <div className="text-sm font-semibold">Retrieval evaluation</div>
              <div className="mt-0.5 text-xs text-slate-500">
                Runs every saved question through retrieval with the current Learning Controls (no LLM
                call). recall@5 = share of questions with a correct page in the top 5.
              </div>
              {note ? <div className="mt-0.5 font-mono text-[10px] text-slate-400">{note}</div> : null}
            </div>
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="Run label (optional)"
              className="w-48 rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs outline-none focus:border-accent"
            />
            <button
              onClick={startRun}
              disabled={running || questions.length === 0 || document.status !== "success"}
              className="flex items-center gap-1.5 rounded-full bg-teal-600 px-4 py-1.5 text-xs font-medium text-white disabled:opacity-40"
            >
              {running ? <LoaderCircle size={13} className="animate-spin" /> : <Play size={13} />}
              {running ? "Running…" : "Run eval"}
            </button>
          </div>
          {running && progress ? (
            <div className="mt-3">
              <div className="h-1.5 overflow-hidden rounded bg-slate-200">
                <div
                  className="h-full bg-accent transition-all"
                  style={{ width: `${((progress.done || 0) / Math.max(progress.total || 1, 1)) * 100}%` }}
                />
              </div>
              <div className="mt-1 truncate font-mono text-[10px] text-slate-500">
                {progress.done}/{progress.total} · {progress.message || ""}
              </div>
            </div>
          ) : null}
          {error ? <p className="mt-2 text-xs text-red-600">{error}</p> : null}
        </div>

        <div className="space-y-4 p-4">
          <RunsTable
            runs={runs}
            selected={selected}
            onToggle={(id) =>
              setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
            }
            onDelete={async (id) => {
              await deleteEvalRun(id);
              setSelected((prev) => prev.filter((x) => x !== id));
              await load();
            }}
          />
          <Comparison
            runs={runs.filter((r) => selected.includes(r.id)).reverse()}
            details={details}
            questions={questions}
          />
        </div>
      </section>
    </div>
  );
}

function parsePages(text: string): number[] {
  const out = new Set<number>();
  for (const part of text.split(/[\s,;]+/)) {
    if (!part) continue;
    const range = part.match(/^p?\.?(\d+)\s*[-–]\s*(\d+)$/i);
    if (range) {
      const [a, b] = [Number(range[1]), Number(range[2])];
      for (let p = Math.min(a, b); p <= Math.max(a, b) && p - a < 50; p++) out.add(p);
      continue;
    }
    const n = Number(part.replace(/^p\.?/i, ""));
    if (Number.isInteger(n) && n > 0) out.add(n);
  }
  return [...out].sort((a, b) => a - b);
}

function QuestionEditor({
  documentId,
  onSaved,
}: {
  documentId: string;
  onSaved: (q: EvalQuestion) => void;
}) {
  const [question, setQuestion] = useState("");
  const [pages, setPages] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const parsed = parsePages(pages);

  async function save() {
    setErr(null);
    if (!question.trim() || parsed.length === 0) {
      setErr("Enter a question and at least one page number.");
      return;
    }
    try {
      onSaved(await createEvalQuestion({ document_id: documentId, question: question.trim(), expected_pages: parsed }));
      setQuestion("");
      setPages("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not save");
    }
  }

  return (
    <div className="space-y-2 border-b border-slate-200 p-4">
      <Label>Add test question</Label>
      <textarea
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        rows={2}
        placeholder="e.g. What is the FY26E EBITDA margin?"
        className="w-full resize-none rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs outline-none focus:border-accent"
      />
      <div className="flex items-center gap-2">
        <input
          value={pages}
          onChange={(e) => setPages(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && save()}
          placeholder="Correct page(s): 24, 58 or 60-62"
          className="min-w-0 flex-1 rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 font-mono text-[11px] outline-none focus:border-accent"
        />
        <button
          onClick={save}
          className="rounded-full bg-ink px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
        >
          Save
        </button>
      </div>
      {parsed.length ? (
        <div className="font-mono text-[10px] text-slate-400">pages: {parsed.join(", ")}</div>
      ) : null}
      {err ? <p className="text-xs text-red-600">{err}</p> : null}
    </div>
  );
}

function QuestionRow({
  q,
  result,
  onJump,
  onChange,
  onDelete,
}: {
  q: EvalQuestion;
  result?: EvalRunDetail["results"][number];
  onJump: (page: number) => void;
  onChange: (q: EvalQuestion) => void;
  onDelete: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(q.question);
  const [pages, setPages] = useState(q.expected_pages.join(", "));

  if (editing) {
    return (
      <div className="mb-1 space-y-2 rounded-xl border border-accent/40 bg-teal-50/40 p-2">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          rows={2}
          className="w-full resize-none rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs outline-none"
        />
        <div className="flex items-center gap-2">
          <input
            value={pages}
            onChange={(e) => setPages(e.target.value)}
            className="min-w-0 flex-1 rounded-full border border-slate-200 bg-white px-3 py-1 font-mono text-[11px] outline-none"
          />
          <button
            className="rounded-full bg-ink p-1.5 text-white"
            aria-label="Save"
            onClick={async () => {
              const expected = parsePages(pages);
              if (!text.trim() || !expected.length) return;
              onChange(await updateEvalQuestion(q.id, { question: text.trim(), expected_pages: expected }));
              setEditing(false);
            }}
          >
            <Check size={12} />
          </button>
          <button className="rounded-full border border-slate-200 p-1.5" aria-label="Cancel" onClick={() => setEditing(false)}>
            <X size={12} />
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="group mb-1 rounded-xl px-2 py-2 hover:bg-slate-50">
      <div className="flex items-start gap-2">
        <ResultBadge result={result} />
        <div className="min-w-0 flex-1">
          <div className="text-xs leading-5 text-ink">{q.question}</div>
          <div className="mt-1 flex flex-wrap gap-1">
            {q.expected_pages.map((p) => (
              <button
                key={p}
                onClick={() => onJump(p)}
                className="rounded-full border border-teal-200 bg-teal-50 px-1.5 font-mono text-[10px] text-teal-800 hover:bg-teal-100"
                title="Open this page in the Reader"
              >
                p.{p}
              </button>
            ))}
          </div>
          {result && !result.hit_at_5 ? (
            <div className="mt-1 font-mono text-[10px] text-slate-400">
              top 5 got: {result.retrieved.slice(0, 5).map((r) => `p.${r.page}`).join(" ")}
            </div>
          ) : null}
        </div>
        <div className="flex shrink-0 gap-1 opacity-0 group-hover:opacity-100">
          <button className="rounded p-1 text-slate-400 hover:text-ink" aria-label="Edit" onClick={() => setEditing(true)}>
            <Pencil size={12} />
          </button>
          <button className="rounded p-1 text-slate-400 hover:text-red-600" aria-label="Delete" onClick={onDelete}>
            <Trash2 size={12} />
          </button>
        </div>
      </div>
    </div>
  );
}

function ResultBadge({ result }: { result?: EvalRunDetail["results"][number] }) {
  if (!result) return <span className="mt-0.5 w-9 shrink-0 font-mono text-[10px] text-slate-300">—</span>;
  if (result.error) return <span className="mt-0.5 w-9 shrink-0 font-mono text-[10px] text-red-600">err</span>;
  const hit = result.hit_at_5;
  return (
    <span
      className={`mt-0.5 w-9 shrink-0 rounded-full px-1 text-center font-mono text-[10px] ${
        hit ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"
      }`}
      title={result.first_hit_rank ? `First correct page at rank ${result.first_hit_rank}` : "No correct page in top 10"}
    >
      {result.first_hit_rank ? `#${result.first_hit_rank}` : "✗"}
    </span>
  );
}

function RunsTable({
  runs,
  selected,
  onToggle,
  onDelete,
}: {
  runs: EvalRun[];
  selected: string[];
  onToggle: (id: string) => void;
  onDelete: (id: string) => void;
}) {
  return (
    <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2.5">
        <Label>Eval runs</Label>
        <span className="text-[11px] text-slate-400">Tick runs to compare side by side</span>
      </div>
      {runs.length === 0 ? (
        <p className="px-4 py-4 text-xs text-slate-500">No runs yet. Press “Run eval”.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 text-[10px] uppercase tracking-wider text-slate-500">
              <tr>
                <th className="w-8 px-3 py-2" />
                <th className="px-2 py-2">When</th>
                <th className="px-2 py-2">Label</th>
                <th className="px-2 py-2 text-right">Qs</th>
                <th className="px-2 py-2 text-right">recall@5</th>
                <th className="px-2 py-2 text-right">MRR@10</th>
                <th className="px-2 py-2 text-right">avg latency</th>
                <th className="px-2 py-2 text-right">embed</th>
                <th className="px-2 py-2 text-right">vector search</th>
                <th className="px-2 py-2 text-right">rerank</th>
                <th className="w-8 px-2 py-2" />
              </tr>
            </thead>
            <tbody className="font-mono text-[11px]">
              {runs.map((r) => (
                <tr
                  key={r.id}
                  className={`border-t border-slate-100 ${selected.includes(r.id) ? "bg-teal-50/50" : ""}`}
                >
                  <td className="px-3 py-2">
                    <input type="checkbox" checked={selected.includes(r.id)} onChange={() => onToggle(r.id)} />
                  </td>
                  <td className="whitespace-nowrap px-2 py-2 text-slate-500">{fmtDate(r.created_at)}</td>
                  <td className="max-w-[180px] truncate px-2 py-2 font-sans text-ink">{r.label || "—"}</td>
                  <td className="px-2 py-2 text-right">{r.question_count}</td>
                  <td className="px-2 py-2 text-right font-semibold text-accent">{pct(r.recall_at_5)}</td>
                  <td className="px-2 py-2 text-right">{r.mrr_at_10.toFixed(3)}</td>
                  <td className="px-2 py-2 text-right">{fmtMs(r.avg_latency_ms)}</td>
                  <td className="px-2 py-2 text-right text-slate-500">{fmtMs(r.avg_timings.query_embedding_ms)}</td>
                  <td className="px-2 py-2 text-right text-slate-500">{fmtMs(r.avg_timings.vector_search_ms)}</td>
                  <td className="px-2 py-2 text-right text-slate-500">{fmtMs(r.avg_timings.rerank_ms)}</td>
                  <td className="px-2 py-2">
                    <button
                      className="text-slate-300 hover:text-red-600"
                      aria-label="Delete run"
                      onClick={() => onDelete(r.id)}
                    >
                      <Trash2 size={12} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

type MetricRow = {
  label: string;
  get: (r: EvalRun) => number | null | undefined;
  fmt: (n: number | null | undefined) => string;
  better: "higher" | "lower";
};

const METRICS: MetricRow[] = [
  { label: "recall@5", get: (r) => r.recall_at_5, fmt: (n) => (n == null ? "—" : pct(n)), better: "higher" },
  { label: "MRR@10", get: (r) => r.mrr_at_10, fmt: (n) => (n == null ? "—" : n.toFixed(3)), better: "higher" },
  {
    label: "distinct pages in top 5",
    get: (r) => r.avg_timings.distinct_pages_top5,
    fmt: (n) => (n == null ? "—" : n.toFixed(2)),
    better: "higher",
  },
  { label: "avg latency", get: (r) => r.avg_latency_ms, fmt: fmtMs, better: "lower" },
  { label: "p50 latency", get: (r) => r.avg_timings.p50_latency_ms, fmt: fmtMs, better: "lower" },
  { label: "query embedding", get: (r) => r.avg_timings.query_embedding_ms, fmt: fmtMs, better: "lower" },
  { label: "vector search", get: (r) => r.avg_timings.vector_search_ms, fmt: fmtMs, better: "lower" },
  { label: "  ↳ get index handle", get: (r) => r.avg_timings.vector_connect_ms, fmt: fmtMs, better: "lower" },
  { label: "  ↳ query round trip", get: (r) => r.avg_timings.vector_query_ms, fmt: fmtMs, better: "lower" },
  { label: "keyword search", get: (r) => r.avg_timings.keyword_ms, fmt: fmtMs, better: "lower" },
  { label: "reranking", get: (r) => r.avg_timings.rerank_ms, fmt: fmtMs, better: "lower" },
];

function Comparison({
  runs,
  details,
  questions,
}: {
  runs: EvalRun[];
  details: Record<string, EvalRunDetail>;
  questions: EvalQuestion[];
}) {
  const settingKeys = useMemo(() => {
    const keys = new Set<string>();
    runs.forEach((r) => Object.keys(r.settings || {}).forEach((k) => keys.add(k)));
    return [...keys].filter((k) => k !== "ingest_trace_id").sort();
  }, [runs]);

  if (runs.length === 0) return null;
  const base = runs[0];

  // Questions from any selected run, in saved-question order, plus deleted ones at the end.
  const qOrder = new Map(questions.map((q, i) => [q.id, i]));
  const rowIds = new Map<string, string>();
  runs.forEach((r) => details[r.id]?.results.forEach((res) => rowIds.set(res.question_id, res.question)));
  const rows = [...rowIds.entries()].sort(
    (a, b) => (qOrder.get(a[0]) ?? 1e9) - (qOrder.get(b[0]) ?? 1e9)
  );

  return (
    <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white">
      <div className="border-b border-slate-200 px-4 py-2.5">
        <Label>Side-by-side comparison</Label>
        <div className="mt-0.5 text-[11px] text-slate-400">
          Oldest selected run on the left. Deltas are relative to it.
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="bg-slate-50 text-[10px] text-slate-500">
            <tr>
              <th className="px-3 py-2 uppercase tracking-wider">Metric</th>
              {runs.map((r) => (
                <th key={r.id} className="min-w-[150px] px-3 py-2">
                  <div className="truncate font-sans text-[11px] font-medium normal-case text-ink">
                    {r.label || "Unlabelled run"}
                  </div>
                  <div className="font-mono font-normal">{fmtDate(r.created_at)}</div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="font-mono text-[11px]">
            {METRICS.map((m) => (
              <tr key={m.label} className="border-t border-slate-100">
                <td className="whitespace-pre px-3 py-1.5 font-sans text-slate-500">{m.label}</td>
                {runs.map((r) => {
                  const v = m.get(r);
                  const b = m.get(base);
                  return (
                    <td key={r.id} className="px-3 py-1.5">
                      <span className="text-ink">{m.fmt(v)}</span>
                      {r.id !== base.id ? <Delta v={v} base={b} better={m.better} metric={m.label} /> : null}
                    </td>
                  );
                })}
              </tr>
            ))}
            <tr className="border-t border-slate-200 bg-slate-50">
              <td colSpan={runs.length + 1} className="px-3 py-1.5 font-sans text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                Settings used
              </td>
            </tr>
            {settingKeys.map((k) => {
              const vals = runs.map((r) => JSON.stringify(r.settings?.[k] ?? null));
              const differs = new Set(vals).size > 1;
              return (
                <tr key={k} className="border-t border-slate-100">
                  <td className="px-3 py-1.5 font-sans text-slate-500">{k}</td>
                  {runs.map((r) => (
                    <td key={r.id} className={`px-3 py-1.5 ${differs ? "bg-amber-50 text-amber-900" : "text-slate-600"}`}>
                      {fmtSetting(r.settings?.[k])}
                    </td>
                  ))}
                </tr>
              );
            })}
            <tr className="border-t border-slate-200 bg-slate-50">
              <td colSpan={runs.length + 1} className="px-3 py-1.5 font-sans text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                Per question — rank of first correct page (✗ = not in top 10)
              </td>
            </tr>
            {rows.map(([qid, text]) => (
              <tr key={qid} className="border-t border-slate-100">
                <td className="max-w-[360px] px-3 py-1.5 font-sans text-slate-600" title={text}>
                  <div className="truncate">{text}</div>
                </td>
                {runs.map((r) => {
                  const res = details[r.id]?.results.find((x) => x.question_id === qid);
                  if (!details[r.id]) return <td key={r.id} className="px-3 py-1.5 text-slate-300">…</td>;
                  if (!res) return <td key={r.id} className="px-3 py-1.5 text-slate-300">not in run</td>;
                  return (
                    <td
                      key={r.id}
                      className="px-3 py-1.5"
                      title={`top 5: ${res.retrieved.slice(0, 5).map((x) => `p.${x.page}`).join(" ")} · ${fmtMs(res.latency_ms)}`}
                    >
                      <span className={res.hit_at_5 ? "text-emerald-700" : "text-red-600"}>
                        {res.error ? "error" : res.first_hit_rank ? `#${res.first_hit_rank}` : "✗"}
                      </span>
                      <span className="ml-2 text-slate-400">{fmtMs(res.latency_ms)}</span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Delta({
  v,
  base,
  better,
  metric,
}: {
  v: number | null | undefined;
  base: number | null | undefined;
  better: "higher" | "lower";
  metric: string;
}) {
  if (v == null || base == null) return null;
  const d = v - base;
  if (Math.abs(d) < 1e-9) return <span className="ml-2 text-slate-400">±0</span>;
  const good = better === "higher" ? d > 0 : d < 0;
  const isRatio = metric.startsWith("recall");
  const isScore = metric.startsWith("MRR") || metric.startsWith("distinct");
  const txt = isRatio
    ? `${d > 0 ? "+" : ""}${(d * 100).toFixed(1)} pts`
    : isScore
      ? `${d > 0 ? "+" : ""}${d.toFixed(3)}`
      : `${d > 0 ? "+" : ""}${Math.round(d)} ms`;
  return <span className={`ml-2 ${good ? "text-emerald-700" : "text-red-600"}`}>{txt}</span>;
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">{children}</div>
  );
}

function pct(n: number) {
  return `${(n * 100).toFixed(1)}%`;
}

function fmtMs(ms: number | null | undefined) {
  if (ms == null) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`;
}

function fmtDate(iso: string | null) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function fmtSetting(v: unknown) {
  if (v == null) return "—";
  if (typeof v === "boolean") return v ? "on" : "off";
  return String(v);
}
