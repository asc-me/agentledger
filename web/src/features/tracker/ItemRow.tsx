import { Github, GitPullRequest, GripVertical } from "lucide-react";
import * as React from "react";

import { Avatar } from "@/components/ui/avatar";
import { cn } from "@/lib/cn";
import { CHECK_COLOR, PR_STATE_COLOR } from "@/lib/meta";
import type { Item, Status } from "@/lib/types";

import { StatusMenu } from "./StatusMenu";

/** "#42" for an issue/PR URL, else the hostname. */
function ghRef(url: string): string {
  const m = url.match(/\/(?:issues|pull)\/(\d+)/);
  if (m) return `#${m[1]}`;
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "link";
  }
}

export function ItemRow({
  item,
  selected,
  onSelect,
  onStatus,
  dragHandlers,
  dragging,
  dragOver,
}: {
  item: Item;
  selected: boolean;
  onSelect: () => void;
  onStatus: (s: Status) => void;
  dragHandlers: {
    onDragStart: (e: React.DragEvent) => void;
    onDragEnter: (e: React.DragEvent) => void;
    onDragEnd: (e: React.DragEvent) => void;
    onDragOver: (e: React.DragEvent) => void;
  };
  dragging: boolean;
  dragOver: boolean;
}) {
  return (
    <div
      draggable
      {...dragHandlers}
      onClick={onSelect}
      className={cn(
        "group flex cursor-pointer items-center gap-3 border-b border-line/70 px-4 py-3 transition-colors",
        selected ? "bg-surface-3" : "hover:bg-surface/60",
        dragging && "opacity-40",
        dragOver && "border-t-2 border-t-accent",
      )}
    >
      <GripVertical
        size={14}
        className="flex-none text-faint-2 opacity-0 transition-opacity group-hover:opacity-100"
      />

      <div className="flex-none" onClick={(e) => e.stopPropagation()}>
        <StatusMenu status={item.status} onChange={onStatus} compact />
      </div>

      <span className="w-[52px] flex-none font-mono text-[11px] text-faint">{item.id}</span>

      <span className="min-w-0 flex-1 truncate text-[13.5px] text-fg-2">{item.title}</span>

      <div className="flex flex-none items-center gap-1.5">
        {item.tags.slice(0, 3).map((t) => (
          <span
            key={t}
            className="rounded-md border border-line-2 bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-muted"
          >
            {t}
          </span>
        ))}
      </div>

      {item.effort > 0 && (
        <span
          className="flex-none rounded-md bg-surface-4 px-1.5 py-0.5 font-mono text-[10px] text-muted-2"
          title="effort"
        >
          {item.effort}
        </span>
      )}

      {item.pr && (
        <span
          className="flex flex-none items-center gap-1 font-mono text-[10px]"
          style={{ color: PR_STATE_COLOR[item.pr.state] ?? "#8b949e" }}
          title={`PR #${item.pr.number} · ${item.pr.state} · checks ${item.pr.checks}`}
        >
          <GitPullRequest size={11} />#{item.pr.number}
          <span
            className="h-1.5 w-1.5 rounded-full"
            style={{ background: CHECK_COLOR[item.pr.checks] ?? "#8b949e" }}
          />
        </span>
      )}

      {item.github_url && !item.pr && (
        <a
          href={item.github_url}
          target="_blank"
          rel="noreferrer noopener"
          onClick={(e) => e.stopPropagation()}
          className="flex flex-none items-center gap-1 font-mono text-[10px] text-muted hover:text-fg"
          title={`Linked: ${item.github_url}`}
        >
          <Github size={11} />
          {ghRef(item.github_url)}
        </a>
      )}

      <span className="w-[52px] flex-none text-right font-mono text-[10px] text-faint-2">
        {item.date}
      </span>

      {item.reporter?.avatar && (
        <Avatar
          initials={(item.reporter.name ?? "?").split(" ").map((p) => p[0]).slice(0, 2).join("")}
          color={item.reporter.avatar}
          size={22}
        />
      )}
    </div>
  );
}
