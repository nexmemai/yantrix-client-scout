import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Building2,
  Copy,
  ExternalLink,
  Gauge,
  Mail,
  MessageCircle,
  PencilLine,
  Phone,
  RefreshCw,
  Save,
  ShieldCheck,
  Sparkles,
  Target,
} from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { apiClient, ApiSession } from "../api/client";
import { CommunicationLog } from "../components/CommunicationLog";
import { SignalPill } from "../components/SignalPill";
import { LeadDetail } from "../lib/types";
import { formatDate, scoreBucket, scoreBucketTone } from "../lib/utils";

/**
 * LeadDetailPage - premium-redesigned lead workspace.
 *
 * Behavioural contract is unchanged from the previous rev: same TanStack
 * queries, same three mutations (regeneratePitch / updateLeadSales /
 * recordContactAttempt), same derived strings (whatsappPitch, emailPitch).
 * What changed:
 *
 * * Hero strip is no longer a generic .surface band. It's a clean page
 *   header that mirrors the rest of the app: small eyebrow ("Leads"),
 *   tight 28px display name, status pills row, primary action button.
 *   The redundant "Back to leads" link was demoted to a tertiary link
 *   on the eyebrow row because AppShell's topbar already shows the
 *   breadcrumb chain ("Client Scout > Leads > Lead detail").
 *
 * * Every section is now a `.card` (new in index.css) - white surface,
 *   subtle border, multi-layer shadow. Headings unify on `.card-eyebrow`
 *   so the top-of-card text reads identically across sections. Replaces
 *   the prior `.surface-strong` + ad-hoc heading combo.
 *
 * * Score breakdown bars switched from a hard `bg-stone-200` track to
 *   `bg-zinc-100` and the fill is the emerald accent gradient instead
 *   of a flat `var(--accent)`, so they read as on-brand at a glance.
 *
 * * Pitch metadata chips converted from teal/amber to emerald/amber
 *   (the new design language). The personalization-notes pills are now
 *   .pill-zinc soft chips instead of bordered grey boxes.
 *
 * * Sales workflow row got proper field labels above each input (the
 *   previous version relied on placeholders, which disappear once a
 *   value is typed and leaves the operator guessing at column meaning).
 *
 * Component is intentionally still in one file. It's a long page (12+
 * sections) but operators expect them all to render in one place; we
 * gain very little by code-splitting and lose CSS locality.
 */

interface LeadDetailPageProps {
  session: ApiSession;
}

