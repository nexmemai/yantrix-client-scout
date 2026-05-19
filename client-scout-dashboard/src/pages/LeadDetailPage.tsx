import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Copy, ExternalLink, MessageCircle, RefreshCw, Save } from "lucide-react";
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
  const [statusDraft, setStatusDraft] = useState("new");
  const [notesDraft, setNotesDraft] = useState("");
  const [followUpDraft, setFollowUpDraft] = useState("");

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

  const salesMutation = useMutation({
    mutationFn: () =>
      apiClient.updateLeadSales(session, leadId, {
        lead_status: statusDraft,
        sales_notes: notesDraft,
        follow_up_at: followUpDraft ? new Date(followUpDraft).toISOString() : null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["lead", leadId] });
      queryClient.invalidateQueries({ queryKey: ["leads"] });
    },
  });

  const contactAttemptMutation = useMutation({
    mutationFn: () => apiClient.recordContactAttempt(session, leadId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["lead", leadId] });
      queryClient.invalidateQueries({ queryKey: ["leads"] });
    },
  });

  const lead = leadQuery.data;
  useEffect(() => {
    if (lead) {
      setStatusDraft(lead.lead_status);
      setNotesDraft(lead.sales_notes ?? "");
      setFollowUpDraft(lead.follow_up_at ? lead.follow_up_at.slice(0, 10) : "");
    }
  }, [lead]);

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
  const painFlags = Object.entries(lead.audit?.pain_flags ?? {}).filter(([, active]) => active);
  const contactEmail = lead.contact_email ?? lead.email ?? "";
  const contactPhone = lead.contact_phone ?? lead.phone ?? "";
  const emailBody = lead.email_body ?? displayedPitch;
  const whatsappPitch = lead.whatsapp_message ?? displayedPitch;
  const emailPitch = `${lead.email_subject ?? `Quick idea for ${lead.name}`}\n\n${emailBody}`;

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
              {lead.score?.agency_fit_bucket ? (
                <span className="rounded-full bg-teal-100 px-3 py-1 text-xs font-semibold text-teal-800">
                  Agency {lead.score.agency_fit_bucket} · {lead.score.agency_fit_score ?? 0}
                </span>
              ) : null}
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
            {lead.contact_name ? <Info label="Contact name" value={lead.contact_name} /> : null}
            {lead.contact_title ? <Info label="Contact title" value={lead.contact_title} /> : null}
            {contactEmail ? <CopyInfo label="Contact email" value={contactEmail} /> : null}
            {contactPhone ? <CopyInfo label="Contact phone" value={contactPhone} /> : null}
            {lead.contact_linkedin_url ? <Info label="LinkedIn" value={lead.contact_linkedin_url} /> : null}
            {lead.contact_confidence ? <Info label="Contact confidence" value={`${lead.contact_confidence}%`} /> : null}
            <Info label="Rating" value={lead.rating ? `${lead.rating} / 5` : "-"} />
            <Info label="Review count" value={lead.review_count?.toString() ?? "-"} />
            <Info label="Budget / Reliability" value={`${lead.budget_tier ?? "-"} / ${lead.reliability ?? "-"}`} />
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
            <Metric label="Agency fit" value={lead.score?.agency_fit_score ?? 0} />
          </div>
          {lead.score?.opportunity_types?.length ? (
            <div className="mt-4 flex flex-wrap gap-2">
              {lead.score.opportunity_types.map((item) => (
                <span key={item} className="rounded-full bg-teal-50 px-2 py-1 text-xs font-semibold text-teal-800">
                  {item}
                </span>
              ))}
            </div>
          ) : null}
          {lead.score?.estimated_deal_value ? (
            <div className="mt-4 text-sm font-semibold text-[var(--muted)]">
              Estimated value ₹{lead.score.estimated_deal_value.toLocaleString("en-IN")}
            </div>
          ) : null}
        </section>
      </div>

      <section className="surface-strong p-5">
        <div className="text-sm font-bold uppercase text-[var(--muted)]">Sales workflow</div>
        <div className="mt-4 grid gap-3 md:grid-cols-[220px_220px_minmax(0,1fr)_auto_auto]">
          <select className="field" value={statusDraft} onChange={(event) => setStatusDraft(event.target.value)}>
            {["new", "contacted", "replied", "meeting_set", "proposal_sent", "won", "lost", "ignored"].map((item) => (
              <option key={item} value={item}>{item}</option>
            ))}
          </select>
          <input className="field" type="date" value={followUpDraft} onChange={(event) => setFollowUpDraft(event.target.value)} />
          <input className="field" value={notesDraft} onChange={(event) => setNotesDraft(event.target.value)} placeholder="Sales notes" />
          <button className="button button-secondary h-11 px-3 text-sm font-semibold" onClick={() => contactAttemptMutation.mutate()}>
            <MessageCircle className="h-4 w-4" />
            Attempt {lead.contact_attempts}
          </button>
          <button className="button button-primary h-11 px-3 text-sm font-semibold" onClick={() => salesMutation.mutate()}>
            <Save className="h-4 w-4" />
            Save
          </button>
        </div>
        <div className="mt-3 text-xs text-[var(--muted)]">Last contacted: {formatDate(lead.last_contacted_at)}</div>
      </section>

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
            <Info label="CMS" value={lead.audit.cms_detected ?? "-"} />
          </div>
        )}
        {painFlags.length ? (
          <div className="mt-4 flex flex-wrap gap-2">
            {painFlags.map(([flag]) => (
              <span key={flag} className="rounded-full bg-amber-100 px-2 py-1 text-xs font-semibold text-amber-800">
                {flag.replace("pain_", "").replaceAll("_", " ")}
              </span>
            ))}
          </div>
        ) : null}
      </section>

      <section className="surface-strong p-5">
        <div className="flex items-center justify-between gap-3">
          <div className="text-sm font-bold uppercase text-[var(--muted)]">Pitch</div>
          {pitchMutation.isError ? <div className="text-xs text-[var(--danger)]">{(pitchMutation.error as Error).message}</div> : null}
        </div>
        {lead.pain_points_used?.length || lead.pitch_recommended_services?.length ? (
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            {lead.pain_points_used?.length ? (
              <PitchMetaBlock title="Pitch uses these gaps" items={lead.pain_points_used} tone="amber" />
            ) : null}
            {lead.pitch_recommended_services?.length ? (
              <PitchMetaBlock title="Recommended services" items={lead.pitch_recommended_services} tone="teal" />
            ) : null}
          </div>
        ) : null}
        <div className="mt-4 flex flex-wrap gap-2">
          {lead.whatsapp_link ? (
            <a className="button button-primary h-10 px-3 text-sm font-semibold" href={lead.whatsapp_link} rel="noreferrer" target="_blank">
              <ExternalLink className="h-4 w-4" />
              Send via WhatsApp
            </a>
          ) : null}
          <button className="button button-secondary h-10 px-3 text-sm font-semibold" onClick={() => navigator.clipboard.writeText(whatsappPitch)}>
            <Copy className="h-4 w-4" />
            Copy WhatsApp
          </button>
          <button className="button button-secondary h-10 px-3 text-sm font-semibold" onClick={() => navigator.clipboard.writeText(emailPitch)}>
            <Copy className="h-4 w-4" />
            Copy email pitch
          </button>
        </div>
        {lead.email_subject ? (
          <div className="mt-5">
            <div className="text-xs font-bold uppercase text-[var(--muted)]">Email subject</div>
            <div className="mt-2 rounded-md border border-[var(--line)] bg-white/70 px-3 py-2 text-sm font-semibold">
              {lead.email_subject}
            </div>
          </div>
        ) : null}
        <div className="mt-5 grid gap-4 lg:grid-cols-2">
          <PitchCopyBlock title="WhatsApp message" text={whatsappPitch} />
          <PitchCopyBlock title="Email body" text={emailBody} />
        </div>
        {lead.whatsapp_follow_up || lead.call_opener ? (
          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            {lead.whatsapp_follow_up ? <PitchCopyBlock title="WhatsApp follow-up" text={lead.whatsapp_follow_up} compact /> : null}
            {lead.call_opener ? <PitchCopyBlock title="Call opener" text={lead.call_opener} compact /> : null}
          </div>
        ) : null}
        {lead.personalization_notes?.length ? (
          <div className="mt-4">
            <div className="text-xs font-bold uppercase text-[var(--muted)]">Personalization notes</div>
            <div className="mt-2 flex flex-wrap gap-2">
              {lead.personalization_notes.map((item) => (
                <span key={item} className="rounded-full border border-[var(--line)] bg-white/80 px-2 py-1 text-xs font-semibold text-[var(--muted)]">
                  {item}
                </span>
              ))}
            </div>
          </div>
        ) : null}
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

