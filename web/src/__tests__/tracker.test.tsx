import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Outlet, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ProjectProvider } from "@/features/ProjectContext";
import { TrackerView } from "@/features/tracker/TrackerView";
import type { Item } from "@/lib/types";

const items: Item[] = [
  {
    id: "AL-01", project_id: "core", title: "In progress thing", description: "",
    status: "in_progress", tags: ["ai"], effort: 5, sort_order: 0, blocker: "", date: "Jul 19",
    reporter: { name: "Alex Cain", handle: "ascme", avatar: "#a78bfa" }, pr: null,
    created_at: "", updated_at: "",
  },
  {
    id: "AL-02", project_id: "core", title: "Finished thing", description: "",
    status: "done", tags: ["ui"], effort: 8, sort_order: 1, blocker: "", date: "Jul 14",
    reporter: { name: "Dana Ruiz", handle: "dev_ren", avatar: "#7ca2ff" }, pr: null,
    created_at: "", updated_at: "",
  },
];

vi.mock("@/lib/api", () => ({
  api: {
    projects: vi.fn(async () => []),
    items: vi.fn(async () => items),
    shards: vi.fn(async () => []),
    updateItem: vi.fn(async (id: string, body: Partial<Item>) => ({ ...items[0], id, ...body })),
    reorderItems: vi.fn(async () => items),
  },
}));

function renderTracker() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ProjectProvider>
        <MemoryRouter initialEntries={["/tracker"]}>
          <Routes>
            <Route element={<Outlet context={""} />}>
              <Route path="/tracker" element={<TrackerView />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </ProjectProvider>
    </QueryClientProvider>,
  );
}

describe("TrackerView", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders the linear stream", async () => {
    renderTracker();
    expect(await screen.findByText("In progress thing")).toBeInTheDocument();
    expect(screen.getByText("Finished thing")).toBeInTheDocument();
  });

  it("filters by status", async () => {
    const user = userEvent.setup();
    renderTracker();
    await screen.findByText("In progress thing");

    // The "Done" filter chip narrows the stream to done items only.
    await user.click(screen.getByRole("button", { name: /^Done/ }));
    expect(screen.queryByText("In progress thing")).not.toBeInTheDocument();
    expect(screen.getByText("Finished thing")).toBeInTheDocument();
  });

  it("changes an item status via the row status menu", async () => {
    const user = userEvent.setup();
    const { api } = await import("@/lib/api");
    renderTracker();
    const row = (await screen.findByText("In progress thing")).closest("div")!;

    // Open the compact status menu on the row and pick "Review".
    const statusBtn = within(row).getByRole("button");
    statusBtn.focus();
    await user.keyboard("{Enter}");
    const reviewItem = await screen.findByRole("menuitem", { name: /Review/ });
    await user.click(reviewItem);

    await waitFor(() => expect(api.updateItem).toHaveBeenCalledWith("AL-01", { status: "review" }));
  });
});
