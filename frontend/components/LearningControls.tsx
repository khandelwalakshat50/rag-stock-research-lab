import { useEffect, useState } from "react";
import { useApp } from "./AppProvider";

export default function LearningControls() {
  const { settings, patchSettings, rerun, reingest, asking, ingesting, selectedTrace } = useApp();
  const [prompt, setPrompt] = useState(settings?.system_prompt || "");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (settings?.system_prompt) setPrompt(settings.system_prompt);
  }, [settings?.system_prompt]);

  if (!settings) return null;

  async function persistPrompt() {
    await patchSettings({ system_prompt: prompt });
    setSaved(true);
    setTimeout(() => setSaved(false), 1200);
  }

  return (
    <div className="h-full overflow-auto scroll-thin">
    <div className="space-y-4 p-4 text-sm text-ink">
      <div>
        <div className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
          Learning controls
        </div>
        <p className="mt-1 text-xs leading-5 text-slate-500">
          Change retrieval knobs, then re-run the last question. Chunk size and overlap require a
          re-ingest because they rewrite the vector index.
        </p>
      </div>

      <Slider
        label="Chunk size"
        value={settings.chunk_size}
        min={200}
        max={3000}
        step={50}
        suffix=" chars"
        onChange={(chunk_size) => patchSettings({ chunk_size })}
      />
      <Slider
        label="Chunk overlap"
        value={settings.chunk_overlap}
        min={0}
        max={800}
        step={20}
        suffix=" chars"
        onChange={(chunk_overlap) => patchSettings({ chunk_overlap })}
      />
      <Slider
        label="Candidate pool"
        value={settings.candidate_pool}
        min={10}
        max={100}
        step={5}
        suffix=" chunks"
        onChange={(candidate_pool) => patchSettings({ candidate_pool })}
      />
      <Slider
        label="Final chunks sent to LLM"
        value={settings.final_k}
        min={1}
        max={15}
        step={1}
        onChange={(final_k) => patchSettings({ final_k })}
      />
      <div>
        <Slider
          label="Keyword vs semantic weight"
          value={settings.keyword_weight}
          min={0}
          max={1}
          step={0.05}
          onChange={(keyword_weight) => patchSettings({ keyword_weight })}
        />
        <div className="mt-0.5 flex justify-between text-[10px] text-slate-400">
          <span>0 = pure semantic</span>
          <span>1 = pure keyword</span>
        </div>
      </div>
      <label className="flex items-center justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs">
        <span>
          Reranker
          <span className="mt-0.5 block text-slate-500">
            A small LLM re-scores every candidate against the question, then the best go to the
            answer model. Off = plain vector-similarity order.
          </span>
        </span>
        <input
          type="checkbox"
          checked={settings.reranker_enabled}
          onChange={(e) => patchSettings({ reranker_enabled: e.target.checked })}
        />
      </label>
      <label className="flex items-center justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs">
        <span>
          Diversity
          <span className="mt-0.5 block text-slate-500">
            Chunks from the same page are always merged into one result. Diversity also moves
            down results that mostly repeat one already picked (e.g. the consolidated copy of a
            standalone note), so other pages get the slots.
          </span>
        </span>
        <input
          type="checkbox"
          checked={settings.diversity_enabled}
          onChange={(e) => patchSettings({ diversity_enabled: e.target.checked })}
        />
      </label>
      <Slider
        label="LLM temperature"
        value={settings.temperature}
        min={0}
        max={1}
        step={0.05}
        onChange={(temperature) => patchSettings({ temperature })}
      />

      <label className="flex items-center justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-xs">
        <span>
          Show similarity threshold
          <span className="mt-0.5 block text-slate-500">
            Grey out retrieved chunks below the cutoff. Re-runs also drop them from the prompt.
          </span>
        </span>
        <input
          type="checkbox"
          checked={settings.show_threshold}
          onChange={(e) => patchSettings({ show_threshold: e.target.checked })}
        />
      </label>
      {settings.show_threshold ? (
        <Slider
          label="Score threshold"
          value={settings.similarity_threshold}
          min={0}
          max={1}
          step={0.01}
          onChange={(similarity_threshold) => patchSettings({ similarity_threshold })}
        />
      ) : null}

      <div>
        <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
          System prompt
        </div>
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={7}
          className="w-full rounded-xl border border-slate-200 bg-white p-2 font-mono text-[11px] leading-5 outline-none"
        />
        <button
          onClick={persistPrompt}
          className="mt-2 rounded-full border border-slate-200 px-3 py-1 text-xs hover:border-accent"
        >
          {saved ? "Saved" : "Save prompt"}
        </button>
      </div>

      <div className="flex flex-col gap-2">
        <button
          disabled={asking || !selectedTrace}
          onClick={() => rerun(selectedTrace?.type === "query" ? selectedTrace.id : undefined)}
          className="rounded-full bg-teal-600 px-3 py-2 text-xs font-medium text-white disabled:opacity-40"
        >
          {asking ? "Re-running…" : "Re-run query with these settings"}
        </button>
        <button
          disabled={ingesting}
          onClick={() => reingest()}
          className="rounded-full border border-slate-200 px-3 py-2 text-xs hover:border-accent disabled:opacity-40"
        >
          {ingesting ? "Re-ingesting…" : "Re-ingest document (new chunks)"}
        </button>
      </div>
    </div>
    </div>
  );
}

function Slider({
  label,
  value,
  min,
  max,
  step,
  suffix,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  suffix?: string;
  onChange: (n: number) => void;
}) {
  return (
    <label className="block">
      <div className="mb-1 flex justify-between text-xs">
        <span className="text-slate-400">{label}</span>
        <span className="font-mono text-accent">
          {typeof value === "number" && step < 1 ? value.toFixed(2) : value}
          {suffix || ""}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full"
      />
    </label>
  );
}
