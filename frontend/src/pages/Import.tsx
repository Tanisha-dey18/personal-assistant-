import { FileText, MessageSquare, NotebookPen, Trash2, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Card, Empty, Field, PageHeader, Progress, Spinner, Tabs, Toggle, toast } from "../components/ui";
import { api, del, get, post } from "../lib/api";
import { cn, timeAgo } from "../lib/utils";

type Tab = "documents" | "chatgpt" | "text";
type Job = { id: string; kind: string; status: string; progress: number; total: number; result: any; error: string; created_at: string };

function useJobs() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const load = () => get("/api/jobs").then((d) => setJobs(d.items));
  useEffect(() => {
    load();
    const t = setInterval(() => load(), 2500);
    return () => clearInterval(t);
  }, []);
  return { jobs, reload: load };
}

function Jobs({ jobs }: { jobs: Job[] }) {
  if (!jobs.length) return null;
  return (
    <Card title="Import activity" className="mt-6">
      <div className="space-y-3">
        {jobs.slice(0, 8).map((j) => (
          <div key={j.id}>
            <div className="mb-1 flex flex-wrap items-center justify-between gap-2 text-sm">
              <span className="text-slate-200">{j.kind === "chatgpt" ? "ChatGPT history" : j.kind === "document" ? "Document" : "Notes"} <span className="text-xs text-slate-500">· {timeAgo(j.created_at)}</span></span>
              <span className={cn("text-xs", j.status === "done" ? "text-emerald-300" : j.status === "failed" ? "text-rose-300" : "text-sky-300")}>
                {j.status}{j.total ? ` · ${j.progress}/${j.total}` : ""}
              </span>
            </div>
            {j.status === "running" || j.status === "queued" ? <Progress value={j.total ? (j.progress / j.total) * 100 : 5} /> : null}
            {j.result && (j.result.created != null) && (
              <p className="mt-1 text-xs text-slate-500">
                {j.result.conversations != null && `${j.result.conversations} conversations · `}{j.result.created} new memories · {j.result.updated} updated{j.result.pending ? ` · ${j.result.pending} awaiting approval` : ""}
              </p>
            )}
            {j.result?.questions?.length > 0 && <p className="mt-1 text-xs text-amber-300">JARVIS has {j.result.questions.length} question(s) for you — check notifications.</p>}
            {j.error && <p className="mt-1 text-xs text-rose-300">{j.error}</p>}
          </div>
        ))}
      </div>
    </Card>
  );
}

