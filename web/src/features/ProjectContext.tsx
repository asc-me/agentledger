import * as React from "react";

import { useProjects } from "@/lib/queries";
import type { Project } from "@/lib/types";

interface ProjectState {
  projects: Project[];
  active: Project | null;
  activeId: string;
  setActiveId: (id: string) => void;
  loading: boolean;
}

const Ctx = React.createContext<ProjectState | null>(null);

export function ProjectProvider({ children }: { children: React.ReactNode }) {
  const { data: projects = [], isLoading } = useProjects();
  const [activeId, setActiveId] = React.useState("");
  const active = projects.find((p) => p.id === activeId) ?? projects[0] ?? null;
  return (
    <Ctx.Provider
      value={{ projects, active, activeId: active?.id ?? activeId, setActiveId, loading: isLoading }}
    >
      {children}
    </Ctx.Provider>
  );
}

export function useProjectCtx() {
  const ctx = React.useContext(Ctx);
  if (!ctx) throw new Error("useProjectCtx must be used within ProjectProvider");
  return ctx;
}
