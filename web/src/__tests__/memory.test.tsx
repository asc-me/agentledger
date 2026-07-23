import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentSidebar } from "@/components/shell/AgentSidebar";
import { ProjectProvider } from "@/features/ProjectContext";
import type { ShardHit } from "@/lib/types";

const hits: ShardHit[] = [
  {
    shard: {
      id: "m1", text: "Decided: use pgvector to keep self-host to one Postgres container.",
      scope: "global", source: "from AL-08", status: "published", origin: "user:ascme",
      item_id: null, project_id: "core", fresh: false, created_at: "",
    },
    score: 0.83,
  },
];

vi.mock("@/lib/api", () => ({
  setActiveProjectId: vi.fn(),
  api: {
    projects: vi.fn(async () => []),
    shards: vi.fn(async () => []),
    searchMemory: vi.fn(async () => hits),
    addShard: vi.fn(async () => hits[0].shard),
    chat: vi.fn(async () => ({ reply: "ok", shards: [] })),
  },
}));

function renderSidebar() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ProjectProvider>
        <AgentSidebar open onClose={() => {}} />
      </ProjectProvider>
    </QueryClientProvider>,
  );
}

describe("Memory panel", () => {
  beforeEach(() => vi.clearAllMocks());

  it("runs a semantic search and shows ranked results", async () => {
    const user = userEvent.setup();
    const { api } = await import("@/lib/api");
    renderSidebar();

    const input = screen.getByPlaceholderText(/Semantic search over memory/i);
    await user.type(input, "pgvector self-host{Enter}");

    expect(await screen.findByText(/keep self-host to one Postgres container/i)).toBeInTheDocument();
    expect(screen.getByText("0.83")).toBeInTheDocument();
    expect(api.searchMemory).toHaveBeenCalledWith("pgvector self-host", 5);
  });
});
