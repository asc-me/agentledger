import * as React from "react";
import { Outlet } from "react-router-dom";

import { ProjectProvider, useProjectCtx } from "@/features/ProjectContext";
import { DocsReader } from "@/features/docs/DocsReader";
import { CreateFirstOrg } from "@/features/onboarding/CreateFirstOrg";
import { CreateFirstProject } from "@/features/onboarding/CreateFirstProject";
import { useConfig, useOrgs } from "@/lib/queries";

import { AgentSidebar } from "./AgentSidebar";
import { LeftNav } from "./LeftNav";
import { TopBar } from "./TopBar";

function Loading() {
  return (
    <div className="flex h-full items-center justify-center font-mono text-[12px] text-faint">
      loading…
    </div>
  );
}

export function AppFrame() {
  // In hosted mode a user must belong to an org before any project can exist (a
  // project is created under an org). Gate on that first, ahead of the project gate.
  const { data: config, isLoading: configLoading } = useConfig();
  const hosted = config?.hosted_mode ?? false;
  const { data: orgs = [], isLoading: orgsLoading } = useOrgs(hosted);

  if (configLoading || (hosted && orgsLoading)) return <Loading />;
  if (hosted && orgs.length === 0) return <CreateFirstOrg />;

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

  if (loading) return <Loading />;

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
