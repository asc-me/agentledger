import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/cn";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-[9px] font-medium transition-colors disabled:opacity-50 disabled:pointer-events-none outline-none focus-visible:ring-1 focus-visible:ring-accent/40",
  {
    variants: {
      variant: {
        default:
          "bg-accent text-bg font-semibold hover:bg-accent-hi shadow-[0_6px_18px_rgba(198,242,78,0.18)]",
        outline:
          "border border-line-2 bg-surface-2 text-fg hover:border-line-hover hover:bg-surface-3",
        ghost: "text-muted hover:text-fg hover:bg-surface-3",
        agent:
          "border border-[#2a2440] bg-[rgba(167,139,250,0.08)] text-purple-2 hover:border-[#3a3358]",
        danger:
          "border border-[rgba(255,107,107,0.25)] bg-[rgba(255,107,107,0.06)] text-st-blocked hover:bg-[rgba(255,107,107,0.12)]",
      },
      size: {
        default: "h-9 px-3.5 text-[12.5px]",
        sm: "h-8 px-3 text-[12px]",
        lg: "h-10 px-5 text-sm",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />
    );
  },
);
Button.displayName = "Button";

export { buttonVariants };
