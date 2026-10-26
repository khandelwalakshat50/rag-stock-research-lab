export type NodeStatus = "success" | "slow" | "error";

export type PipelineNode = {
  id: string;
  type: string;
  label: string;
  status: NodeStatus;
  latency_ms: number;
  summary: string;
  key_metric?: string | null;
  error?: string | null;
  data: Record<string, unknown>;
};

export type TraceSummary = {
  id: string;
  type: "ingestion" | "query" | string;
  document_id: string;
  query_text: string | null;
  parent_trace_id: string | null;
  created_at: string | null;
  total_latency_ms: number;
  total_cost_usd: number;
  status: string;
};

export type TraceDetail = TraceSummary & {
  filename?: string | null;
  settings?: Record<string, unknown>;
  nodes: PipelineNode[];
};

export type Citation = {
  page: number;
  chunk_index: number;
  score: number;
  excerpt: string;
  heading?: string | null;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  trace_id: string | null;
  created_at: string | null;
};

export type DocumentInfo = {
  id: string;
  filename: string;
  size_bytes: number;
  page_count: number;
  status: string;
  created_at: string | null;
  ingest_trace_id: string | null;
  chunk_count?: number;
  file_url?: string;
};

export type AppSettings = {
  chunk_size: number;
  chunk_overlap: number;
  top_k: number;
  similarity_threshold: number;
  show_threshold: boolean;
  system_prompt: string;
  temperature: number;
  candidate_pool: number;
  final_k: number;
  reranker_enabled: boolean;
  keyword_weight: number;
  diversity_enabled: boolean;
};

export type ProgressEvent = {
  stage: string;
  progress: number;
  message: string;
  document_id?: string;
  trace_id?: string;
  status?: string;
};

export type RetrievedChunk = {
  rank: number;
  vector_rank?: number;
  id: string;
  score: number | null;
  rerank_score?: number | null;
  sent_to_llm?: boolean;
  found_by?: "semantic" | "keyword" | "both" | null;
  semantic_rank?: number | null;
  keyword_rank?: number | null;
  bm25?: number | null;
  matched_terms?: string[];
  merged_count?: number;
  merged_chunk_indices?: number[];
  pre_diversity_rank?: number | null;
  redundancy?: number | null;
  below_threshold: boolean;
  chunk_index: number;
  page_number: number;
  heading?: string | null;
  is_table: boolean;
  text: string;
};

export type Health = {
  ok: boolean;
  keys_configured: {
    pinecone: boolean;
    openai: boolean;
  };
  index_name: string;
  embedding_model: string;
  llm_model: string;
};

export type EvalQuestion = {
  id: string;
  document_id: string;
  question: string;
  expected_pages: number[];
  notes?: string | null;
  created_at: string | null;
};

export type EvalTimings = {
  query_embedding_ms?: number | null;
  vector_search_ms?: number | null;
  vector_connect_ms?: number | null;
  vector_query_ms?: number | null;
  keyword_ms?: number | null;
  rerank_ms?: number | null;
  distinct_pages_top5?: number | null;
  pre_merge_distinct_pages_top5?: number | null;
  p50_latency_ms?: number | null;
  errors?: number;
};

export type EvalRun = {
  id: string;
  document_id: string;
  label: string | null;
  created_at: string | null;
  settings: Record<string, unknown>;
  question_count: number;
  recall_at_5: number;
  mrr_at_10: number;
  avg_latency_ms: number;
  avg_timings: EvalTimings;
};

export type EvalResult = {
  question_id: string;
  question: string;
  expected_pages: number[];
  retrieved: { page: number | null; score: number | null; id: string; found_by?: string | null }[];
  first_hit_rank: number | null;
  hit_at_5: boolean;
  latency_ms: number;
  timings: EvalTimings;
  error: string | null;
};

export type EvalRunDetail = EvalRun & { results: EvalResult[] };

export type EvalProgress = {
  stage: "running" | "done" | "error";
  done?: number;
  total?: number;
  message?: string;
  run_id?: string;
};
