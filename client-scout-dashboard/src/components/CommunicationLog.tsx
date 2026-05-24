import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Mail,
  MessageSquare,
  XCircle,
} from "lucide-react";
import { apiClient, ApiSession } from "../api/client";
import {
  LeadOutreachStatus,
  OutreachAttempt,
  OutreachAttemptStatus,
  OutreachChannel,
} from "../lib/types";
import { formatDate } from "../lib/utils";

/**
 * CommunicationLog - Phase 4 read-only timeline rendered on LeadDetailPage.
 *
 * Data source: GET /api/v1/leads/{id}/outreach. The endpoint returns both a
 * summary header (lead-level) and the ordered attempt list, so we fetch
 * once and render both halves from the same TanStack Query.
 *
 * Behaviour:
 *   * Polls every 8 seconds while the latest attempt is "pending" so a
 *     fresh autonomous send shows up live without a refresh. Stops
 *     polling once everything is terminal.
 *   * Empty state explicitly distinguishes "never attempted" (idle)
 *     from "no contact channel on file" (skipped) - operators care
 *     about the difference when chasing missing data.
 *   * Failed attempts surface the verbatim provider error from the
 *     backend in a callout the same colour as the toast error variant
 *     so the visual language stays consistent.
 *
 * Why a separate component (vs. inline on LeadDetailPage):
 *   * The page already lives near its component-line budget; pulling
 *     this out keeps the page readable.
 *   * Future surfaces (Kanban card popover, daily digest email preview)
 *     can reuse the same renderer.
 */
