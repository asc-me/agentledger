import { cn } from "@/lib/cn";

export function Avatar({
  initials,
  color,
  size = 28,
  className,
}: {
  initials: string;
  color: string;
  size?: number;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex flex-none items-center justify-center rounded-full font-mono font-bold text-bg",
        className,
      )}
      style={{ width: size, height: size, background: color, fontSize: size * 0.4 }}
    >
      {initials}
    </span>
  );
}
