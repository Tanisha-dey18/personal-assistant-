import { motion } from "framer-motion";
import { Check, ShieldAlert, X } from "lucide-react";
import { useState } from "react";
import { post } from "../lib/api";
import type { PendingAction } from "../lib/types";
import { Spinner, toast } from "./ui";

const LABELS: Record<string, string> = {
  gmail_send: "Send email",
  calendar_create_event: "Create calendar event",
  forget_memory: "Delete memory",
};

/** Human-in-the-loop confirmation for consequential actions prepared by JARVIS. */
export default function ActionCard({ action, onResolved }: { action: PendingAction; onResolved?: (a: PendingAction) => void }) {
  const [state, setState] = useState(action);
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);

  const act = async (kind: "approve" | "reject") => {
    setBusy(kind);
    try {
      const r = await post<PendingAction>(`/api/actions/${state.id}/${kind}`);
      setState(r);
      onResolved?.(r);
      if (r.status === "failed") toast(`Action failed: ${r.result}`, "error");
    } catch (e: any) {
      toast(e.message, "error");
    } finally {
      setBusy(null);
    }
  };

  const done = state.status !== "pending";
  return (
    <motion.div initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }}
      className="my-2 rounded-xl border border-amber-400/25 bg-amber-400/[0.06] p-4">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-amber-300">
        <ShieldAlert className="h-4 w-4" /> {LABELS[state.tool] || state.tool} — needs your confirmation
      </div>
      <pre className="mt-2 whitespace-pre-wrap font-sans text-sm text-slate-200">{state.summary}</pre>
      {done ? (
        <p className={"mt-3 text-sm " + (state.status === "executed" ? "text-emerald-300" : state.status === "rejected" ? "text-slate-400" : "text-rose-300")}>
          {state.status === "executed" ? "✓ Done" : state.status === "rejected" ? "Cancelled" : `Failed: ${state.result}`}
        </p>
      ) : (
        <div className="mt-3 flex gap-2">
          <button className="btn-primary !py-1.5" disabled={!!busy} onClick={() => act("approve")}>
            {busy === "approve" ? <Spinner /> : <Check className="h-4 w-4" />} Confirm
          </button>
          <button className="btn-outline !py-1.5" disabled={!!busy} onClick={() => act("reject")}>
            {busy === "reject" ? <Spinner /> : <X className="h-4 w-4" />} Cancel
          </button>
        </div>
      )}
    </motion.div>
  );
}
