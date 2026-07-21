import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { lineDiff } from "@/lib/diff";
import { Markdown } from "@/lib/markdown";

describe("Markdown renderer", () => {
  it("renders headings, lists, and inline formatting", () => {
    render(<Markdown source={"# Title\n\n## Goals\n- first **bold**\n- second `code`"} />);
    expect(screen.getByRole("heading", { level: 1, name: "Title" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Goals" })).toBeInTheDocument();
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(screen.getByText("bold").tagName).toBe("STRONG");
    expect(screen.getByText("code").tagName).toBe("CODE");
  });
});

describe("lineDiff", () => {
  it("marks added and removed lines", () => {
    const ops = lineDiff("a\nb\nc", "a\nB\nc\nd");
    const added = ops.filter((o) => o.type === "add").map((o) => o.text);
    const removed = ops.filter((o) => o.type === "del").map((o) => o.text);
    expect(added).toContain("B");
    expect(added).toContain("d");
    expect(removed).toContain("b");
    expect(ops.filter((o) => o.type === "same").map((o) => o.text)).toEqual(["a", "c"]);
  });
});
