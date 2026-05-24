import { Check, CircleDashed, X } from "lucide-react";

interface SignalPillProps {
  label: string;
  value?: boolean | null;
}

/**
 * SignalPill - tri-state audit signal chip.
 *
 * Three visual states map to three operator semantics:
 *   * yes     -> emerald soft pill, ✓ icon (signal is healthy)
 *   * no      -> zinc soft pill,    ✕ icon (signal is missing)
 *   * unknown -> amber soft pill,   ◌ icon (audit hasn't decided yet)
 *
 * The token choices match the .pill-* family in index.css so the chip
 * reads the same as the table's status pills - one design language.
 */

export function SignalPill({ label, value }: SignalPillProps) {
  const state = value === undefined || value === null ? "unknown" : value ? "yes" : "no";
  const icon =
    state === "yes" ? (
      <Check className="h-3.5 w-3.5" />
    ) : state === "no" ? (
      <X className="h-3.5 w-3.5" />
    ) : (
      <CircleDashed className="h-3.5 w-3.5" />
    );
  const tone =
    state === "yes"
      ? "border-emerald-200/70 bg-emerald-50 text-emerald-700"
      : state === "no"
        ? "border-zinc-200/80 bg-zinc-50 text-zinc-500"
        : "border-amber-200/70 bg-amber-50 text-amber-700";

  return (
    <div
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold transition-colors ${tone}`}
    >
      {icon}
      {label}
    </div>
  );
}
