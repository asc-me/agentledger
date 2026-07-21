import * as React from "react";
import { Outlet } from "react-router-dom";

import { ProjectProvider, useProjectCtx } from "@/features/ProjectContext";
import { DocsReader } from "@/features/docs/DocsReader";
import { CreateFirstProject } from "@/features/onboarding/CreateFirstProject";

import { AgentSidebar } from "./AgentSidebar";
import { LeftNav } from "./LeftNav";
import { TopBar } from "./TopBar";

export function AppFrame() {
  return (
    <ProjectProvider>
      <FrameBody />
    </ProjectProvider>
  );
}

function FrameBody() {
  const { projects, loading } = useProjectCtx();
  const [agentOpen, setAgentOpen] = React.useState(true);
  const [search, setSearch] = React.useState("");

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center font-mono text-[12px] text-faint">
        loading…
      </div>
    );
  }

  // Freshly registered user (or a wiped database) has no workspace yet.
  if (projects.length === 0) return <CreateFirstProject />;

  return (
    <div className="flex h-full flex-col">
      <TopBar
        agentOpen={agentOpen}
        onToggleAgent={() => setAgentOpen((v) => !v)}
        search={search}
        onSearch={setSearch}
      />
      <div className="flex min-h-0 flex-1">
        <LeftNav />
        <main className="relative min-w-0 flex-1">
          <Outlet context={search} />
        </main>
        <AgentSidebar open={agentOpen} onClose={() => setAgentOpen(false)} />
      </div>
      <DocsReader />
    </div>
  );
}
