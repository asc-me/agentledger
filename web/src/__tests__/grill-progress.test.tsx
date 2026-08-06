import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { GrillProgress } from "@/features/prds/GrillProgress";
import { PRD_SETTABLE_STATUSES, PRD_STATUS_ORDER } from "@/features/prds/meta";
import type { GrillState } from "@/lib/types";

/** Approval is shown as EARNED, not picked (AL-301 / PRD-15 D7).
 *
 *  Two things a reader has to be able to tell apart and previously could not: what is
 *  still open versus what the author deliberately deferred, and whether a real model
 *  graded the answers or the offline stub merely counted them. */

function state(over: Partial<GrillState> = {}): GrillState {
  const dims = {
    scope_edges: { outcome: "resolved", note: "local only", turn_seq: 1,
                   graded_by: "anthropic", question: "q" },
    failure_modes: { outcome: "resolved", note: "", turn_seq: 2,
                     graded_by: "anthropic", question: "q" },
    contracts: { outcome: "deferred", note: "wire format after the spike", turn_seq: 3,
                 graded_by: "author", question: "q" },
    open_decisions: { outcome: "unanswered", note: "", turn_seq: null,
                      graded_by: "", question: "q" },
  } as GrillState["dimensions"];
  return {
    prd_id: "AL-P15", turns: [], questions: 4, answers: 3, grilled: true,
    dimensions: dims, outstanding: ["open_decisions"], deferred: ["contracts"],
    complete: false, ...over,
  };
}

describe("grill progress (AL-301)", () => {
  it("shows every dimension with its outcome", () => {
    render(<GrillProgress state={state()} />);
    expect(screen.getByText("Scope edges")).toBeInTheDocument();
    expect(screen.getByText("Failure modes")).toBeInTheDocument();
    expect(screen.getByText("Contracts")).toBeInTheDocument();
    expect(screen.getByText("Open decisions")).toBeInTheDocument();
  });

  it("distinguishes a deliberate deferral from something still open", () => {
    render(<GrillProgress state={state()} />);
    // Both are "not answered", and conflating them is the exact failure PRD-15's
    // three-outcome design exists to prevent.
    expect(screen.getByText("deferred")).toBeInTheDocument();
    expect(screen.getByText("open")).toBeInTheDocument();
    expect(screen.getByText(/wire format after the spike/)).toBeInTheDocument();
  });

  it("counts progress while the grill is unfinished", () => {
    render(<GrillProgress state={state()} />);
    expect(screen.getByText("3/4")).toBeInTheDocument();
    expect(screen.getByText(/approves itself/)).toBeInTheDocument();
  });

  it("says approval was reached, not set", () => {
    const done = state({ complete: true, outstanding: [] });
    render(<GrillProgress state={done} />);
    expect(screen.getByText("Approved by grilling")).toBeInTheDocument();
    expect(screen.getByText(/not by anyone setting a status/)).toBeInTheDocument();
  });

  it("flags a dimension the offline stub graded", () => {
    /** The one that protects a reader from over-trusting a default install: `stub`
     *  means an answer was recorded, NOT that it was any good. */
    const s = state();
    s.dimensions.scope_edges.graded_by = "stub";
    render(<GrillProgress state={s} />);
    expect(screen.getByText("offline")).toBeInTheDocument();
  });

  it("does not flag dimensions a real provider graded", () => {
    render(<GrillProgress state={state()} />);
    expect(screen.queryByText("offline")).not.toBeInTheDocument();
  });

  it("warns on a completed grill that was graded offline", () => {
    const s = state({ complete: true, outstanding: [] });
    Object.values(s.dimensions).forEach((d) => { d.graded_by = "stub"; });
    render(<GrillProgress state={s} />);
    expect(screen.getByText(/substance was not assessed/)).toBeInTheDocument();
  });
});

describe("the status control (AL-301)", () => {
  it("does not offer approved as a choice", () => {
    /** Offering it would be a control whose every use the server refuses with a 409. */
    expect(PRD_SETTABLE_STATUSES).toEqual(["draft", "review"]);
  });

  it("still knows how to render approved", () => {
    /** It remains a real status — it just isn't pickable. Dropping it from the display
     *  metadata would leave approved PRDs rendering as unknown. */
    expect(PRD_STATUS_ORDER).toContain("approved");
  });
});
