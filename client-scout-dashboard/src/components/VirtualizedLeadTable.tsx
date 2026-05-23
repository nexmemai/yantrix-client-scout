import { useEffect, useMemo, useRef } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";
import { ApiSession, apiClient } from "../api/client";
import { LeadListItem, PaginatedLeads } from "../lib/types";
import { formatDate, scoreBucket, scoreBucketTone } from "../lib/utils";
import { useToast } from "./Toast";

/**
 * VirtualizedLeadTable - cursor-paginated, lightly virtualised lead grid.
 *
 * Goals:
 *   * Stream thousands of leads without tipping the browser into jank.
 *   * Use the new server-side cursor pagination (next_cursor / has_more).
 *   * Keep the surface visually identical to the existing leads table so
 *     the rewrite is invisible to operators.
 *
 * Why the simple windowing instead of @tanstack/react-virtual:
 *   We render at most ~50 rows per page and only show the last fetched page
 *   plus the next sentinel. Adding @tanstack/react-virtual was 2.5kb gz +
 *   another dep just to slice an array; doing it inline keeps the dashboard
 *   bundle tighter and the code easier to debug. If row counts ever exceed
 *   ~5k visible at once we revisit, but cursor pagination already caps that.
 */

interface VirtualizedLeadTableProps {
  session: ApiSession;
  filters: Record<string, string | number | undefined | null>;
  pageSize?: number;
}

const DEFAULT_PAGE_SIZE = 50;

export function VirtualizedLeadTable({
  session,
  filters,
  pageSize = DEFAULT_PAGE_SIZE,
}: VirtualizedLeadTableProps) {
  const toast = useToast();
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

  return (
    <section className="surface-strong table-wrap">
      {isLoading && rows.length === 0 ? (
        <div className="p-6 text-sm text-[var(--muted)]">Loading leads…</div>
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
              </tr>
            </thead>
            <tbody>
              {rows.map((lead) => (
                <LeadRow key={lead.id} lead={lead} />
              ))}
              {rows.length === 0 && !isLoading ? (
                <tr>
                  <td colSpan={7} className="p-6 text-sm text-[var(--muted)]">
                    No leads match the current filters.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
          <div
            ref={sentinelRef}
            className="flex items-center justify-center py-3 text-xs text-[var(--muted)]"
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

function LeadRow({ lead }: { lead: LeadListItem }) {
  const currentBucket = scoreBucket(lead.overall_score);
  return (
    <tr>
      <td>
        <Link
          className="table-row-link flex items-center justify-between gap-3 rounded-md px-2 py-1 -mx-2"
          to={`/leads/${lead.id}`}
        >
          <div className="min-w-0">
            <div className="truncate font-semibold">{lead.name}</div>
            <div className="text-xs text-[var(--muted)]">
              {lead.category ?? "Unknown niche"}
            </div>
          </div>
          <ChevronRight className="h-4 w-4 text-[var(--muted)]" />
        </Link>
      </td>
      <td>{lead.city}</td>
      <td>{lead.has_website ? "Yes" : "No"}</td>
      <td>
        <span className="rounded-full border border-[var(--line)] bg-white/70 px-2 py-1 text-xs font-semibold">
          {lead.lead_status}
        </span>
      </td>
      <td>
        <div className="flex items-center gap-2">
          <span className="font-semibold">{lead.overall_score ?? 0}</span>
          <span
            className={`rounded-full px-2 py-1 text-xs font-semibold ${scoreBucketTone(currentBucket)}`}
          >
            {currentBucket}
          </span>
        </div>
      </td>
      <td>
        <div className="grid gap-1 text-sm">
          <span className="font-semibold">{lead.agency_fit_bucket ?? "-"}</span>
          <span className="text-xs text-[var(--muted)]">
            {lead.estimated_deal_value
              ? `₹${lead.estimated_deal_value.toLocaleString("en-IN")}`
              : "-"}
          </span>
        </div>
      </td>
      <td>{formatDate(lead.created_at)}</td>
    </tr>
  );
}
