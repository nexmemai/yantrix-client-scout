import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Inbox,
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
 * UI rev (premium pass):
 *   * Wrapped in the new `.card` surface so it visually belongs to the
 *     same column of cards as Business Info / Score Breakdown.
 *   * Header uses the standard `.card-eyebrow` treatment + an Inbox
 *     icon chip so a quick scan of the page reads as one consistent
 *     section pattern.
 *   * Attempts rendered as a real vertical timeline (zinc-200 connector
 *     line, channel-tinted dots) instead of a stack of bordered cards.
 *     The connector visually proves "these events are ordered in time"
 *     without us needing to label that fact.
 *   * Status pills moved to the global `.pill-*` family - emerald for
 *     sent, amber for pending, rose for failed, zinc for skipped. Same
 *     vocabulary as the table and toast variants.
 *   * Dry-run badge converted from a chunky uppercase chip to a sleek
 *     hairline pill ("• Dry run") so it reads as quiet metadata, not
 *     a primary signal.
 *
 * Behavioural contract is unchanged: same TanStack Query key, same
 * 8s polling rule while pending, same envelope shape (summary +
 * attempts) consumed from `apiClient.getLeadOutreach`.
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
    <section className="card p-5">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="flex h-6 w-6 items-center justify-center rounded-md bg-zinc-100 text-zinc-500">
            <Inbox className="h-3.5 w-3.5" />
          </span>
          <span className="card-eyebrow">Communication log</span>
        </div>
        {query.data ? (
          <LeadStatusBadge status={query.data.summary.outreach_status} />
        ) : null}
      </header>

      {query.isLoading ? (
        // Three matched-height skeletons keep the layout from jumping when
        // the first render lands. Same shimmer keyframe as the rest of the
        // app's loading states.
        <div className="mt-5 grid gap-3">
          <div className="skeleton h-16 w-full" />
          <div className="skeleton h-16 w-full" />
        </div>
      ) : query.isError ? (
        <ErrorBanner
          message={(query.error as Error)?.message ?? "Try refreshing the page."}
        />
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

  // Surface "why an attempt would have skipped this lead" text up front so
  // the empty state can name the missing channel(s).
  const channelHints: string[] = [];
  if (!summary.has_email_channel) channelHints.push("no email on file");
  if (!summary.has_whatsapp_channel) channelHints.push("no phone on file");

  if (attempts.length === 0) {
    return (
      <EmptyState
        title="No outreach attempts yet"
        body={
          channelHints.length > 0
            ? `Auto-send will skip this lead until enrichment fills in ${channelHints.join(" and ")}.`
            : "Run a scout with auto-send enabled, or trigger a manual send, to populate this log."
        }
      />
    );
  }

  return (
    <>
      {summary.last_outreach_error ? (
        // Polished error callout. Replaces the previous flat red box with
        // a hairline rose-tinted card that uses the same shadow scale as
        // the parent .card so it reads as part of the surface, not an
        // alarm popping out of the page.
        <div className="mt-5 flex items-start gap-2.5 rounded-[10px] border border-rose-200/70 bg-rose-50/80 px-3.5 py-2.5">
          <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-rose-100 text-rose-600">
            <AlertTriangle className="h-3 w-3" />
          </span>
          <div className="min-w-0">
            <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-rose-700">
              Last outreach error
            </div>
            <div className="mt-0.5 break-words text-[12.5px] font-medium text-rose-900">
              {summary.last_outreach_error}
            </div>
          </div>
        </div>
      ) : null}

      <Timeline attempts={attempts} />
    </>
  );
}

/**
 * Vertical timeline.
 *
 * The connector line is a single 1px column running down the left side of
 * the dot column (`border-zinc-200/70`). Each item gets:
 *   * a 28px dot in the channel's tint color, sitting on top of the
 *     connector so it visually "punches through" the line,
 *   * a content card that sits to the right of the dot.
 *
 * We render the connector with an absolutely-positioned span instead of a
 * border on the OL itself so the line stops cleanly at the last dot
 * without dangling past the final item.
 */
function Timeline({ attempts }: { attempts: OutreachAttempt[] }) {
  return (
    <ol className="relative mt-5 grid gap-5 pl-7">
      <span
        aria-hidden
        className="absolute left-[13px] top-1 bottom-1 w-px bg-gradient-to-b from-zinc-200 via-zinc-200/70 to-transparent"
      />
      {attempts.map((attempt) => (
        <TimelineItem key={attempt.id} attempt={attempt} />
      ))}
    </ol>
  );
}

function TimelineItem({ attempt }: { attempt: OutreachAttempt }) {
  const channel = channelMeta(attempt.channel);
  const status = statusMeta(attempt.status);

  return (
    <li className="relative">
      {/* Dot marker. Absolutely positioned so the content card next to it
          aligns to the same baseline regardless of card height. The ring
          gives the dot a clean separation from the connector line. */}
      <span
        aria-hidden
        className={`absolute -left-7 top-0.5 flex h-7 w-7 items-center justify-center rounded-full ring-4 ring-white ${channel.dotBg} ${channel.dotText}`}
      >
        <channel.Icon className="h-3.5 w-3.5" />
      </span>

      <article className="rounded-[10px] border border-zinc-200/70 bg-white p-3.5 shadow-[var(--shadow-sm)] transition-all duration-200 hover:border-zinc-300 hover:shadow-[var(--shadow-md)]">
        {/* Top metadata row: channel name, status pill, dry-run hairline,
            provider, and timestamp. The timestamp is right-aligned so a
            quick visual scan of the right edge tells you the pace. */}
        <div className="flex flex-wrap items-center gap-2 text-[11.5px]">
          <span className="font-semibold text-zinc-900">{channel.label}</span>

          <span className={`pill ${status.pillClass}`}>
            <status.Icon className="h-3 w-3" />
            {status.label}
          </span>

          {attempt.is_dry_run ? <DryRunChip /> : null}

          {attempt.provider ? (
            <span className="text-zinc-400">via {attempt.provider}</span>
          ) : null}

          <span className="ml-auto font-medium text-zinc-400">
            {formatDate(attempt.attempted_at)}
          </span>
        </div>

        {attempt.recipient ? (
          <div className="mt-2 text-[12px] text-zinc-500">
            To{" "}
            <span className="font-semibold text-zinc-800">{attempt.recipient}</span>
          </div>
        ) : null}

        {attempt.payload_subject ? (
          <div className="mt-2 text-[13.5px] font-semibold leading-snug text-zinc-900">
            {attempt.payload_subject}
          </div>
        ) : null}

        {attempt.payload_body ? (
          <p className="mt-1.5 line-clamp-3 whitespace-pre-wrap text-[13px] leading-relaxed text-zinc-600">
            {attempt.payload_body}
          </p>
        ) : null}

        {attempt.error_message ? (
          // Inline, lower-key version of the page-level error callout. We
          // don't want a second loud alarm on the page when there's
          // already a summary one above the timeline.
          <div className="mt-2.5 flex items-start gap-1.5 rounded-md border border-rose-200/70 bg-rose-50/60 px-2.5 py-1.5 text-[11.5px] font-medium text-rose-800">
            <XCircle className="mt-px h-3 w-3 shrink-0 text-rose-500" />
            <span className="break-words">{attempt.error_message}</span>
          </div>
        ) : null}
      </article>
    </li>
  );
}

// ---------------------------------------------------------------------------
// Small bits
// ---------------------------------------------------------------------------

/**
 * Sleek minimal chip, used only for the dry-run flag.
 *
 * Style intent: read as quiet metadata, not a primary status. A small
 * leading dot, hairline border, no fill. If we ever introduce a "test
 * mode" or "shadow run" flag we should reuse this exact component so
 * "this attempt is informational, not real" is a single visual cue.
 */
function DryRunChip() {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-zinc-200/80 bg-white px-1.5 py-0.5 text-[10px] font-semibold text-zinc-500">
      <span aria-hidden className="h-1 w-1 rounded-full bg-zinc-400" />
      Dry run
    </span>
  );
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="mt-5 flex items-start gap-2.5 rounded-[10px] border border-rose-200/70 bg-rose-50/80 px-3.5 py-2.5 text-[12.5px] font-medium text-rose-900">
      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-rose-100 text-rose-600">
        <AlertTriangle className="h-3 w-3" />
      </span>
      <div>
        <div className="font-semibold text-rose-800">Could not load outreach history</div>
        <div className="mt-0.5 text-rose-700/90">{message}</div>
      </div>
    </div>
  );
}

