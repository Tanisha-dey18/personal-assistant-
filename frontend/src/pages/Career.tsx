import { Award, Briefcase, ExternalLink, Flag, GraduationCap, MessageSquare, Plus, Trash2, Wrench } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Card, Empty, Field, Modal, PageHeader, Progress, Spinner, toast } from "../components/ui";
import { del, get, patch, post } from "../lib/api";
import type { CareerItem } from "../lib/types";
import { cn } from "../lib/utils";

const KINDS = [
  { id: "application", label: "Application", icon: Briefcase },
  { id: "internship", label: "Internship", icon: GraduationCap },
  { id: "achievement", label: "Achievement", icon: Award },
  { id: "skill", label: "Skill", icon: Wrench },
  { id: "milestone", label: "Roadmap milestone", icon: Flag },
];
const APP_STAGES = ["wishlist", "applied", "interviewing", "offer", "rejected"];
const STAGE_COLOR: Record<string, string> = { wishlist: "text-slate-300", applied: "text-sky-300", interviewing: "text-amber-300", offer: "text-emerald-300", rejected: "text-rose-300" };

function ItemForm({ open, onClose, initial, onSaved }: { open: boolean; onClose: () => void; initial: Partial<CareerItem>; onSaved: () => void }) {
  const [f, setF] = useState<Partial<CareerItem>>(initial);
  const [busy, setBusy] = useState(false);
  useEffect(() => setF(initial), [initial]);
  const save = async () => {
    setBusy(true);
    try {
      if (f.id) await patch(`/api/career/${f.id}`, f);
      else await post("/api/career", f);
      onSaved();
      onClose();
    } catch (e: any) { toast(e.message, "error"); } finally { setBusy(false); }
  };
  return (
    <Modal open={open} onClose={onClose} title={f.id ? "Edit item" : "Add to career tracker"}>
      <div className="space-y-3">
        {!f.id && <Field label="Type"><select className="input" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>{KINDS.map((k) => <option key={k.id} value={k.id}>{k.label}</option>)}</select></Field>}
        <Field label="Title"><input className="input" value={f.title || ""} onChange={(e) => setF({ ...f, title: e.target.value })} placeholder={f.kind === "skill" ? "e.g. PyTorch" : "e.g. ML Intern"} /></Field>
        {f.kind !== "skill" && <Field label="Organization"><input className="input" value={f.organization || ""} onChange={(e) => setF({ ...f, organization: e.target.value })} /></Field>}
        {f.kind === "application" && <Field label="Stage"><select className="input" value={f.status || "applied"} onChange={(e) => setF({ ...f, status: e.target.value })}>{APP_STAGES.map((s) => <option key={s}>{s}</option>)}</select></Field>}
        {f.kind === "milestone" && <Field label="Status"><select className="input" value={f.status || "todo"} onChange={(e) => setF({ ...f, status: e.target.value })}><option>todo</option><option>in progress</option><option>done</option></select></Field>}
        {f.kind === "skill" && <Field label={`Level: ${f.level || 0}%`}><input type="range" min={0} max={100} step={5} className="w-full accent-violet-500" value={f.level || 0} onChange={(e) => setF({ ...f, level: +e.target.value })} /></Field>}
        <div className="grid grid-cols-2 gap-3">
          <Field label="Date"><input className="input" placeholder="2026-05" value={f.date || ""} onChange={(e) => setF({ ...f, date: e.target.value })} /></Field>
          <Field label="Link"><input className="input" value={f.link || ""} onChange={(e) => setF({ ...f, link: e.target.value })} /></Field>
        </div>
        <Field label="Notes"><textarea className="input" value={f.notes || ""} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
        <button className="btn-primary w-full" disabled={busy || !f.title} onClick={save}>{busy && <Spinner />} Save</button>
      </div>
    </Modal>
  );
}

