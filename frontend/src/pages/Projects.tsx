import { Calendar, CheckCircle2, Circle, ExternalLink, Github, MessageSquare, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Card, Empty, Field, Modal, PageHeader, Progress, Spinner, toast } from "../components/ui";
import { del, get, patch, post } from "../lib/api";
import type { Project } from "../lib/types";
import { cn, fmtDateTime, fromLocalInput, timeAgo, toLocalInput } from "../lib/utils";

const STATUS_COLOR: Record<string, string> = { idea: "text-slate-300", active: "text-emerald-300", paused: "text-amber-300", done: "text-sky-300" };

function ProjectForm({ open, onClose, initial, onSaved }: { open: boolean; onClose: () => void; initial: Partial<Project>; onSaved: () => void }) {
  const [f, setF] = useState<Partial<Project>>(initial);
  const [stack, setStack] = useState((initial.tech_stack || []).join(", "));
  const [busy, setBusy] = useState(false);
  useEffect(() => { setF(initial); setStack((initial.tech_stack || []).join(", ")); }, [initial]);
  const save = async () => {
    setBusy(true);
    const body = { ...f, tech_stack: stack.split(",").map((s) => s.trim()).filter(Boolean) };
    delete (body as any).tasks;
    try {
      if (f.id) await patch(`/api/projects/${f.id}`, body);
      else await post("/api/projects", body);
      onSaved();
      onClose();
    } catch (e: any) { toast(e.message, "error"); } finally { setBusy(false); }
  };
  return (
    <Modal open={open} onClose={onClose} title={f.id ? `Edit ${f.name}` : "New project"} wide>
      <div className="space-y-3">
        <Field label="Name"><input className="input" value={f.name || ""} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label="Description"><textarea className="input" value={f.description || ""} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
        <Field label="Tech stack (comma separated)"><input className="input" value={stack} onChange={(e) => setStack(e.target.value)} placeholder="FastAPI, React, PostgreSQL" /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Status"><select className="input" value={f.status || "active"} onChange={(e) => setF({ ...f, status: e.target.value })}>{["idea", "active", "paused", "done"].map((s) => <option key={s}>{s}</option>)}</select></Field>
          <Field label="Deadline"><input type="datetime-local" className="input" value={toLocalInput(f.deadline)} onChange={(e) => setF({ ...f, deadline: fromLocalInput(e.target.value) })} /></Field>
        </div>
        <Field label={`Progress: ${f.progress || 0}%`}><input type="range" min={0} max={100} step={5} className="w-full accent-violet-500" value={f.progress || 0} onChange={(e) => setF({ ...f, progress: +e.target.value })} /></Field>
        <Field label="GitHub / repo URL"><input className="input" value={f.repo_url || ""} onChange={(e) => setF({ ...f, repo_url: e.target.value })} /></Field>
        <Field label="Documentation / notes" hint="Markdown welcome. JARVIS appends progress notes here when you tell it about updates."><textarea className="input min-h-[140px] font-mono text-xs" value={f.docs || ""} onChange={(e) => setF({ ...f, docs: e.target.value })} /></Field>
        <button className="btn-primary w-full" disabled={busy || !f.name} onClick={save}>{busy && <Spinner />} Save project</button>
      </div>
    </Modal>
  );
}