function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="mt-5 flex flex-col items-center rounded-[10px] border border-dashed border-zinc-200 bg-zinc-50/50 px-4 py-8 text-center">
      <span className="flex h-9 w-9 items-center justify-center rounded-full bg-emerald-50 text-emerald-600">
        <Inbox className="h-4 w-4" />
      </span>
      <div className="mt-3 text-sm font-semibold text-zinc-900">{title}</div>
      <div className="mt-1 max-w-md text-[12.5px] leading-relaxed text-zinc-500">
        {body}
      </div>
    </div>
  );
}

function LeadStatusBadge({ status }: { status: LeadOutreachStatus }) {
  const { pillClass, label } = leadStatusMeta(status);
  return <span className={`pill ${pillClass}`}>{label}</span>;
}

// ---------------------------------------------------------------------------
// Lookups
// ---------------------------------------------------------------------------

function channelMeta(channel: OutreachChannel): {
  Icon: typeof Mail;
  label: string;
  dotBg: string;
  dotText: string;
} {
  if (channel === "email") {
    return {
      Icon: Mail,
      label: "Email",
      dotBg: "bg-sky-100",
      dotText: "text-sky-600",
    };
  }
  if (channel === "whatsapp") {
    return {
      Icon: MessageSquare,
      label: "WhatsApp",
      dotBg: "bg-emerald-100",
      dotText: "text-emerald-600",
    };
  }
  return {
    Icon: MessageSquare,
    label: "SMS",
    dotBg: "bg-violet-100",
    dotText: "text-violet-600",
  };
}

function statusMeta(status: OutreachAttemptStatus): {
  Icon: typeof Mail;
  pillClass: string;
  label: string;
} {
  switch (status) {
    case "sent":
      return { Icon: CheckCircle2, pillClass: "pill-emerald", label: "Sent" };
    case "failed":
      return { Icon: XCircle, pillClass: "pill-rose", label: "Failed" };
    case "skipped":
      return { Icon: AlertTriangle, pillClass: "pill-zinc", label: "Skipped" };
    case "pending":
    default:
      return { Icon: Clock, pillClass: "pill-amber", label: "Pending" };
  }
}

function leadStatusMeta(
  status: LeadOutreachStatus,
): { pillClass: string; label: string } {
  switch (status) {
    case "sent":
      return { pillClass: "pill-emerald", label: "All channels sent" };
    case "partial":
      return { pillClass: "pill-amber", label: "Partial — one channel failed" };
    case "failed":
      return { pillClass: "pill-rose", label: "All channels failed" };
    case "skipped":
      return { pillClass: "pill-zinc", label: "Skipped — no contact channel" };
    case "pending":
      return { pillClass: "pill-amber", label: "Send in progress" };
    case "idle":
    default:
      return { pillClass: "pill-zinc", label: "Not yet contacted" };
  }
}
