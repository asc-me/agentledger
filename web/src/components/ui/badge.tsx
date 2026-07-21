import * as React from "react";

import { cn } from "@/lib/cn";

/** A small mono metadata chip. Pass an explicit color for status/type dots. */
export function Badge({
  className,
  mono = true,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & { mono?: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md border border-line-2 px-2 py-0.5 text-[10px] leading-none",
        mono && "font-mono tracking-wide",
        className,
      )}
      {...props}
    />
  );
}

export function Dot({ color, glow = false }: { color: string; glow?: boolean }) {
  return (
    <span
      className="inline-block h-1.5 w-1.5 rounded-full"
      style={{ background: color, boxShadow: glow ? `0 0 8px ${color}` : undefined }}
    />
  );
}
