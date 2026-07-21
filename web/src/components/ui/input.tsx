import * as React from "react";

import { cn } from "@/lib/cn";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "h-9 w-full rounded-[9px] border border-line-2 bg-surface-2 px-3 text-[13px] text-fg outline-none",
        "placeholder:text-faint transition-colors focus:border-line-hover focus:bg-surface-3",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";

export const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea
    ref={ref}
    className={cn(
      "w-full rounded-[9px] border border-line-2 bg-surface-2 px-3 py-2 text-[13px] text-fg outline-none",
      "placeholder:text-faint transition-colors focus:border-line-hover focus:bg-surface-3 resize-none",
      className,
    )}
    {...props}
  />
));
Textarea.displayName = "Textarea";