function CopyInfo({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs font-bold uppercase text-[var(--muted)]">{label}</div>
      <button className="mt-2 inline-flex items-center gap-2 text-left text-sm font-semibold" onClick={() => navigator.clipboard.writeText(value)}>
        {value}
        <Copy className="h-3.5 w-3.5 text-[var(--muted)]" />
      </button>
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

function PitchMetaBlock({ title, items, tone }: { title: string; items: string[]; tone: "amber" | "teal" }) {
  const className =
    tone === "amber"
      ? "rounded-full bg-amber-100 px-2 py-1 text-xs font-semibold text-amber-800"
      : "rounded-full bg-teal-50 px-2 py-1 text-xs font-semibold text-teal-800";
  return (
    <div>
      <div className="text-xs font-bold uppercase text-[var(--muted)]">{title}</div>
      <div className="mt-2 flex flex-wrap gap-2">
        {items.map((item) => (
          <span key={item} className={className}>
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}

function PitchCopyBlock({ title, text, compact = false }: { title: string; text: string; compact?: boolean }) {
  return (
    <div>
      <div className="text-xs font-bold uppercase text-[var(--muted)]">{title}</div>
      <pre className={`mt-2 whitespace-pre-wrap rounded-md border border-[var(--line)] bg-white/70 p-3 text-sm leading-7 text-[var(--text)] ${compact ? "min-h-24" : "min-h-48"}`}>
        {text}
      </pre>
    </div>
  );
}
