import * as React from "react";

import type { RoadmapPhase } from "@/lib/types";

import { RoadmapBoard } from "./RoadmapBoard";

/** Public, read-only roadmap for the shareable link: /embed/roadmap */
export function EmbedRoadmapPage() {
  const [phases, setPhases] = React.useState<RoadmapPhase[] | null>(null);

  React.useEffect(() => {
    const project = new URLSearchParams(window.location.search).get("project");
    const url = project ? `/api/public/roadmap?project_id=${encodeURIComponent(project)}` : "/api/public/roadmap";
    fetch(url)
      .then((r) => (r.ok ? r.json() : []))
      .then(setPhases)
      .catch(() => setPhases([]));
  }, []);

  return (
    <div className="mx-auto max-w-5xl px-6 py-10">
      <div className="mb-6 flex items-center gap-2.5">
        <div
          className="flex h-7 w-7 items-center justify-center rounded-[7px]"
          style={{ background: "linear-gradient(150deg,#c6f24e,#8fd12e)" }}
        >
          <svg width="15" height="15" viewBox="0 0 16 16" fill="none">
            <path d="M3 2v12M3 4h8M3 8h6M3 12h9" stroke="#0a0c0e" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
        </div>
        <div>
          <div className="text-[15px] font-bold tracking-tight">AgentLedger Roadmap</div>
          <div className="font-mono text-[10px] tracking-[0.6px] text-faint">PUBLIC · READ ONLY</div>
        </div>
      </div>
      {phases === null ? (
        <div className="p-8 text-center text-[13px] text-muted">Loading…</div>
      ) : (
        <RoadmapBoard phases={phases} />
      )}
    </div>
  );
}
