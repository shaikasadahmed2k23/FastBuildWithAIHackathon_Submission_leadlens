"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import * as React from "react";

import { useToast } from "@/components/toast";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

/** Restores the seed-42 dataset and the pre-computed answer cache, after an explicit confirmation. */
export function ResetDemoButton() {
  const [open, setOpen] = React.useState(false);
  const qc = useQueryClient();
  const toast = useToast();
  const reset = useMutation({
    mutationFn: api.resetDemo,
    onSuccess: (r) => {
      setOpen(false);
      qc.invalidateQueries(); // every view reads the replaced database
      toast(
        `Demo data restored: ${r.leads.toLocaleString()} leads, ${r.cached_answers_loaded} cached answers` +
          (r.cache_seed_found ? "" : " (no cache seed file)"),
      );
    },
    onError: (e) => toast(e instanceof Error ? e.message : "Reset failed", "error"),
  });

  return (
    <Dialog.Root open={open} onOpenChange={(o) => !reset.isPending && setOpen(o)}>
      <Dialog.Trigger asChild>
        <button className="flex items-center gap-1.5 text-ink-500 underline decoration-ink-300 underline-offset-2 hover:text-ink">
          Reset demo data
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fade-in fixed inset-0 z-40 bg-ink/15" />
        <Dialog.Content className="fade-in fixed left-1/2 top-1/2 z-50 w-[440px] -translate-x-1/2 -translate-y-1/2 rounded border border-ink bg-panel p-6 focus:outline-none">
          <Dialog.Title className="font-serif text-xl font-semibold">Reset demo data?</Dialog.Title>
          <Dialog.Description className="mt-2 text-sm text-ink-600">
            Restores the original seed dataset (4,992 leads) and the pre-computed answers for the example questions.
            Approvals, imports and merges made since are discarded for everyone using this deployment.
          </Dialog.Description>
          <div className="mt-5 flex justify-end gap-2">
            <Dialog.Close asChild>
              <Button variant="ghost" disabled={reset.isPending}>
                Cancel
              </Button>
            </Dialog.Close>
            <Button variant="danger" disabled={reset.isPending} onClick={() => reset.mutate()}>
              {reset.isPending ? "Resetting…" : "Reset demo data"}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
