import { Bot, Brain, Download, Mic, Shield, Sparkles, Volume2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Card, Field, PageHeader, Spinner, Toggle, toast } from "../components/ui";
import { get, patch, post } from "../lib/api";
import { useStore } from "../lib/store";
import { VoicePlayer } from "../lib/voice";

export default function Settings() {
  const [s, setS] = useState<any>(null);
  const [meta, setMeta] = useState<any>(null);
  const [usage, setUsage] = useState<any>(null);
  const [status, setStatus] = useState<any>(null);
  const [name, setName] = useState("");
  const { user, setUser, logout, setLevel } = useStore();
  const [pw, setPw] = useState({ current: "", next: "" });
  const [wipe, setWipe] = useState({ scope: "memories", password: "" });

  useEffect(() => {
    get("/api/settings").then((r) => { setS(r.settings); setMeta(r); });
    get("/api/usage").then(setUsage);
    get("/api/status").then(setStatus);
    setName(user?.name || "");
  }, [user]);

  const save = async (p: any) => {
    try {
      const r = await patch("/api/settings", p);
      setS(r.settings);
    } catch (e: any) { toast(e.message, "error"); }
  };

  const exportAll = async () => {
    const data = await get("/api/export");
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `astra-export-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
  };

  if (!s) return <div className="flex justify-center py-20"><Spinner /></div>;
  const P = s.personality, V = s.voice, M = s.memory, PR = s.proactive;

  return (
    <div>
      <PageHeader title="AI settings" subtitle="Shape JARVIS's personality, brain, voice, memory and privacy." />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title={<span className="flex items-center gap-2"><Sparkles className="h-4 w-4" /> Personality</span>}>
          <div className="space-y-4">
            <Field label={`Sarcasm · ${Math.round(P.sarcasm * 100)}%`}><input type="range" min={0} max={1} step={0.1} value={P.sarcasm} className="w-full accent-violet-500" onChange={(e) => save({ personality: { sarcasm: +e.target.value } })} /></Field>
            <Field label="Verbosity"><select className="input" value={P.verbosity} onChange={(e) => save({ personality: { verbosity: e.target.value } })}><option>concise</option><option>balanced</option><option>detailed</option></select></Field>
            <Field label="Default mode"><select className="input" value={s.default_mode} onChange={(e) => save({ default_mode: e.target.value })}>
              <option value="auto">Auto</option>{meta.modes.map((m: any) => <option key={m.id} value={m.id}>{m.label}</option>)}</select></Field>
            <Toggle checked={P.hinglish} onChange={(v) => save({ personality: { hinglish: v } })} label="Hinglish" hint="Understand and reply in Hinglish when you use it" />
            <Field label="Learning level"><select className="input" value={s.learning.level} onChange={(e) => save({ learning: { level: e.target.value } })}><option>beginner</option><option>intermediate</option><option>advanced</option></select></Field>
            <Field label="Teaching style"><input className="input" defaultValue={s.learning.style} onBlur={(e) => save({ learning: { style: e.target.value } })} /></Field>
            <Field label="Custom instructions" hint="Anything JARVIS should always keep in mind."><textarea className="input" defaultValue={P.custom_instructions} onBlur={(e) => save({ personality: { custom_instructions: e.target.value } })} /></Field>
          </div>
        </Card>

        <Card title={<span className="flex items-center gap-2"><Bot className="h-4 w-4" /> Brain</span>}>
          <div className="space-y-4">
            <div className="flex flex-wrap gap-1.5 text-xs">
              <span className={"chip " + (status?.ai_configured ? "text-emerald-300" : "text-amber-300")}>{status?.ai_configured ? "AI connected" : "No AI key — see Integrations"}</span>
              <span className="chip">DB: {status?.database}</span><span className="chip">Vectors: {status?.vector_store}</span><span className="chip">Cache: {status?.cache}</span>
            </div>
            <Field label="Chat model"><select className="input" value={s.model || ""} onChange={(e) => save({ model: e.target.value || null })}>
              <option value="">Server default ({meta.default_model})</option>{meta.available_models.map((m: string) => <option key={m}>{m}</option>)}</select></Field>
            <Field label={`Creativity (temperature) · ${s.temperature}`} hint="Ignored by reasoning models (gpt-5, o-series)."><input type="range" min={0} max={1.2} step={0.1} value={s.temperature} className="w-full accent-violet-500" onChange={(e) => save({ temperature: +e.target.value })} /></Field>
            <Field label="Timezone"><input className="input" defaultValue={s.timezone} onBlur={(e) => save({ timezone: e.target.value })} placeholder="Asia/Kolkata" /></Field>
            <div>
              <p className="label">API usage · last 30 days</p>
              <p className="text-2xl font-semibold text-white">{usage?.total_tokens?.toLocaleString() ?? "–"} <span className="text-sm font-normal text-slate-500">tokens</span></p>
              <div className="mt-2 space-y-1">{usage?.items?.map((u: any, i: number) => (
                <div key={i} className="flex justify-between text-xs text-slate-400"><span>{u.kind} · {u.model}</span><span>{u.calls} calls · {(u.prompt_tokens + u.completion_tokens).toLocaleString()} tok</span></div>
              ))}</div>
            </div>
          </div>
        </Card>

        <Card title={<span className="flex items-center gap-2"><Mic className="h-4 w-4" /> Voice</span>}>
          <div className="space-y-4">
            <Field label="Voice"><div className="flex gap-2">
              <select className="input" value={V.voice} onChange={(e) => save({ voice: { voice: e.target.value } })}>{meta.voices.map((v: string) => <option key={v}>{v}</option>)}</select>
              <button className="btn-outline shrink-0" onClick={() => new VoicePlayer(setLevel).speak(`Hey${user?.name ? " " + user.name.split(" ")[0] : ""}, I'm JARVIS. This is how I sound.`, V.voice, V.speed)}><Volume2 className="h-4 w-4" /> Preview</button>
            </div></Field>
            <Field label={`Speed · ${V.speed}x`}><input type="range" min={0.7} max={1.4} step={0.05} value={V.speed} className="w-full accent-violet-500" onChange={(e) => save({ voice: { speed: +e.target.value } })} /></Field>
            <Toggle checked={V.auto_speak} onChange={(v) => save({ voice: { auto_speak: v } })} label="Speak replies by default" hint="Voice messages always get spoken replies" />
            <Toggle checked={V.hands_free} onChange={(v) => save({ voice: { hands_free: v } })} label="Hands-free conversation" hint="After JARVIS speaks, the mic re-opens automatically. Never listens in the background." />
          </div>
        </Card>

        <Card title={<span className="flex items-center gap-2"><Brain className="h-4 w-4" /> Memory & proactivity</span>}>
          <Toggle checked={M.auto_save} onChange={(v) => save({ memory: { auto_save: v } })} label="Learn automatically from conversations" hint="Off = every extracted fact waits in Pending for approval" />
          <Toggle checked={M.ask_before_sensitive} onChange={(v) => save({ memory: { ask_before_sensitive: v } })} label="Ask before storing sensitive info" hint="Health, finances, relationships… (always encrypted)" />
          <Field label={`Memories per reply · ${M.max_context_memories}`}><input type="range" min={4} max={30} value={M.max_context_memories} className="w-full accent-violet-500" onChange={(e) => save({ memory: { max_context_memories: +e.target.value } })} /></Field>
          <div className="mt-4 border-t border-white/[0.06] pt-3">
            <Toggle checked={PR.enabled} onChange={(v) => save({ proactive: { enabled: v } })} label="Proactive nudges" />
            {PR.enabled && <div className="pl-3">
              <Toggle checked={PR.reminders} onChange={(v) => save({ proactive: { reminders: v } })} label="Reminders" />
              <Toggle checked={PR.task_deadlines} onChange={(v) => save({ proactive: { task_deadlines: v } })} label="Task deadlines" />
              <Toggle checked={PR.stale_projects} onChange={(v) => save({ proactive: { stale_projects: v } })} label="Stale project check-ins" />
              <Toggle checked={PR.career_followups} onChange={(v) => save({ proactive: { career_followups: v } })} label="Application follow-ups" />
              <Toggle checked={PR.weekly_report} onChange={(v) => save({ proactive: { weekly_report: v } })} label="Weekly report (Sundays)" />
            </div>}
          </div>
        </Card>

        <Card title={<span className="flex items-center gap-2"><Shield className="h-4 w-4" /> Account & privacy</span>} className="lg:col-span-2">
          <div className="grid gap-6 md:grid-cols-3">
            <div className="space-y-2">
              <Field label="Display name"><input className="input" value={name} onChange={(e) => setName(e.target.value)} /></Field>
              <button className="btn-outline" onClick={async () => { const u = await patch("/api/auth/me", { name }); setUser(u); toast("Saved"); }}>Save name</button>
              <div className="pt-3">
                <p className="label">Change password</p>
                <input className="input mb-2" type="password" placeholder="Current" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} />
                <input className="input mb-2" type="password" placeholder="New (8+)" value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} />
                <button className="btn-outline" onClick={async () => { try { await post("/api/auth/password", { current_password: pw.current, new_password: pw.next }); toast("Password changed"); setPw({ current: "", next: "" }); } catch (e: any) { toast(e.message, "error"); } }}>Update password</button>
              </div>
            </div>
            <div>
              <p className="label">Your data</p>
              <p className="mb-3 text-sm text-slate-400">Download everything JARVIS stores about you (memories decrypted, conversations, tasks, projects…). Credentials are never exported.</p>
              <button className="btn-outline" onClick={exportAll}><Download className="h-4 w-4" /> Export all data (JSON)</button>
            </div>
            <div>
              <p className="label text-rose-300">Danger zone</p>
              <select className="input mb-2" value={wipe.scope} onChange={(e) => setWipe({ ...wipe, scope: e.target.value })}>
                <option value="memories">Erase all memories & knowledge graph</option>
                <option value="conversations">Erase all conversation history</option>
                <option value="everything">Erase ALL personal data (keep account)</option>
              </select>
              <input className="input mb-2" type="password" placeholder="Confirm with password" value={wipe.password} onChange={(e) => setWipe({ ...wipe, password: e.target.value })} />
              <div className="flex flex-wrap gap-2">
                <button className="btn-danger" onClick={async () => {
                  if (!confirm("This permanently deletes the selected data. It cannot be undone. Continue?")) return;
                  try { await post("/api/data/wipe", wipe); toast("Erased."); setWipe({ ...wipe, password: "" }); } catch (e: any) { toast(e.message, "error"); }
                }}>Erase</button>
                <button className="btn-danger" onClick={async () => {
                  if (!confirm("Delete your account and ALL data forever? This cannot be undone.")) return;
                  try { await post("/api/auth/delete-account", { password: wipe.password }); logout(); } catch (e: any) { toast(e.message, "error"); }
                }}>Delete account</button>
              </div>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}
