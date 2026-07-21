import * as React from "react";

/** Minimal, dependency-free markdown renderer for PRD bodies.
 *  Supports: # ## ### headings, - lists, ``` code fences, `inline code`,
 *  **bold**, *italic*, --- rules, and paragraphs. React escapes all text. */
function inline(text: string, keyBase: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    const tok = m[0];
    const key = `${keyBase}-${i++}`;
    if (tok.startsWith("**")) nodes.push(<strong key={key}>{tok.slice(2, -2)}</strong>);
    else if (tok.startsWith("`"))
      nodes.push(
        <code key={key} className="rounded bg-surface-4 px-1 py-0.5 font-mono text-[12px] text-accent">
          {tok.slice(1, -1)}
        </code>,
      );
    else nodes.push(<em key={key}>{tok.slice(1, -1)}</em>);
    last = m.index + tok.length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

export function Markdown({ source }: { source: string }) {
  const lines = source.split("\n");
  const blocks: React.ReactNode[] = [];
  let i = 0;
  let key = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (line.startsWith("```")) {
      const buf: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) buf.push(lines[i++]);
      i++; // closing fence
      blocks.push(
        <pre key={key++} className="my-3 overflow-x-auto rounded-lg border border-line-2 bg-surface-2 p-3 font-mono text-[12px] text-fg-2">
          {buf.join("\n")}
        </pre>,
      );
      continue;
    }

    const h = /^(#{1,3})\s+(.*)$/.exec(line);
    if (h) {
      const level = h[1].length;
      const cls =
        level === 1
          ? "mt-4 mb-2 text-[19px] font-bold tracking-tight"
          : level === 2
            ? "mt-4 mb-1.5 text-[15px] font-semibold text-fg"
            : "mt-3 mb-1 text-[13px] font-semibold text-muted-2";
      const content = inline(h[2], `h${key}`);
      blocks.push(React.createElement(`h${level}`, { key: key++, className: cls }, content));
      i++;
      continue;
    }

    if (line.trim() === "---") {
      blocks.push(<hr key={key++} className="my-4 border-line-2" />);
      i++;
      continue;
    }

    if (/^[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^[-*]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^[-*]\s+/, ""));
        i++;
      }
      blocks.push(
        <ul key={key++} className="my-2 list-disc space-y-1 pl-5 text-[13px] text-fg-2">
          {items.map((it, idx) => (
            <li key={idx}>{inline(it, `li${key}-${idx}`)}</li>
          ))}
        </ul>,
      );
      continue;
    }

    if (line.trim() === "") {
      i++;
      continue;
    }

    // Paragraph: gather consecutive plain lines.
    const buf: string[] = [];
    while (i < lines.length && lines[i].trim() !== "" && !/^(#{1,3}\s|[-*]\s|```)/.test(lines[i])) {
      buf.push(lines[i++]);
    }
    blocks.push(
      <p key={key++} className="my-2 text-[13px] leading-relaxed text-fg-2">
        {inline(buf.join(" "), `p${key}`)}
      </p>,
    );
  }

  return <div>{blocks}</div>;
}
