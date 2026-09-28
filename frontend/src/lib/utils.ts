import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

const number = new Intl.NumberFormat("en-US");
const currency = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

export const fmt = {
  int: (n: number | null | undefined) => (n == null ? "—" : number.format(Math.round(n))),
  score: (n: number | null | undefined) => (n == null ? "—" : n.toFixed(1)),
  money: (n: number | null | undefined) => (n == null ? "—" : currency.format(n)),
  pct: (n: number | null | undefined, digits = 1) => (n == null ? "—" : `${(n * 100).toFixed(digits)}%`),
  date: (s: string | null | undefined) =>
    s ? new Date(s.replace(" ", "T")).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "—",
  dateTime: (s: string | null | undefined) =>
    s
      ? new Date(s.replace(" ", "T")).toLocaleString("en-US", {
          month: "short",
          day: "numeric",
          hour: "numeric",
          minute: "2-digit",
        })
      : "—",
  label: (s: string | null | undefined) => (s ? s.replace(/_/g, " ") : "—"),
};

/** Days between the dataset's frozen "now" and a timestamp. */
export function daysSince(asOf: string, ts: string | null | undefined): number | null {
  if (!ts) return null;
  const diff = new Date(asOf).getTime() - new Date(ts.replace(" ", "T")).getTime();
  return Math.floor(diff / 86_400_000);
}
