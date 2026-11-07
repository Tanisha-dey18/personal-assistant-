import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D from "react-force-graph-2d";
import { get } from "../lib/api";
import type { MemoryItem } from "../lib/types";
import { Empty, Spinner } from "./ui";

const TYPE_COLOR: Record<string, string> = {
  self: "#e0e7ff", person: "#f472b6", event: "#fbbf24", project: "#60a5fa", technology: "#22d3ee", skill: "#34d399",
  goal: "#a78bfa", achievement: "#facc15", organization: "#fb923c", place: "#94a3b8", course: "#f9a8d4", concept: "#c4b5fd", other: "#64748b",
};

type GNode = { id: string; name: string; type: string; degree: number; x?: number; y?: number };

export default function KnowledgeGraph() {
  const [data, setData] = useState<{ nodes: GNode[]; links: any[] } | null>(null);
  const [selected, setSelected] = useState<{ entity: any; memories: MemoryItem[] } | null>(null);
  const [filter, setFilter] = useState<string>("all");
  const wrap = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(800);

  useEffect(() => { get("/api/memory/graph/data").then(setData); }, []);
  useEffect(() => {
    const ro = new ResizeObserver(() => setW(wrap.current?.clientWidth || 800));
    if (wrap.current) ro.observe(wrap.current);
    return () => ro.disconnect();
  }, []);

  const graph = useMemo(() => {
    if (!data) return { nodes: [], links: [] };
    const nodes = filter === "all" ? data.nodes : data.nodes.filter((n) => n.type === filter || n.type === "self");
    const ids = new Set(nodes.map((n) => n.id));
    return { nodes: nodes.map((n) => ({ ...n })), links: data.links.filter((l) => ids.has(l.source) && ids.has(l.target)).map((l) => ({ ...l })) };
  }, [data, filter]);

  if (!data) return <div className="flex justify-center py-20"><Spinner /></div>;
  if (!data.nodes.length) return <Empty title="Your knowledge graph is empty" text="As you talk about people, projects, hackathons and skills, ASTRA links them here." />;
  const types = Array.from(new Set(data.nodes.map((n) => n.type)));

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
      <div className="card !p-0 overflow-hidden" ref={wrap}>
        <div className="flex flex-wrap gap-1.5 border-b border-white/[0.06] p-3">
          {["all", ...types].map((t) => (
            <button key={t} onClick={() => setFilter(t)} className={"chip " + (filter === t ? "!border-violet-400/40 !text-white" : "")}>
              {t !== "all" && <span className="h-2 w-2 rounded-full" style={{ background: TYPE_COLOR[t] || "#64748b" }} />}{t}
            </button>
          ))}
        </div>
        <ForceGraph2D
          graphData={graph}
          width={w}
          height={520}
          backgroundColor="rgba(0,0,0,0)"
          nodeRelSize={4}
          linkColor={() => "rgba(148,163,184,0.25)"}
          linkDirectionalArrowLength={3}
          linkDirectionalArrowRelPos={1}
          linkLabel={(l: any) => l.relation}
          cooldownTicks={120}
          onNodeClick={async (n: any) => setSelected(await get(`/api/memory/graph/entity/${n.id}`))}
          nodeCanvasObject={(n: any, ctx, scale) => {
            const r = 3 + Math.sqrt(n.degree || 1) * 2.2 + (n.type === "self" ? 4 : 0);
            const color = TYPE_COLOR[n.type] || "#64748b";
            ctx.beginPath();
            ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
            ctx.fillStyle = color;
            ctx.shadowColor = color;
            ctx.shadowBlur = 12;
            ctx.fill();
            ctx.shadowBlur = 0;
            const fs = Math.max(10 / scale, 2.5);
            if (scale > 0.8 || n.degree > 2 || n.type === "self") {
              ctx.font = `${fs}px Inter, sans-serif`;
              ctx.textAlign = "center";
              ctx.fillStyle = "rgba(226,232,240,0.9)";
              ctx.fillText(n.name, n.x, n.y + r + fs + 1);
            }
          }}
        />
      </div>
      <div className="card">
        {selected ? (
          <>
            <div className="flex items-center gap-2"><span className="h-3 w-3 rounded-full" style={{ background: TYPE_COLOR[selected.entity.type] }} />
              <h3 className="font-display text-lg font-semibold text-white">{selected.entity.name}</h3></div>
            <p className="text-xs uppercase tracking-wider text-slate-500">{selected.entity.type}</p>
            <div className="mt-4 space-y-2">
              {selected.memories.length ? selected.memories.map((m) => <div key={m.id} className="rounded-lg border border-white/[0.06] p-2.5 text-sm text-slate-300">{m.content}</div>)
                : <p className="text-sm text-slate-500">No memories linked.</p>}
            </div>
          </>
        ) : <p className="text-sm text-slate-500">Click a node to see what ASTRA knows about it. Drag to rearrange, scroll to zoom.</p>}
      </div>
    </div>
  );
}
