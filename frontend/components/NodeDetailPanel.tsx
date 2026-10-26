import { useState } from "react";
import type { PipelineNode, RetrievedChunk } from "@/lib/types";
import { regionNote, useDiagnostics } from "@/lib/useDiagnostics";
import { useApp } from "./AppProvider";

type Props = {
  node: PipelineNode | null;
};

export default function NodeDetailPanel({ node }: Props) {
  if (!node) {
    return (
      <div className="flex h-full items-center justify-center px-6 text-center text-sm text-slate-500">
        Click a node on the canvas to inspect its exact inputs, outputs, and metadata.
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b border-slate-200 px-4 py-3">
        <div className="flex items-center gap-2">
          <StatusPill status={node.status} />
          <div className="text-sm font-semibold text-ink">{node.label}</div>
        </div>
        <div className="mt-1 font-mono text-[11px] text-slate-500">
          {node.latency_ms ? `${node.latency_ms.toFixed(1)} ms` : "no extra latency"} · {node.summary}
        </div>
        {node.error ? <p className="mt-2 text-xs text-red-600">{node.error}</p> : null}
      </div>
      <div className="min-h-0 flex-1 overflow-auto px-4 py-3 text-sm text-slate-700 scroll-thin">
        <NodeBody node={node} />
      </div>
    </div>
  );
}

function NodeBody({ node }: { node: PipelineNode }) {
  const d = node.data;
  switch (node.type) {
    case "pdf_upload":
      return (
        <KV
          rows={[
            ["File", String(d.filename)],
            ["Size", String(d.size_human || d.size_bytes)],
            ["Pages", String(d.page_count)],
            ["Document ID", String(d.document_id)],
          ]}
        />
      );
    case "text_extraction":
      return <ExtractionDetail data={d} />;
    case "chunking":
      return <ChunkingDetail data={d} />;
    case "embedding":
    case "query_embedding":
      return (
        <div className="space-y-3">
          <KV
            rows={[
              ["Model", String(d.model)],
              ["Dimensions", String(d.dimensions)],
              ["Tokens", String(d.total_tokens ?? d.tokens)],
              ["Cost", d.cost_usd != null ? `$${Number(d.cost_usd).toFixed(6)}` : "—"],
              ["Time", `${d.time_ms ?? d.latency_ms ?? "—"} ms`],
            ]}
          />
          <Label>Sample vector (first 10 numbers)</Label>
          <pre className="wrap rounded-xl bg-slate-50 p-3 font-mono text-[11px] text-accent">
            {JSON.stringify(d.sample_vector_preview || d.vector_preview || [])}
          </pre>
        </div>
      );
    case "pinecone_upsert":
      return (
        <KV
          rows={[
            ["Index", String(d.index_name)],
            ["Namespace", String(d.namespace)],
            ["Vectors uploaded", String(d.vectors_uploaded)],
            ["Metadata keys", ((d.metadata_keys as string[]) || []).join(", ")],
            ["Time", `${d.time_ms ?? "—"} ms`],
          ]}
        />
      );
    case "user_query":
      return (
        <div>
          <Label>Question</Label>
          <p className="rounded-xl bg-slate-50 p-3 text-ink">{String(d.question)}</p>
          <KV rows={[["Timestamp", String(d.timestamp)], ["File", String(d.filename)]]} />
        </div>
      );
    case "pinecone_search":
      return <SearchDetail data={d} />;
    case "rerank":
      return <RerankDetail data={d} />;
    case "keyword_search":
      return <KeywordDetail data={d} />;
    case "merge_diversity":
      return <MergeDetail data={d} />;
    case "retrieved_chunks":
      return <RetrievedDetail data={d} />;
    case "prompt_assembly":
      return <PromptDetail data={d} />;
    case "llm_call":
      return (
        <KV
          rows={[
            ["Model", String(d.model)],
            ["Temperature", String(d.temperature)],
            ["Input tokens", String(d.input_tokens)],
            ["Output tokens", String(d.output_tokens)],
            ["Latency", `${d.latency_ms ?? "—"} ms`],
            ["Cost", d.cost_usd != null ? `$${Number(d.cost_usd).toFixed(6)}` : "—"],
          ]}
        />
      );
    case "final_answer":
      return <AnswerDetail data={d} />;
    default:
      return (
        <pre className="wrap rounded-xl bg-slate-50 p-3 font-mono text-[11px] text-slate-700">
          {JSON.stringify(d, null, 2)}
        </pre>
      );
  }
}

function ExtractionDetail({ data }: { data: Record<string, unknown> }) {
  const pages = (data.pages as Array<Record<string, unknown>>) || [];
  return (
    <div className="space-y-3">
      <KV
        rows={[
          ["Characters", Number(data.total_characters).toLocaleString()],
          ["Pages with tables", String(data.pages_with_tables)],
          ["Tables detected", String(data.table_count)],
          ["Empty pages", ((data.empty_pages as number[]) || []).join(", ") || "none"],
          ["Failed pages", ((data.failed_pages as number[]) || []).join(", ") || "none"],
        ]}
      />
      <Label>Per-page extract</Label>
      <div className="max-h-80 overflow-auto rounded-xl border border-slate-200">
        <table className="w-full text-left font-mono text-[11px]">
          <thead className="sticky top-0 bg-slate-50 text-slate-500">
            <tr>
              <th className="px-2 py-1">p</th>
              <th className="px-2 py-1">chars</th>
              <th className="px-2 py-1">tables</th>
              <th className="px-2 py-1">flag</th>
            </tr>
          </thead>
          <tbody>
            {pages.map((p) => (
              <tr key={String(p.page)} className="border-t border-slate-200">
                <td className="px-2 py-1">{String(p.page)}</td>
                <td className="px-2 py-1">{String(p.chars)}</td>
                <td className="px-2 py-1">{String(p.table_count)}</td>
                <td className="px-2 py-1 text-amber-700">
                  {p.failed ? "failed" : p.empty ? "empty" : p.has_table ? "table" : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ChunkingDetail({ data }: { data: Record<string, unknown> }) {
  const [q, setQ] = useState("");
  const chunks = (data.chunks as Array<Record<string, unknown>>) || [];
  const hist = (data.histogram as Array<{ range: string; count: number }>) || [];
  const max = Math.max(1, ...hist.map((h) => h.count));
  const filtered = chunks.filter((c) => {
    if (!q) return true;
    const blob = `${c.page_number} ${c.heading || ""} ${c.text}`.toLowerCase();
    return blob.includes(q.toLowerCase());
  });

  return (
    <div className="space-y-3">
      <KV
        rows={[
          ["Chunk size", String(data.chunk_size)],
          ["Overlap", String(data.overlap)],
          ["Total chunks", String(data.total_chunks)],
          ["Min / avg / max", `${data.min_length} / ${data.avg_length} / ${data.max_length}`],
          ["Table chunks", String(data.table_chunks)],
        ]}
      />
      <Label>Length histogram</Label>
      <div className="flex h-24 items-end gap-1 rounded-xl bg-slate-50 p-2">
        {hist.map((h) => (
          <div key={h.range} className="flex h-full flex-1 flex-col justify-end" title={`${h.range}: ${h.count}`}>
            <div
              className="w-full rounded-t bg-teal-400/80"
              style={{ height: `${(h.count / max) * 100}%` }}
            />
          </div>
        ))}
      </div>
      <div className="flex justify-between font-mono text-[10px] text-slate-500">
        <span>{hist[0]?.range}</span>
        <span>{hist[hist.length - 1]?.range}</span>
      </div>
      <Label>All chunks ({filtered.length})</Label>
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Filter by text, heading, or page"
        className="w-full rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs outline-none"
      />
      <div className="space-y-2">
        {filtered.slice(0, 80).map((c) => (
          <ChunkCard
            key={String(c.chunk_index)}
            page={Number(c.page_number)}
            heading={c.heading ? String(c.heading) : undefined}
            isTable={Boolean(c.is_table)}
            text={String(c.text)}
            meta={`#${c.chunk_index} · ${c.char_length} chars`}
          />
        ))}
        {filtered.length > 80 ? (
          <p className="text-xs text-slate-500">Showing first 80 matches. Narrow the filter to browse more.</p>
        ) : null}
      </div>
    </div>
  );
}

type Timings = {
  query_embedding_ms?: number | null;
  vector_search_ms?: number | null;
  vector_connect_ms?: number | null;
  vector_query_ms?: number | null;
  keyword_ms?: number | null;
  rerank_ms?: number | null;
  llm_ms?: number | null;
};

const STAGES: { key: keyof Timings; label: string; color: string }[] = [
  { key: "query_embedding_ms", label: "Query embedding", color: "bg-sky-400" },
  { key: "vector_search_ms", label: "Vector search", color: "bg-teal-600" },
  { key: "keyword_ms", label: "Keyword search", color: "bg-amber-600" },
  { key: "rerank_ms", label: "Reranking", color: "bg-violet-400" },
  { key: "llm_ms", label: "LLM answer", color: "bg-amber-400" },
];

function LatencyBreakdown({ timings }: { timings: Timings }) {
  const note = regionNote(useDiagnostics());
  const total = STAGES.reduce((sum, s) => sum + (timings[s.key] || 0), 0) || 1;
  return (
    <div className="space-y-2">
      <Label>Latency breakdown</Label>
      <div className="flex h-2.5 overflow-hidden rounded-full bg-slate-200">
        {STAGES.map((s) =>
          timings[s.key] ? (
            <div
              key={s.key}
              className={s.color}
              style={{ width: `${((timings[s.key] || 0) / total) * 100}%` }}
              title={`${s.label}: ${Math.round(timings[s.key] || 0)} ms`}
            />
          ) : null
        )}
      </div>
      <dl className="space-y-1">
        {STAGES.map((s) => {
          const v = timings[s.key];
          return (
            <div key={s.key}>
              <div className="grid grid-cols-[12px_140px_1fr] items-center gap-2 text-xs">
                <span className={`h-2 w-2 rounded-full ${v != null ? s.color : "bg-slate-200"}`} />
                <dt className="text-slate-500">{s.label}</dt>
                <dd className="font-mono text-slate-700">
                  {v != null ? `${v.toFixed(0)} ms · ${Math.round((v / total) * 100)}%` : "not enabled"}
                </dd>
              </div>
              {s.key === "vector_search_ms" && timings.vector_connect_ms != null ? (
                <div className="ml-[22px] mt-0.5 space-y-0.5 font-mono text-[11px] text-slate-400">
                  <div>↳ get index handle {timings.vector_connect_ms.toFixed(0)} ms</div>
                  <div>↳ query round trip {(timings.vector_query_ms ?? 0).toFixed(0)} ms</div>
                  {note ? <div className="font-sans text-slate-400">{note}</div> : null}
                </div>
              ) : null}
            </div>
          );
        })}
        <div className="grid grid-cols-[12px_140px_1fr] gap-2 border-t border-slate-100 pt-1 text-xs">
          <span />
          <dt className="text-slate-500">Sum of stages</dt>
          <dd className="font-mono text-ink">{total.toFixed(0)} ms</dd>
        </div>
      </dl>
    </div>
  );
}

function SearchDetail({ data }: { data: Record<string, unknown> }) {
  const scores = (data.raw_scores as Array<Record<string, unknown>>) || [];
  const timings = data.timings as Timings | undefined;
  return (
    <div className="space-y-3">
      <KV
        rows={[
          ["Index", String(data.index_name)],
          ["Namespace", String(data.namespace)],
          ["top_k", String(data.top_k)],
          ["Latency", `${data.latency_ms ?? "—"} ms`],
        ]}
      />
      {timings ? (
        <LatencyBreakdown timings={timings} />
      ) : (
        <p className="text-xs text-slate-400">
          Per-stage timings are recorded for queries run after the latency breakdown was added.
        </p>
      )}
      <Label>Raw similarity scores</Label>
      <div className="space-y-1">
        {scores.map((s, i) => (
          <div key={String(s.id)} className="flex items-center gap-2 font-mono text-[11px]">
            <span className="w-5 text-slate-500">{i + 1}</span>
            <div className="h-1.5 flex-1 overflow-hidden rounded bg-slate-200">
              <div
                className="h-full bg-accent"
                style={{ width: `${Math.min(100, Number(s.score) * 100)}%` }}
              />
            </div>
            <span className="w-16 text-right text-accent">{Number(s.score).toFixed(4)}</span>
            <span className="w-10 text-slate-500">p.{String(s.page_number)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function RetrievedDetail({ data }: { data: Record<string, unknown> }) {
  const { settings } = useApp();
  const [showRest, setShowRest] = useState(false);
  const chunks = (data.chunks as RetrievedChunk[]) || [];
  const threshold = settings?.show_threshold ? settings.similarity_threshold : 0;
  // Traces from before Phase 3 have no sent_to_llm flag: everything was sent.
  const legacy = chunks.every((c) => c.sent_to_llm === undefined);
  const sent = legacy ? chunks : chunks.filter((c) => c.sent_to_llm);
  const rest = legacy ? [] : chunks.filter((c) => !c.sent_to_llm);
  const reranked = Boolean(data.reranked);
  return (
    <div className="space-y-2">
      <p className="text-xs text-slate-400">
        {legacy
          ? "Click a card to jump to that page in the Reader."
          : `${sent.length} of ${chunks.length} candidates sent to the LLM, ${
              reranked ? "chosen by the reranker" : "in vector-similarity order (reranker off)"
            }. Click a card to jump to its page.`}
        {settings?.show_threshold ? ` Chunks below ${threshold.toFixed(2)} similarity are greyed out.` : ""}
      </p>
      {sent.map((c) => (
        <ChunkResult key={c.id} c={c} threshold={threshold} />
      ))}
      {rest.length ? (
        <div className="pt-2">
          <button
            onClick={() => setShowRest((v) => !v)}
            className="text-[11px] font-medium text-accent hover:underline"
          >
            {showRest ? "Hide" : "Show"} the other {rest.length} candidates (not sent to the LLM)
          </button>
          {showRest ? (
            <div className="mt-2 space-y-2 opacity-70">
              {rest.map((c) => (
                <ChunkResult key={c.id} c={c} threshold={threshold} compact />
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function Movement({ from, to }: { from?: number; to: number }) {
  if (from == null) return <span className="font-mono text-ink">#{to}</span>;
  const cls = to < from ? "bg-emerald-50 text-emerald-700" : to > from ? "bg-red-50 text-red-700" : "bg-slate-100 text-slate-500";
  return (
    <span className={`rounded-full px-1.5 py-0.5 font-mono text-[10px] ${cls}`} title="Rank before reranking (vector or hybrid order) → final rank">
      #{from} → #{to}
    </span>
  );
}

const FOUND_BY: Record<string, string> = {
  both: "bg-teal-50 text-teal-800 border-teal-200",
  semantic: "bg-sky-50 text-sky-800 border-sky-200",
  keyword: "bg-amber-50 text-amber-800 border-amber-200",
};

function FoundBy({ by }: { by: string }) {
  const title =
    by === "both"
      ? "Found by both semantic (vector) and keyword (BM25) search"
      : by === "keyword"
        ? "Found only by keyword (BM25) search"
        : "Found only by semantic (vector) search";
  return (
    <span className={`shrink-0 rounded-full border px-1.5 py-0.5 text-[10px] ${FOUND_BY[by] || ""}`} title={title}>
      {by}
    </span>
  );
}

function KeywordDetail({ data }: { data: Record<string, unknown> }) {
  const hits = (data.hits as Array<{ id: string; bm25: number; page_number: number; matched_terms: string[] }>) || [];
  const counts = (data.fused_counts as Record<string, number>) || {};
  const max = Math.max(1e-9, ...hits.map((h) => h.bm25));
  return (
    <div className="space-y-3">
      <KV
        rows={[
          ["Query terms", ((data.query_terms as string[]) || []).join(", ") || "—"],
          ["Keyword weight", String(data.keyword_weight)],
          ["Merged pool", `${counts.both ?? 0} both · ${counts.semantic ?? 0} semantic only · ${counts.keyword ?? 0} keyword only`],
          ["Latency", `${data.latency_ms ?? "—"} ms (local BM25)`],
        ]}
      />
      <Label>Top keyword hits (BM25)</Label>
      <div className="space-y-1">
        {hits.map((h, i) => (
          <div key={h.id} className="flex items-center gap-2 font-mono text-[11px]">
            <span className="w-5 text-slate-500">{i + 1}</span>
            <div className="h-1.5 flex-1 overflow-hidden rounded bg-slate-200">
              <div className="h-full bg-amber-400" style={{ width: `${(h.bm25 / max) * 100}%` }} />
            </div>
            <span className="w-12 text-right text-slate-600">{h.bm25.toFixed(2)}</span>
            <span className="w-12 text-slate-500">p.{h.page_number}</span>
            <span className="w-40 truncate text-slate-400">{h.matched_terms.join(", ")}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ScoreBar({ label, value, color }: { label: string; value: number | null | undefined; color: string }) {
  return (
    <div className="grid grid-cols-[62px_1fr_46px] items-center gap-2 font-mono text-[10px]">
      <span className="text-slate-400">{label}</span>
      <div className="h-1.5 overflow-hidden rounded bg-slate-200">
        {value != null ? <div className={`h-full ${color}`} style={{ width: `${Math.min(100, value * 100)}%` }} /> : null}
      </div>
      <span className="text-right text-slate-600">{value != null ? value.toFixed(label === "rerank" ? 2 : 4) : "—"}</span>
    </div>
  );
}

function ChunkResult({ c, threshold, compact }: { c: RetrievedChunk; threshold: number; compact?: boolean }) {
  const { jumpTo, settings } = useApp();
  const dim = settings?.show_threshold && c.score != null && c.score < threshold;
  return (
    <button
      onClick={() => jumpTo({ page: Number(c.page_number), excerpt: c.text.slice(0, 80) })}
      className={`w-full rounded-xl border p-3 text-left ${
        dim ? "border-slate-200 bg-slate-50 opacity-40" : "border-slate-200 bg-white hover:border-accent"
      }`}
    >
      <div className="mb-1.5 flex items-center justify-between gap-2 text-[11px]">
        <span className="flex min-w-0 items-center gap-2">
          <Movement from={c.vector_rank} to={c.rank} />
          {c.found_by ? <FoundBy by={c.found_by} /> : null}
          <span className="truncate font-medium text-ink">
            p.{c.page_number}
            {c.is_table ? " · table" : ""}
            {c.heading ? ` · ${c.heading}` : ""}
          </span>
        </span>
        {c.sent_to_llm ? (
          <span className="shrink-0 rounded-full bg-teal-50 px-1.5 py-0.5 text-[10px] text-teal-800">sent to LLM</span>
        ) : null}
      </div>
      <div className="mb-2 space-y-1">
        <ScoreBar label="similarity" value={c.score} color="bg-accent" />
        {c.rerank_score !== undefined ? <ScoreBar label="rerank" value={c.rerank_score} color="bg-violet-400" /> : null}
        {c.merged_count && c.merged_count > 1 ? (
          <div className="font-mono text-[10px] text-slate-400">
            merged {c.merged_count} chunks from this page ({(c.merged_chunk_indices || []).map((i) => `#${i}`).join(", ")})
          </div>
        ) : null}
        {c.pre_diversity_rank != null && c.pre_diversity_rank !== c.rank ? (
          <div className="font-mono text-[10px] text-slate-400">
            diversity moved this from result #{c.pre_diversity_rank}
            {c.redundancy ? ` · overlap with earlier results ${Math.round(c.redundancy * 100)}%` : ""}
          </div>
        ) : null}
        {c.bm25 != null ? (
          <div className="font-mono text-[10px] text-slate-400">
            BM25 {c.bm25.toFixed(2)} · keyword #{c.keyword_rank}
            {c.matched_terms?.length ? ` · matched: ${c.matched_terms.join(", ")}` : ""}
          </div>
        ) : null}
      </div>
      <p className={`${compact ? "line-clamp-2" : "line-clamp-6"} whitespace-pre-wrap text-xs leading-5 text-slate-600`}>
        {c.text}
      </p>
    </button>
  );
}

function MergeDetail({ data }: { data: Record<string, unknown> }) {
  const merged = (data.merged_pages as Array<{ page_number: number; chunks: number; chunk_indices: number[] }>) || [];
  const finals =
    (data.final_pages as Array<{ page_number: number; result_rank: number; pre_diversity_rank: number | null; redundancy: number | null }>) || [];
  return (
    <div className="space-y-3">
      <KV
        rows={[
          ["Chunks in", String(data.chunks_in)],
          ["Page results out", String(data.results_out)],
          ["Repeated-page slots freed", `${data.repeated_page_slots_before} (in the top slots before merging)`],
          ["Diversity", data.diversity_enabled ? "on" : "off"],
        ]}
      />
      {merged.length ? (
        <>
          <Label>Pages merged from several chunks</Label>
          <div className="space-y-1 font-mono text-[11px] text-slate-600">
            {merged.map((m) => (
              <div key={m.page_number}>
                p.{m.page_number}: {m.chunks} chunks ({m.chunk_indices.map((i) => `#${i}`).join(", ")})
              </div>
            ))}
          </div>
        </>
      ) : null}
      <Label>Final page order</Label>
      <div className="space-y-1">
        {finals.map((f) => (
          <div key={f.result_rank} className="flex items-center gap-2 font-mono text-[11px]">
            {data.diversity_enabled && f.pre_diversity_rank != null ? (
              <Movement from={f.pre_diversity_rank} to={f.result_rank} />
            ) : (
              <span className="text-ink">#{f.result_rank}</span>
            )}
            <span className="w-12 text-slate-500">p.{f.page_number}</span>
            {f.redundancy != null ? (
              <span className="text-slate-400">overlap with earlier {Math.round(f.redundancy * 100)}%</span>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

function RerankDetail({ data }: { data: Record<string, unknown> }) {
  const moves = (data.moves as Array<{ page_number: number; vector_rank: number; final_rank: number; rerank_score: number | null }>) || [];
  const finalK = Number(data.final_k || 0);
  return (
    <div className="space-y-3">
      <KV
        rows={[
          ["Model", String(data.model ?? "—")],
          ["Candidates scored", String(data.candidates)],
          ["Sent to LLM", String(finalK)],
          ["Tokens", `${data.tokens_in ?? 0} in · ${data.tokens_out ?? 0} out`],
          ["Cost", data.cost_usd != null ? `$${Number(data.cost_usd).toFixed(6)}` : "—"],
          ["Latency", `${data.latency_ms ?? "—"} ms`],
        ]}
      />
      {data.fallback ? <p className="text-xs text-amber-700">{String(data.fallback)}</p> : null}
      <Label>How the order changed</Label>
      <div className="space-y-1">
        {moves.map((m) => (
          <div key={`${m.vector_rank}-${m.final_rank}`} className={`flex items-center gap-2 font-mono text-[11px] ${m.final_rank > finalK ? "opacity-50" : ""}`}>
            <Movement from={m.vector_rank} to={m.final_rank} />
            <span className="w-12 text-slate-500">p.{m.page_number}</span>
            <div className="h-1.5 flex-1 overflow-hidden rounded bg-slate-200">
              <div className="h-full bg-violet-400" style={{ width: `${(m.rerank_score ?? 0) * 100}%` }} />
            </div>
            <span className="w-10 text-right text-slate-600">{m.rerank_score != null ? m.rerank_score.toFixed(2) : "—"}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function PromptDetail({ data }: { data: Record<string, unknown> }) {
  const [copied, setCopied] = useState(false);
  const prompt = String(data.final_prompt || "");
  return (
    <div className="space-y-3">
      <KV
        rows={[
          ["Total tokens", String(data.total_tokens)],
          ["Chunks included", ((data.included_chunk_indices as number[]) || []).join(", ")],
          [
            "Dropped below threshold",
            ((data.excluded_below_threshold as number[]) || []).join(", ") || "none",
          ],
        ]}
      />
      <div className="flex items-center justify-between">
        <Label>Exact prompt sent to the LLM</Label>
        <button
          className="text-[11px] text-accent"
          onClick={async () => {
            await navigator.clipboard.writeText(prompt);
            setCopied(true);
            setTimeout(() => setCopied(false), 1200);
          }}
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="wrap max-h-[480px] overflow-auto rounded-xl bg-slate-50 p-3 font-mono text-[11px] leading-5 text-slate-700">
        {prompt}
      </pre>
    </div>
  );
}

function AnswerDetail({ data }: { data: Record<string, unknown> }) {
  const cited = (data.cited_chunk_indices as number[]) || [];
  const ignored = (data.ignored_chunk_indices as number[]) || [];
  return (
    <div className="space-y-3">
      <Label>Answer</Label>
      <p className="whitespace-pre-wrap rounded-xl bg-slate-50 p-3 leading-6 text-ink">
        {String(data.answer || "")}
      </p>
      <KV
        rows={[
          ["Cited pages", ((data.cited_pages as number[]) || []).map((p) => `p.${p}`).join(", ") || "none"],
          ["Cited chunks", cited.join(", ") || "none"],
          ["Retrieved but ignored", ignored.join(", ") || "none"],
        ]}
      />
    </div>
  );
}

function ChunkCard({
  page,
  heading,
  isTable,
  text,
  meta,
}: {
  page: number;
  heading?: string;
  isTable?: boolean;
  text: string;
  meta: string;
}) {
  const { jumpTo } = useApp();
  return (
    <button
      onClick={() => jumpTo({ page, excerpt: text.slice(0, 80) })}
      className="w-full rounded-xl border border-slate-200 bg-white p-3 text-left hover:border-accent"
    >
      <div className="mb-1 flex justify-between text-[11px] text-slate-400">
        <span>
          p.{page}
          {isTable ? " · table" : ""}
          {heading ? ` · ${heading}` : ""}
        </span>
        <span className="font-mono">{meta}</span>
      </div>
      <p className="line-clamp-5 whitespace-pre-wrap text-xs leading-5 text-slate-600">{text}</p>
    </button>
  );
}

function KV({ rows }: { rows: [string, string][] }) {
  return (
    <dl className="mb-3 space-y-1.5">
      {rows.map(([k, v]) => (
        <div key={k} className="grid grid-cols-[140px_1fr] gap-2 text-xs">
          <dt className="text-slate-500">{k}</dt>
          <dd className="break-all font-mono text-slate-700">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
      {children}
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const cls =
    status === "error"
      ? "bg-red-50 text-red-700"
      : status === "slow"
        ? "bg-amber-50 text-amber-800"
        : "bg-emerald-50 text-emerald-700";
  return <span className={`rounded-full px-2 py-0.5 text-[10px] uppercase ${cls}`}>{status}</span>;
}
