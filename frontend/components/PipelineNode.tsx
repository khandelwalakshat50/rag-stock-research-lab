import { Handle, Position, type NodeProps } from "@xyflow/react";
import type { PipelineNode } from "@/lib/types";

const STATUS: Record<string, string> = {
  success: "bg-emerald-500",
  slow: "bg-amber-500",
  error: "bg-red-500",
};

const RING: Record<string, string> = {
  success: "border-emerald-200",
  slow: "border-amber-200",
  error: "border-red-200",
};

export default function PipelineNodeCard({ data, selected }: NodeProps) {
  const node = data as unknown as PipelineNode;
  return (
    <div
      className={`w-[240px] rounded-2xl border bg-white px-3.5 py-3 text-ink shadow-sm ${
        selected ? "border-accent ring-2 ring-teal-500/20" : RING[node.status] || "border-slate-200"
      }`}
    >
      <Handle type="target" position={Position.Left} className="!h-2 !w-2 !bg-slate-400" />
      <div className="flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full ${STATUS[node.status] || STATUS.success}`} />
        <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-500">
          {node.label}
        </span>
      </div>
      <div className="mt-2 text-sm font-medium leading-5 text-ink">
        {node.key_metric || node.summary}
      </div>
      <div className="mt-1 truncate text-[11px] text-slate-500">{node.summary}</div>
      <div className="mt-2 font-mono text-[11px] text-slate-400">
        {node.latency_ms ? `${node.latency_ms.toFixed(0)} ms` : "—"}
      </div>
      <Handle type="source" position={Position.Right} className="!h-2 !w-2 !bg-slate-400" />
    </div>
  );
}
