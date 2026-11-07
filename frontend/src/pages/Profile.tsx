import { Lock, RefreshCw, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Markdown from "../components/Markdown";
import MemoryCard from "../components/MemoryCard";
import { Card, Empty, PageHeader, Spinner, toast } from "../components/ui";
import { get, post } from "../lib/api";
import type { MemoryItem } from "../lib/types";
import { timeAgo } from "../lib/utils";

type Knowledge = {
  sections: { key: string; title: string; items: MemoryItem[] }[];
  total: number;
  pending: MemoryItem[];
  needs_review: MemoryItem[];
  portrait: string;
  portrait_generated_at: string | null;
};

export default function Profile() {
  const [k, setK] = useState<Knowledge | null>(null);
  const [synth, setSynth] = useState(false);
  const load = () => get<Knowledge>("/api/memory/profile/knowledge").then(setK);
  useEffect(() => { load(); }, []);

  const synthesize = async () => {
    setSynth(true);
    try {
      await post("/api/memory/profile/synthesize");
      await load();
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setSynth(false);
    }
  };

  if (!k) return <div className="flex justify-center py-20"><Spinner /></div>;
  const filled = k.sections.filter((s) => s.items.length);

  return (
    <div>
      <PageHeader title="What ASTRA knows about me" subtitle={`Built live from ${k.total} memories. Edit anything that's wrong — ASTRA uses the corrected version immediately.`}
        actions={<button className="btn-primary" onClick={synthesize} disabled={synth || !k.total}>{synth ? <Spinner /> : <Sparkles className="h-4 w-4" />} {k.portrait ? "Regenerate portrait" : "Generate portrait"}</button>} />

      {k.portrait && (
        <Card className="mb-6" title="ASTRA's portrait of you" action={<span className="flex items-center gap-1 text-xs text-slate-500"><RefreshCw className="h-3 w-3" /> {timeAgo(k.portrait_generated_at)}</span>}>
          <Markdown text={k.portrait} />
        </Card>
      )}

      {(k.pending.length > 0 || k.needs_review.length > 0) && (
        <div className="mb-6 grid gap-6 md:grid-cols-2">
          {k.pending.length > 0 && (
            <Card title={<span className="flex items-center gap-2"><Lock className="h-4 w-4 text-rose-300" /> Sensitive — needs your OK</span>}>
              <p className="mb-3 text-xs text-slate-500">ASTRA won't use these until you approve them. They're stored encrypted.</p>
              <div className="space-y-2">{k.pending.map((m) => <MemoryCard key={m.id} m={m} compact onChange={load} onDelete={load} />)}</div>
            </Card>
          )}
          {k.needs_review.length > 0 && (
            <Card title="Assumptions to confirm">
              <p className="mb-3 text-xs text-slate-500">ASTRA inferred these but isn't sure. Confirm, fix or delete.</p>
              <div className="space-y-2">{k.needs_review.slice(0, 8).map((m) => <MemoryCard key={m.id} m={m} onChange={load} onDelete={load} />)}</div>
            </Card>
          )}
        </div>
      )}

      {filled.length === 0 ? (
        <Empty title="ASTRA doesn't know much about you yet" text="Chat naturally, run onboarding, or import your CV / notes / ChatGPT history."
          action={<div className="flex gap-2"><Link to="/onboarding" className="btn-primary">Start onboarding</Link><Link to="/import" className="btn-outline">Import knowledge</Link></div>} />
      ) : (
        <div className="grid gap-6 md:grid-cols-2">
          {filled.map((s) => (
            <Card key={s.key} title={`${s.title} · ${s.items.length}`}>
              <div className="space-y-2">{s.items.map((m) => <MemoryCard key={m.id} m={m} compact onChange={load} onDelete={load} />)}</div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
