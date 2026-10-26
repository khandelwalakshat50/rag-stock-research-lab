import { useEffect, useMemo, useRef, useState } from "react";
import { useApp } from "./AppProvider";
import LearningControls from "./LearningControls";
import NodeDetailPanel from "./NodeDetailPanel";
import TraceSidebar from "./TraceSidebar";
import PipelineGraph from "./PipelineGraph";

const MIN_BOTTOM = 140;
const DEFAULT_BOTTOM = 256;

export default function InspectorTab() {
  const { selectedTrace, traces, selectTrace } = useApp();
  const [nodeId, setNodeId] = useState<string | null>(null);
  const [rightTab, setRightTab] = useState<"node" | "controls">("node");
  const [bottomH, setBottomH] = useState(DEFAULT_BOTTOM);
  const wrapRef = useRef<HTMLDivElement>(null);
  const bottomHRef = useRef(bottomH);
  const listenersRef = useRef<{
    move: (e: MouseEvent | PointerEvent) => void;
    up: () => void;
  } | null>(null);
  bottomHRef.current = bottomH;

  useEffect(() => {
    setNodeId(null);
  }, [selectedTrace?.id]);

  useEffect(() => {
    try {
      const stored = Number(localStorage.getItem("rag-inspector-bottom-h"));
      if (stored >= MIN_BOTTOM) setBottomH(stored);
    } catch {
      /* ignore */
    }
    return () => {
      const listeners = listenersRef.current;
      if (!listeners) return;
      document.removeEventListener("pointermove", listeners.move);
      document.removeEventListener("pointerup", listeners.up);
      document.removeEventListener("mousemove", listeners.move);
      document.removeEventListener("mouseup", listeners.up);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
  }, []);

  const selectedNode = useMemo(
    () => selectedTrace?.nodes.find((n) => n.id === nodeId) || null,
    [nodeId, selectedTrace]
  );

  const sibling = useMemo(() => {
    if (!selectedTrace?.parent_trace_id) return null;
    return traces.find((t) => t.id === selectedTrace.parent_trace_id) || null;
  }, [selectedTrace, traces]);

  function startDrag(e: React.PointerEvent | React.MouseEvent) {
    e.preventDefault();
    const startY = e.clientY;
    const startH = bottomHRef.current;
    document.body.style.cursor = "row-resize";
    document.body.style.userSelect = "none";

    const move = (ev: MouseEvent | PointerEvent) => {
      const wrap = wrapRef.current;
      if (!wrap) return;
      const next = Math.min(
        Math.max(startH + (startY - ev.clientY), MIN_BOTTOM),
        Math.floor(wrap.clientHeight * 0.75)
      );
      bottomHRef.current = next;
      setBottomH(next);
    };
    const up = () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", up);
      listenersRef.current = null;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      try {
        localStorage.setItem("rag-inspector-bottom-h", String(bottomHRef.current));
      } catch {
        /* ignore */
      }
    };
    listenersRef.current = { move, up };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up);
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up);
  }

  return (
    <div className="flex h-full min-h-0 overflow-hidden bg-paper text-ink">
      <div className="w-60 shrink-0 overflow-hidden border-r border-slate-200">
        <TraceSidebar />
      </div>
      <div ref={wrapRef} className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3">
            <div>
              <div className="text-sm font-semibold">
                {selectedTrace
                  ? selectedTrace.type === "ingestion"
                    ? "Ingestion graph"
                    : selectedTrace.query_text
                  : "Select a run"}
              </div>
              {selectedTrace ? (
                <div className="mt-1 font-mono text-[11px] text-slate-500">
                  End-to-end {fmtMs(selectedTrace.total_latency_ms)} · total cost{" "}
                  ${Number(selectedTrace.total_cost_usd || 0).toFixed(4)} · {selectedTrace.status}
                  {runSettingsLabel(selectedTrace.settings)}
                </div>
              ) : (
                <div className="mt-1 text-xs text-slate-500">
                  Ingestion and every question become a node graph you can inspect.
                </div>
              )}
            </div>
            {sibling ? (
              <button
                onClick={() => selectTrace(sibling.id)}
                className="rounded-full border border-slate-200 bg-white px-3 py-1 text-[11px] text-slate-600 hover:border-accent"
              >
                Compare vs original ({fmtMs(sibling.total_latency_ms)}, ${sibling.total_cost_usd.toFixed(4)})
              </button>
            ) : null}
          </div>
          <div className="relative min-h-0 flex-1">
            {selectedTrace ? (
              <PipelineGraph
                key={selectedTrace.id}
                nodes={selectedTrace.nodes}
                selectedId={nodeId}
                onSelect={(id) => {
                  setNodeId(id || null);
                  if (id) setRightTab("node");
                }}
              />
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-slate-500">
                Upload a report or pick a run from the left.
              </div>
            )}
          </div>
        </div>

        <div
          role="separator"
          aria-orientation="horizontal"
          aria-label="Resize details panel"
          onPointerDown={startDrag}
          onMouseDown={startDrag}
          className="group flex h-3 w-full shrink-0 cursor-row-resize items-center justify-center border-y border-slate-200 bg-slate-50 hover:bg-slate-100"
        >
          <span className="h-1 w-10 rounded-full bg-slate-300 group-hover:bg-slate-400" />
        </div>

        <div
          className="flex shrink-0 flex-col overflow-hidden bg-white"
          style={{ height: bottomH }}
        >
          <div className="flex border-b border-slate-200 text-xs">
            <button
              className={`flex-1 py-2.5 ${
                rightTab === "node"
                  ? "bg-slate-50 font-medium text-ink"
                  : "text-slate-500 hover:text-ink"
              }`}
              onClick={() => setRightTab("node")}
            >
              Node detail
            </button>
            <button
              className={`flex-1 py-2.5 ${
                rightTab === "controls"
                  ? "bg-slate-50 font-medium text-ink"
                  : "text-slate-500 hover:text-ink"
              }`}
              onClick={() => setRightTab("controls")}
            >
              Controls
            </button>
          </div>
          <div className="min-h-0 flex-1 overflow-hidden">
            {rightTab === "node" ? <NodeDetailPanel node={selectedNode} /> : <LearningControls />}
          </div>
        </div>
      </div>
    </div>
  );
}

function fmtMs(ms: number) {
  if (!ms) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(2)}s` : `${Math.round(ms)}ms`;
}

function runSettingsLabel(s?: Record<string, unknown>) {
  if (!s) return "";
  if (s.candidate_pool != null) {
    return ` · pool=${String(s.candidate_pool)} → ${String(s.final_k)} to LLM · reranker ${s.reranker_enabled ? "on" : "off"}`;
  }
  return s.top_k != null ? ` · top_k=${String(s.top_k)}` : "";
}