export function CommunicationLog({
  session,
  leadId,
}: {
  session: ApiSession;
  leadId: string;
}) {
  const query = useQuery({
    queryKey: ["lead", leadId, "outreach"],
    queryFn: () => apiClient.getLeadOutreach(session, leadId),
    enabled: Boolean(leadId),
    refetchInterval: (q) => {
      const data = q.state.data;
      if (!data) return false;
      // Keep polling while a send is in flight so the operator sees the
      // outcome without refreshing. 8s is comfortably below the SMTP
      // retry budget but not noisy.
      const hasPending = data.attempts.some((a) => a.status === "pending");
      const summaryPending = data.summary.outreach_status === "pending";
      return hasPending || summaryPending ? 8_000 : false;
    },
  });

  return (
    <section className="surface-strong p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm font-bold uppercase text-[var(--muted)]">
          Communication log
        </div>
        {query.data ? <LeadStatusBadge status={query.data.summary.outreach_status} /> : null}
      </div>

      {query.isLoading ? (
        <div className="mt-4 text-sm text-[var(--muted)]">
          Loading outreach timeline…
        </div>
      ) : query.isError ? (
        <div className="mt-4 flex items-start gap-2 rounded-md border border-[var(--danger)]/30 bg-red-50 px-3 py-2 text-sm text-[var(--danger)]">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            Could not load outreach history.{" "}
            {(query.error as Error)?.message ?? "Try refreshing the page."}
          </span>
        </div>
      ) : query.data ? (
        <CommunicationLogBody data={query.data} />
      ) : null}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Body
// ---------------------------------------------------------------------------

function CommunicationLogBody({
  data,
}: {
  data: { summary: import("../lib/types").OutreachLeadSummary; attempts: OutreachAttempt[] };
}) {
  const { summary, attempts } = data;

  // Channel availability strip - explains *why* an empty timeline is empty.
  const channelHints: string[] = [];
  if (!summary.has_email_channel) channelHints.push("no email on file");
  if (!summary.has_whatsapp_channel) channelHints.push("no phone on file");

  if (attempts.length === 0) {
    return (
      <div className="mt-4 rounded-md border border-dashed border-[var(--line)] bg-white/70 px-3 py-4 text-sm text-[var(--muted)]">
        <div className="font-semibold text-[var(--text)]">
          No outreach attempts yet
        </div>
        <div className="mt-1">
          {channelHints.length > 0
            ? `Auto-send will skip this lead until enrichment fills in ${channelHints.join(" and ")}.`
            : "Run a scout with auto-send enabled, or trigger a manual send, to populate this log."}
        </div>
      </div>
    );
  }

  return (
    <>
      {summary.last_outreach_error ? (
        <div className="mt-4 flex items-start gap-2 rounded-md border border-[var(--danger)]/30 bg-red-50 px-3 py-2 text-xs font-semibold text-[var(--danger)]">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span className="break-words">
            Last outreach error: {summary.last_outreach_error}
          </span>
        </div>
      ) : null}

      <ol className="mt-4 grid gap-3">
        {attempts.map((attempt) => (
          <CommunicationLogItem key={attempt.id} attempt={attempt} />
        ))}
      </ol>
    </>
  );
}

function CommunicationLogItem({ attempt }: { attempt: OutreachAttempt }) {
  const { Icon: ChannelIcon, label: channelLabel } = channelMeta(attempt.channel);
  const { Icon: StatusIcon, tone, label: statusLabel } = statusMeta(attempt.status);

  return (
    <li
      className={`relative rounded-lg border px-3 py-3 ${
        attempt.status === "failed"
          ? "border-[var(--danger)]/30 bg-red-50/60"
          : "border-[var(--line)] bg-white/80"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="inline-flex items-center gap-1.5 rounded-full border border-[var(--line)] bg-white px-2 py-1 font-semibold text-[var(--muted)]">
          <ChannelIcon className="h-3.5 w-3.5" />
          {channelLabel}
        </span>
        <span
          className={`inline-flex items-center gap-1.5 rounded-full px-2 py-1 font-semibold ${tone}`}
        >
          <StatusIcon className="h-3.5 w-3.5" />
          {statusLabel}
        </span>
        {attempt.is_dry_run ? (
          <span className="inline-flex items-center gap-1 rounded-full border border-[var(--line)] bg-stone-100 px-2 py-0.5 text-[10px] font-bold uppercase text-[var(--muted)]">
            dry run
          </span>
        ) : null}
        {attempt.provider ? (
          <span className="text-[var(--muted)]">via {attempt.provider}</span>
        ) : null}
        <span className="ml-auto text-[var(--muted)]">
          {formatDate(attempt.attempted_at)}
        </span>
      </div>

      {attempt.recipient ? (
        <div className="mt-2 text-xs text-[var(--muted)]">
          To <span className="font-semibold text-[var(--text)]">{attempt.recipient}</span>
        </div>
      ) : null}

      {attempt.payload_subject ? (
        <div className="mt-2 text-sm font-semibold leading-snug">
          {attempt.payload_subject}
        </div>
      ) : null}

      {attempt.payload_body ? (
        <p className="mt-1 line-clamp-3 whitespace-pre-wrap text-sm leading-relaxed text-[var(--text)]">
          {attempt.payload_body}
        </p>
      ) : null}

      {attempt.error_message ? (
        <div className="mt-2 rounded-md border border-[var(--danger)]/30 bg-white px-2 py-1 text-xs font-semibold text-[var(--danger)]">
          {attempt.error_message}
        </div>
      ) : null}
    </li>
  );
}

// ---------------------------------------------------------------------------
// Lookups
// ---------------------------------------------------------------------------

function channelMeta(channel: OutreachChannel): {
  Icon: typeof Mail;
  label: string;
} {
  if (channel === "email") return { Icon: Mail, label: "Email" };
  if (channel === "whatsapp") return { Icon: MessageSquare, label: "WhatsApp" };
  return { Icon: MessageSquare, label: "SMS" };
}

function statusMeta(status: OutreachAttemptStatus): {
  Icon: typeof Mail;
  tone: string;
  label: string;
} {
  switch (status) {
    case "sent":
      return {
        Icon: CheckCircle2,
        tone: "bg-emerald-100 text-emerald-800",
        label: "Sent",
      };
    case "failed":
      return {
        Icon: XCircle,
        tone: "bg-red-100 text-[var(--danger)]",
        label: "Failed",
      };
    case "skipped":
      return {
        Icon: AlertTriangle,
        tone: "bg-stone-200 text-stone-700",
        label: "Skipped",
      };
    case "pending":
    default:
      return {
        Icon: Clock,
        tone: "bg-amber-100 text-amber-800",
        label: "Pending",
      };
  }
}

function LeadStatusBadge({ status }: { status: LeadOutreachStatus }) {
  const { tone, label } = leadStatusMeta(status);
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ${tone}`}
    >
      {label}
    </span>
  );
}

function leadStatusMeta(status: LeadOutreachStatus): { tone: string; label: string } {
  switch (status) {
    case "sent":
      return { tone: "bg-emerald-100 text-emerald-800", label: "All channels sent" };
    case "partial":
      return { tone: "bg-amber-100 text-amber-800", label: "Partial — one channel failed" };
    case "failed":
      return { tone: "bg-red-100 text-[var(--danger)]", label: "All channels failed" };
    case "skipped":
      return { tone: "bg-stone-200 text-stone-700", label: "Skipped — no contact channel" };
    case "pending":
      return { tone: "bg-amber-100 text-amber-800", label: "Send in progress" };
    case "idle":
    default:
      return { tone: "bg-stone-100 text-[var(--muted)]", label: "Not yet contacted" };
  }
}
