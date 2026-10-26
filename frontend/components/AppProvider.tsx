import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  askQuestion,
  getHealth,
  getSettings,
  getTrace,
  listDocuments,
  listMessages,
  listTraces,
  reingestDocument,
  updateSettings as saveSettings,
  uploadPdf,
  warmDocument,
} from "@/lib/api";
import type {
  AppSettings,
  ChatMessage,
  Citation,
  DocumentInfo,
  Health,
  ProgressEvent,
  TraceDetail,
  TraceSummary,
} from "@/lib/types";

export type TabId = "reader" | "inspector" | "eval";

type JumpTarget = {
  page: number;
  excerpt?: string;
};

type AppState = {
  tab: TabId;
  setTab: (tab: TabId) => void;
  health: Health | null;
  documents: DocumentInfo[];
  document: DocumentInfo | null;
  selectDocument: (id: string) => Promise<void>;
  messages: ChatMessage[];
  traces: TraceSummary[];
  selectedTrace: TraceDetail | null;
  selectedTraceId: string | null;
  selectTrace: (id: string) => Promise<void>;
  settings: AppSettings | null;
  patchSettings: (patch: Partial<AppSettings>) => Promise<void>;
  progress: ProgressEvent | null;
  ingesting: boolean;
  asking: boolean;
  error: string | null;
  setError: (msg: string | null) => void;
  page: number;
  setPage: (n: number) => void;
  highlight: string | null;
  jumpTo: (target: JumpTarget, switchToReader?: boolean) => void;
  upload: (file: File) => Promise<void>;
  ask: (question: string) => Promise<void>;
  rerun: (parentTraceId?: string, question?: string) => Promise<void>;
  reingest: () => Promise<void>;
  refresh: () => Promise<DocumentInfo[]>;
};

const Ctx = createContext<AppState | null>(null);

