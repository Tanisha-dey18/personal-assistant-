import { Brain, Clock, Download, GitBranch, MessageSquare, Plus, Search, Sparkles } from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import MemoryCard from "../components/MemoryCard";
import { Card, Empty, Field, Modal, PageHeader, Spinner, Tabs, toast } from "../components/ui";
import { get, post } from "../lib/api";
import type { Conversation, MemoryItem } from "../lib/types";
import { CATEGORIES } from "../lib/types";
import { cn, timeAgo } from "../lib/utils";

const KnowledgeGraph = lazy(() => import("../components/KnowledgeGraph"));
type Tab = "memories" | "pending" | "timeline" | "graph" | "history";

function AddMemory({ open, onClose, onAdded }: { open: boolean; onClose: () => void; onAdded: () => void }) {
  const [f, setF] = useState({ content: "", category: "personal", memory_type: "confirmed", importance: 0.6, sensitive: false, event_date: "" });
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      const r = await post("/api/memory", { ...f, event_date: f.event_date || null });
      toast(r.created ? "Memory saved" : "Similar memory already existed — updated it");
      onAdded();
      onClose();
      setF({ ...f, content: "" });
    } catch (e: any) { toast(e.message, "error"); } finally { setBusy(false); }
  };
  return (
    <Modal open={open} onClose={onClose} title="Add a memory">
      <div className="space-y-4">
        <Field label="What should ASTRA remember?"><textarea className="input min-h-[90px]" value={f.content} onChange={(e) => setF({ ...f, content: e.target.value })} placeholder="e.g. I won 2nd place at Smart India Hackathon 2025 with a crop-disease detector." /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Category"><select className="input" value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}</select></Field>
          <Field label="Type"><select className="input" value={f.memory_type} onChange={(e) => setF({ ...f, memory_type: e.target.value })}><option>confirmed</option><option>assumption</option><option>temporary</option></select></Field>
          <Field label="Date (optional)"><input className="input" placeholder="2025-12 or 2025-12-08" value={f.event_date} onChange={(e) => setF({ ...f, event_date: e.target.value })} /></Field>
          <Field label={`Importance ${f.importance}`}><input type="range" min={0} max={1} step={0.1} className="mt-3 w-full accent-violet-500" value={f.importance} onChange={(e) => setF({ ...f, importance: +e.target.value })} /></Field>
        </div>
        <label className="flex items-center gap-2 text-sm text-slate-300"><input type="checkbox" className="accent-violet-500" checked={f.sensitive} onChange={(e) => setF({ ...f, sensitive: e.target.checked })} /> Sensitive (encrypt at rest)</label>
        <button className="btn-primary w-full" disabled={busy || f.content.length < 2} onClick={save}>{busy && <Spinner />} Save memory</button>
      </div>
    </Modal>
  );
}

