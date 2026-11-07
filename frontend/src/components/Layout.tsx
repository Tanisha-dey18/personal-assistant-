import { AnimatePresence, motion } from "framer-motion";
import {
  Bell, Brain, Briefcase, CalendarCheck, FolderKanban, Home, LogOut, Menu, MessageSquare, Plug, Settings, Sparkles, Upload, UserRound, X,
} from "lucide-react";
import { ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { get, post } from "../lib/api";
import { useStore } from "../lib/store";
import { cn, timeAgo } from "../lib/utils";

const NAV = [
  { to: "/", label: "Home", icon: Home },
  { to: "/chat", label: "Chat", icon: MessageSquare },
  { to: "/me", label: "What ASTRA knows", icon: UserRound },
  { to: "/memory", label: "Memory", icon: Brain },
  { to: "/career", label: "Career", icon: Briefcase },
  { to: "/projects", label: "Projects", icon: FolderKanban },
  { to: "/productivity", label: "Productivity", icon: CalendarCheck },
  { to: "/import", label: "Knowledge import", icon: Upload },
  { to: "/integrations", label: "Integrations", icon: Plug },
  { to: "/settings", label: "AI settings", icon: Settings },
];

function Logo() {
  return (
    <div className="flex items-center gap-3 px-2">
      <div className="relative h-8 w-8">
        <div className="absolute inset-0 rounded-full bg-gradient-to-br from-sky-300 via-indigo-500 to-violet-700 shadow-glow" />
        <div className="absolute inset-[30%] rounded-full bg-white/70 blur-[3px]" />
      </div>
      <div>
        <div className="font-display text-lg font-bold tracking-[0.2em] text-white">ASTRA</div>
        <div className="-mt-0.5 text-[10px] tracking-wider text-slate-500">Your mind, extended.</div>
      </div>
    </div>
  );
}

function NavList({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="mt-8 flex flex-col gap-0.5">
      {NAV.map(({ to, label, icon: Icon }) => (
        <NavLink key={to} to={to} end={to === "/"} onClick={onNavigate}
          className={({ isActive }) => cn("group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition",
            isActive ? "text-white" : "text-slate-400 hover:bg-white/[0.04] hover:text-slate-200")}>
          {({ isActive }) => (
            <>
              {isActive && <motion.span layoutId="nav-active" className="absolute inset-0 rounded-xl border border-white/10 bg-gradient-to-r from-astra-blue/15 to-astra-violet/10" transition={{ type: "spring", duration: 0.45 }} />}
              <Icon className={cn("relative h-4 w-4", isActive && "text-sky-300")} />
              <span className="relative">{label}</span>
            </>
          )}
        </NavLink>
      ))}
    </nav>
  );
}

type Notif = { id: string; kind: string; title: string; body: string; read: boolean; created_at: string };

function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<{ items: Notif[]; unread: number }>({ items: [], unread: 0 });
  const seen = useRef<Set<string>>(new Set());
  const first = useRef(true);

  const load = useCallback(async () => {
    try {
      const d = await get<{ items: Notif[]; unread: number }>("/api/notifications");
      setData(d);
      // Browser notifications for new unread items (only if the user granted permission)
      if (!first.current && "Notification" in window && Notification.permission === "granted") {
        d.items.filter((n) => !n.read && !seen.current.has(n.id)).forEach((n) => new Notification(n.title, { body: n.body, icon: "/favicon.svg" }));
      }
      d.items.forEach((n) => seen.current.add(n.id));
      first.current = false;
    } catch { /* offline */ }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [load]);

  return (
    <div className="relative">
      <button className="btn-ghost relative !p-2" onClick={() => setOpen((o) => !o)} aria-label="Notifications">
        <Bell className="h-5 w-5" />
        {data.unread > 0 && <span className="absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-violet-500 px-1 text-[10px] font-bold text-white">{data.unread}</span>}
      </button>
      <AnimatePresence>
        {open && (
          <motion.div initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }}
            className="glass-strong absolute right-0 top-12 z-40 w-[min(92vw,380px)] rounded-2xl p-2 shadow-2xl">
            <div className="flex items-center justify-between px-3 py-2">
              <span className="text-sm font-semibold text-white">Notifications</span>
              <div className="flex gap-1">
                {"Notification" in window && Notification.permission === "default" && (
                  <button className="btn-ghost !px-2 !py-1 text-xs" onClick={() => Notification.requestPermission()}>Enable alerts</button>
                )}
                <button className="btn-ghost !px-2 !py-1 text-xs" onClick={async () => { await post("/api/notifications/read-all"); load(); }}>Mark all read</button>
              </div>
            </div>
            <div className="max-h-[60vh] overflow-y-auto">
              {data.items.length === 0 && <p className="px-3 py-8 text-center text-sm text-slate-500">Nothing yet. ASTRA will nudge you about reminders, deadlines and stale projects.</p>}
              {data.items.map((n) => (
                <div key={n.id} className={cn("rounded-xl px-3 py-2.5", !n.read && "bg-white/[0.04]")}>
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm text-slate-100">{n.title}</p>
                    <span className="shrink-0 text-[10px] text-slate-500">{timeAgo(n.created_at)}</span>
                  </div>
                  {n.body && <p className="mt-0.5 whitespace-pre-wrap text-xs text-slate-400">{n.body}</p>}
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export default function Layout({ children }: { children: ReactNode }) {
  const { user, logout } = useStore();
  const [drawer, setDrawer] = useState(false);
  const loc = useLocation();
  const isChat = loc.pathname.startsWith("/chat");

  return (
    <div className="flex h-full">
      {/* Desktop sidebar */}
      <aside className="hidden w-64 shrink-0 flex-col border-r border-white/[0.06] bg-ink-950/60 p-4 backdrop-blur-xl lg:flex">
        <Logo />
        <NavList />
        <div className="mt-auto rounded-xl border border-white/[0.06] p-3">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-slate-600 to-slate-800 text-sm font-semibold">
              {(user?.name || user?.email || "?")[0].toUpperCase()}
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm text-slate-200">{user?.name || "You"}</div>
              <div className="truncate text-[11px] text-slate-500">{user?.email}</div>
            </div>
            <button className="btn-ghost !p-1.5" title="Sign out" onClick={logout}><LogOut className="h-4 w-4" /></button>
          </div>
        </div>
      </aside>

      {/* Mobile drawer */}
      <AnimatePresence>
        {drawer && (
          <motion.div className="fixed inset-0 z-50 bg-black/60 lg:hidden" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setDrawer(false)}>
            <motion.aside initial={{ x: -300 }} animate={{ x: 0 }} exit={{ x: -300 }} transition={{ type: "spring", damping: 30, stiffness: 300 }}
              className="glass-strong flex h-full w-72 flex-col p-4" onClick={(e) => e.stopPropagation()}>
              <div className="flex items-center justify-between"><Logo /><button className="btn-ghost !p-1.5" onClick={() => setDrawer(false)}><X className="h-5 w-5" /></button></div>
              <NavList onNavigate={() => setDrawer(false)} />
              <button className="btn-ghost mt-auto justify-start" onClick={logout}><LogOut className="h-4 w-4" /> Sign out</button>
            </motion.aside>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-white/[0.06] px-3 sm:px-5">
          <div className="flex items-center gap-2">
            <button className="btn-ghost !p-2 lg:hidden" onClick={() => setDrawer(true)} aria-label="Menu"><Menu className="h-5 w-5" /></button>
            <span className="flex items-center gap-1.5 text-xs text-slate-500"><Sparkles className="h-3.5 w-3.5 text-violet-400" />
              {new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}
            </span>
          </div>
          <NotificationBell />
        </header>
        <main className={cn("min-h-0 flex-1", isChat ? "overflow-hidden" : "overflow-y-auto")}>
          {isChat ? children : <div className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 sm:py-8">{children}</div>}
        </main>
      </div>
    </div>
  );
}
