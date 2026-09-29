"use client";

import { X } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

type Toast = { id: number; message: string; tone: "default" | "error" };
const ToastContext = React.createContext<(message: string, tone?: Toast["tone"]) => void>(() => {});

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = React.useState<Toast[]>([]);
  const push = React.useCallback((message: string, tone: Toast["tone"] = "default") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, message, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4000);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex flex-col gap-2" aria-live="polite">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={cn(
              "fade-in pointer-events-auto flex items-center gap-3 rounded border border-l-2 bg-panel px-3 py-2 text-sm",
              t.tone === "error" ? "border-rule border-l-alert text-ink" : "border-rule border-l-accent text-ink",
            )}
          >
            {t.message}
            <button
              className="text-ink-500 hover:text-ink"
              onClick={() => setToasts((all) => all.filter((x) => x.id !== t.id))}
              aria-label="Dismiss"
            >
              <X className="size-3.5" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => React.useContext(ToastContext);
