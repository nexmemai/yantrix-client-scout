import { ScoreBucket } from "./types";

export function scoreBucket(score?: number | null): ScoreBucket {
  const value = score ?? 0;
  if (value >= 60) return "high-fit";
  if (value >= 40) return "mid-fit";
  return "low-fit";
}

export function scoreBucketTone(bucket: ScoreBucket): string {
  // Soft tinted backgrounds + saturated foregrounds, matching the .pill
  // family in index.css. Returned as raw Tailwind classes so the same
  // helper works on both <span className="pill ..."> and bespoke chips.
  if (bucket === "high-fit") return "bg-emerald-100 text-emerald-800";
  if (bucket === "mid-fit") return "bg-amber-100 text-amber-800";
  return "bg-zinc-100 text-zinc-700";
}

export function formatDate(value?: string | null): string {
  if (!value) return "-";
  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(new Date(value));
}

export function withinDateRange(
  value: string,
  from?: string,
  to?: string,
): boolean {
  const date = new Date(value);
  if (from) {
    const fromDate = new Date(from);
    if (date < fromDate) return false;
  }
  if (to) {
    const toDate = new Date(to);
    toDate.setHours(23, 59, 59, 999);
    if (date > toDate) return false;
  }
  return true;
}
