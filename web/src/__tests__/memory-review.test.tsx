import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { MemoryReviewView } from "@/features/memory/MemoryReviewView";
import { ProjectProvider } from "@/features/ProjectContext";
import type { Shard } from "@/lib/types";

const candidate: Shard = {
  id: "m9", text: "Agent guess: batch writes for perf.", scope: "item", source: "lesson from AL-12",
  status: "candidate", origin: "agent:loop-agent", item_id: "AL-12", project_id: "core",
  fresh: true, created_at: "",
};

// Hoisted so the (hoisted) vi.mock factory can reference the spy eagerly.
const { publishSpy } = vi.hoisted(() => ({ publishSpy: vi.fn(async () => ({})) }));

vi.mock("@/lib/api", () => ({
  setActiveProjectId: vi.fn(),
  api: {
    projects: vi.fn(async () => []),
    candidateShards: vi.fn(async () => [candidate]),
    publishShard: publishSpy,
    rejectShard: vi.fn(async () => ({ ...candidate, status: "rejected" })),
  },
}));

describe("Memory review queue", () => {
  it("shows candidates and publishes one", async () => {
    const user = userEvent.setup();
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <ProjectProvider>
          <MemoryReviewView />
        </ProjectProvider>
      </QueryClientProvider>,
    );

    expect(await screen.findByText(/Agent guess: batch writes/)).toBeInTheDocument();
    expect(screen.getByText("agent:loop-agent")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Publish/ }));
    expect(publishSpy).toHaveBeenCalledWith("m9");
  });
});