export default function Memory() {
  const [tab, setTab] = useState<Tab>("memories");
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [cat, setCat] = useState<string>("");
  const [q, setQ] = useState("");
  const [semantic, setSemantic] = useState(true);
  const [loading, setLoading] = useState(false);
  const [adding, setAdding] = useState(false);
  const [pending, setPending] = useState<MemoryItem[]>([]);
  const [timeline, setTimeline] = useState<any[]>([]);
  const [convs, setConvs] = useState<Conversation[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      if (q.trim() && semantic) {
        const r = await get(`/api/memory/search?q=${encodeURIComponent(q)}&limit=30`);
        setItems(r.items);
      } else {
        const r = await get(`/api/memory?limit=300${cat ? `&category=${cat}` : ""}${q ? `&q=${encodeURIComponent(q)}` : ""}`);
        setItems(r.items);
        setCounts(r.categories);
      }
    } catch (e: any) { toast(e.message, "error"); } finally { setLoading(false); }
  }, [q, cat, semantic]);

  useEffect(() => { if (tab === "memories") { const t = setTimeout(load, q ? 350 : 0); return () => clearTimeout(t); } }, [load, tab, q]);
  useEffect(() => {
    if (tab === "pending") get("/api/memory?status=pending").then((r) => setPending(r.items));
    if (tab === "timeline") get("/api/memory/timeline/items").then((r) => setTimeline(r.items));
    if (tab === "history") get("/api/conversations?limit=200").then((r) => setConvs(r.items));
  }, [tab]);

  const exportMemories = async () => {
    const data = await get("/api/export/memories");
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `astra-memories-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
  };

  const total = Object.values(counts).reduce((a, b) => a + b, 0);

  return (
    <div>
      <PageHeader title="Memory" subtitle="Everything ASTRA remembers — searchable, editable, deletable. You're in control."
        actions={<>
          <button className="btn-outline" onClick={exportMemories}><Download className="h-4 w-4" /> Export</button>
          <button className="btn-primary" onClick={() => setAdding(true)}><Plus className="h-4 w-4" /> Add memory</button>
        </>} />
      <Tabs value={tab} onChange={setTab} tabs={[
        { id: "memories", label: "Memories", icon: <Brain className="h-4 w-4" /> },
        { id: "pending", label: "Pending", icon: <Sparkles className="h-4 w-4" /> },
        { id: "timeline", label: "Timeline", icon: <Clock className="h-4 w-4" /> },
        { id: "graph", label: "Knowledge graph", icon: <GitBranch className="h-4 w-4" /> },
        { id: "history", label: "Conversations", icon: <MessageSquare className="h-4 w-4" /> },
      ]} />

      {tab === "memories" && (
        <div className="grid gap-6 lg:grid-cols-[220px_1fr]">
          <div className="space-y-1">
            <button onClick={() => setCat("")} className={cn("flex w-full justify-between rounded-lg px-3 py-1.5 text-sm", !cat ? "bg-white/[0.07] text-white" : "text-slate-400 hover:bg-white/[0.04]")}>All <span className="text-slate-500">{total}</span></button>
            {CATEGORIES.filter((c) => counts[c]).map((c) => (
              <button key={c} onClick={() => setCat(c)} className={cn("flex w-full justify-between rounded-lg px-3 py-1.5 text-sm capitalize", cat === c ? "bg-white/[0.07] text-white" : "text-slate-400 hover:bg-white/[0.04]")}>{c} <span className="text-slate-500">{counts[c]}</span></button>
            ))}
          </div>
          <div>
            <div className="mb-4 flex gap-2">
              <div className="relative flex-1">
                <Search className="absolute left-3.5 top-3 h-4 w-4 text-slate-500" />
                <input className="input !pl-10" placeholder={semantic ? "Search by meaning — e.g. 'that hackathon with the drone'" : "Keyword filter"} value={q} onChange={(e) => setQ(e.target.value)} />
              </div>
              <button className={cn("btn-outline shrink-0 !text-xs", semantic && "!border-violet-400/40 text-violet-200")} onClick={() => setSemantic(!semantic)}>{semantic ? "Semantic" : "Keyword"}</button>
            </div>
            {loading ? <div className="flex justify-center py-10"><Spinner /></div> : items.length ? (
              <div className="space-y-2">{items.map((m) => <MemoryCard key={m.id} m={m} onChange={(nm) => setItems((s) => s.map((x) => (x.id === nm.id ? nm : x)))} onDelete={(id) => setItems((s) => s.filter((x) => x.id !== id))} />)}</div>
            ) : <Empty icon={<Brain className="h-8 w-8" />} title={q ? "No matching memories" : "No memories yet"} text="ASTRA extracts important facts automatically as you chat. You can also add them manually or import documents." />}
          </div>
        </div>
      )}

      {tab === "pending" && (
        pending.length ? <div className="space-y-2">{pending.map((m) => <MemoryCard key={m.id} m={m} onChange={() => setPending((s) => s.filter((x) => x.id !== m.id))} onDelete={(id) => setPending((s) => s.filter((x) => x.id !== id))} />)}</div>
          : <Empty title="Nothing waiting" text="Sensitive facts (health, finances, etc.) wait here for your approval before ASTRA remembers them." />
      )}

      {tab === "timeline" && (
        timeline.length ? (
          <div className="relative ml-3 border-l border-white/10 pl-6">
            {timeline.map((t, i) => (
              <div key={i} className="relative mb-6">
                <span className="absolute -left-[31px] top-1.5 h-3 w-3 rounded-full border-2 border-ink-950 bg-gradient-to-br from-astra-blue to-astra-violet" />
                <p className="text-xs font-medium tracking-wider text-violet-300">{t.date}</p>
                <p className="mt-0.5 text-sm text-slate-200">{t.title}</p>
                <span className="chip mt-1">{t.kind}</span>
              </div>
            ))}
          </div>
        ) : <Empty icon={<Clock className="h-8 w-8" />} title="Your timeline is empty" text="Dated memories, career milestones and projects show up here." />
      )}

      {tab === "graph" && <Suspense fallback={<Spinner />}><KnowledgeGraph /></Suspense>}

      {tab === "history" && (
        <Card>
          {convs.length ? (
            <ul className="divide-y divide-white/[0.05]">
              {convs.map((c) => (
                <li key={c.id}><Link to={`/chat/${c.id}`} className="flex items-center gap-3 px-1 py-3 hover:text-white">
                  <MessageSquare className="h-4 w-4 shrink-0 text-slate-500" />
                  <div className="min-w-0 flex-1"><p className="truncate text-sm text-slate-200">{c.title}</p>{c.summary && <p className="truncate text-xs text-slate-500">{c.summary}</p>}</div>
                  {c.source === "chatgpt" && <span className="chip">ChatGPT</span>}
                  <span className="shrink-0 text-xs text-slate-500">{timeAgo(c.updated_at)}</span>
                </Link></li>
              ))}
            </ul>
          ) : <Empty title="No conversations yet" />}
        </Card>
      )}

      <AddMemory open={adding} onClose={() => setAdding(false)} onAdded={load} />
    </div>
  );
}
