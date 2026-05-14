import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, RefreshCw } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { apiClient, ApiSession } from "../api/client";
import { SignalPill } from "../components/SignalPill";
import { formatDate, scoreBucket, scoreBucketTone } from "../lib/utils";

interface LeadDetailPageProps {
  session: ApiSession;
}

export function LeadDetailPage({ session }: LeadDetailPageProps) {
  const { leadId = "" } = useParams();
  const queryClient = useQueryClient();
  const [freshPitch, setFreshPitch] = useState<string | null>(null);

  const leadQuery = useQuery({
    queryKey: ["lead", leadId],
    queryFn: () => apiClient.getLead(session, leadId),
    enabled: Boolean(leadId),
  });

  const pitchMutation = useMutation({
    mutationFn: () => apiClient.regeneratePitch(session, leadId),
    onSuccess: (data) => {
      setFreshPitch(data.pitch_notes);
      queryClient.invalidateQueries({ queryKey: ["lead", leadId] });
    },
  });

  const lead = leadQuery.data;
  const signals = useMemo<[string, boolean][]>( 
    () =>
      lead?.audit
        ? [
            ["Website", lead.audit.has_website],
            ["SSL", lead.audit.ssl_valid],
            ["Mobile", lead.audit.mobile_friendly],
            ["Form", lead.audit.has_forms],
            ["CTA", lead.audit.has_cta],
            ["WhatsApp", lead.audit.has_whatsapp],
            ["Booking", lead.audit.has_booking],
            ["Chatbot", lead.audit.has_chatbot],
            ["Facebook", lead.audit.has_facebook],
            ["Instagram", lead.audit.has_instagram],
          ]
        : [],
    [lead],
  );

  if (leadQuery.isLoading) {
    return <div className="surface section-band text-sm text-[var(--muted)]">Loading lead…</div>;
  }

  if (leadQuery.isError || !lead) {
    return <div className="surface section-band text-sm text-[var(--danger)]">{(leadQuery.error as Error)?.message ?? "Lead not found."}</div>;
  }

  const bucket = scoreBucket(lead.score?.overall_score);
  const displayedPitch = freshPitch ?? lead.score?.pitch_notes ?? "No pitch generated yet.";

  return (
    <div className="grid gap-4">
      <section className="surface section-band">
        <Link className="mb-4 inline-flex items-center gap-2 text-sm font-semibold text-[var(--muted)]" to="/leads">
          <ArrowLeft className="h-4 w-4" />
          Back to leads
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="text-2xl font-extrabold">{lead.name}</div>
            <div className="mt-2 text-sm text-[var(--muted)]">
              {lead.category ?? "Unknown niche"} · {lead.city ?? "Unknown city"} · {lead.source}
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <span className={`rounded-full px-3 py-1 text-xs font-semibold ${scoreBucketTone(bucket)}`}>{bucket}</span>
              <span className="rounded-full border border-[var(--line)] bg-white/80 px-3 py-1 text-xs font-semibold">
                Score {lead.score?.overall_score ?? 0}
              </span>
            </div>
          </div>
          <button
            className="button button-primary h-11 px-4 text-sm font-semibold"
            onClick={() => pitchMutation.mutate()}
            disabled={pitchMutation.isPending}
          >
            <RefreshCw className={`h-4 w-4 ${pitchMutation.isPending ? "animate-spin" : ""}`} />
            Regenerate pitch
          </button>
        </div>
      </section>

      <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
        <section className="surface-strong p-5">
          <div className="text-sm font-bold uppercase text-[var(--muted)]">Business info</div>
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            <Info label="Website" value={lead.website_url ?? "-"} />
            <Info label="Phone" value={lead.phone ?? "-"} />
            <Info label="Email" value={lead.email ?? "-"} />
            <Info label="Rating" value={lead.rating ? `${lead.rating} / 5` : "-"} />
            <Info label="Review count" value={lead.review_count?.toString() ?? "-"} />
            <Info label="Created" value={formatDate(lead.created_at)} />
          </div>
        </section>

        <section className="surface-strong p-5">
          <div className="text-sm font-bold uppercase text-[var(--muted)]">Score breakdown</div>
          <div className="mt-4 grid gap-3">
            <Metric label="Website quality" value={lead.score?.website_quality ?? 0} />
            <Metric label="Online presence" value={lead.score?.online_presence ?? 0} />
            <Metric label="Conversion readiness" value={lead.score?.conversion_readiness ?? 0} />
            <Metric label="Urgency" value={lead.score?.urgency ?? 0} />
          </div>
        </section>
      </div>

      <section className="surface-strong p-5">
        <div className="text-sm font-bold uppercase text-[var(--muted)]">Audit signals</div>
        <div className="mt-4 flex flex-wrap gap-2">
          {signals.map(([label, value]) => (
            <SignalPill key={label} label={label} value={Boolean(value)} />
          ))}
        </div>
        {lead.audit && (
          <div className="mt-5 grid gap-3 md:grid-cols-3">
            <Info label="Load time" value={lead.audit.load_time_ms ? `${lead.audit.load_time_ms} ms` : "-"} />
            <Info label="PageSpeed" value={lead.audit.page_speed_score?.toString() ?? "-"} />
            <Info label="Tech stack" value={lead.audit.tech_stack?.join(", ") || "-"} />
          </div>
        )}
      </section>

      <section className="surface-strong p-5">
        <div className="flex items-center justify-between gap-3">
          <div className="text-sm font-bold uppercase text-[var(--muted)]">Pitch</div>
          {pitchMutation.isError ? <div className="text-xs text-[var(--danger)]">{(pitchMutation.error as Error).message}</div> : null}
        </div>
        <pre className="mt-4 whitespace-pre-wrap text-sm leading-7 text-[var(--text)]">{displayedPitch}</pre>
      </section>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs font-bold uppercase text-[var(--muted)]">{label}</div>
      <div className="mt-2 text-sm font-semibold">{value}</div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-sm">
        <span className="font-semibold">{label}</span>
        <span className="text-[var(--muted)]">{value}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-stone-200">
        <div className="h-full rounded-full bg-[var(--accent)]" style={{ width: `${Math.max(0, Math.min(value, 100))}%` }} />
      </div>
    </div>
  );
}
