import { AnimatePresence, motion } from "framer-motion";
import {
  Brain, ChevronDown, History, Mic, MicOff, Pin, Plus, Search, Send, Square, Trash2, Volume2, VolumeX, Wrench, X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import ActionCard from "../components/ActionCard";
import Markdown from "../components/Markdown";
import Orb from "../components/Orb";
import { Spinner, toast } from "../components/ui";
import { del, get, patch } from "../lib/api";
import { useStore } from "../lib/store";
import type { ChatMessage, Conversation, MemoryItem } from "../lib/types";
import { MODE_COLORS, MODES } from "../lib/types";
import { cn, timeAgo } from "../lib/utils";
import { VoicePlayer, VoiceRecorder, transcribe } from "../lib/voice";
import { ChatSocket, ServerEvent } from "../lib/ws";

const SUGGESTIONS = [
  "Hey Jarvis, what's going on?",
  "I'm bored. Talk to me.",
  "Explain logistic regression like I'm smart but sleepy",
  "Plan my day around my open tasks",
  "Be brutally honest: what should I focus on this semester?",
];

const TOOL_LABEL: Record<string, string> = {
  search_memory: "Searching memory", save_memory: "Saving memory", update_memory: "Updating memory", web_search: "Searching the web",
  read_webpage: "Reading page", get_weather: "Checking weather", create_task: "Creating task", list_tasks: "Checking tasks",
  create_reminder: "Setting reminder", daily_briefing: "Building briefing", calendar_list_events: "Reading calendar",
  gmail_search: "Reading Gmail", github_list_repos: "Reading GitHub", github_repo_activity: "Reading GitHub",
  search_documents: "Searching documents", upsert_project: "Updating project", add_career_item: "Updating career tracker",
};

function ConversationList({ activeId, onPick, onClose }: { activeId?: string; onPick: (id?: string) => void; onClose?: () => void }) {
  const [items, setItems] = useState<Conversation[]>([]);
  const [q, setQ] = useState("");
  const load = useCallback(() => get<{ items: Conversation[] }>(`/api/conversations?limit=100${q ? `&q=${encodeURIComponent(q)}` : ""}`).then((d) => setItems(d.items)).catch(() => {}), [q]);
  useEffect(() => { load(); }, [load, activeId]);
  useEffect(() => {
    const h = () => load();
    window.addEventListener("astra:conversations", h);
    return () => window.removeEventListener("astra:conversations", h);
  }, [load]);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 p-3">
        <button className="btn-primary flex-1 !py-2" onClick={() => { onPick(undefined); onClose?.(); }}><Plus className="h-4 w-4" /> New chat</button>
        {onClose && <button className="btn-ghost !p-2" onClick={onClose}><X className="h-4 w-4" /></button>}
      </div>
      <div className="relative px-3 pb-2">
        <Search className="absolute left-6 top-2.5 h-3.5 w-3.5 text-slate-500" />
        <input className="input !py-2 !pl-8 !text-xs" placeholder="Search conversations" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <div className="flex-1 space-y-0.5 overflow-y-auto px-2 pb-4">
        {items.map((c) => (
          <div key={c.id} className={cn("group flex items-center gap-1 rounded-lg px-2.5 py-2 text-sm transition", c.id === activeId ? "bg-white/[0.07] text-white" : "text-slate-400 hover:bg-white/[0.04]")}>
            <button className="min-w-0 flex-1 text-left" onClick={() => { onPick(c.id); onClose?.(); }}>
              <div className="flex items-center gap-1.5 truncate">{c.pinned && <Pin className="h-3 w-3 shrink-0 text-violet-300" />}<span className="truncate">{c.title}</span></div>
              <div className="text-[10px] text-slate-500">{c.source === "chatgpt" ? "imported · " : ""}{timeAgo(c.updated_at)}</div>
            </button>
            <button className="hidden !p-1 text-slate-500 hover:text-violet-300 group-hover:block" title="Pin" onClick={async () => { await patch(`/api/conversations/${c.id}`, { pinned: !c.pinned }); load(); }}><Pin className="h-3.5 w-3.5" /></button>
            <button className="hidden !p-1 text-slate-500 hover:text-rose-300 group-hover:block" title="Delete" onClick={async () => {
              if (!confirm("Delete this conversation? Memories extracted from it are kept.")) return;
              await del(`/api/conversations/${c.id}`); if (c.id === activeId) onPick(undefined); load();
            }}><Trash2 className="h-3.5 w-3.5" /></button>
          </div>
        ))}
        {items.length === 0 && <p className="px-3 py-6 text-center text-xs text-slate-500">No conversations yet.</p>}
      </div>
    </div>
  );
}

