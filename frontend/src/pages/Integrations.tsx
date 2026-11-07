import { CalendarDays, CheckCircle2, CloudSun, Github, KeyRound, Mail, Search, XCircle } from "lucide-react";
import { ReactNode, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Card, PageHeader, Spinner, toast } from "../components/ui";
import { del, get, post } from "../lib/api";
import { cn } from "../lib/utils";

function Status({ ok, label }: { ok: boolean; label?: string }) {
  return (
    <span className={cn("chip", ok ? "text-emerald-300" : "text-slate-400")}>
      {ok ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />} {label || (ok ? "Connected" : "Not connected")}
    </span>
  );
}

function Block({ icon, title, desc, status, children }: { icon: ReactNode; title: string; desc: string; status: ReactNode; children: ReactNode }) {
  return (
    <Card>
      <div className="flex items-start gap-4">
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-white/[0.05] text-slate-200">{icon}</div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-display text-base font-semibold text-white">{title}</h3>{status}</div>
          <p className="mt-1 text-sm text-slate-400">{desc}</p>
          <div className="mt-4">{children}</div>
        </div>
      </div>
    </Card>
  );
}

function KeyForm({ placeholder, onSubmit, extra }: { placeholder: string; onSubmit: (v: string, extra?: string) => Promise<void>; extra?: string }) {
  const [v, setV] = useState("");
  const [x, setX] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <form className="flex flex-col gap-2 sm:flex-row" onSubmit={async (e) => { e.preventDefault(); setBusy(true); try { await onSubmit(v, x); setV(""); } finally { setBusy(false); } }}>
      <input className="input" type="password" autoComplete="off" placeholder={placeholder} value={v} onChange={(e) => setV(e.target.value)} />
      {extra && <input className="input sm:max-w-[220px]" placeholder={extra} value={x} onChange={(e) => setX(e.target.value)} />}
      <button className="btn-primary shrink-0" disabled={busy || v.length < 10}>{busy && <Spinner />} Save</button>
    </form>
  );
}

export default function Integrations() {
  const [d, setD] = useState<any>(null);
  const [params, setParams] = useSearchParams();
  const load = () => get("/api/integrations").then(setD);
  useEffect(() => { load(); }, []);
  useEffect(() => {
    const g = params.get("google");
    if (g) {
      toast(g === "connected" ? "Google connected ✓" : "Google connection failed — try again.", g === "connected" ? "ok" : "error");
      setParams({}, { replace: true });
    }
  }, [params, setParams]);

  const disconnect = async (p: string) => { if (confirm(`Disconnect ${p}? Stored credentials will be deleted.`)) { await del(`/api/integrations/${p}`); load(); } };
  const wrap = async (fn: () => Promise<any>, ok: string) => { try { await fn(); toast(ok); load(); } catch (e: any) { toast(e.message, "error"); } };

  if (!d) return <div className="flex justify-center py-20"><Spinner /></div>;
  return (
    <div>
      <PageHeader title="Integrations" subtitle="Credentials are encrypted on the server and never sent to the browser. ASTRA always asks before sending emails or creating events." />
      <div className="grid gap-5 lg:grid-cols-2">
        <Block icon={<KeyRound className="h-5 w-5" />} title="AI brain (OpenAI-compatible)" desc="Powers chat, memory extraction, embeddings and voice. A server key in backend/.env works for everyone; a personal key here overrides it for your account."
          status={<Status ok={d.openai.connected || d.openai.server_key} label={d.openai.connected ? `Personal key ${d.openai.meta.key_hint}` : d.openai.server_key ? "Using server key" : "Not configured"} />}>
          <KeyForm placeholder="sk-…" extra="Base URL (optional)" onSubmit={(v, x) => wrap(() => post("/api/integrations/openai", { api_key: v, base_url: x || "" }), "AI key verified & saved")} />
          {d.openai.connected && <button className="btn-ghost mt-2 !px-2 text-xs" onClick={() => disconnect("openai")}>Remove personal key</button>}
          <p className="mt-2 text-xs text-slate-500">Get a key at platform.openai.com → API keys. Base URL lets you use OpenRouter, Groq, Together or a local Ollama.</p>
        </Block>

        <Block icon={<div className="flex gap-0.5"><CalendarDays className="h-4 w-4" /><Mail className="h-4 w-4" /></div>} title="Google Calendar & Gmail"
          desc="Read your schedule and inbox, draft emails and propose events. Sending and creating always require your confirmation."
          status={<Status ok={d.google.connected} label={d.google.connected ? d.google.meta.email : undefined} />}>
          {!d.google.server_configured ? (
            <p className="text-sm text-amber-200/80">Server not set up for Google yet: add <code className="rounded bg-white/10 px-1">GOOGLE_CLIENT_ID</code> and <code className="rounded bg-white/10 px-1">GOOGLE_CLIENT_SECRET</code> to backend/.env (see README). Redirect URI: <code className="break-all rounded bg-white/10 px-1">{d.google.redirect_uri}</code></p>
          ) : d.google.connected ? (
            <button className="btn-outline" onClick={() => disconnect("google")}>Disconnect</button>
          ) : (
            <button className="btn-primary" onClick={() => wrap(async () => { const r = await get("/api/integrations/google/auth-url"); window.location.href = r.url; }, "Redirecting to Google…")}>Connect Google</button>
          )}
        </Block>

        <Block icon={<Github className="h-5 w-5" />} title="GitHub" desc="Lets ASTRA see your repositories, recent commits and open issues (read-only)."
          status={<Status ok={d.github.connected} label={d.github.connected ? `@${d.github.meta.login}` : undefined} />}>
          {d.github.connected ? <button className="btn-outline" onClick={() => disconnect("github")}>Disconnect</button> : (
            <>
              <KeyForm placeholder="github_pat_… (fine-grained token, read-only)" onSubmit={(v) => wrap(() => post("/api/integrations/github", { token: v }), "GitHub connected")} />
              <p className="mt-2 text-xs text-slate-500">GitHub → Settings → Developer settings → Fine-grained tokens. Grant read-only access to Contents, Issues, Metadata.</p>
            </>
          )}
        </Block>

        <Block icon={<Search className="h-5 w-5" />} title="Web search (Tavily)" desc="Enables Research mode to search the live web and cite sources. Reading a specific URL works without it."
          status={<Status ok={d.tavily.connected || d.tavily.server_key} label={d.tavily.connected ? `Key ${d.tavily.meta.key_hint}` : d.tavily.server_key ? "Using server key" : undefined} />}>
          <KeyForm placeholder="tvly-…" onSubmit={(v) => wrap(() => post("/api/integrations/tavily", { api_key: v }), "Search key saved")} />
          {d.tavily.connected && <button className="btn-ghost mt-2 !px-2 text-xs" onClick={() => disconnect("tavily")}>Remove key</button>}
          <p className="mt-2 text-xs text-slate-500">Free tier at tavily.com (1,000 searches/month).</p>
        </Block>

        <Block icon={<CloudSun className="h-5 w-5" />} title="Weather" desc="Current conditions and 3-day forecast via Open-Meteo." status={<Status ok label="Always on — no key needed" />}>
          <p className="text-xs text-slate-500">Try: “What's the weather in Kolkata tomorrow?”</p>
        </Block>
      </div>
    </div>
  );
}
