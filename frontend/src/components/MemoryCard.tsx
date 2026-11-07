import { Check, Lock, Pencil, Trash2, X } from "lucide-react";
import { useState } from "react";
import { del, patch, post } from "../lib/api";
import type { MemoryItem } from "../lib/types";
import { CATEGORIES } from "../lib/types";
import { cn, timeAgo } from "../lib/utils";
import { Spinner, toast } from "./ui";

const TYPE_STYLE: Record<string, string> = {
  confirmed: "text-emerald-300 border-emerald-400/25 bg-emerald-400/10",
  assumption: "text-amber-300 border-amber-400/25 bg-amber-400/10",
  temporary: "text-sky-300 border-sky-400/25 bg-sky-400/10",
};

export default function MemoryCard({ m, onChange, onDelete, compact }: {
  m: MemoryItem; onChange?: (m: MemoryItem) => void; onDelete?: (id: string) => void; compact?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(m.content);
  const [cat, setCat] = useState(m.category);
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    try {
      const r = await patch<MemoryItem>(`/api/memory/${m.id}`, { content: text, category: cat, memory_type: "confirmed" });
      onChange?.(r);
      setEditing(false);
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };
  const remove = async () => {
    if (!confirm("Delete this memory permanently? This can't be undone.")) return;
    await del(`/api/memory/${m.id}`);
    onDelete?.(m.id);
  };
  const approve = async () => onChange?.(await post<MemoryItem>(`/api/memory/${m.id}/approve`));
  const confirmIt = async () => onChange?.(await post<MemoryItem>(`/api/memory/${m.id}/confirm`));

  return (
    <div className={cn("group rounded-xl border border-white/[0.06] bg-white/[0.02] transition hover:border-white/[0.12]", compact ? "p-3" : "p-4")}>
      {editing ? (
        <div className="space-y-2">
          <textarea className="input min-h-[70px]" value={text} onChange={(e) => setText(e.target.value)} />
          <div className="flex flex-wrap items-center gap-2">
            <select className="input !w-auto !py-1.5" value={cat} onChange={(e) => setCat(e.target.value)}>
              {CATEGORIES.map((c) => <option key={c}>{c}</option>)}
            </select>
            <button className="btn-primary !py-1.5" onClick={save} disabled={busy}>{busy ? <Spinner /> : <Check className="h-4 w-4" />} Save</button>
            <button className="btn-ghost !py-1.5" onClick={() => { setEditing(false); setText(m.content); }}><X className="h-4 w-4" /></button>
          </div>
        </div>
      ) : (
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <p className="text-sm leading-relaxed text-slate-200">{m.content}</p>
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <span className="chip">{m.category}</span>
              <span className={cn("chip", TYPE_STYLE[m.memory_type])}>{m.memory_type}</span>
              {m.sensitive && <span className="chip text-rose-300"><Lock className="h-3 w-3" /> encrypted</span>}
              {m.event_date && <span className="chip">{m.event_date}</span>}
              {!compact && <span className="text-[11px] text-slate-500">{m.source}{m.source_ref && m.source !== "chat" ? ` · ${m.source_ref.slice(0, 40)}` : ""} · {timeAgo(m.updated_at)}</span>}
              {m.score != null && <span className="text-[11px] text-violet-300">match {Math.round(m.score * 100)}%</span>}
              {!compact && (
                <span className="ml-1 flex items-center gap-0.5" title={`importance ${m.importance}`}>
                  {[0.2, 0.4, 0.6, 0.8, 1].map((v) => <span key={v} className={cn("h-1 w-2.5 rounded-full", m.importance >= v - 0.1 ? "bg-violet-400/80" : "bg-white/10")} />)}
                </span>
              )}
            </div>
            {m.status === "pending" && (
              <div className="mt-3 flex gap-2">
                <button className="btn-primary !py-1 !text-xs" onClick={approve}><Check className="h-3.5 w-3.5" /> Remember this</button>
                <button className="btn-outline !py-1 !text-xs" onClick={remove}><X className="h-3.5 w-3.5" /> Don't store</button>
              </div>
            )}
            {m.status === "active" && m.memory_type === "assumption" && !compact && (
              <button className="mt-2 text-xs text-amber-300 hover:underline" onClick={confirmIt}>This is correct → mark confirmed</button>
            )}
          </div>
          {onChange && (
            <div className="flex shrink-0 gap-0.5 opacity-60 transition group-hover:opacity-100">
              <button className="btn-ghost !p-1.5" onClick={() => setEditing(true)} title="Edit"><Pencil className="h-3.5 w-3.5" /></button>
              <button className="btn-ghost !p-1.5 hover:!text-rose-300" onClick={remove} title="Delete"><Trash2 className="h-3.5 w-3.5" /></button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
