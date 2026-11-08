import { Bell, CalendarDays, CheckCircle2, Circle, ListTodo, MessageSquare, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Card, Empty, PageHeader, Tabs } from "../components/ui";
import { del, get, patch, post } from "../lib/api";
import type { Reminder, Task } from "../lib/types";
import { cn, fmtDateTime, fromLocalInput, parseDate, timeAgo } from "../lib/utils";

type Tab = "tasks" | "planner" | "reminders" | "calendar";
const PRIO = { high: "text-rose-300", medium: "text-amber-300", low: "text-slate-400" } as const;

export default function Productivity() {
  const [tab, setTab] = useState<Tab>("tasks");
  const [tasks, setTasks] = useState<Task[]>([]);
  const [rems, setRems] = useState<Reminder[]>([]);
  const [filter, setFilter] = useState<"open" | "done" | "all">("open");
  const [t, setT] = useState({ title: "", priority: "medium", due: "" });
  const [r, setR] = useState({ text: "", at: "" });
  const [google, setGoogle] = useState<boolean | null>(null);
  const navigate = useNavigate();

  const load = () => {
    get("/api/tasks").then((d) => setTasks(d.items));
    get("/api/reminders").then((d) => setRems(d.items));
  };
  useEffect(() => { load(); get("/api/integrations").then((d) => setGoogle(d.google.connected)); }, []);

  const addTask = async () => {
    if (!t.title.trim()) return;
    await post("/api/tasks", { title: t.title, priority: t.priority, due_at: fromLocalInput(t.due) });
    setT({ title: "", priority: "medium", due: "" });
    load();
  };
  const addRem = async () => {
    if (!r.text.trim() || !r.at) return;
    await post("/api/reminders", { text: r.text, remind_at: fromLocalInput(r.at) });
    setR({ text: "", at: "" });
    load();
  };

  const shown = tasks.filter((x) => (filter === "all" ? true : filter === "done" ? x.status === "done" : x.status !== "done"));
  const today = new Date();
  const days = Array.from({ length: 7 }, (_, i) => new Date(today.getFullYear(), today.getMonth(), today.getDate() + i));

  return (
    <div>
      <PageHeader title="Productivity" subtitle="Tasks, reminders and your week — JARVIS's executive mode can manage all of it by voice or chat."
        actions={<button className="btn-outline" onClick={() => navigate("/chat", { state: { prefill: "Give me my daily briefing and plan my day.", mode: "executive" } })}><MessageSquare className="h-4 w-4" /> Plan my day</button>} />
      <Tabs value={tab} onChange={setTab} tabs={[
        { id: "tasks", label: "Tasks", icon: <ListTodo className="h-4 w-4" /> },
        { id: "planner", label: "Week planner", icon: <CalendarDays className="h-4 w-4" /> },
        { id: "reminders", label: "Reminders", icon: <Bell className="h-4 w-4" /> },
        { id: "calendar", label: "Calendar", icon: <CalendarDays className="h-4 w-4" /> },
      ]} />

      {tab === "tasks" && (
        <Card>
          <form className="mb-4 grid gap-2 sm:grid-cols-[1fr_120px_200px_auto]" onSubmit={(e) => { e.preventDefault(); addTask(); }}>
            <input className="input" placeholder="New task…" value={t.title} onChange={(e) => setT({ ...t, title: e.target.value })} />
            <select className="input" value={t.priority} onChange={(e) => setT({ ...t, priority: e.target.value })}><option>high</option><option>medium</option><option>low</option></select>
            <input type="datetime-local" className="input" value={t.due} onChange={(e) => setT({ ...t, due: e.target.value })} />
            <button className="btn-primary"><Plus className="h-4 w-4" /> Add</button>
          </form>
          <div className="mb-3 flex gap-1">{(["open", "done", "all"] as const).map((f) => <button key={f} onClick={() => setFilter(f)} className={cn("chip capitalize", filter === f && "!text-white !border-violet-400/40")}>{f}</button>)}</div>
          {shown.length ? (
            <ul className="divide-y divide-white/[0.04]">
              {shown.map((x) => {
                const overdue = x.due_at && x.status !== "done" && parseDate(x.due_at)! < new Date();
                return (
                  <li key={x.id} className="group flex items-center gap-3 py-2.5">
                    <button onClick={async () => { await patch(`/api/tasks/${x.id}`, { status: x.status === "done" ? "todo" : "done" }); load(); }}>
                      {x.status === "done" ? <CheckCircle2 className="h-5 w-5 text-emerald-400" /> : <Circle className="h-5 w-5 text-slate-500 hover:text-emerald-300" />}
                    </button>
                    <span className={cn("flex-1 text-sm", x.status === "done" ? "text-slate-500 line-through" : "text-slate-200")}>{x.title}</span>
                    <span className={cn("chip", PRIO[x.priority])}>{x.priority}</span>
                    {x.due_at && <span className={cn("hidden text-xs sm:inline", overdue ? "text-rose-300" : "text-slate-500")}>{overdue ? "overdue · " : ""}{fmtDateTime(x.due_at)}</span>}
                    <button className="opacity-0 transition group-hover:opacity-100" onClick={async () => { await del(`/api/tasks/${x.id}`); load(); }}><Trash2 className="h-4 w-4 text-slate-500 hover:text-rose-300" /></button>
                  </li>
                );
              })}
            </ul>
          ) : <Empty title={filter === "done" ? "Nothing completed yet" : "All clear"} />}
        </Card>
      )}

      {tab === "planner" && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-7">
          {days.map((d) => {
            const key = d.toDateString();
            const dayTasks = tasks.filter((x) => x.due_at && parseDate(x.due_at)!.toDateString() === key);
            const dayRems = rems.filter((x) => !x.done && parseDate(x.remind_at)!.toDateString() === key);
            const isToday = key === today.toDateString();
            return (
              <div key={key} className={cn("glass min-h-[160px] rounded-2xl p-3", isToday && "!border-violet-400/40")}>
                <p className={cn("text-xs font-semibold uppercase tracking-wider", isToday ? "text-violet-300" : "text-slate-400")}>{d.toLocaleDateString(undefined, { weekday: "short" })} {d.getDate()}</p>
                <div className="mt-2 space-y-1.5">
                  {dayTasks.map((x) => <p key={x.id} className={cn("rounded-lg bg-white/[0.04] px-2 py-1 text-xs", x.status === "done" ? "text-slate-500 line-through" : "text-slate-200")}>{x.title}</p>)}
                  {dayRems.map((x) => <p key={x.id} className="rounded-lg bg-sky-400/10 px-2 py-1 text-xs text-sky-200">⏰ {x.text}</p>)}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {tab === "reminders" && (
        <Card>
          <form className="mb-4 grid gap-2 sm:grid-cols-[1fr_220px_auto]" onSubmit={(e) => { e.preventDefault(); addRem(); }}>
            <input className="input" placeholder="Remind me to…" value={r.text} onChange={(e) => setR({ ...r, text: e.target.value })} />
            <input type="datetime-local" className="input" value={r.at} onChange={(e) => setR({ ...r, at: e.target.value })} />
            <button className="btn-primary"><Plus className="h-4 w-4" /> Add</button>
          </form>
          {rems.length ? (
            <ul className="divide-y divide-white/[0.04]">
              {rems.map((x) => (
                <li key={x.id} className="group flex items-center gap-3 py-2.5">
                  <button onClick={async () => { await patch(`/api/reminders/${x.id}?done=${!x.done}`, {}); load(); }}>
                    {x.done ? <CheckCircle2 className="h-5 w-5 text-emerald-400" /> : <Bell className="h-5 w-5 text-sky-300" />}
                  </button>
                  <span className={cn("flex-1 text-sm", x.done ? "text-slate-500 line-through" : "text-slate-200")}>{x.text}</span>
                  <span className="text-xs text-slate-500">{fmtDateTime(x.remind_at)} · {timeAgo(x.remind_at)}</span>
                  <button className="opacity-0 group-hover:opacity-100" onClick={async () => { await del(`/api/reminders/${x.id}`); load(); }}><Trash2 className="h-4 w-4 text-slate-500 hover:text-rose-300" /></button>
                </li>
              ))}
            </ul>
          ) : <Empty title="No reminders" text="Say “remind me to call mom at 7pm” in chat." />}
          <p className="mt-4 text-xs text-slate-500">Reminders appear in the bell menu (and as browser notifications if you enable them) while JARVIS's backend is running.</p>
        </Card>
      )}

      {tab === "calendar" && (
        <Card>
          {google ? (
            <p className="text-sm text-slate-300">Google Calendar is connected. Ask JARVIS “what’s on my calendar this week?” or “schedule a study session tomorrow 6pm” — new events always ask for your confirmation first.</p>
          ) : (
            <Empty icon={<CalendarDays className="h-8 w-8" />} title="Google Calendar isn't connected" text="Connect it so JARVIS can read your schedule and propose events."
              action={<Link className="btn-primary" to="/integrations">Connect Google</Link>} />
          )}
        </Card>
      )}
    </div>
  );
}
