import { useMemo } from "react";
import {
  Background,
  Controls,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { PipelineNode } from "@/lib/types";
import PipelineNodeCard from "./PipelineNode";

const nodeTypes = { pipeline: PipelineNodeCard };

type Props = {
  nodes: PipelineNode[];
  selectedId: string | null;
  onSelect: (id: string) => void;
};

export default function PipelineGraph({ nodes, selectedId, onSelect }: Props) {
  const flowNodes: Node[] = useMemo(
    () =>
      nodes.map((n, i) => ({
        id: n.id,
        type: "pipeline",
        position: { x: i * 260, y: 24 },
        data: n,
        selected: n.id === selectedId,
      })),
    [nodes, selectedId]
  );

  const edges: Edge[] = useMemo(
    () =>
      nodes.slice(1).map((n, i) => ({
        id: `e-${nodes[i].id}-${n.id}`,
        source: nodes[i].id,
        target: n.id,
        label: n.latency_ms ? `${n.latency_ms.toFixed(0)} ms` : undefined,
        labelStyle: { fill: "#64748b", fontSize: 11, fontFamily: "IBM Plex Mono, monospace" },
        labelBgStyle: { fill: "#f6f3ee" },
        labelBgPadding: [4, 6] as [number, number],
        style: {
          stroke:
            n.status === "error" ? "#ef4444" : n.status === "slow" ? "#d97706" : "#94a3b8",
          strokeWidth: 1.6,
        },
        animated: n.status === "slow",
      })),
    [nodes]
  );

  const zoom = Math.min(0.85, Math.max(0.22, 520 / Math.max(nodes.length * 260, 1)));

  return (
    <div className="h-full w-full overflow-hidden rf-canvas">
      <ReactFlow
        nodes={flowNodes}
        edges={edges}
        nodeTypes={nodeTypes}
        defaultViewport={{ x: 16, y: 72, zoom }}
        nodesDraggable={false}
        onNodeClick={(_, node) => onSelect(node.id)}
        onPaneClick={() => onSelect("")}
        minZoom={0.15}
        maxZoom={1.6}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#d6d3cd" gap={18} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
