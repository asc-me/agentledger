import * as React from "react";
import { Outlet } from "react-router-dom";

import { ProjectProvider } from "@/features/ProjectContext";
import { DocsReader } from "@/features/docs/DocsReader";

import { AgentSidebar } from "./AgentSidebar";
import { LeftNav } from "./LeftNav";
import { TopBar } from "./TopBar";

export function AppFrame() {
  const [agentOpen, setAgentOpen] = React.useState(true);
  const [search, setSearch] = React.useState("");

  return (
    <ProjectProvider>
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
    </ProjectProvider>
  );
}