export default function Career() {
  const [items, setItems] = useState<CareerItem[]>([]);
  const [form, setForm] = useState<Partial<CareerItem> | null>(null);
  const navigate = useNavigate();
  const load = () => get("/api/career").then((r) => setItems(r.items));
  useEffect(() => { load(); }, []);
  const by = (k: string) => items.filter((i) => i.kind === k);
  const remove = async (id: string) => { if (confirm("Delete this item?")) { await del(`/api/career/${id}`); load(); } };

  const Row = ({ i }: { i: CareerItem }) => (
    <div className="group flex items-start gap-3 rounded-xl border border-white/[0.06] p-3 hover:border-white/[0.12]">
      <button className="min-w-0 flex-1 text-left" onClick={() => setForm(i)}>
        <p className="text-sm font-medium text-slate-100">{i.title}{i.organization && <span className="text-slate-400"> · {i.organization}</span>}</p>
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          {i.status && <span className={cn("chip", STAGE_COLOR[i.status])}>{i.status}</span>}
          {i.date && <span className="chip">{i.date}</span>}
        </div>
        {i.notes && <p className="mt-1.5 line-clamp-2 text-xs text-slate-500">{i.notes}</p>}
      </button>
      {i.link && <a href={i.link} target="_blank" rel="noreferrer" className="btn-ghost !p-1.5"><ExternalLink className="h-3.5 w-3.5" /></a>}
      <button className="btn-ghost !p-1.5 opacity-0 group-hover:opacity-100" onClick={() => remove(i.id)}><Trash2 className="h-3.5 w-3.5" /></button>
    </div>
  );

  return (
    <div>
      <PageHeader title="Career" subtitle="Roadmap, applications, internships, skills and wins — ASTRA's mentor mode reads all of this."
        actions={<>
          <button className="btn-outline" onClick={() => navigate("/chat", { state: { prefill: "Career mentor time: based on everything you know about me, what should my roadmap for the next 6 months look like?", mode: "mentor" } })}><MessageSquare className="h-4 w-4" /> Ask mentor</button>
          <button className="btn-primary" onClick={() => setForm({ kind: "application", status: "applied" })}><Plus className="h-4 w-4" /> Add</button>
        </>} />

      <Card className="mb-6" title="Internship & job pipeline">
        <div className="grid gap-3 overflow-x-auto md:grid-cols-5">
          {APP_STAGES.map((s) => (
            <div key={s} className="min-w-[180px] rounded-xl bg-white/[0.02] p-2.5">
              <p className={cn("mb-2 text-xs font-semibold uppercase tracking-wider", STAGE_COLOR[s])}>{s} · {by("application").filter((a) => (a.status || "applied") === s).length}</p>
              <div className="space-y-2">{by("application").filter((a) => (a.status || "applied") === s).map((a) => (
                <div key={a.id} className="rounded-lg border border-white/[0.06] bg-ink-850 p-2.5">
                  <button className="block w-full text-left" onClick={() => setForm(a)}>
                    <p className="text-sm text-slate-100">{a.title}</p><p className="text-xs text-slate-500">{a.organization}</p>
                  </button>
                  <select className="mt-2 w-full rounded-md bg-white/5 px-1.5 py-1 text-[11px] text-slate-300 outline-none" value={a.status || "applied"}
                    onChange={async (e) => { await patch(`/api/career/${a.id}`, { status: e.target.value }); load(); }}>
                    {APP_STAGES.map((x) => <option key={x}>{x}</option>)}
                  </select>
                </div>
              ))}</div>
            </div>
          ))}
        </div>
      </Card>

      <div className="grid gap-6 md:grid-cols-2">
        <Card title="Roadmap" action={<button className="btn-ghost !p-1" onClick={() => setForm({ kind: "milestone", status: "todo" })}><Plus className="h-4 w-4" /></button>}>
          {by("milestone").length ? <div className="space-y-2">{by("milestone").map((i) => <Row key={i.id} i={i} />)}</div> : <Empty title="No milestones yet" text="Ask ASTRA to draft a roadmap, then add the steps here." />}
        </Card>
        <Card title="Technical skills" action={<button className="btn-ghost !p-1" onClick={() => setForm({ kind: "skill", level: 50 })}><Plus className="h-4 w-4" /></button>}>
          {by("skill").length ? <div className="space-y-3">{by("skill").sort((a, b) => b.level - a.level).map((s) => (
            <button key={s.id} className="block w-full text-left" onClick={() => setForm(s)}>
              <div className="mb-1 flex justify-between text-sm"><span className="text-slate-200">{s.title}</span><span className="text-xs text-slate-500">{s.level}%</span></div>
              <Progress value={s.level} />
            </button>
          ))}</div> : <Empty title="No skills tracked" />}
        </Card>
        <Card title="Internships & experience" action={<button className="btn-ghost !p-1" onClick={() => setForm({ kind: "internship" })}><Plus className="h-4 w-4" /></button>}>
          {by("internship").length ? <div className="space-y-2">{by("internship").map((i) => <Row key={i.id} i={i} />)}</div> : <Empty title="No internships yet" />}
        </Card>
        <Card title="Achievements" action={<button className="btn-ghost !p-1" onClick={() => setForm({ kind: "achievement" })}><Plus className="h-4 w-4" /></button>}>
          {by("achievement").length ? <div className="space-y-2">{by("achievement").map((i) => <Row key={i.id} i={i} />)}</div> : <Empty title="No achievements logged" text="Hackathon wins, certifications, papers — log them so ASTRA can use them in your CV and interviews." />}
        </Card>
      </div>
      <ItemForm open={!!form} onClose={() => setForm(null)} initial={form || {}} onSaved={load} />
    </div>
  );
}
