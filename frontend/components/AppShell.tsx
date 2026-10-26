import { useRef } from "react";
import { BookOpen, FlaskConical, GitBranch, Upload } from "lucide-react";
import { useApp } from "./AppProvider";
import EvalTab from "./EvalTab";
import InspectorTab from "./InspectorTab";
import ReaderTab from "./ReaderTab";

export default function AppShell() {
  const { tab, setTab, document, documents, selectDocument, health, upload, ingesting } = useApp();
  const fileRef = useRef<HTMLInputElement>(null);

  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center justify-between gap-4 border-b border-slate-200 bg-white px-4 py-2.5">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-ink text-sm font-semibold text-white">
            RS
          </div>
          <div>
            <div className="text-sm font-semibold tracking-tight">RAG Stock Research Lab</div>
            <div className="text-[11px] text-slate-500">
              Inspectable retrieval for equity reports
            </div>
          </div>
        </div>

        <div className="flex rounded-full bg-slate-100 p-1">
          <TabButton active={tab === "reader"} onClick={() => setTab("reader")} icon={<BookOpen size={14} />}>
            Reader
          </TabButton>
          <TabButton
            active={tab === "inspector"}
            onClick={() => setTab("inspector")}
            icon={<GitBranch size={14} />}
          >
            Pipeline Inspector
          </TabButton>
          <TabButton active={tab === "eval"} onClick={() => setTab("eval")} icon={<FlaskConical size={14} />}>
            Evaluation
          </TabButton>
        </div>

        <div className="flex items-center gap-2">
          {documents.length > 0 ? (
            <select
              value={document?.id || ""}
              onChange={(e) => e.target.value && selectDocument(e.target.value)}
              className="max-w-[220px] rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs"
            >
              {documents.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.filename}
                </option>
              ))}
            </select>
          ) : null}
          <button
            onClick={() => fileRef.current?.click()}
            disabled={ingesting}
            className="flex items-center gap-1.5 rounded-full border border-slate-200 px-3 py-1.5 text-xs font-medium hover:border-slate-400 disabled:opacity-40"
          >
            <Upload size={13} />
            New PDF
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="application/pdf"
            hidden
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) upload(file);
              e.target.value = "";
            }}
          />
          <KeyDots health={health} />
        </div>
      </header>
      <main className="min-h-0 flex-1">
        {tab === "reader" ? <ReaderTab /> : tab === "inspector" ? <InspectorTab /> : <EvalTab />}
      </main>
    </div>
  );
}

function TabButton({
  active,
  onClick,
  icon,
  children,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1.5 whitespace-nowrap rounded-full px-4 py-1.5 text-sm ${
        active ? "bg-white text-ink shadow-sm" : "text-slate-500"
      }`}
    >
      {icon}
      {children}
    </button>
  );
}

function KeyDots({
  health,
}: {
  health: ReturnType<typeof useApp>["health"];
}) {
  if (!health) return null;
  const items = [
    ["Pinecone", health.keys_configured.pinecone],
    ["OpenAI", health.keys_configured.openai],
  ] as const;
  return (
    <div className="hidden items-center gap-2 xl:flex" title="API keys loaded from .env">
      {items.map(([name, ok]) => (
        <span key={name} className="flex items-center gap-1 font-mono text-[10px] text-slate-500">
          <span className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-emerald-500" : "bg-red-400"}`} />
          {name}
        </span>
      ))}
    </div>
  );
}
