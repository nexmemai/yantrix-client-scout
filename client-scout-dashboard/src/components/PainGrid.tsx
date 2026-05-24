/**
 * PainGrid - 11-square density indicator for an audit's pain flags.
 *
 * Sales operators scan boards faster than they scan labels. A row of small
 * filled/unfilled squares lets them see "5 of 11 pain points" at a glance
 * without reading anything. Each square has a tooltip so the underlying
 * flag is still discoverable on hover.
 *
 * Order matches `PAIN_PRIORITY` in the backend's pain_translator so the
 * leftmost squares are always the highest-revenue-impact gaps.
 */

const PAIN_ORDER: Array<{ key: string; label: string }> = [
  { key: "pain_no_website", label: "No working website" },
  { key: "pain_slow_load", label: "Slow homepage" },
  { key: "pain_no_form", label: "No enquiry form" },
  { key: "pain_no_booking", label: "No online booking" },
  { key: "pain_no_cta", label: "No clear CTA" },
  { key: "pain_not_mobile", label: "Mobile UX broken" },
  { key: "pain_no_whatsapp", label: "No WhatsApp" },
  { key: "pain_no_chatbot", label: "No chatbot" },
  { key: "pain_no_ssl", label: "No SSL" },
  { key: "pain_no_facebook", label: "No Facebook" },
  { key: "pain_no_instagram", label: "No Instagram" },
];

interface PainGridProps {
  flags?: Record<string, boolean> | null;
  count?: number;
}

export function PainGrid({ flags, count }: PainGridProps) {
  const active = count ?? Object.values(flags ?? {}).filter(Boolean).length;
  const total = PAIN_ORDER.length;

  return (
    <div
      className="inline-flex items-center gap-1.5"
      aria-label={`${active} of ${total} pain points detected`}
    >
      <div className="flex gap-[2px]">
        {PAIN_ORDER.map(({ key, label }) => {
          const isActive = Boolean(flags?.[key]);
          return (
            <span
              key={key}
              title={`${isActive ? "Pain: " : "OK: "}${label}`}
              className={`h-[7px] w-[7px] rounded-[1px] transition ${
                isActive ? "bg-[var(--danger)]" : "bg-[var(--line)]"
              }`}
            />
          );
        })}
      </div>
      <span className="text-[11px] font-semibold text-[var(--muted)]" aria-hidden>
        {active}/{total}
      </span>
    </div>
  );
}
