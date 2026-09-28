import * as React from "react";

import { cn } from "@/lib/utils";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "h-8 w-full rounded border border-zinc-200 bg-white px-2.5 text-sm placeholder:text-zinc-400 focus:border-zinc-400 focus:outline-none focus-visible:ring-0",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(
  ({ className, ...props }, ref) => (
    <textarea
      ref={ref}
      className={cn(
        "w-full rounded border border-zinc-200 bg-white px-2.5 py-1.5 text-sm placeholder:text-zinc-400 focus:border-zinc-400 focus:outline-none focus-visible:ring-0",
        className,
      )}
      {...props}
    />
  ),
);
Textarea.displayName = "Textarea";

export function Select({ className, ...props }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        "h-8 rounded border border-zinc-200 bg-white pl-2 pr-7 text-sm text-zinc-700 focus:border-zinc-400 focus:outline-none focus-visible:ring-0",
        className,
      )}
      {...props}
    />
  );
}