const LEAD_STATUS_OPTIONS: Array<{ value: string; label: string }> = [
  { value: "new", label: "New" },
  { value: "contacted", label: "Contacted" },
  { value: "replied", label: "Replied" },
  { value: "meeting_set", label: "Meeting set" },
  { value: "proposal_sent", label: "Proposal sent" },
  { value: "won", label: "Won" },
  { value: "lost", label: "Lost" },
  { value: "ignored", label: "Ignored" },
];

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

  // ── Loading / error states ───────────────────────────────────────────
  if (leadQuery.isLoading) {
    return (
      <div className="grid gap-4">
        {/* Skeletons mirror the actual section layout so the shift is
            invisible when data lands - the operator never sees content
            jump from "spinner" to "real card". */}
        <div className="skeleton h-24 w-full" />
        <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
          <div className="skeleton h-72 w-full" />
          <div className="skeleton h-72 w-full" />
        </div>
        <div className="skeleton h-40 w-full" />
        <div className="skeleton h-64 w-full" />
      </div>
    );
  }

  if (leadQuery.isError || !lead) {
    return (
      <div className="card p-5 text-sm font-medium text-rose-700">
        {(leadQuery.error as Error)?.message ?? "Lead not found."}
      </div>
    );
  }

  const bucket = scoreBucket(lead.score?.overall_score);
  const displayedPitch = freshPitch ?? lead.score?.pitch_notes ?? "No pitch generated yet.";
  // Object.entries widens the record value to `unknown`. Narrow back to a
  // [name, boolean] tuple so AuditCard can type-check without the rest of
  // the page taking the hit.
  const painFlags: [string, boolean][] = Object.entries(
    lead.audit?.pain_flags ?? {},
  )
    .filter(([, active]) => Boolean(active))
    .map(([key, active]) => [key, Boolean(active)]);
  const contactEmail = lead.contact_email ?? lead.email ?? "";
  const contactPhone = lead.contact_phone ?? lead.phone ?? "";
  const emailBody = lead.email_body ?? displayedPitch;
  const whatsappPitch = lead.whatsapp_message ?? displayedPitch;
  const emailPitch = `${lead.email_subject ?? `Quick idea for ${lead.name}`}\n\n${emailBody}`;
  const isSavingSales = salesMutation.isPending;

  return (
    <div className="grid gap-5">
      <PageHeader
        lead={lead}
        bucket={bucket}
        onRegenerate={() => pitchMutation.mutate()}
        isRegenerating={pitchMutation.isPending}
      />

      <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
        <BusinessInfoCard
          lead={lead}
          contactEmail={contactEmail}
          contactPhone={contactPhone}
        />
        <ScoreCard lead={lead} />
      </div>

      <SalesWorkflowCard
        lead={lead}
        statusDraft={statusDraft}
        notesDraft={notesDraft}
        followUpDraft={followUpDraft}
        onStatusChange={setStatusDraft}
        onNotesChange={setNotesDraft}
        onFollowUpChange={setFollowUpDraft}
        onRecordAttempt={() => contactAttemptMutation.mutate()}
        onSave={() => salesMutation.mutate()}
        isSaving={isSavingSales}
        attemptInFlight={contactAttemptMutation.isPending}
      />

      <CommunicationLog session={session} leadId={lead.id} />

      <AuditCard lead={lead} signals={signals} painFlags={painFlags} />

      <PitchCard
        lead={lead}
        whatsappPitch={whatsappPitch}
        emailBody={emailBody}
        emailPitch={emailPitch}
        pitchError={pitchMutation.isError ? (pitchMutation.error as Error).message : null}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page header
// ---------------------------------------------------------------------------

function PageHeader({
  lead,
  bucket,
  onRegenerate,
  isRegenerating,
}: {
  lead: LeadDetail;
  bucket: ReturnType<typeof scoreBucket>;
  onRegenerate: () => void;
  isRegenerating: boolean;
}) {
  return (
    <section>
      {/* Eyebrow with a back-link affordance. The shell already shows the
          breadcrumb chain, but this in-page link is the keyboardable
          equivalent and gives an obvious target on long detail pages
          where the topbar is scrolled away. */}
      <Link
        to="/leads"
        className="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-400 transition-colors hover:text-emerald-600"
      >
        <ArrowLeft className="h-3 w-3" />
        Leads
      </Link>

      <div className="mt-2 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="truncate text-[28px] font-bold tracking-tight text-zinc-900">
            {lead.name}
          </h1>
          <div className="mt-1.5 text-sm text-zinc-500">
            {lead.category ?? "Unknown niche"}
            <span className="mx-1.5 text-zinc-300">·</span>
            {lead.city ?? "Unknown city"}
            <span className="mx-1.5 text-zinc-300">·</span>
            <span className="capitalize">{lead.source}</span>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className={`pill ${scoreBucketTone(bucket)} capitalize`}>{bucket}</span>
            <span className="pill pill-zinc tabular-nums">
              Score {lead.score?.overall_score ?? 0}
            </span>
            {lead.score?.agency_fit_bucket ? (
              <span className="pill pill-emerald capitalize">
                Agency {lead.score.agency_fit_bucket}
                <span className="ml-1 tabular-nums opacity-80">
                  · {lead.score.agency_fit_score ?? 0}
                </span>
              </span>
            ) : null}
            {lead.score?.estimated_deal_value ? (
              <span className="pill pill-violet tabular-nums">
                ₹{lead.score.estimated_deal_value.toLocaleString("en-IN")} est.
              </span>
            ) : null}
          </div>
        </div>

        {/* Primary action. Uses the global .button-primary so the radius,
            hover halo, and active translate match the rest of the app. */}
        <button
          type="button"
          className="button button-primary h-10 px-4 text-sm"
          onClick={onRegenerate}
          disabled={isRegenerating}
        >
          <RefreshCw className={`h-4 w-4 ${isRegenerating ? "animate-spin" : ""}`} />
          {isRegenerating ? "Regenerating…" : "Regenerate pitch"}
        </button>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Business info
// ---------------------------------------------------------------------------

function BusinessInfoCard({
  lead,
  contactEmail,
  contactPhone,
}: {
  lead: LeadDetail;
  contactEmail: string;
  contactPhone: string;
}) {
  return (
    <section className="card p-5">
      <CardHeader icon={<Building2 className="h-3.5 w-3.5" />} title="Business info" />

      <div className="mt-4 grid gap-x-4 gap-y-5 md:grid-cols-2">
        <Info label="Website" value={lead.website_url ?? "—"} />
        <Info label="Phone" value={lead.phone ?? "—"} />
        <Info label="Email" value={lead.email ?? "—"} />
        {lead.contact_name ? <Info label="Contact name" value={lead.contact_name} /> : null}
        {lead.contact_title ? <Info label="Contact title" value={lead.contact_title} /> : null}
        {contactEmail ? (
          <CopyInfo
            icon={<Mail className="h-3.5 w-3.5" />}
            label="Contact email"
            value={contactEmail}
          />
        ) : null}
        {contactPhone ? (
          <CopyInfo
            icon={<Phone className="h-3.5 w-3.5" />}
            label="Contact phone"
            value={contactPhone}
          />
        ) : null}
        {lead.contact_linkedin_url ? (
          <Info label="LinkedIn" value={lead.contact_linkedin_url} />
        ) : null}
        {lead.contact_confidence ? (
          <Info label="Contact confidence" value={`${lead.contact_confidence}%`} />
        ) : null}
        <Info
          label="Rating"
          value={lead.rating ? `${lead.rating} / 5 · ${lead.review_count ?? 0} reviews` : "—"}
        />
        <Info
          label="Budget / Reliability"
          value={`${capitalise(lead.budget_tier) ?? "—"} / ${capitalise(lead.reliability) ?? "—"}`}
        />
        <Info label="Created" value={formatDate(lead.created_at)} />
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Score breakdown
// ---------------------------------------------------------------------------

function ScoreCard({ lead }: { lead: LeadDetail }) {
  return (
    <section className="card p-5">
      <CardHeader icon={<Gauge className="h-3.5 w-3.5" />} title="Score breakdown" />

      <div className="mt-4 grid gap-3.5">
        <Metric label="Website quality" value={lead.score?.website_quality ?? 0} />
        <Metric label="Online presence" value={lead.score?.online_presence ?? 0} />
        <Metric label="Conversion readiness" value={lead.score?.conversion_readiness ?? 0} />
        <Metric label="Urgency" value={lead.score?.urgency ?? 0} />
        <Metric label="Agency fit" value={lead.score?.agency_fit_score ?? 0} />
      </div>

      {lead.score?.opportunity_types?.length ? (
        <div className="mt-5 border-t border-zinc-200/70 pt-4">
          <div className="card-eyebrow">Opportunity types</div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {lead.score.opportunity_types.map((item) => (
              <span key={item} className="pill pill-emerald">
                {item}
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Sales workflow
// ---------------------------------------------------------------------------

function SalesWorkflowCard({
  lead,
  statusDraft,
  notesDraft,
  followUpDraft,
  onStatusChange,
  onNotesChange,
  onFollowUpChange,
  onRecordAttempt,
  onSave,
  isSaving,
  attemptInFlight,
}: {
  lead: LeadDetail;
  statusDraft: string;
  notesDraft: string;
  followUpDraft: string;
  onStatusChange: (next: string) => void;
  onNotesChange: (next: string) => void;
  onFollowUpChange: (next: string) => void;
  onRecordAttempt: () => void;
  onSave: () => void;
  isSaving: boolean;
  attemptInFlight: boolean;
}) {
  return (
    <section className="card p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <CardHeader icon={<Target className="h-3.5 w-3.5" />} title="Sales workflow" />
        <span className="text-[11px] font-medium text-zinc-500">
          Last contacted: <span className="text-zinc-700">{formatDate(lead.last_contacted_at)}</span>
        </span>
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-[180px_180px_minmax(0,1fr)]">
        <FieldLabel htmlFor="lead-status" label="Status">
          <select
            id="lead-status"
            className="field"
            value={statusDraft}
            onChange={(event) => onStatusChange(event.target.value)}
          >
            {LEAD_STATUS_OPTIONS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </FieldLabel>

        <FieldLabel htmlFor="lead-followup" label="Follow up">
          <input
            id="lead-followup"
            className="field"
            type="date"
            value={followUpDraft}
            onChange={(event) => onFollowUpChange(event.target.value)}
          />
        </FieldLabel>

        <FieldLabel htmlFor="lead-notes" label="Notes">
          <input
            id="lead-notes"
            className="field"
            value={notesDraft}
            onChange={(event) => onNotesChange(event.target.value)}
            placeholder="Sales notes (visible to your team)"
          />
        </FieldLabel>
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-end gap-2">
        <button
          type="button"
          className="button button-secondary h-9 px-3 text-sm"
          onClick={onRecordAttempt}
          disabled={attemptInFlight}
          title="Log another outreach attempt"
        >
          <MessageCircle className="h-4 w-4" />
          Attempt {lead.contact_attempts ?? 0}
        </button>
        <button
          type="button"
          className="button button-primary h-9 px-3 text-sm"
          onClick={onSave}
          disabled={isSaving}
        >
          <Save className="h-4 w-4" />
          {isSaving ? "Saving…" : "Save"}
        </button>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Audit signals
// ---------------------------------------------------------------------------

function AuditCard({
  lead,
  signals,
  painFlags,
}: {
  lead: LeadDetail;
  signals: [string, boolean][];
  painFlags: [string, boolean][];
}) {
  return (
    <section className="card p-5">
      <CardHeader icon={<ShieldCheck className="h-3.5 w-3.5" />} title="Audit signals" />

      <div className="mt-4 flex flex-wrap gap-1.5">
        {signals.map(([label, value]) => (
          <SignalPill key={label} label={label} value={Boolean(value)} />
        ))}
      </div>

      {lead.audit ? (
        <div className="mt-5 grid gap-x-4 gap-y-5 border-t border-zinc-200/70 pt-4 md:grid-cols-3">
          <Info label="Load time" value={lead.audit.load_time_ms ? `${lead.audit.load_time_ms} ms` : "—"} />
          <Info label="PageSpeed" value={lead.audit.page_speed_score?.toString() ?? "—"} />
          <Info label="Tech stack" value={lead.audit.tech_stack?.join(", ") || "—"} />
          <Info label="CMS" value={lead.audit.cms_detected ?? "—"} />
        </div>
      ) : null}

      {painFlags.length ? (
        <div className="mt-5 border-t border-zinc-200/70 pt-4">
          <div className="card-eyebrow">Pain flags</div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {painFlags.map(([flag]) => (
              <span key={flag} className="pill pill-amber">
                {flag.replace("pain_", "").replaceAll("_", " ")}
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Pitch
// ---------------------------------------------------------------------------

function PitchCard({
  lead,
  whatsappPitch,
  emailBody,
  emailPitch,
  pitchError,
}: {
  lead: LeadDetail;
  whatsappPitch: string;
  emailBody: string;
  emailPitch: string;
  pitchError: string | null;
}) {
  return (
    <section className="card p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <CardHeader icon={<Sparkles className="h-3.5 w-3.5" />} title="Pitch" />
        {pitchError ? (
          <div className="pill pill-rose">
            {pitchError}
          </div>
        ) : null}
      </div>

      {lead.pain_points_used?.length || lead.pitch_recommended_services?.length ? (
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          {lead.pain_points_used?.length ? (
            <PitchMetaBlock
              title="Pitch uses these gaps"
              items={lead.pain_points_used}
              tone="amber"
            />
          ) : null}
          {lead.pitch_recommended_services?.length ? (
            <PitchMetaBlock
              title="Recommended services"
              items={lead.pitch_recommended_services}
              tone="emerald"
            />
          ) : null}
        </div>
      ) : null}

      <div className="mt-4 flex flex-wrap gap-2">
        {lead.whatsapp_link ? (
          <a
            className="button button-primary h-9 px-3 text-sm"
            href={lead.whatsapp_link}
            rel="noreferrer"
            target="_blank"
          >
            <ExternalLink className="h-4 w-4" />
            Send via WhatsApp
          </a>
        ) : null}
        <button
          className="button button-secondary h-9 px-3 text-sm"
          onClick={() => navigator.clipboard.writeText(whatsappPitch)}
          type="button"
        >
          <Copy className="h-4 w-4" />
          Copy WhatsApp
        </button>
        <button
          className="button button-secondary h-9 px-3 text-sm"
          onClick={() => navigator.clipboard.writeText(emailPitch)}
          type="button"
        >
          <Copy className="h-4 w-4" />
          Copy email pitch
        </button>
      </div>

      {lead.email_subject ? (
        <div className="mt-5">
          <div className="card-eyebrow">Email subject</div>
          <div className="mt-2 rounded-[10px] border border-zinc-200/70 bg-zinc-50 px-3 py-2 text-sm font-semibold text-zinc-900">
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
          {lead.whatsapp_follow_up ? (
            <PitchCopyBlock title="WhatsApp follow-up" text={lead.whatsapp_follow_up} compact />
          ) : null}
          {lead.call_opener ? (
            <PitchCopyBlock title="Call opener" text={lead.call_opener} compact />
          ) : null}
        </div>
      ) : null}

      {lead.personalization_notes?.length ? (
        <div className="mt-5 border-t border-zinc-200/70 pt-4">
          <div className="card-eyebrow">Personalization notes</div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {lead.personalization_notes.map((item) => (
              <span key={item} className="pill pill-zinc">
                {item}
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Tiny shared sub-components
// ---------------------------------------------------------------------------

/**
 * Standardised section heading. Every premium card on the page uses this
 * exact treatment - small icon chip, eyebrow text - so a quick scan of
 * the page reads as a coherent column of sections.
 */
function CardHeader({ icon, title }: { icon: React.ReactNode; title: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="flex h-6 w-6 items-center justify-center rounded-md bg-zinc-100 text-zinc-500">
        {icon}
      </span>
      <span className="card-eyebrow">{title}</span>
    </div>
  );
}

/**
 * Read-only label/value pair. Layout:
 *
 *   LABEL        (zinc-400, 11px, uppercase, 0.08em tracking)
 *   value text   (zinc-900, 14px, semibold)
 *
 * Truncates at the parent's content box so a long URL or comma-joined
 * tech stack doesn't break the column grid.
 */
function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="text-[10.5px] font-semibold uppercase tracking-[0.08em] text-zinc-400">
        {label}
      </div>
      <div className="mt-1.5 truncate text-sm font-semibold text-zinc-800" title={value}>
        {value}
      </div>
    </div>
  );
}

/**
 * Same shape as Info but the value is a button that copies to clipboard
 * on click. We surface the copy affordance inline (icon + value) instead
 * of behind a separate icon button, because operators copy contact info
 * dozens of times per session and a target the size of the value itself
 * is meaningfully faster than a 12px icon.
 */
function CopyInfo({
  icon,
  label,
  value,
}: {
  icon?: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="min-w-0">
      <div className="text-[10.5px] font-semibold uppercase tracking-[0.08em] text-zinc-400">
        {label}
      </div>
      <button
        type="button"
        onClick={() => navigator.clipboard.writeText(value)}
        title={`Copy ${label.toLowerCase()}`}
        className="group mt-1.5 flex w-full min-w-0 items-center gap-2 rounded-md text-left text-sm font-semibold text-zinc-800 transition-colors hover:text-emerald-700"
      >
        {icon ? (
          <span className="text-zinc-400 transition-colors group-hover:text-emerald-500">
            {icon}
          </span>
        ) : null}
        <span className="truncate">{value}</span>
        <Copy className="h-3 w-3 shrink-0 text-zinc-300 transition-colors group-hover:text-emerald-500" />
      </button>
    </div>
  );
}

/**
 * One row of the score breakdown. The track sits on a soft zinc-100 base
 * and the fill is a left-to-right emerald gradient, so the bar reads as
 * the same visual language as the metric cards on /board.
 *
 * Width is clamped 0..100 so a stale row that overshoots (negative or
 * >100) never paints outside the track.
 */
function Metric({ label, value }: { label: string; value: number }) {
  const clamped = Math.max(0, Math.min(value, 100));
  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between text-[12.5px]">
        <span className="font-semibold text-zinc-800">{label}</span>
        <span className="font-mono tabular-nums text-zinc-500">{clamped}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-zinc-100">
        <div
          className="h-full rounded-full bg-gradient-to-r from-emerald-400 to-emerald-600 transition-[width] duration-500 ease-out"
          style={{ width: `${clamped}%` }}
        />
      </div>
    </div>
  );
}

/**
 * Form field wrapper - label sits above the input in the same eyebrow
 * style as section headings. Single source of truth for spacing means
 * three fields side-by-side stay vertically aligned no matter how long
 * a label gets.
 */
function FieldLabel({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid gap-1.5">
      <label
        htmlFor={htmlFor}
        className="flex items-center gap-1 text-[10.5px] font-semibold uppercase tracking-[0.08em] text-zinc-500"
      >
        <PencilLine className="h-3 w-3 text-zinc-400" />
        {label}
      </label>
      {children}
    </div>
  );
}

/**
 * Tag-grid block used in the Pitch card.
 *
 * Two tones ("amber" for pain-related context, "emerald" for positive
 * recommendations) so the operator can tell at a glance which side of
 * the pitch each chip belongs to.
 */
function PitchMetaBlock({
  title,
  items,
  tone,
}: {
  title: string;
  items: string[];
  tone: "amber" | "emerald";
}) {
  const pillClass = tone === "amber" ? "pill pill-amber" : "pill pill-emerald";
  return (
    <div>
      <div className="card-eyebrow">{title}</div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {items.map((item) => (
          <span key={item} className={pillClass}>
            {item}
          </span>
        ))}
      </div>
    </div>
  );
}

/**
 * Long-form pitch text with a subtle frame. The compact variant is for
 * shorter "WhatsApp follow-up" / "call opener" snippets so they don't
 * hog vertical space.
 */
function PitchCopyBlock({
  title,
  text,
  compact = false,
}: {
  title: string;
  text: string;
  compact?: boolean;
}) {
  return (
    <div>
      <div className="card-eyebrow">{title}</div>
      <pre
        className={`mt-2 whitespace-pre-wrap rounded-[10px] border border-zinc-200/70 bg-zinc-50 p-3 font-sans text-sm leading-7 text-zinc-800 ${
          compact ? "min-h-24" : "min-h-48"
        }`}
      >
        {text}
      </pre>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function capitalise(value: string | null | undefined): string | null {
  if (!value) return null;
  return value.charAt(0).toUpperCase() + value.slice(1);
}
