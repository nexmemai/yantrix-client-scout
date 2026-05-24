import { MouseEvent, useEffect, useMemo, useRef } from "react";
import { useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Inbox, MessageCircle } from "lucide-react";
import { Link } from "react-router-dom";
import { ApiSession, apiClient } from "../api/client";
import {
  LeadDetail,
  LeadListItem,
  PaginatedLeads,
} from "../lib/types";
import { formatDate, scoreBucket, scoreBucketTone } from "../lib/utils";
import { useToast } from "./Toast";

/**
 * VirtualizedLeadTable - cursor-paginated, lightly virtualised lead grid.
 *
 * In addition to streaming pages via cursor pagination, each row exposes
 * inline actions so SDRs do not have to drill into a detail page for the
 * 80% case (move status, fire WhatsApp):
 *
 *   * WhatsApp deep-link icon - resolves the lead's phone + AI-generated
 *     whatsapp_message via /api/v1/leads/{id} (cached) and opens wa.me in
 *     a new tab. Falls back to a clipboard copy + toast if the lead has
 *     no usable phone number.
 *   * Four status dots - new / contacted / qualified (mapped to
 *     `meeting_set` server-side) / won. Each click is an optimistic
 *     useMutation that patches every cached page of every infinite query
 *     so the row updates instantly. Failure rolls back via the snapshot.
 *
 * Why we don't use @tanstack/react-virtual here: the page sizes are small
 * (50 rows) and we only render a single window of fetched data; doing the
 * virtualisation inline keeps the dep tree slim and the optimistic update
 * code easier to reason about.
 */

interface VirtualizedLeadTableProps {
  session: ApiSession;
  filters: Record<string, string | number | undefined | null>;
  pageSize?: number;
}

const DEFAULT_PAGE_SIZE = 50;

// Quick-toggle status set. The label in the UI uses "qualified" (operator
// vocabulary), but the backend lead_status enum stores it as
// `meeting_set` so the API contract stays unchanged.
type QuickStatusKey = "new" | "contacted" | "qualified" | "won";
const QUICK_STATUSES: Array<{
  key: QuickStatusKey;
  apiValue: string;
  label: string;
  className: string;
}> = [
  { key: "new",        apiValue: "new",         label: "New",       className: "bg-zinc-300" },
  { key: "contacted",  apiValue: "contacted",   label: "Contacted", className: "bg-amber-400" },
  { key: "qualified",  apiValue: "meeting_set", label: "Qualified", className: "bg-sky-500" },
  { key: "won",        apiValue: "won",         label: "Won",       className: "bg-emerald-500" },
];

// Soft-tinted status pill classes, Linear/Attio style: low-saturation bg
// + saturated foreground. Fallback covers any backend-only state we
// haven't styled yet (e.g. a future "qualified_meeting_held").
function leadStatusPillClass(status: string): string {
  switch (status) {
    case "new":
      return "bg-zinc-100 text-zinc-700";
    case "contacted":
      return "bg-amber-100 text-amber-800";
    case "replied":
      return "bg-sky-100 text-sky-800";
    case "meeting_set":
      return "bg-violet-100 text-violet-800";
    case "proposal_sent":
      return "bg-indigo-100 text-indigo-800";
    case "won":
      return "bg-emerald-100 text-emerald-800";
    case "lost":
      return "bg-rose-100 text-rose-800";
    case "ignored":
      return "bg-zinc-100 text-zinc-500";
    default:
      return "bg-zinc-100 text-zinc-700";
  }
}

function leadStatusLabel(status: string): string {
  // Operator-friendly labels. We never show backend-internal underscored
  // names in tooltips/badges - they read like database columns.
  switch (status) {
    case "meeting_set":   return "Qualified";
    case "proposal_sent": return "Proposal";
    default:
      return status.charAt(0).toUpperCase() + status.slice(1);
  }
}

