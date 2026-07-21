import * as React from "react";

import { useProjectCtx } from "@/features/ProjectContext";
import { cn } from "@/lib/cn";
import { useLinks } from "@/lib/queries";
import type { GraphLink, LinkType } from "@/lib/types";

const LINK_META: Record<LinkType, { label: string; color: string }> = {
  dependency: { label: "Dependency", color: "#c6f24e" },
  code: { label: "Code", color: "#7ca2ff" },
  semantic: { label: "Semantic", color: "#a78bfa" },
  tag: { label: "Tag", color: "#e0b34a" },
};
const LINK_TYPES = Object.keys(LINK_META) as LinkType[];

const W = 900;
const H = 560;

interface Pos {
  x: number;
  y: number;
}

/** Deterministic force-directed layout (no randomness — stable across renders). */
function computeLayout(ids: string[], edges: GraphLink[]): Record<string, Pos> {
  const n = ids.length;
  const cx = W / 2;
  const cy = H / 2;
  const r = Math.min(W, H) / 2.6;
  const pos: Record<string, Pos> = {};
  ids.forEach((id, i) => {
    const a = (2 * Math.PI * i) / Math.max(1, n);
    pos[id] = { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) };
  });

  const REST = 150;
  for (let iter = 0; iter < 300; iter++) {
    const disp: Record<string, Pos> = {};
    ids.forEach((id) => (disp[id] = { x: 0, y: 0 }));
    // Repulsion between all pairs.
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const u = ids[i];
        const v = ids[j];
        let dx = pos[u].x - pos[v].x;
        let dy = pos[u].y - pos[v].y;
        let d2 = dx * dx + dy * dy || 0.01;
        const f = 26000 / d2;
        const d = Math.sqrt(d2);
        dx /= d;
        dy /= d;
        disp[u].x += dx * f;
        disp[u].y += dy * f;
        disp[v].x -= dx * f;
        disp[v].y -= dy * f;
      }
    }
    // Springs along edges.
    for (const e of edges) {
      if (!pos[e.a] || !pos[e.b]) continue;
      let dx = pos[e.b].x - pos[e.a].x;
      let dy = pos[e.b].y - pos[e.a].y;
      const d = Math.hypot(dx, dy) || 0.01;
      const f = (d - REST) * 0.06;
      dx = (dx / d) * f;
      dy = (dy / d) * f;
      disp[e.a].x += dx;
      disp[e.a].y += dy;
      disp[e.b].x -= dx;
      disp[e.b].y -= dy;
    }
    // Center pull + integrate (capped step).
    for (const id of ids) {
      disp[id].x += (cx - pos[id].x) * 0.02;
      disp[id].y += (cy - pos[id].y) * 0.02;
      const step = 0.6;
      pos[id].x += Math.max(-14, Math.min(14, disp[id].x * step));
      pos[id].y += Math.max(-14, Math.min(14, disp[id].y * step));
    }
  }
  return pos;
}

