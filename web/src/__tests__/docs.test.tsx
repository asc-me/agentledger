import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { DocsReader } from "@/features/docs/DocsReader";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <DocsReader />
    </MemoryRouter>,
  );
}

describe("DocsReader", () => {
  it("opens context-aware help for the current page", async () => {
    const user = userEvent.setup();
    renderAt("/tracker");
    await user.click(screen.getByLabelText("Open docs for this page"));
    expect(screen.getByRole("heading", { name: "Tracker" })).toBeInTheDocument();
    expect(screen.getByText(/Advance status/)).toBeInTheDocument();
    expect(screen.getByText("TRACKER")).toBeInTheDocument(); // page badge
  });

  it("shows the PRD editor entry on /prds/:id", async () => {
    const user = userEvent.setup();
    renderAt("/prds/PRD-1");
    await user.click(screen.getByLabelText("Open docs for this page"));
    expect(screen.getByRole("heading", { name: "PRD editor" })).toBeInTheDocument();
  });

  it("toggles with the ? shortcut and records feedback locally", async () => {
    const user = userEvent.setup();
    renderAt("/dashboard");
    fireEvent.keyDown(window, { key: "?" });
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
    await user.click(screen.getByLabelText("Helpful"));
    expect(screen.getByText(/Thanks for the feedback/)).toBeInTheDocument();
  });
});
