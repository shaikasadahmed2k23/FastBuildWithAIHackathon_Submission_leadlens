"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type * as React from "react";

import { cn } from "@/lib/utils";

export function Sheet({
  open,
  onOpenChange,
  title,
  description,
  children,
  className,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: React.ReactNode;
  description?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fade-in fixed inset-0 z-40 bg-ink/10" />
        <Dialog.Content
          // Focus the panel itself rather than the close button, so no ring shows on open.
          onOpenAutoFocus={(e) => {
            e.preventDefault();
            (e.currentTarget as HTMLElement).focus();
          }}
          className={cn(
            "fade-in fixed inset-y-0 right-0 z-50 flex w-full max-w-[560px] flex-col border-l border-ink bg-panel focus:outline-none",
            className,
          )}
        >
          <div className="flex h-14 shrink-0 items-center justify-between gap-3 border-b border-rule px-5">
            <div className="min-w-0">
              <Dialog.Title className="truncate font-serif text-lg leading-6">{title}</Dialog.Title>
              {description ? (
                <Dialog.Description className="truncate text-xs text-ink-500">{description}</Dialog.Description>
              ) : (
                <Dialog.Description className="sr-only">Details</Dialog.Description>
              )}
            </div>
            <Dialog.Close className="rounded p-1 text-ink-500 hover:bg-ink-50 hover:text-ink" aria-label="Close">
              <X className="size-4" />
            </Dialog.Close>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