export function LinksGraphView() {
  const { activeId } = useProjectCtx();
  const { data: links = [], isLoading } = useLinks(activeId);
  const [enabled, setEnabled] = React.useState<Record<LinkType, boolean>>({
    dependency: true, code: true, semantic: true, tag: true,
  });
  const [sel, setSel] = React.useState<{ kind: "node"; id: string } | { kind: "link"; id: number } | null>(null);

  const shown = links.filter((l) => enabled[l.type]);

  const ids = React.useMemo(() => {
    const s = new Set<string>();
    links.forEach((l) => {
      s.add(l.a);
      s.add(l.b);
    });
    return [...s].sort();
  }, [links]);

  const pos = React.useMemo(() => computeLayout(ids, links), [ids, links]);

  const nodeKind = (id: string) => (id.startsWith("R-") ? "request" : "item");

  // Highlight set for the current selection.
  const hl = React.useMemo(() => {
    if (!sel) return null;
    const nodes = new Set<string>();
    const edgeIds = new Set<number>();
    if (sel.kind === "node") {
      nodes.add(sel.id);
      shown.forEach((l) => {
        if (l.a === sel.id || l.b === sel.id) {
          edgeIds.add(l.id);
          nodes.add(l.a);
          nodes.add(l.b);
        }
      });
    } else {
      const l = links.find((x) => x.id === sel.id);
      if (l) {
        edgeIds.add(l.id);
        nodes.add(l.a);
        nodes.add(l.b);
      }
    }
    return { nodes, edgeIds };
  }, [sel, shown, links]);

  const selLink = sel?.kind === "link" ? links.find((l) => l.id === sel.id) : null;
  const selNodeLinks = sel?.kind === "node" ? shown.filter((l) => l.a === sel.id || l.b === sel.id) : [];

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex flex-none flex-wrap items-center gap-3 border-b border-line px-5 py-4">
        <div>
          <h1 className="text-[18px] font-semibold tracking-tight">Links</h1>
          <p className="mt-0.5 text-[12.5px] text-muted">
            Typed relationships between items and requests. Click a node or edge to inspect.
          </p>
        </div>
        <div className="ml-auto flex flex-wrap gap-1.5">
          {LINK_TYPES.map((t) => (
            <button
              key={t}
              onClick={() => setEnabled((e) => ({ ...e, [t]: !e[t] }))}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[11.5px] transition-colors",
                enabled[t] ? "border-line-hover bg-surface-3 text-fg" : "border-line-2 bg-surface-2 text-faint",
              )}
            >
              <span className="h-2 w-2 rounded-full" style={{ background: LINK_META[t].color, opacity: enabled[t] ? 1 : 0.35 }} />
              {LINK_META[t].label}
            </button>
          ))}
        </div>
      </div>

      <div className="relative min-h-0 flex-1 overflow-hidden">
        {isLoading ? (
          <div className="p-8 text-center text-[13px] text-muted">Loading graph…</div>
        ) : (
          <svg
            viewBox={`0 0 ${W} ${H}`}
            className="h-full w-full"
            onClick={() => setSel(null)}
          >
            {shown.map((l) => {
              const active = !hl || hl.edgeIds.has(l.id);
              const a = pos[l.a];
              const b = pos[l.b];
              if (!a || !b) return null;
              return (
                <line
                  key={l.id}
                  x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                  stroke={LINK_META[l.type].color}
                  strokeWidth={sel?.kind === "link" && sel.id === l.id ? 3 : 2}
                  strokeOpacity={active ? 0.7 : 0.12}
                  className="cursor-pointer"
                  onClick={(e) => {
                    e.stopPropagation();
                    setSel({ kind: "link", id: l.id });
                  }}
                />
              );
            })}
            {ids.map((id) => {
              const p = pos[id];
              if (!p) return null;
              const active = !hl || hl.nodes.has(id);
              const kind = nodeKind(id);
              const color = kind === "request" ? "#4fd6c4" : "#c6f24e";
              return (
                <g
                  key={id}
                  transform={`translate(${p.x},${p.y})`}
                  className="cursor-pointer"
                  opacity={active ? 1 : 0.25}
                  onClick={(e) => {
                    e.stopPropagation();
                    setSel({ kind: "node", id });
                  }}
                >
                  <circle r={8} fill={color} stroke="#0a0c0e" strokeWidth={2} />
                  <text x={12} y={4} fontSize={11} fontFamily="IBM Plex Mono, monospace" fill="#8b949e">
                    {id}
                  </text>
                </g>
              );
            })}
          </svg>
        )}

        {(selLink || (sel?.kind === "node")) && (
          <div className="absolute bottom-4 left-4 w-[320px] animate-fade rounded-[13px] border border-line-hover bg-surface-3/95 p-4 shadow-[0_20px_48px_rgba(0,0,0,0.5)]">
            {selLink ? (
              <>
                <div className="mb-1 flex items-center gap-2 font-mono text-[10px] uppercase tracking-wide" style={{ color: LINK_META[selLink.type].color }}>
                  <span className="h-1.5 w-1.5 rounded-full" style={{ background: LINK_META[selLink.type].color }} />
                  {LINK_META[selLink.type].label} · {Math.round(selLink.confidence * 100)}%
                </div>
                <div className="mb-1.5 font-mono text-[12px] text-fg-2">{selLink.a} ↔ {selLink.b}</div>
                <p className="text-[12.5px] leading-relaxed text-muted">{selLink.reason}</p>
              </>
            ) : (
              <>
                <div className="mb-1 font-mono text-[11px] text-faint">{(sel as { id: string }).id}</div>
                <div className="mb-2 font-mono text-[10px] uppercase tracking-wide text-faint">
                  {selNodeLinks.length} connection{selNodeLinks.length === 1 ? "" : "s"}
                </div>
                <div className="space-y-1.5">
                  {selNodeLinks.map((l) => (
                    <div key={l.id} className="flex items-center gap-2 text-[12px]">
                      <span className="h-1.5 w-1.5 flex-none rounded-full" style={{ background: LINK_META[l.type].color }} />
                      <span className="font-mono text-[10px] text-faint">
                        {l.a === (sel as { id: string }).id ? l.b : l.a}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-muted">{l.reason}</span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