export default function Chat() {
  const { id: routeId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { user, orb, setOrb, setLevel } = useStore();
  const [convId, setConvId] = useState<string | undefined>(routeId);
  const [title, setTitle] = useState("New conversation");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [mode, setMode] = useState<string>("auto");
  const [activeMode, setActiveMode] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<ChatSocket["status"]>("connecting");
  const [modeMenu, setModeMenu] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [voiceOn, setVoiceOn] = useState(false); // speak replies
  const [handsFree, setHandsFree] = useState(false);
  const [recording, setRecording] = useState(false);
  const [contextPanel, setContextPanel] = useState<MemoryItem[] | null>(null);
  const [voiceSettings, setVoiceSettings] = useState<{ voice?: string; speed?: number }>({});

  const sock = useRef<ChatSocket>();
  const recorder = useRef<VoiceRecorder>();
  const player = useRef<VoicePlayer>();
  const scroller = useRef<HTMLDivElement>(null);
  const lastWasVoice = useRef(false);
  const convRef = useRef(convId);
  convRef.current = convId;
  const handsFreeRef = useRef(handsFree);
  handsFreeRef.current = handsFree;
  const voiceOnRef = useRef(voiceOn);
  voiceOnRef.current = voiceOn;
  const voiceSettingsRef = useRef(voiceSettings);
  voiceSettingsRef.current = voiceSettings;
  const sendRef = useRef<(t: string, v?: boolean) => void>(() => {});
  const prefillDone = useRef<string | null>(null);

  // settings → defaults for mode + voice
  useEffect(() => {
    get("/api/settings").then((s) => {
      setMode(s.settings.default_mode || "auto");
      setVoiceOn(!!s.settings.voice.auto_speak);
      setHandsFree(!!s.settings.voice.hands_free);
      setVoiceSettings({ voice: s.settings.voice.voice, speed: s.settings.voice.speed });
    }).catch(() => {});
  }, []);

  // load conversation from route
  useEffect(() => {
    setConvId(routeId);
    if (!routeId) { setMessages([]); setTitle("New conversation"); setActiveMode(null); return; }
    if (routeId === convRef.current && messages.length) return;
    get(`/api/conversations/${routeId}`).then((d) => {
      setTitle(d.conversation.title);
      setMessages(d.messages);
      const lastA = [...d.messages].reverse().find((m: ChatMessage) => m.role === "assistant");
      setActiveMode(lastA?.mode || null);
    }).catch(() => navigate("/chat"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeId]);

  const startListening = useCallback(async () => {
    if (recorder.current?.active) return;
    player.current?.stop(); // interrupt JARVIS if she's talking
    try {
      setRecording(true);
      setOrb("listening");
      const done = await recorder.current!.start();
      const blob = await done;
      setRecording(false);
      if (!blob || blob.size < 2000) { setOrb("idle"); return; }
      setOrb("thinking");
      const text = await transcribe(blob);
      if (!text.trim()) { setOrb("idle"); return; }
      lastWasVoice.current = true;
      sendRef.current(text, true);
    } catch (e: any) {
      setRecording(false);
      setOrb("idle");
      toast(e?.name === "NotAllowedError" ? "Microphone permission denied." : e.message || "Voice failed", "error");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // socket + voice engines
  useEffect(() => {
    const s = new ChatSocket();
    s.onStatus = setStatus;
    s.connect();
    sock.current = s;
    recorder.current = new VoiceRecorder((l) => setLevel(l));
    player.current = new VoicePlayer((l) => setLevel(l));

    const off = s.on((ev: ServerEvent) => {
      switch (ev.type) {
        case "start":
          setActiveMode(ev.mode);
          if (!convRef.current) {
            convRef.current = ev.conversation_id;
            setConvId(ev.conversation_id);
            navigate(`/chat/${ev.conversation_id}`, { replace: true });
          }
          setMessages((m) => [...m, { id: "streaming", role: "assistant", content: "", streaming: true, mode: ev.mode, tools: [], pending: [] }]);
          break;
        case "context":
          setMessages((m) => m.map((x) => (x.id === "streaming" ? { ...x, memories: ev.memories } : x)));
          break;
        case "token":
          setOrb("thinking");
          setMessages((m) => m.map((x) => (x.id === "streaming" ? { ...x, content: x.content + ev.content } : x)));
          break;
        case "tool":
          setMessages((m) => m.map((x) => {
            if (x.id !== "streaming") return x;
            const tools = [...(x.tools || [])];
            const i = tools.findIndex((t) => t.name === ev.name && t.status === "running");
            if (i >= 0) tools[i] = { name: ev.name, status: ev.status, error: ev.error };
            else tools.push({ name: ev.name, status: ev.status, error: ev.error });
            return { ...x, tools };
          }));
          break;
        case "pending_action":
          setMessages((m) => m.map((x) => (x.id === "streaming" ? { ...x, pending: [...(x.pending || []), ev.action] } : x)));
          break;
        case "done": {
          setBusy(false);
          let finalText = "";
          setMessages((m) => m.map((x) => {
            if (x.id !== "streaming") return x;
            finalText = ev.message.content;
            return { ...x, ...ev.message, streaming: false };
          }));
          window.dispatchEvent(new Event("astra:conversations"));
          const shouldSpeak = voiceOnRef.current || lastWasVoice.current;
          lastWasVoice.current = false;
          if (shouldSpeak && finalText) {
            setOrb("speaking");
            player.current!.speak(finalText, voiceSettingsRef.current.voice, voiceSettingsRef.current.speed).finally(() => {
              setOrb("idle");
              if (handsFreeRef.current) setTimeout(() => startListening(), 300);
            });
          } else setOrb("idle");
          break;
        }
        case "title":
          setTitle(ev.title);
          window.dispatchEvent(new Event("astra:conversations"));
          break;
        case "memory_update": {
          const n = ev.created.length + ev.updated.length;
          if (n) toast(`🧠 Remembered ${n} thing${n > 1 ? "s" : ""}: ${[...ev.created, ...ev.updated][0].content.slice(0, 70)}…`);
          if (ev.pending.length) toast(`🔒 ${ev.pending.length} sensitive memory awaiting your approval (Memory → Pending)`);
          break;
        }
        case "error":
          setBusy(false);
          setOrb("idle");
          setMessages((m) => m.filter((x) => !(x.id === "streaming" && !x.content)).map((x) => (x.id === "streaming" ? { ...x, id: `e${Date.now()}`, streaming: false } : x)));
          toast(ev.message, "error");
          if (ev.code === "ai_unavailable") setMessages((m) => [...m, { id: `sys${Date.now()}`, role: "system", content: ev.message }]);
          break;
      }
    });
    return () => { off(); s.close(); player.current?.stop(); recorder.current?.stop(); setOrb("idle"); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const sendText = (text: string, voice = false) => {
    const t = text.trim();
    if (!t || busy) return;
    setBusy(true);
    setOrb("thinking");
    setMessages((m) => [...m, { id: `u${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, role: "user", content: t, meta: { voice } }]);
    sock.current!.send({ type: "chat", content: t, conversation_id: convRef.current, mode, voice });
    setInput("");
  };
  sendRef.current = sendText;

  // Prefilled prompt from other pages (Home quick-chat, "Ask mentor", etc.)
  useEffect(() => {
    const st = location.state as { prefill?: string; mode?: string } | null;
    if (!st?.prefill || prefillDone.current === location.key) return;
    prefillDone.current = location.key;
    if (st.mode) setMode(st.mode);
    const text = st.prefill;
    navigate(location.pathname, { replace: true, state: null });
    setTimeout(() => {
      setBusy(true);
      setOrb("thinking");
      setMessages((m) => [...m, { id: `u${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, role: "user", content: text }]);
      sock.current!.send({ type: "chat", content: text, conversation_id: convRef.current, mode: st.mode || mode });
    }, 50);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.state]);

  const toggleMic = () => {
    if (recording) recorder.current?.stop();
    else startListening();
  };

  const modeInfo = useMemo(() => MODES.find((m) => m.id === mode)!, [mode]);
  const empty = messages.length === 0;

  return (
    <div className="flex h-full">
      {/* history (desktop) */}
      <aside className="hidden w-64 shrink-0 border-r border-white/[0.06] xl:block">
        <ConversationList activeId={convId} onPick={(id) => navigate(id ? `/chat/${id}` : "/chat")} />
      </aside>
      <AnimatePresence>
        {historyOpen && (
          <motion.div className="fixed inset-0 z-40 bg-black/60 xl:hidden" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setHistoryOpen(false)}>
            <motion.div className="glass-strong h-full w-72" initial={{ x: -300 }} animate={{ x: 0 }} exit={{ x: -300 }} onClick={(e) => e.stopPropagation()}>
              <ConversationList activeId={convId} onPick={(id) => navigate(id ? `/chat/${id}` : "/chat")} onClose={() => setHistoryOpen(false)} />
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="relative flex min-w-0 flex-1 flex-col">
        {/* top bar */}
        <div className="flex items-center gap-2 border-b border-white/[0.06] px-3 py-2 sm:px-5">
          <button className="btn-ghost !p-2 xl:hidden" onClick={() => setHistoryOpen(true)} title="History"><History className="h-4 w-4" /></button>
          <div className="min-w-0 flex-1 truncate text-sm text-slate-300">{title}</div>
          <span className={cn("hidden items-center gap-1.5 text-[11px] sm:flex", status === "online" ? "text-emerald-400" : status === "connecting" ? "text-amber-400" : "text-rose-400")}>
            <span className="h-1.5 w-1.5 rounded-full bg-current" /> {status}
          </span>
          <button className={cn("btn-ghost !p-2", voiceOn && "text-sky-300")} title={voiceOn ? "Voice replies on" : "Voice replies off"} onClick={() => { setVoiceOn((v) => !v); player.current?.stop(); }}>
            {voiceOn ? <Volume2 className="h-4 w-4" /> : <VolumeX className="h-4 w-4" />}
          </button>
          <div className="relative">
            <button className="btn-outline !px-3 !py-1.5 text-xs" onClick={() => setModeMenu((o) => !o)}>
              <span className={cn("h-2 w-2 rounded-full bg-gradient-to-r", MODE_COLORS[activeMode || "companion"])} />
              {modeInfo.label}{mode === "auto" && activeMode ? ` · ${MODES.find((m) => m.id === activeMode)?.label}` : ""}
              <ChevronDown className="h-3.5 w-3.5" />
            </button>
            <AnimatePresence>
              {modeMenu && (
                <motion.div initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
                  className="glass-strong absolute right-0 top-10 z-30 w-64 rounded-xl p-1.5 shadow-2xl">
                  {MODES.map((m) => (
                    <button key={m.id} onClick={() => { setMode(m.id); setModeMenu(false); }}
                      className={cn("flex w-full items-start gap-2.5 rounded-lg px-3 py-2 text-left hover:bg-white/[0.06]", mode === m.id && "bg-white/[0.06]")}>
                      <span className={cn("mt-1.5 h-2 w-2 shrink-0 rounded-full bg-gradient-to-r", m.id === "auto" ? "from-slate-300 to-slate-500" : MODE_COLORS[m.id])} />
                      <span><span className="block text-sm text-slate-100">{m.label}</span><span className="block text-[11px] text-slate-500">{m.hint}</span></span>
                    </button>
                  ))}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>

        {/* messages */}
        <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto">
          {empty ? (
            <div className="flex h-full flex-col items-center justify-center px-4 text-center">
              <Orb size={170} onClick={toggleMic} />
              <h2 className="mt-2 font-display text-2xl font-semibold text-white sm:text-3xl">
                {user?.name ? `Hey ${user.name.split(" ")[0]}.` : "Hey there."} <span className="gradient-text">What's on your mind?</span>
              </h2>
              <p className="mt-2 text-sm text-slate-500">Type, or tap the orb to talk. I remember what matters.</p>
              <div className="mt-6 flex max-w-2xl flex-wrap justify-center gap-2">
                {SUGGESTIONS.map((s) => (
                  <button key={s} className="glass rounded-full px-3.5 py-1.5 text-xs text-slate-300 transition hover:border-white/20 hover:text-white" onClick={() => sendText(s)}>{s}</button>
                ))}
              </div>
            </div>
          ) : (
            <div className="mx-auto w-full max-w-3xl space-y-6 px-4 py-6 sm:px-6">
              {messages.map((m) => (
                <motion.div key={m.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }}>
                  {m.role === "user" ? (
                    <div className="flex justify-end">
                      <div className="max-w-[85%] rounded-2xl rounded-br-md bg-gradient-to-br from-astra-blue/25 to-astra-violet/20 px-4 py-2.5 text-[15px] text-slate-100 ring-1 ring-white/10">
                        {m.meta?.voice && <Mic className="mr-1.5 inline h-3.5 w-3.5 text-sky-300" />}
                        <span className="whitespace-pre-wrap">{m.content}</span>
                      </div>
                    </div>
                  ) : m.role === "system" ? (
                    <div className="rounded-xl border border-amber-400/20 bg-amber-400/[0.06] p-4 text-sm text-amber-100">
                      {m.content} <Link to="/integrations" className="ml-1 underline">Set up the AI key →</Link>
                    </div>
                  ) : (
                    <div className="flex gap-3">
                      <div className="mt-1 h-7 w-7 shrink-0 rounded-full bg-gradient-to-br from-sky-300 via-indigo-500 to-violet-700 shadow-glow-sm" />
                      <div className="min-w-0 flex-1">
                        <div className="mb-1 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                          <span className="font-semibold tracking-wider text-slate-300">JARVIS</span>
                          {m.mode && <span className={cn("rounded-full bg-gradient-to-r px-2 py-px text-[10px] font-semibold text-ink-950", MODE_COLORS[m.mode])}>{MODES.find((x) => x.id === m.mode)?.label}</span>}
                          {!!m.memories?.length && (
                            <button className="flex items-center gap-1 hover:text-violet-300" onClick={() => setContextPanel(m.memories!)}>
                              <Brain className="h-3 w-3" /> {m.memories.length} memories used
                            </button>
                          )}
                          {!m.memories && m.meta?.memory_ids?.length > 0 && <span className="flex items-center gap-1"><Brain className="h-3 w-3" /> {m.meta.memory_ids.length} memories used</span>}
                        </div>
                        {(m.tools?.length || 0) > 0 && (
                          <div className="mb-2 flex flex-wrap gap-1.5">
                            {m.tools!.map((t, i) => (
                              <span key={i} className={cn("chip", t.status === "error" ? "text-rose-300" : t.status === "running" ? "text-sky-300" : "text-slate-400")} title={t.error}>
                                {t.status === "running" ? <Spinner className="h-3 w-3" /> : <Wrench className="h-3 w-3" />}
                                {TOOL_LABEL[t.name] || t.name}{t.status === "awaiting_confirmation" ? " · awaiting you" : t.status === "error" ? " · failed" : ""}
                              </span>
                            ))}
                          </div>
                        )}
                        {m.streaming && !m.content ? (
                          <div className="flex items-center gap-1.5 py-2">
                            {[0, 1, 2].map((i) => <motion.span key={i} className="h-1.5 w-1.5 rounded-full bg-violet-300" animate={{ opacity: [0.2, 1, 0.2], y: [0, -3, 0] }} transition={{ repeat: Infinity, duration: 1, delay: i * 0.15 }} />)}
                          </div>
                        ) : (
                          <Markdown text={m.content} streaming={m.streaming} />
                        )}
                        {m.pending?.map((a) => <ActionCard key={a.id} action={a} onResolved={() => window.dispatchEvent(new Event("astra:conversations"))} />)}
                      </div>
                    </div>
                  )}
                </motion.div>
              ))}
            </div>
          )}
        </div>

        {/* composer */}
        <div className="border-t border-white/[0.06] bg-ink-950/60 px-3 pb-[max(12px,env(safe-area-inset-bottom))] pt-3 backdrop-blur-xl sm:px-6">
          <div className="mx-auto flex max-w-3xl items-end gap-2">
            {!empty && (
              <div className="mb-1 hidden h-11 w-11 shrink-0 items-center justify-center sm:flex"><Orb size={30} onClick={toggleMic} /></div>
            )}
            <div className="glass flex min-w-0 flex-1 items-end gap-1 rounded-2xl p-1.5 focus-within:border-astra-blue/40">
              <textarea
                className="max-h-48 min-h-[40px] flex-1 resize-none bg-transparent px-2.5 py-2 text-[15px] text-slate-100 outline-none placeholder:text-slate-500"
                placeholder={recording ? "Listening… (stops when you pause)" : `Message JARVIS${mode !== "auto" ? ` · ${modeInfo.label}` : ""}`}
                rows={1}
                value={input}
                onChange={(e) => { setInput(e.target.value); e.target.style.height = "auto"; e.target.style.height = Math.min(e.target.scrollHeight, 192) + "px"; }}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendText(input); } }}
              />
              {orb === "speaking" && (
                <button className="btn-ghost !p-2.5 text-violet-300" title="Stop speaking" onClick={() => { player.current?.stop(); setOrb("idle"); }}><Square className="h-4 w-4" /></button>
              )}
              <button className={cn("btn !p-2.5", recording ? "bg-rose-500/20 text-rose-300 ring-1 ring-rose-400/40" : "btn-ghost")}
                title={recording ? "Stop recording" : "Talk to JARVIS"} onClick={toggleMic} disabled={busy && !recording}>
                {recording ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
              </button>
              <button className="btn-primary !p-2.5" onClick={() => sendText(input)} disabled={!input.trim() || busy} title="Send">
                {busy ? <Spinner /> : <Send className="h-4 w-4" />}
              </button>
            </div>
          </div>
          <div className="mx-auto mt-1.5 flex max-w-3xl items-center justify-between px-1 text-[11px] text-slate-600">
            <label className="flex cursor-pointer items-center gap-1.5">
              <input type="checkbox" className="accent-violet-500" checked={handsFree} onChange={(e) => setHandsFree(e.target.checked)} />
              Hands-free (keep listening after replies)
            </label>
            <span className="hidden sm:inline">Mic is only on while the orb is listening.</span>
          </div>
        </div>

        {/* memories-used side panel */}
        <AnimatePresence>
          {contextPanel && (
            <motion.div initial={{ x: 400 }} animate={{ x: 0 }} exit={{ x: 400 }} transition={{ type: "spring", damping: 30, stiffness: 300 }}
              className="glass-strong absolute inset-y-0 right-0 z-30 w-full max-w-sm overflow-y-auto p-5 shadow-2xl">
              <div className="mb-4 flex items-center justify-between">
                <h3 className="font-display font-semibold text-white">Memories JARVIS used</h3>
                <button className="btn-ghost !p-1.5" onClick={() => setContextPanel(null)}><X className="h-4 w-4" /></button>
              </div>
              <p className="mb-4 text-xs text-slate-500">Only these were sent to the model for that reply — not your whole memory.</p>
              <div className="space-y-2">{contextPanel.map((m) => (
                <div key={m.id} className="rounded-xl border border-white/[0.06] p-3 text-sm text-slate-300">
                  {m.content}
                  <div className="mt-1.5 flex gap-1.5"><span className="chip">{m.category}</span>{m.score != null && <span className="chip text-violet-300">{Math.round(m.score * 100)}% match</span>}</div>
                </div>
              ))}</div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