export function VirtualizedLeadTable({
  session,
  filters,
  pageSize = DEFAULT_PAGE_SIZE,
}: VirtualizedLeadTableProps) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  const {
    data,
    error,
    fetchNextPage,
    hasNextPage,
    isFetching,
    isFetchingNextPage,
    isLoading,
  } = useInfiniteQuery<PaginatedLeads, Error>({
    queryKey: ["leads", "cursor", filters, pageSize],
    initialPageParam: undefined,
    queryFn: async ({ pageParam }) =>
      apiClient.listLeads(session, {
        ...filters,
        cursor: (pageParam as string | undefined) ?? undefined,
        limit: pageSize,
      }),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });

  const rows = useMemo<LeadListItem[]>(
    () => data?.pages.flatMap((page) => page.items) ?? [],
    [data],
  );

  // Surface fetch errors via toast so the failure mode is consistent with
  // the rest of the app instead of an inline grey box.
  useEffect(() => {
    if (error) {
      toast.error("Failed to load leads", error.message);
    }
  }, [error, toast]);

  // IntersectionObserver-based infinite scroll. Uses a sentinel so we never
  // depend on imperative scroll position math, which is fragile across
  // browsers and zoom levels.
  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel) return;
    const observer = new IntersectionObserver(
      (entries) => {
        const [entry] = entries;
        if (entry.isIntersecting && hasNextPage && !isFetchingNextPage) {
          fetchNextPage();
        }
      },
      { rootMargin: "320px 0px" },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [fetchNextPage, hasNextPage, isFetchingNextPage]);

  // ── Optimistic status mutation ────────────────────────────────────────
  // Snapshots every infinite-query page that contains the lead, patches
  // them in-place, and rolls back on error. We also patch the legacy
  // `["leads"]` cache key (used by polling and other views) so the lead's
  // new status survives navigation.
  const statusMutation = useMutation<
    void,
    Error,
    { leadId: string; status: string },
    { snapshots: Array<[readonly unknown[], unknown]> }
  >({
    mutationFn: async ({ leadId, status }) => {
      await apiClient.updateLeadSales(session, leadId, { lead_status: status });
    },
    onMutate: async ({ leadId, status }) => {
      // Cancel in-flight fetches so we don't race them.
      await queryClient.cancelQueries({ queryKey: ["leads"] });

      // Capture every leads cache (cursor, polling, summary cards) BEFORE
      // we touch them so onError can put them back exactly as they were.
      const snapshots: Array<[readonly unknown[], unknown]> = [];

      queryClient
        .getQueryCache()
        .findAll({ queryKey: ["leads"] })
        .forEach((cached) => {
          snapshots.push([cached.queryKey, cached.state.data]);
          const data = cached.state.data;
          if (!data) return;

          // Infinite query shape: { pages: [{ items: [...] }, ...] }.
          if (typeof data === "object" && data !== null && "pages" in data) {
            const next = {
              ...data,
              pages: (data as { pages: PaginatedLeads[] }).pages.map((page) => ({
                ...page,
                items: page.items.map((item) =>
                  item.id === leadId ? { ...item, lead_status: status } : item,
                ),
              })),
            };
            queryClient.setQueryData(cached.queryKey, next);
            return;
          }

          // Single-page shape (older /leads consumers).
          if (typeof data === "object" && data !== null && "items" in data) {
            const next = {
              ...data,
              items: (data as PaginatedLeads).items.map((item) =>
                item.id === leadId ? { ...item, lead_status: status } : item,
              ),
            };
            queryClient.setQueryData(cached.queryKey, next);
          }
        });

      return { snapshots };
    },
    onError: (err, _vars, context) => {
      // Rollback every snapshot we took.
      context?.snapshots.forEach(([key, value]) => {
        queryClient.setQueryData(key, value);
      });
      toast.error("Status update failed", err.message);
    },
    onSuccess: () => {
      toast.success("Status updated", "Lead moved to its new column.");
    },
    onSettled: () => {
      // Fresh server data for the board view + summary counters.
      queryClient.invalidateQueries({ queryKey: ["leads", "board"] });
      queryClient.invalidateQueries({ queryKey: ["leads", "summary"] });
    },
  });

  // ── WhatsApp deep-link ────────────────────────────────────────────────
  // The list payload doesn't carry phone or whatsapp_message, so we lazily
  // fetch the lead detail when the icon is clicked. The detail endpoint
  // produces a fully-formed wa.me link (`whatsapp_link`), and falls back to
  // composing one client-side here when the server-side helper short-circuits
  // (no phone) so the operator sees an explicit toast either way.
  const openWhatsApp = async (leadId: string) => {
    try {
      const detail: LeadDetail = await queryClient.fetchQuery({
        queryKey: ["lead", leadId],
        queryFn: () => apiClient.getLead(session, leadId),
      });
      if (detail.whatsapp_link) {
        window.open(detail.whatsapp_link, "_blank", "noopener,noreferrer");
        return;
      }
      const phone = (detail.contact_phone || detail.phone || "").replace(/\D/g, "");
      if (!phone || phone.length < 8) {
        toast.warning(
          "No usable phone number",
          "This lead has no contact number we can deep-link to WhatsApp.",
        );
        return;
      }
      const message = detail.whatsapp_message || `Hi ${detail.name},`;
      const link = `https://wa.me/${phone}?text=${encodeURIComponent(message)}`;
      window.open(link, "_blank", "noopener,noreferrer");
    } catch (err) {
      toast.error(
        "Could not open WhatsApp",
        err instanceof Error ? err.message : "Unknown error",
      );
    }
  };

  return (
    <section className="surface-strong table-wrap">
      {isLoading && rows.length === 0 ? (
        // Skeleton rows while the first page loads. Three matches the visible
        // window most operators see before scrolling, so the layout doesn't
        // jump on first paint.
        <div className="grid gap-3 p-5">
          {Array.from({ length: 4 }).map((_, idx) => (
            <div key={idx} className="skeleton h-12 w-full" />
          ))}
        </div>
      ) : (
        <>
          <table>
            <thead>
              <tr>
                <th>Lead</th>
                <th>City</th>
                <th>Website</th>
                <th>Status</th>
                <th>Score</th>
                <th>Agency fit</th>
                <th>Created</th>
                <th aria-label="Quick actions" />
              </tr>
            </thead>
            <tbody>
              {rows.map((lead) => (
                <LeadRow
                  key={lead.id}
                  lead={lead}
                  isPending={
                    statusMutation.isPending &&
                    statusMutation.variables?.leadId === lead.id
                  }
                  onSetStatus={(apiValue) =>
                    statusMutation.mutate({ leadId: lead.id, status: apiValue })
                  }
                  onWhatsApp={() => openWhatsApp(lead.id)}
                />
              ))}
              {rows.length === 0 && !isLoading ? (
                <tr>
                  <td colSpan={8} className="px-5 py-12">
                    <EmptyTableState />
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
          <div
            ref={sentinelRef}
            className="flex items-center justify-center py-3 text-xs font-medium text-zinc-400"
            aria-live="polite"
          >
            {isFetchingNextPage
              ? "Loading more…"
              : hasNextPage
                ? "Scroll for more"
                : isFetching
                  ? "Refreshing…"
                  : rows.length > 0
                    ? "End of pipeline"
                    : null}
          </div>
        </>
      )}
    </section>
  );
}

/**
 * Empty state for the pipeline table.
 *
 * The previous "No leads match the current filters." string read like an
 * error condition. The redesign frames it as a deliberate state with a
 * soft icon, a clear explanation, and a discoverability hint that the
 * command palette is the fastest way to either run a scout or clear the
 * filter, instead of forcing the operator to dig through the form.
 */
function EmptyTableState() {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-emerald-50 text-emerald-600">
        <Inbox className="h-5 w-5" />
      </div>
      <div className="mt-4 text-sm font-semibold text-zinc-900">No leads match these filters</div>
      <div className="mt-1 text-xs text-zinc-500">
        Loosen a filter, or press
        <kbd className="mx-1 rounded border border-zinc-200 bg-white px-1 py-[1px] text-[10px] font-semibold text-zinc-600">
          ⌘K
        </kbd>
        to run a fresh scout.
      </div>
    </div>
  );
}

