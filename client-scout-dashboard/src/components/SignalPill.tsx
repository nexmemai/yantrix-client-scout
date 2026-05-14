import { Check, CircleDashed, X } from "lucide-react";

interface SignalPillProps {
  label: string;
  value?: boolean | null;
}

export function SignalPill({ label, value }: SignalPillProps) {
  const state = value === undefined || value === null ? "unknown" : value ? "yes" : "no";
  const icon =
    state === "yes" ? <Check className="h-3.5 w-3.5" /> : state === "no" ? <X className="h-3.5 w-3.5" /> : <CircleDashed className="h-3.5 w-3.5" />;
  const tone =
    state === "yes"
      ? "border-emerald-200 bg-emerald-50 text-emerald-800"
      : state === "no"
        ? "border-stone-300 bg-stone-100 text-stone-700"
        : "border-amber-200 bg-amber-50 text-amber-800";

  return (
    <div className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold ${tone}`}>
      {icon}
      {label}
    </div>
  );
}
