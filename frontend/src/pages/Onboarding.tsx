import { AnimatePresence, motion } from "framer-motion";
import { ArrowLeft, ArrowRight, Sparkles } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import Orb from "../components/Orb";
import { Spinner, toast } from "../components/ui";
import { post } from "../lib/api";
import { useStore } from "../lib/store";

const STEPS = [
  { key: "name", q: "First things first — what should I call you?", ph: "e.g. Tanisha" },
  { key: "education", q: "What are you studying, and where?", ph: "e.g. B.Tech Computer Science, 3rd year, XYZ Institute of Technology (graduating 2027)" },
  { key: "current_focus", q: "What are you focused on these days?", ph: "e.g. Machine learning, DSA for placements, building my portfolio" },
  { key: "skills", q: "What skills do you already have?", ph: "e.g. Python, FastAPI, SQL, basic React, pandas" },
  { key: "projects", q: "What have you built (or are building)?", ph: "e.g. StudyBuddy — FastAPI + React app for exam prep; a sentiment analysis model for a hackathon" },
  { key: "career_goals", q: "Where do you want your career to go?", ph: "e.g. ML engineer at a product company; summer internship in 2026" },
  { key: "interests", q: "What do you enjoy outside of work?", ph: "e.g. F1, indie music, sketching, chai-fuelled late-night coding" },
  { key: "learning_style", q: "How do you like things explained?", ph: "e.g. Intuition first with analogies, then the math, then code" },
] as const;

export default function Onboarding() {
  const navigate = useNavigate();
  const { user, setUser } = useStore();
  const [i, setI] = useState(0);
  const [data, setData] = useState<Record<string, string>>({ name: user?.name || "" });
  const [busy, setBusy] = useState(false);
  const step = STEPS[i];
  const last = i === STEPS.length - 1;

  const finish = async () => {
    setBusy(true);
    try {
      const r = await post("/api/onboarding", { ...data, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone });
      toast(`🧠 JARVIS now knows ${r.created.length} things about you.`);
      setUser({ ...user!, name: data.name || user!.name, onboarded: true });
      navigate("/chat");
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const skip = async () => {
    await post("/api/onboarding/skip");
    setUser({ ...user!, onboarded: true });
    navigate("/");
  };

  return (
    <div className="flex min-h-full flex-col items-center justify-center px-4 py-10">
      <Orb size={110} />
      <div className="mt-2 w-full max-w-xl">
        <div className="mb-6 flex items-center gap-1">
          {STEPS.map((_, k) => <div key={k} className={"h-1 flex-1 rounded-full transition " + (k <= i ? "bg-gradient-to-r from-astra-blue to-astra-violet" : "bg-white/10")} />)}
        </div>
        <AnimatePresence mode="wait">
          <motion.div key={i} initial={{ opacity: 0, x: 20 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -20 }} transition={{ duration: 0.25 }}>
            <p className="mb-2 flex items-center gap-2 text-xs uppercase tracking-widest text-violet-300"><Sparkles className="h-3.5 w-3.5" /> Getting to know you · {i + 1}/{STEPS.length}</p>
            <h2 className="font-display text-2xl font-semibold text-white sm:text-3xl">{step.q}</h2>
            <textarea autoFocus className="input mt-5 min-h-[110px] text-base" placeholder={step.ph} value={data[step.key] || ""}
              onChange={(e) => setData({ ...data, [step.key]: e.target.value })}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); last ? finish() : setI(i + 1); } }} />
            <p className="mt-2 text-xs text-slate-500">Skip anything you like. You can always tell me more in chat or import your CV & ChatGPT history later.</p>
          </motion.div>
        </AnimatePresence>
        <div className="mt-6 flex items-center justify-between">
          <button className="btn-ghost" onClick={() => (i ? setI(i - 1) : skip())}>{i ? <><ArrowLeft className="h-4 w-4" /> Back</> : "Skip for now"}</button>
          {last ? (
            <button className="btn-primary" disabled={busy} onClick={finish}>{busy && <Spinner />} Finish & meet JARVIS</button>
          ) : (
            <button className="btn-primary" onClick={() => setI(i + 1)}>Next <ArrowRight className="h-4 w-4" /></button>
          )}
        </div>
      </div>
    </div>
  );
}
