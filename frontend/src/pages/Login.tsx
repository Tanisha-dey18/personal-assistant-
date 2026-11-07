import { motion } from "framer-motion";
import { useState } from "react";
import Orb from "../components/Orb";
import { Spinner } from "../components/ui";
import { post } from "../lib/api";
import { useStore } from "../lib/store";

export default function Login() {
  const login = useStore((s) => s.login);
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr("");
    setBusy(true);
    try {
      const r = await post(`/api/auth/${mode}`, mode === "login" ? { email, password } : { email, password, name });
      login(r.token, r.user);
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-full flex-col items-center justify-center px-4 py-10">
      <Orb size={150} />
      <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="mt-2 w-full max-w-sm text-center">
        <h1 className="font-display text-4xl font-bold tracking-[0.25em] text-white">ASTRA</h1>
        <p className="mt-1 text-sm text-slate-400">Adaptive Smart Thinking & Responsive Assistant</p>
        <p className="gradient-text mt-1 text-sm font-medium">Your mind, extended.</p>
        <form onSubmit={submit} className="card mt-8 space-y-3 text-left">
          {mode === "register" && <input className="input" placeholder="Your name" value={name} onChange={(e) => setName(e.target.value)} />}
          <input className="input" type="email" placeholder="Email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          <input className="input" type="password" placeholder="Password (8+ characters)" autoComplete={mode === "login" ? "current-password" : "new-password"}
            required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} />
          {err && <p className="text-sm text-rose-300">{err}</p>}
          <button className="btn-primary w-full !py-2.5" disabled={busy}>{busy && <Spinner />}{mode === "login" ? "Wake ASTRA" : "Create my ASTRA"}</button>
        </form>
        <button className="mt-4 text-sm text-slate-400 hover:text-white" onClick={() => { setMode(mode === "login" ? "register" : "login"); setErr(""); }}>
          {mode === "login" ? "First time? Create your account" : "Already have an account? Sign in"}
        </button>
      </motion.div>
    </div>
  );
}