export default function Projects() {
  const [items, setItems] = useState<Project[] | null>(null);
  const [form, setForm] = useState<Partial<Project> | null>(null);
  const [newTask, setNewTask] = useState<Record<string, string>>({});
  const navigate = useNavigate();
  const load = () => get("/api/projects").then((r) => setItems(r.items));
  useEffect(() => { load(); }, []);

  const addTask = async (pid: string) => {
    const title = newTask[pid]?.trim();
    if (!title) return;
    await post("/api/tasks", { title, project_id: pid });
    setNewTask({ ...newTask, [pid]: "" });
    load();
  };

  return (
    <div>
      <PageHeader title="Projects" subtitle="What you're building. JARVIS nudges you when something goes quiet."
        actions={<button className="btn-primary" onClick={() => setForm({ status: "active", progress: 0 })}><Plus className="h-4 w-4" /> New project</button>} />
      {!items ? <div className="flex justify-center py-10"><Spinner /></div> : items.length === 0 ? (
        <Empty title="No projects yet" text='Add one here, or just tell JARVIS "I started building a resume parser with FastAPI".' />
      ) : (
        <div className="grid gap-5 md:grid-cols-2">
          {items.map((p) => (
            <Card key={p.id} className="flex flex-col">
              <div className="flex items-start justify-between gap-3">
                <button className="min-w-0 text-left" onClick={() => setForm(p)}>
                  <h3 className="font-display text-lg font-semibold text-white">{p.name}</h3>
                  <span className={cn("text-xs font-medium uppercase tracking-wider", STATUS_COLOR[p.status])}>{p.status}</span>
                  <span className="text-xs text-slate-500"> · updated {timeAgo(p.updated_at)}</span>
                </button>
                <div className="flex shrink-0 gap-1">
                  {p.repo_url && <a className="btn-ghost !p-1.5" href={p.repo_url} target="_blank" rel="noreferrer" title="Repository">{p.repo_url.includes("github") ? <Github className="h-4 w-4" /> : <ExternalLink className="h-4 w-4" />}</a>}
                  <button className="btn-ghost !p-1.5" title="Discuss with JARVIS" onClick={() => navigate("/chat", { state: { prefill: `Let's talk about my project ${p.name}. Where am I at and what should I do next?` } })}><MessageSquare className="h-4 w-4" /></button>
                  <button className="btn-ghost !p-1.5 hover:!text-rose-300" onClick={async () => { if (confirm(`Delete ${p.name}?`)) { await del(`/api/projects/${p.id}`); load(); } }}><Trash2 className="h-4 w-4" /></button>
                </div>
              </div>
              {p.description && <p className="mt-2 text-sm text-slate-400">{p.description}</p>}
              <div className="mt-3 flex flex-wrap gap-1.5">{p.tech_stack.map((t) => <span key={t} className="chip text-sky-200">{t}</span>)}</div>
              <div className="mt-4"><div className="mb-1 flex justify-between text-xs text-slate-500"><span>Progress</span><span>{p.progress}%</span></div><Progress value={p.progress} /></div>
              {p.deadline && <p className="mt-2 flex items-center gap-1.5 text-xs text-amber-300/80"><Calendar className="h-3.5 w-3.5" /> Deadline {fmtDateTime(p.deadline)}</p>}
              <div className="mt-4 border-t border-white/[0.05] pt-3">
                {(p.tasks || []).map((t) => (
                  <button key={t.id} className="flex w-full items-center gap-2 py-1 text-left text-sm" onClick={async () => { await patch(`/api/tasks/${t.id}`, { status: t.status === "done" ? "todo" : "done" }); load(); }}>
                    {t.status === "done" ? <CheckCircle2 className="h-4 w-4 text-emerald-400" /> : <Circle className="h-4 w-4 text-slate-500" />}
                    <span className={t.status === "done" ? "text-slate-500 line-through" : "text-slate-300"}>{t.title}</span>
                  </button>
                ))}
                <form className="mt-1 flex gap-2" onSubmit={(e) => { e.preventDefault(); addTask(p.id); }}>
                  <input className="input !py-1.5 !text-xs" placeholder="Add a task…" value={newTask[p.id] || ""} onChange={(e) => setNewTask({ ...newTask, [p.id]: e.target.value })} />
                </form>
              </div>
            </Card>
          ))}
        </div>
      )}
      <ProjectForm open={!!form} onClose={() => setForm(null)} initial={form || {}} onSaved={load} />
    </div>
  );
}