export default function Import() {
  const [tab, setTab] = useState<Tab>("documents");
  const { jobs, reload } = useJobs();
  const [docs, setDocs] = useState<any[]>([]);
  const [extract, setExtract] = useState(true);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<any>(null);
  const [cgFile, setCgFile] = useState<File | null>(null);
  const [maxConv, setMaxConv] = useState(100);
  const [text, setText] = useState("");
  const [label, setLabel] = useState("notes");
  const fileRef = useRef<HTMLInputElement>(null);

  const loadDocs = () => get("/api/documents").then((d) => setDocs(d.items));
  useEffect(() => { loadDocs(); const t = setInterval(loadDocs, 4000); return () => clearInterval(t); }, []);

  const uploadDoc = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true);
    for (const f of Array.from(files)) {
      const form = new FormData();
      form.append("file", f);
      form.append("extract_memories", String(extract));
      try {
        await api("/api/documents", { method: "POST", form });
        toast(`Uploaded ${f.name} — processing…`);
      } catch (e: any) { toast(`${f.name}: ${e.message}`, "error"); }
    }
    setBusy(false);
    loadDocs();
    reload();
    if (fileRef.current) fileRef.current.value = "";
  };

  const previewChatgpt = async (f: File | null) => {
    setCgFile(f);
    setPreview(null);
    if (!f) return;
    const form = new FormData();
    form.append("file", f);
    try { setPreview(await api("/api/import/chatgpt/preview", { method: "POST", form })); } catch (e: any) { toast(e.message, "error"); }
  };

  const importChatgpt = async () => {
    if (!cgFile) return;
    setBusy(true);
    const form = new FormData();
    form.append("file", cgFile);
    form.append("max_conversations", String(maxConv));
    form.append("extract_memories", "true");
    try { await api("/api/import/chatgpt", { method: "POST", form }); toast("Import started — this runs in the background."); reload(); }
    catch (e: any) { toast(e.message, "error"); } finally { setBusy(false); }
  };

  const importText = async () => {
    setBusy(true);
    try { await post("/api/import/text", { text, label }); toast("Reading your notes…"); setText(""); reload(); }
    catch (e: any) { toast(e.message, "error"); } finally { setBusy(false); }
  };

  return (
    <div>
      <PageHeader title="Knowledge import" subtitle="Feed JARVIS your CV, project docs, notes and ChatGPT history. It extracts facts — it never invents missing details." />
      <Tabs value={tab} onChange={setTab} tabs={[
        { id: "documents", label: "Documents & CV", icon: <FileText className="h-4 w-4" /> },
        { id: "chatgpt", label: "ChatGPT export", icon: <MessageSquare className="h-4 w-4" /> },
        { id: "text", label: "Write / paste notes", icon: <NotebookPen className="h-4 w-4" /> },
      ]} />

      {tab === "documents" && (
        <div className="grid gap-6 lg:grid-cols-[1fr_1.2fr]">
          <Card title="Upload">
            <label className="flex cursor-pointer flex-col items-center justify-center rounded-2xl border border-dashed border-white/15 px-6 py-10 text-center transition hover:border-violet-400/50 hover:bg-white/[0.02]"
              onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); uploadDoc(e.dataTransfer.files); }}>
              {busy ? <Spinner className="h-6 w-6" /> : <Upload className="h-7 w-7 text-violet-300" />}
              <p className="mt-3 text-sm text-slate-200">Drop files or click to upload</p>
              <p className="mt-1 text-xs text-slate-500">PDF, DOCX, TXT, MD, CSV, JSON, code · max 25 MB</p>
              <input ref={fileRef} type="file" multiple className="hidden" accept=".pdf,.docx,.txt,.md,.markdown,.csv,.json,.py,.js,.ts,.html" onChange={(e) => uploadDoc(e.target.files)} />
            </label>
            <div className="mt-4"><Toggle checked={extract} onChange={setExtract} label="Learn about me from these files" hint="Extract facts into memory (use for CV, project docs, achievements). Off = just make them searchable." /></div>
          </Card>
          <Card title={`Your documents · ${docs.length}`}>
            {docs.length ? (
              <ul className="space-y-2">
                {docs.map((d) => (
                  <li key={d.id} className="group rounded-xl border border-white/[0.06] p-3">
                    <div className="flex items-center gap-2">
                      <FileText className="h-4 w-4 shrink-0 text-slate-500" />
                      <span className="flex-1 truncate text-sm text-slate-200">{d.filename}</span>
                      <span className={cn("chip", d.status === "ready" ? "text-emerald-300" : d.status === "failed" ? "text-rose-300" : "text-sky-300")}>{d.status === "processing" && <Spinner className="h-3 w-3" />}{d.status}</span>
                      <button className="opacity-0 group-hover:opacity-100" onClick={async () => { if (confirm(`Delete ${d.filename}? Memories learned from it are kept.`)) { await del(`/api/documents/${d.id}`); loadDocs(); } }}><Trash2 className="h-4 w-4 text-slate-500 hover:text-rose-300" /></button>
                    </div>
                    {d.summary && <p className="mt-2 text-xs text-slate-400">{d.summary}</p>}
                    {d.error && <p className="mt-2 text-xs text-rose-300">{d.error}</p>}
                  </li>
                ))}
              </ul>
            ) : <Empty title="No documents yet" text="Start with your CV — it's the fastest way for JARVIS to understand your background." />}
          </Card>
        </div>
      )}

      {tab === "chatgpt" && (
        <Card>
          <ol className="mb-5 list-decimal space-y-1 pl-5 text-sm text-slate-400">
            <li>In ChatGPT: Settings → Data controls → <b className="text-slate-200">Export data</b>. You'll get an email with a .zip.</li>
            <li>Upload the whole .zip (or just <code className="rounded bg-white/10 px-1">conversations.json</code>) below.</li>
            <li>JARVIS stores the chats as searchable history, summarises each one, and extracts facts about you <i>only from your own messages</i>.</li>
          </ol>
          <input type="file" accept=".zip,.json" className="input" onChange={(e) => previewChatgpt(e.target.files?.[0] || null)} />
          {preview && (
            <div className="mt-5 space-y-4">
              <p className="text-sm text-slate-200">Found <b>{preview.conversations}</b> conversations with <b>{preview.messages}</b> messages.</p>
              <div className="flex flex-wrap gap-1.5">{preview.sample.map((s: any, i: number) => <span key={i} className="chip">{s.title}</span>)}</div>
              <Field label={`Import the most recent ${maxConv} conversations`} hint="Each conversation costs ~2 small AI calls (roughly $0.002–0.005 each on gpt-4.1-mini). Start smaller if you like.">
                <input type="range" min={10} max={Math.max(10, Math.min(2000, preview.conversations))} step={10} value={Math.min(maxConv, Math.max(10, preview.conversations))} onChange={(e) => setMaxConv(+e.target.value)} className="w-full accent-violet-500" />
              </Field>
              <button className="btn-primary" onClick={importChatgpt} disabled={busy}>{busy && <Spinner />} Start import</button>
            </div>
          )}
        </Card>
      )}

      {tab === "text" && (
        <Card>
          <Field label="Label"><input className="input mb-3" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. about me, hackathon notes, semester goals" /></Field>
          <Field label="Tell JARVIS anything" hint="Background, story, achievements, people in your life, plans… JARVIS extracts the important facts and asks if something's ambiguous.">
            <textarea className="input min-h-[240px]" value={text} onChange={(e) => setText(e.target.value)} placeholder="I'm a 3rd-year CSE student… Last year our team won the college hackathon with…" />
          </Field>
          <button className="btn-primary mt-4" disabled={busy || text.length < 10} onClick={importText}>{busy && <Spinner />} Teach JARVIS</button>
        </Card>
      )}

      <Jobs jobs={jobs} />
    </div>
  );
}
