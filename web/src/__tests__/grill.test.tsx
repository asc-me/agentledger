import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { GrillPanel } from "@/features/prds/GrillPanel";

// grillStream streams two deltas (the opening questions); grillApply folds a decision in.
const { grillStream, grillApply } = vi.hoisted(() => ({
  grillStream: vi.fn(
    async (_id: string, _msg: string, _hist: unknown[], onDelta: (t: string) => void) => {
      onDelta("- What is out of scope?\n");
      onDelta("- What happens on bad input?");
    },
  ),
  grillApply: vi.fn(async () => ({ body: "# PRD\n\n## Decisions from grilling\n- Mobile is out\n" })),
}));

vi.mock("@/lib/api", () => ({ api: { grillStream, grillApply } }));

function renderPanel(onApply = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <GrillPanel prdId="PRD-1" onApply={onApply} />
    </QueryClientProvider>,
  );
  return onApply;
}

describe("Grill panel", () => {
  it("streams opening questions on mount", async () => {
    renderPanel();
    expect(await screen.findByText(/What is out of scope/)).toBeInTheDocument();
    expect(grillStream).toHaveBeenCalled();
  });

  it("answers, then applies decisions to the PRD", async () => {
    const user = userEvent.setup();
    const onApply = renderPanel();
    await screen.findByText(/What is out of scope/);

    await user.type(screen.getByPlaceholderText(/Answer the questions/), "Mobile is out{Enter}");

    // The Apply button appears once there's an answer.
    const applyBtn = await screen.findByRole("button", { name: /Apply to PRD/ });
    await user.click(applyBtn);
    await waitFor(() => expect(onApply).toHaveBeenCalledWith(expect.stringContaining("Decisions from grilling")));
  });
});