interface LeadRowProps {
  lead: LeadListItem;
  isPending: boolean;
  onSetStatus: (apiValue: string) => void;
  onWhatsApp: () => void;
}

function LeadRow({ lead, isPending, onSetStatus, onWhatsApp }: LeadRowProps) {
  const currentBucket = scoreBucket(lead.overall_score);

  // Stop the row's <Link> from intercepting clicks on the quick-action
  // buttons. Using onClickCapture on each button avoids fighting React
  // Router's anchor-click delegation.
  const swallow = (event: MouseEvent) => {
    event.preventDefault();
    event.stopPropagation();
  };

  return (
    <tr className={isPending ? "opacity-70" : undefined}>
      <td>
        <Link
          className="table-row-link -mx-2 flex items-center justify-between gap-3 rounded-md px-2 py-1"
          to={`/leads/${lead.id}`}
        >
          <div className="min-w-0">
            <div className="truncate text-[14px] font-semibold text-zinc-900">{lead.name}</div>
            <div className="truncate text-[12px] text-zinc-400">
              {lead.category ?? "Unknown niche"}
            </div>
          </div>
          <ChevronRight className="h-4 w-4 shrink-0 text-zinc-300 transition-colors group-hover:text-zinc-500" />
        </Link>
      </td>
      <td className="text-[13px] text-zinc-700">{lead.city ?? "—"}</td>
      <td>
        {lead.has_website ? (
          <span className="pill pill-emerald">Yes</span>
        ) : (
          <span className="pill pill-zinc">No</span>
        )}
      </td>
      <td>
        <span className={`pill ${leadStatusPillClass(lead.lead_status)}`}>
          {leadStatusLabel(lead.lead_status)}
        </span>
      </td>
      <td>
        <div className="flex items-center gap-2">
          <span className="text-[14px] font-semibold tabular-nums text-zinc-900">
            {lead.overall_score ?? 0}
          </span>
          <span className={`pill ${scoreBucketTone(currentBucket)}`}>
            {currentBucket}
          </span>
        </div>
      </td>
      <td>
        <div className="grid gap-0.5">
          <span className="text-[13px] font-semibold capitalize text-zinc-800">
            {lead.agency_fit_bucket ?? "—"}
          </span>
          <span className="text-[11px] tabular-nums text-zinc-400">
            {lead.estimated_deal_value
              ? `₹${lead.estimated_deal_value.toLocaleString("en-IN")}`
              : "—"}
          </span>
        </div>
      </td>
      <td className="text-[12px] text-zinc-500">{formatDate(lead.created_at)}</td>
      <td>
        <div className="flex items-center justify-end gap-2">
          {/* WhatsApp deep-link icon. Detail fetch happens on click, not on hover,
              to avoid a wave of GETs as the user scrolls. */}
          <button
            type="button"
            aria-label="Send via WhatsApp"
            title="Send via WhatsApp"
            onClickCapture={(event) => {
              swallow(event);
              onWhatsApp();
            }}
            className="flex h-7 w-7 items-center justify-center rounded-md border border-zinc-200 bg-white text-zinc-500 shadow-[var(--shadow-sm)] transition-all duration-200 hover:border-emerald-300 hover:bg-emerald-50 hover:text-emerald-600"
          >
            <MessageCircle className="h-3.5 w-3.5" />
          </button>

          {/* Four status dots. Each is keyboard accessible (aria-label) and
              shows the canonical operator label as a tooltip. The active
              dot gets an emerald ring + small scale-up so it pops without
              shifting layout. */}
          <div className="flex items-center gap-1 rounded-full border border-zinc-200 bg-white p-1 shadow-[var(--shadow-sm)]">
            {QUICK_STATUSES.map((status) => {
              const active = lead.lead_status === status.apiValue;
              return (
                <button
                  key={status.key}
                  type="button"
                  aria-label={`Mark as ${status.label}`}
                  title={status.label}
                  onClickCapture={(event) => {
                    swallow(event);
                    if (active || isPending) return;
                    onSetStatus(status.apiValue);
                  }}
                  disabled={isPending}
                  className={`h-3 w-3 rounded-full transition-all duration-200 ${status.className} ${
                    active
                      ? "ring-2 ring-emerald-400 ring-offset-1 ring-offset-white scale-110"
                      : "opacity-50 hover:opacity-100 hover:scale-110"
                  } disabled:cursor-wait`}
                />
              );
            })}
          </div>
        </div>
      </td>
    </tr>
  );
}
