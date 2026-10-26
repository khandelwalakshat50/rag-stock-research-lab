import type {
  AppSettings,
  ChatMessage,
  DocumentInfo,
  EvalProgress,
  EvalQuestion,
  EvalRun,
  EvalRunDetail,
  Health,
  ProgressEvent,
  TraceDetail,
  TraceSummary,
} from "./types";

export const API_BASE = String(import.meta.env.VITE_API_URL || "").replace(/\/$/, "");

async function parseError(res: Response): Promise<string> {
  try {
    const data = await res.json();
    if (typeof data.detail === "string") return data.detail;
    return JSON.stringify(data.detail || data);
  } catch {
    return res.statusText;
  }
}

export async function getHealth(): Promise<Health> {
  const res = await fetch(`${API_BASE}/api/health`);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function listDocuments(): Promise<DocumentInfo[]> {
  const res = await fetch(`${API_BASE}/api/documents`);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function getDocument(id: string): Promise<DocumentInfo> {
  const res = await fetch(`${API_BASE}/api/documents/${id}`);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export function documentFileUrl(id: string): string {
  return `${API_BASE}/api/documents/${id}/file`;
}

export async function listMessages(documentId: string): Promise<ChatMessage[]> {
  const res = await fetch(`${API_BASE}/api/documents/${documentId}/messages`);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function listTraces(documentId?: string): Promise<TraceSummary[]> {
  const url = documentId
    ? `${API_BASE}/api/traces?document_id=${encodeURIComponent(documentId)}`
    : `${API_BASE}/api/traces`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function getTrace(id: string): Promise<TraceDetail> {
  const res = await fetch(`${API_BASE}/api/traces/${id}`);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function getSettings(): Promise<AppSettings> {
  const res = await fetch(`${API_BASE}/api/settings`);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function updateSettings(
  patch: Partial<AppSettings>
): Promise<AppSettings> {
  const res = await fetch(`${API_BASE}/api/settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function askQuestion(body: {
  document_id: string;
  question: string;
  candidate_pool?: number;
  final_k?: number;
  reranker_enabled?: boolean;
  keyword_weight?: number;
  diversity_enabled?: boolean;
  similarity_threshold?: number;
  system_prompt?: string;
  temperature?: number;
  parent_trace_id?: string;
}): Promise<{
  trace_id: string;
  answer: string;
  citations: ChatMessage["citations"];
  total_latency_ms: number;
  total_cost_usd: number;
  status: string;
  trace: TraceDetail;
}> {
  const res = await fetch(`${API_BASE}/api/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

async function readSse<T = ProgressEvent>(
  res: Response,
  onEvent: (event: T) => void
): Promise<T | null> {
  if (!res.body) throw new Error("No response body");
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let last: T | null = null;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";
    for (const part of parts) {
      const line = part.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;
      const event = JSON.parse(line.slice(6)) as T;
      last = event;
      onEvent(event);
    }
  }
  return last;
}

export async function uploadPdf(
  file: File,
  onEvent: (event: ProgressEvent) => void
): Promise<ProgressEvent | null> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/api/documents/upload`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(await parseError(res));
  return readSse(res, onEvent);
}

export async function reingestDocument(
  documentId: string,
  onEvent: (event: ProgressEvent) => void
): Promise<ProgressEvent | null> {
  const res = await fetch(`${API_BASE}/api/documents/${documentId}/reingest`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(await parseError(res));
  return readSse(res, onEvent);
}

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function listEvalQuestions(documentId: string): Promise<EvalQuestion[]> {
  return jsonOrThrow(
    await fetch(`${API_BASE}/api/evals/questions?document_id=${encodeURIComponent(documentId)}`)
  );
}

export async function createEvalQuestion(body: {
  document_id: string;
  question: string;
  expected_pages: number[];
}): Promise<EvalQuestion> {
  return jsonOrThrow(
    await fetch(`${API_BASE}/api/evals/questions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  );
}

export async function updateEvalQuestion(
  id: string,
  patch: { question?: string; expected_pages?: number[] }
): Promise<EvalQuestion> {
  return jsonOrThrow(
    await fetch(`${API_BASE}/api/evals/questions/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    })
  );
}

export async function deleteEvalQuestion(id: string): Promise<void> {
  await jsonOrThrow(await fetch(`${API_BASE}/api/evals/questions/${id}`, { method: "DELETE" }));
}

export async function listEvalRuns(documentId: string): Promise<EvalRun[]> {
  return jsonOrThrow(
    await fetch(`${API_BASE}/api/evals/runs?document_id=${encodeURIComponent(documentId)}`)
  );
}

export async function getEvalRun(id: string): Promise<EvalRunDetail> {
  return jsonOrThrow(await fetch(`${API_BASE}/api/evals/runs/${id}`));
}

export async function deleteEvalRun(id: string): Promise<void> {
  await jsonOrThrow(await fetch(`${API_BASE}/api/evals/runs/${id}`, { method: "DELETE" }));
}

export async function runEval(
  documentId: string,
  label: string,
  onEvent: (event: EvalProgress) => void
): Promise<EvalProgress | null> {
  const res = await fetch(`${API_BASE}/api/evals/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ document_id: documentId, label }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return readSse<EvalProgress>(res, onEvent);
}

export function warmDocument(documentId: string): void {
  // Fire-and-forget: primes the Pinecone namespace so the first question is fast.
  fetch(`${API_BASE}/api/documents/${documentId}/warm`, { method: "POST" }).catch(() => undefined);
}
