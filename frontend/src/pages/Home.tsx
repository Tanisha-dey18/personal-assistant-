import { motion } from "framer-motion";
import { AlertTriangle, ArrowRight, Bell, Brain, CheckCircle2, Circle, FolderKanban, MessageSquare, Send, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import ActionCard from "../components/ActionCard";
import Orb from "../components/Orb";
import { Card, Empty, Progress } from "../components/ui";
import { get, patch } from "../lib/api";
import { useStore } from "../lib/store";
import { cn, fmtDateTime, greeting, timeAgo } from "../lib/utils";

function Clock() {
  const [now, setNow] = useState(new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  return (
    <div className="font-display text-5xl font-light tabular-nums tracking-tight text-white sm:text-6xl">
      {now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
      <span className="ml-1 text-xl text-slate-500">{String(now.getSeconds()).padStart(2, "0")}</span>
    </div>
  );
}

export default function Home() {
  const user = useStore((s) => s.user);
  const navigate = useNavigate();
  const [d, setD] = useState<any>(null);
  const [q, setQ] = useState("");

  const load = () => get("/api/dashboard").then(setD).catch(() => {});
  useEffect(() => { load(); }, []);

  const toggleTask = async (id: string, done: boolean) => {
    await patch(`/api/tasks/${id}`, { status: done ? "done" : "todo" });
    load();
  };

  const maxDone = Math.max(1, ...(d?.weekly_progress || []).map((x: any) => x.done));

  return (
    <div className="space-y-6">
      {/* hero */}
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="card relative overflow-hidden !p-6 sm:!p-8">
        <div className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-violet-600/20 blur-3xl" />
        <div className="relative flex flex-col items-start justify-between gap-6 md:flex-row md:items-center">
          <div className="min-w-0">
            <p className="text-sm text-slate-400">{greeting()},</p>
            <h1 className="font-display text-3xl font-semibold text-white sm:text-4xl">{user?.name?.split(" ")[0] || "friend"}<span className="gradient-text">.</span></h1>
            <div className="mt-4"><Clock /></div>
            <p className="mt-1 text-sm text-slate-400">{new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long", year: "numeric" })}</p>
            <div className="mt-4 flex flex-wrap items-center gap-2 text-xs">
              <span className={cn("chip", d?.ai_configured ? "text-emerald-300" : "text-amber-300")}>
                <span className="h-1.5 w-1.5 rounded-full bg-current" /> {d ? (d.ai_configured ? "AI brain online" : "AI key missing") : "…"}
              </span>
              <span className="chip"><Brain className="h-3 w-3" /> {d?.stats.memories ?? "–"} memories · +{d?.stats.memories_week ?? 0} this week</span>
              <span className="chip"><CheckCircle2 className="h-3 w-3" /> {d?.stats.tasks_done_week ?? 0} tasks done this week</span>
            </div>
          </div>
          <div className="hidden md:block"><Orb size={150} onClick={() => navigate("/chat")} /></div>
        </div>
        <form className="relative mt-6 flex gap-2" onSubmit={(e) => { e.preventDefault(); if (q.trim()) navigate("/chat", { state: { prefill: q } }); }}>
          <input className="input !py-3 !text-base" placeholder="Hey Jarvis, what's going on?" value={q} onChange={(e) => setQ(e.target.value)} />
          <button className="btn-primary !px-4"><Send className="h-4 w-4" /></button>
        </form>
      </motion.div>

      {d && !d.ai_configured && (
        <div className="flex items-start gap-3 rounded-2xl border border-amber-400/25 bg-amber-400/[0.06] p-4 text-sm text-amber-100">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-300" />
          <div>JARVIS's brain isn't connected yet. Add <code className="rounded bg-white/10 px-1">OPENAI_API_KEY</code> to <code className="rounded bg-white/10 px-1">backend/.env</code>, or paste a key in <Link className="underline" to="/integrations">Integrations</Link>.</div>
        </div>
      )}
      {d && !d.user.onboarded && (
        <Link to="/onboarding" className="flex items-center justify-between rounded-2xl border border-violet-400/25 bg-violet-400/[0.06] p-4 text-sm text-violet-100 hover:bg-violet-400/10">
          <span className="flex items-center gap-2"><Sparkles className="h-4 w-4" /> Let JARVIS get to know you — 2 minute onboarding</span><ArrowRight className="h-4 w-4" />
        </Link>
      )}

      {d?.pending_actions?.length > 0 && (
        <Card title="Waiting for your confirmation">{d.pending_actions.map((a: any) => <ActionCard key={a.id} action={a} onResolved={load} />)}</Card>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2" title="Today's priorities" action={<Link to="/productivity" className="text-xs text-slate-400 hover:text-white">All tasks →</Link>}>
          {d?.priorities?.length ? (
            <ul className="space-y-1">
              {d.priorities.map((t: any) => (
                <li key={t.id} className="flex items-center gap-3 rounded-xl px-2 py-2 hover:bg-white/[0.03]">
                  <button onClick={() => toggleTask(t.id, true)} className="text-slate-500 hover:text-emerald-300"><Circle className="h-5 w-5" /></button>
                  <span className="flex-1 text-sm text-slate-200">{t.title}</span>
                  <span className={cn("chip", t.priority === "high" ? "text-rose-300" : t.priority === "low" ? "text-slate-400" : "text-amber-300")}>{t.priority}</span>
                  {t.due_at && <span className="hidden text-xs text-slate-500 sm:inline">{timeAgo(t.due_at)}</span>}
                </li>
              ))}
            </ul>
          ) : <Empty title="No open tasks" text='Tell JARVIS "add a task to finish my DBMS assignment by Friday".' />}
        </Card>

        <Card title="Reminders" action={<Bell className="h-4 w-4 text-slate-500" />}>
          {d?.reminders?.length ? (
            <ul className="space-y-3">
              {d.reminders.map((r: any) => (
                <li key={r.id} className="text-sm"><p className="text-slate-200">{r.text}</p><p className="text-xs text-slate-500">{fmtDateTime(r.remind_at)}</p></li>
              ))}
            </ul>
          ) : <p className="text-sm text-slate-500">No upcoming reminders.</p>}
        </Card>

        <Card title="Weekly progress">
          <div className="flex h-32 items-end gap-2">
            {(d?.weekly_progress || []).map((x: any) => (
              <div key={x.date} className="flex flex-1 flex-col items-center gap-1.5">
                <motion.div className="w-full rounded-md bg-gradient-to-t from-astra-blue/60 to-astra-violet/80" initial={{ height: 0 }}
                  animate={{ height: `${(x.done / maxDone) * 100}%` }} style={{ minHeight: 3 }} title={`${x.done} done`} />
                <span className="text-[10px] text-slate-500">{new Date(x.date).toLocaleDateString(undefined, { weekday: "narrow" })}</span>
              </div>
            ))}
          </div>
          <p className="mt-2 text-xs text-slate-500">Tasks completed per day</p>
        </Card>

        <Card title="Active projects" action={<Link to="/projects" className="text-xs text-slate-400 hover:text-white">All →</Link>}>
          {d?.projects?.length ? d.projects.map((p: any) => (
            <div key={p.id} className="mb-3 last:mb-0">
              <div className="mb-1 flex justify-between text-sm"><span className="flex items-center gap-2 text-slate-200"><FolderKanban className="h-3.5 w-3.5 text-slate-500" />{p.name}</span><span className="text-xs text-slate-500">{p.progress}%</span></div>
              <Progress value={p.progress} />
            </div>
          )) : <p className="text-sm text-slate-500">No active projects yet.</p>}
        </Card>

        <Card title="Recent conversations">
          {d?.recent_conversations?.length ? (
            <ul className="space-y-1">
              {d.recent_conversations.map((c: any) => (
                <li key={c.id}><Link to={`/chat/${c.id}`} className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-slate-300 hover:bg-white/[0.04]">
                  <MessageSquare className="h-3.5 w-3.5 shrink-0 text-slate-500" /><span className="flex-1 truncate">{c.title}</span><span className="text-[10px] text-slate-500">{timeAgo(c.updated_at)}</span>
                </Link></li>
              ))}
            </ul>
          ) : <p className="text-sm text-slate-500">Start your first conversation.</p>}
        </Card>
      </div>
    </div>
  );
}
