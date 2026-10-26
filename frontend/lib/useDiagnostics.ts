import { useEffect, useState } from "react";
import { API_BASE } from "./api";

export type Diagnostics = {
  pinecone: {
    warmed_up?: boolean;
    cloud?: string | null;
    region?: string | null;
    network_rtt_ms?: number | null;
    floor_query_ms?: number;
    region_far?: boolean;
    warm_query_ms?: number;
  };
};

let cached: Diagnostics | null = null;

export function useDiagnostics(): Diagnostics | null {
  const [diag, setDiag] = useState<Diagnostics | null>(cached);
  useEffect(() => {
    if (cached?.pinecone.warmed_up) return;
    fetch(`${API_BASE}/api/diagnostics`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d: Diagnostics | null) => {
        if (d) {
          cached = d;
          setDiag(d);
        }
      })
      .catch(() => undefined);
  }, []);
  return diag;
}

export function regionNote(d: Diagnostics | null): string | null {
  const p = d?.pinecone;
  if (!p?.network_rtt_ms) return null;
  const where = `${p.cloud}/${p.region}`;
  return p.region_far
    ? `Index is in ${where}, ${Math.round(p.network_rtt_ms)} ms network round trip from this machine. That sets a floor of ≈${p.floor_query_ms} ms per vector search.`
    : `Index is in ${where}, ${Math.round(p.network_rtt_ms)} ms round trip from this machine.`;
}
