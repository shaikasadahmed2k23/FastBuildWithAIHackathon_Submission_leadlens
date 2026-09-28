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
        <Dialog.Overlay className="fixed inset-0 z-40 bg-zinc-900/10" />
        <Dialog.Content
          className={cn(
            "fixed inset-y-0 right-0 z-50 flex w-full max-w-[560px] flex-col border-l border-zinc-200 bg-white shadow-sm focus:outline-none",
            className,
          )}
        >
          <div className="flex h-12 shrink-0 items-center justify-between gap-3 border-b border-zinc-200 px-4">
            <div className="min-w-0">
              <Dialog.Title className="truncate text-sm font-medium">{title}</Dialog.Title>
              {description ? (
                <Dialog.Description className="truncate text-xs text-zinc-500">{description}</Dialog.Description>
              ) : (
                <Dialog.Description className="sr-only">Details</Dialog.Description>
              )}
            </div>
            <Dialog.Close className="rounded p-1 text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900" aria-label="Close">
              <X className="size-4" />
            </Dialog.Close>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