const DEFAULT_SETTINGS: AppSettings = {
  chunk_size: 1000,
  chunk_overlap: 200,
  top_k: 10,
  similarity_threshold: 0,
  show_threshold: false,
  system_prompt: "",
  temperature: 0.2,
  candidate_pool: 40,
  final_k: 5,
  reranker_enabled: true,
  keyword_weight: 0.5,
  diversity_enabled: false,
};

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [tab, setTab] = useState<TabId>("reader");
  const [health, setHealth] = useState<Health | null>(null);
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [document, setDocument] = useState<DocumentInfo | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [selectedTrace, setSelectedTrace] = useState<TraceDetail | null>(null);
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [progress, setProgress] = useState<ProgressEvent | null>(null);
  const [ingesting, setIngesting] = useState(false);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [highlight, setHighlight] = useState<string | null>(null);

  const loadTraces = useCallback(async (docId: string) => {
    const rows = await listTraces(docId);
    setTraces(rows);
    return rows;
  }, []);

  const selectTrace = useCallback(async (id: string) => {
    const detail = await getTrace(id);
    setSelectedTrace(detail);
    setSelectedTraceId(id);
  }, []);

  const selectDocument = useCallback(
    async (id: string) => {
      const [doc, msgs, rows] = await Promise.all([
        listDocuments().then((all) => all.find((d) => d.id === id) || null),
        listMessages(id),
        loadTraces(id),
      ]);
      if (!doc) return;
      if (doc.status === "success") warmDocument(doc.id);
      setDocument(doc);
      setMessages(msgs);
      setPage(1);
      setHighlight(null);
      const ingest = rows.find((t) => t.type === "ingestion");
      const first = ingest || rows[0];
      if (first) await selectTrace(first.id);
      else {
        setSelectedTrace(null);
        setSelectedTraceId(null);
      }
    },
    [loadTraces, selectTrace]
  );

  const refresh = useCallback(async () => {
    try {
      const [h, docs, s] = await Promise.all([
        getHealth(),
        listDocuments(),
        getSettings(),
      ]);
      setHealth(h);
      setDocuments(docs);
      setSettings(s);
      if (document) {
        const latest = docs.find((d) => d.id === document.id);
        if (latest) setDocument(latest);
        setMessages(await listMessages(document.id));
        await loadTraces(document.id);
      }
      return docs;
    } catch (err) {
      const msg =
        err instanceof TypeError && /fetch/i.test(err.message)
          ? "Cannot reach the API. Make sure the backend is running on port 8006."
          : err instanceof Error
            ? err.message
            : "Could not reach the API";
      setError(msg);
      return [];
    }
  }, [document, loadTraces]);

  useEffect(() => {
    (async () => {
      const docs = await refresh();
      if (docs[0]) await selectDocument(docs[0].id);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const jumpTo = useCallback((target: JumpTarget, switchToReader = true) => {
    setPage(target.page);
    setHighlight(target.excerpt || null);
    if (switchToReader) setTab("reader");
  }, []);

  const patchSettings = useCallback(async (patch: Partial<AppSettings>) => {
    const next = await saveSettings(patch);
    setSettings(next);
  }, []);

  const upload = useCallback(
    async (file: File) => {
      setError(null);
      setIngesting(true);
      setProgress({
        stage: "parsing",
        progress: 0.01,
        message: `Uploading ${file.name}`,
      });
      try {
        const last = await uploadPdf(file, (event) => {
          setProgress(event);
          if (event.document_id) {
            setDocument((prev) =>
              prev && prev.id === event.document_id
                ? prev
                : {
                    id: event.document_id!,
                    filename: file.name,
                    size_bytes: file.size,
                    page_count: 0,
                    status: "running",
                    created_at: new Date().toISOString(),
                    ingest_trace_id: event.trace_id || null,
                  }
            );
          }
        });
        const docId = last?.document_id;
        await refresh();
        if (docId) await selectDocument(docId);
        if (last?.trace_id) await selectTrace(last.trace_id);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Upload failed");
      } finally {
        setIngesting(false);
      }
    },
    [refresh, selectDocument, selectTrace]
  );

  const reingest = useCallback(async () => {
    if (!document) return;
    setError(null);
    setIngesting(true);
    try {
      const last = await reingestDocument(document.id, setProgress);
      await selectDocument(document.id);
      if (last?.trace_id) await selectTrace(last.trace_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Re-ingest failed");
    } finally {
      setIngesting(false);
    }
  }, [document, selectDocument, selectTrace]);

  const ask = useCallback(
    async (question: string) => {
      if (!document) return;
      setError(null);
      setAsking(true);
      const optimistic: ChatMessage = {
        id: `local-${Date.now()}`,
        role: "user",
        content: question,
        citations: [],
        trace_id: null,
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, optimistic]);
      try {
        const result = await askQuestion({
          document_id: document.id,
          question,
          candidate_pool: settings?.candidate_pool,
          final_k: settings?.final_k,
          reranker_enabled: settings?.reranker_enabled,
          keyword_weight: settings?.keyword_weight,
          diversity_enabled: settings?.diversity_enabled,
          similarity_threshold: settings?.show_threshold
            ? settings.similarity_threshold
            : 0,
          system_prompt: settings?.system_prompt,
          temperature: settings?.temperature,
        });
        setMessages(await listMessages(document.id));
        await loadTraces(document.id);
        await selectTrace(result.trace_id);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Query failed");
        setMessages((prev) => prev.filter((m) => m.id !== optimistic.id));
      } finally {
        setAsking(false);
      }
    },
    [document, loadTraces, selectTrace, settings]
  );

  const rerun = useCallback(
    async (parentTraceId?: string, question?: string) => {
      if (!document) return;
      const parent =
        traces.find((t) => t.id === parentTraceId) ||
        traces.find((t) => t.id === selectedTraceId && t.type === "query") ||
        traces.find((t) => t.type === "query");
      const q = question || parent?.query_text;
      if (!q) {
        setError("No query to re-run yet. Ask a question in the Reader tab first.");
        return;
      }
      setAsking(true);
      setError(null);
      try {
        const result = await askQuestion({
          document_id: document.id,
          question: q,
          candidate_pool: settings?.candidate_pool,
          final_k: settings?.final_k,
          reranker_enabled: settings?.reranker_enabled,
          keyword_weight: settings?.keyword_weight,
          diversity_enabled: settings?.diversity_enabled,
          similarity_threshold: settings?.show_threshold
            ? settings.similarity_threshold
            : 0,
          system_prompt: settings?.system_prompt,
          temperature: settings?.temperature,
          parent_trace_id: parent?.id,
        });
        setMessages(await listMessages(document.id));
        await loadTraces(document.id);
        await selectTrace(result.trace_id);
        setTab("inspector");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Re-run failed");
      } finally {
        setAsking(false);
      }
    },
    [document, loadTraces, selectTrace, selectedTraceId, settings, traces]
  );

  const value = useMemo<AppState>(
    () => ({
      tab,
      setTab,
      health,
      documents,
      document,
      selectDocument,
      messages,
      traces,
      selectedTrace,
      selectedTraceId,
      selectTrace,
      settings: settings || DEFAULT_SETTINGS,
      patchSettings,
      progress,
      ingesting,
      asking,
      error,
      setError,
      page,
      setPage,
      highlight,
      jumpTo,
      upload,
      ask,
      rerun,
      reingest,
      refresh,
    }),
    [
      tab,
      health,
      documents,
      document,
      selectDocument,
      messages,
      traces,
      selectedTrace,
      selectedTraceId,
      selectTrace,
      settings,
      patchSettings,
      progress,
      ingesting,
      asking,
      error,
      page,
      highlight,
      jumpTo,
      upload,
      ask,
      rerun,
      reingest,
      refresh,
    ]
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApp() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useApp must be used inside AppProvider");
  return ctx;
}

export function citationJump(citation: Citation): JumpTarget {
  return { page: citation.page, excerpt: citation.excerpt };
}
