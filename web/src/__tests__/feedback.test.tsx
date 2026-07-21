import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FeedbackWidget } from "@/features/feedback/FeedbackWidget";
import { DEFAULT_CONFIG } from "@/features/feedback/config";
import type { DuplicateHit } from "@/lib/types";

const dups: DuplicateHit[] = [
  { kind: "request", id: "R-31", title: "Two-way GitHub issue sync", score: 0.82, type: "feature" },
];

vi.mock("@/lib/publicApi", () => ({
  publicApi: {
    duplicates: vi.fn(async () => dups),
    submit: vi.fn(async () => ({
      request: { id: "R-99", type: "feature", title: "x", by: "public", votes: 0, status: "new",
        linked_to: null, ago: "now", project_id: "core", created_at: "" },
      duplicates: dups,
    })),
  },
}));

describe("FeedbackWidget", () => {
  beforeEach(() => vi.clearAllMocks());

  it("surfaces likely duplicates as you type the title", async () => {
    const user = userEvent.setup();
    render(<FeedbackWidget config={DEFAULT_CONFIG} />);
    await user.type(screen.getByPlaceholderText("Summary"), "GitHub issue sync");
    expect(await screen.findByText(/Possibly already reported/i)).toBeInTheDocument();
    expect(screen.getByText("Two-way GitHub issue sync")).toBeInTheDocument();
    expect(screen.getByText("82%")).toBeInTheDocument();
  });

  it("submits and shows the tracked reference", async () => {
    const user = userEvent.setup();
    const { api } = { api: (await import("@/lib/publicApi")).publicApi };
    render(<FeedbackWidget config={DEFAULT_CONFIG} />);
    await user.type(screen.getByPlaceholderText("Summary"), "Please add dark mode toggle");
    await user.click(screen.getByRole("button", { name: /send feedback/i }));
    await waitFor(() => expect(api.submit).toHaveBeenCalled());
    expect(await screen.findByText(/Tracked as R-99/i)).toBeInTheDocument();
  });
});
