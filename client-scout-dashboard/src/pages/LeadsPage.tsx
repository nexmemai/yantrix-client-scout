import { FormEvent, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Filter, Play } from "lucide-react";
import { Filter, Play } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { apiClient, ApiSession } from "../api/client";
import { VirtualizedLeadTable } from "../components/VirtualizedLeadTable";
import { useJobEvents } from "../hooks/useJobEvents";
import { useToast } from "../components/Toast";

interface LeadsPageProps {
  session: ApiSession;
}

/**
 * LeadsPage - filter form + virtualised cursor-paginated table.
 *
 * Filters drive the QueryKey so swapping a filter creates a fresh
 * useInfiniteQuery cache. The Run-Scout form remains an SSE-tracked job
 * launcher; success/failure surface via the existing toast layer.
 *
 * URL query params (?bucket=hot, ?lead_status=contacted, etc.) seed initial
 * filter state so the command palette's "Filter: hot" command works as a
 * deep link.
 */
export function LeadsPage({ session }: LeadsPageProps) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [searchParams, setSearchParams] = useSearchParams();

  // Filters: read from URL on mount so palette deep-links work.
  const [city, setCity] = useState(searchParams.get("city") ?? "");
  const [niche, setNiche] = useState(searchParams.get("niche") ?? "");
  const [bucket, setBucket] = useState(searchParams.get("bucket") ?? "");
  const [agencyBucket, setAgencyBucket] = useState(searchParams.get("agency_fit_bucket") ?? "");
  const [leadStatus, setLeadStatus] = useState(searchParams.get("lead_status") ?? "");
  const [search, setSearch] = useState(searchParams.get("search") ?? "");

  // Run-scout form state.
  const [runNiche, setRunNiche] = useState("dental");
  const [runCity, setRunCity] = useState("");
  const [maxBusinesses, setMaxBusinesses] = useState(25);
  // Phase 4 - Autonomous Outreach toggle. Defaults to false so a user
  // who never noticed the switch never accidentally mass-mails leads.
  // The toast / aria-live announcement on flip-to-true reinforces that
  // intent before submission.
  const [autoSendEnabled, setAutoSendEnabled] = useState(false);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);

  // Server-side filters consumed by the virtualised table. We only forward
  // params the API supports; everything else is local UI state.
  const filters = useMemo(
    () => ({
      city: city || undefined,
      niche: niche || undefined,
      bucket: bucket || undefined,
      agency_fit_bucket: agencyBucket || undefined,
      lead_status: leadStatus || undefined,
      search: search || undefined,
    }),
    [agencyBucket, bucket, city, leadStatus, niche, search],
  );

  // Mirror filter state back into the URL so the command palette deep-links
  // remain bookmarkable. Replace (not push) keeps history tidy.
  useEffect(() => {
    const next = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => {
      if (value !== undefined && value !== "") next.set(key, String(value));
    });
    setSearchParams(next, { replace: true });
  }, [filters, setSearchParams]);

  const summaryQuery = useQuery({
    queryKey: ["leads", "summary"],
    queryFn: () => apiClient.getLeadSummary(session),
  });

  const runScoutMutation = useMutation({
    mutationFn: () =>
      apiClient.runScout(session, {
        niche: runNiche.trim(),
        city: runCity.trim(),
        max_businesses: maxBusinesses,
        auto_send_enabled: autoSendEnabled,
      }),
    onSuccess: (response) => {
      setActiveJobId(response.job_id);
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      toast.info(
        autoSendEnabled ? "Scout queued (auto-send ON)" : "Scout queued",
        autoSendEnabled
          ? `Job ${response.job_id.slice(0, 8)}… - high/mid-fit leads will be auto-contacted as pitches generate.`
          : `Job ${response.job_id.slice(0, 8)}… is in the queue.`,
      );
    },
    onError: (error: unknown) => {
      toast.error(
        "Scout failed to start",
        error instanceof Error ? error.message : "Unknown error",
      );
    },
  });

  const { job, transport } = useJobEvents({
    session,
    jobId: activeJobId,
    onJobCompleted: (event) => {
      const data = event.data as Record<string, number | undefined>;
      const discovered = data.discovered ?? 0;
      const audited = data.audited ?? 0;
      const pitched = data.pitched ?? 0;
      toast.success(
        "Scout completed",
        `${discovered} discovered • ${audited} audited • ${pitched} pitched`,
      );
      queryClient.invalidateQueries({ queryKey: ["leads"] });
      queryClient.invalidateQueries({ queryKey: ["leads", "summary"] });
      queryClient.invalidateQueries({ queryKey: ["leads", "board"] });
    },
    onJobFailed: (event) => {
      const data = event.data as { error?: string; reaper?: boolean };
      const reason = data.reaper
        ? "The worker process died before completion. The reaper marked it failed."
        : data.error ?? "Pipeline error.";
      toast.error("Scout failed", reason);
    },
  });

  // One-off toast when SSE transport degrades.
  useEffect(() => {
    if (transport === "polling") {
      toast.warning(
        "Live updates degraded",
        "Real-time event stream is unavailable. Falling back to polling every 4s.",
      );
    }
  }, [transport, toast]);

  const jobRunning =
    runScoutMutation.isPending ||
    job?.status === "running" ||
    job?.status === "queued" ||
    job?.status === "pending";

  const jobProgressText = job
    ? `${job.total_scored || job.total_audited || job.total_discovered} / ${Math.max(job.total_discovered, maxBusinesses)} leads processed`
    : "No active scout job";

  const submitRunScout = (event: FormEvent) => {
    event.preventDefault();
    if (!runNiche.trim() || !runCity.trim() || jobRunning) return;
    runScoutMutation.mutate();
  };

  return (
    <div className="grid gap-4">
      <section className="surface section-band">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-2xl font-extrabold">Leads</div>
            <div className="mt-1 text-sm text-[var(--muted)]">
              Filter live scout output by location, niche, fit, and freshness. Press
              <kbd className="mx-1 rounded border border-[var(--line)] bg-white/70 px-1 text-[10px] font-bold text-[var(--muted)]">⌘K</kbd>
              for the command palette.
            </div>
          </div>
          <div className="inline-flex items-center gap-2 rounded-full border border-[var(--line)] bg-white/70 px-3 py-2 text-xs font-semibold text-[var(--muted)]">
            <Filter className="h-3.5 w-3.5 text-[var(--warm)]" />
            cursor pagination
          </div>
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <SummaryStat label="Follow-ups today" value={summaryQuery.data?.followups_today ?? 0} />
          <SummaryStat label="New hot leads" value={summaryQuery.data?.new_hot_leads ?? 0} />
          <SummaryStat label="Stale contacted" value={summaryQuery.data?.stale_contacted ?? 0} />
        </div>
        <form
          className="mt-5 grid gap-3 border-y border-[var(--line)] py-4 lg:grid-cols-[1fr_1fr_160px_auto]"
          onSubmit={submitRunScout}
        >
          <input
            className="field"
            placeholder="Niche (any industry, e.g. EV charging)"
            value={runNiche}
            onChange={(event) => setRunNiche(event.target.value)}
          />
          <input
            className="field"
            placeholder="City (incl. spaces, hyphens, apostrophes)"
            value={runCity}
            onChange={(event) => setRunCity(event.target.value)}
          />
          <input
            className="field"
            max={100}
            min={1}
            type="number"
            value={maxBusinesses}
            onChange={(event) => setMaxBusinesses(Number(event.target.value))}
          />
          <button
            className="button button-primary h-11 px-4 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-60"
            disabled={jobRunning || !runNiche.trim() || !runCity.trim()}
            type="submit"
          >
            <Play className="h-4 w-4" />
            {jobRunning ? "Running..." : "Run Scout"}
          </button>
          <div className="lg:col-span-4">
            <AutoSendToggle
              enabled={autoSendEnabled}
              disabled={jobRunning}
              onChange={setAutoSendEnabled}
            />
          </div>
          <div className="lg:col-span-4">
            {job ? (
              <div className="inline-flex max-w-full flex-wrap items-center gap-2 rounded-full border border-[var(--line)] bg-white/70 px-3 py-2 text-xs font-semibold text-[var(--muted)]">
                <span
                  className={
                    job.status === "failed" ? "text-[var(--danger)]" : "text-[var(--accent)]"
                  }
                >
                  Job {job.status}
                </span>
                <span>
                  {job.niche ?? runNiche} in {job.city ?? runCity}
                </span>
                <span>{jobProgressText}</span>
              </div>
            ) : null}
            {runScoutMutation.isError ? (
              <div className="mt-2 text-sm text-[var(--danger)]">
                {(runScoutMutation.error as Error).message}
              </div>
            ) : null}
          </div>
        </form>
        <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-6">
          <input
            className="field"
            placeholder="City"
            value={city}
            onChange={(event) => setCity(event.target.value)}
          />
          <input
            className="field"
            placeholder="Niche key"
            value={niche}
            onChange={(event) => setNiche(event.target.value)}
          />
          <input
            className="field"
            placeholder="Search by name"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
          <select
            className="field"
            value={bucket}
            onChange={(event) => setBucket(event.target.value)}
          >
            <option value="">All score buckets</option>
            <option value="high-fit">high-fit</option>
            <option value="mid-fit">mid-fit</option>
            <option value="low-fit">low-fit</option>
          </select>
          <select
            className="field"
            value={agencyBucket}
            onChange={(event) => setAgencyBucket(event.target.value)}
          >
            <option value="">All agency fits</option>
            <option value="hot">hot</option>
            <option value="warm">warm</option>
            <option value="cold">cold</option>
            <option value="skip">skip</option>
          </select>
          <select
            className="field"
            value={leadStatus}
            onChange={(event) => setLeadStatus(event.target.value)}
          >
            <option value="">All statuses</option>
            <option value="new">new</option>
            <option value="contacted">contacted</option>
            <option value="replied">replied</option>
            <option value="meeting_set">meeting_set</option>
            <option value="proposal_sent">proposal_sent</option>
            <option value="won">won</option>
            <option value="lost">lost</option>
            <option value="ignored">ignored</option>
          </select>
        </div>
      </section>

      <VirtualizedLeadTable session={session} filters={filters} />
    </div>
  );
}

function SummaryStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-[var(--line)] bg-white/70 px-3 py-2">
      <div className="text-xs font-bold uppercase text-[var(--muted)]">{label}</div>
      <div className="mt-1 text-xl font-extrabold">{value}</div>
    </div>
  );
}

/**
 * Phase 4 - Autonomous Outreach toggle.
 *
 * Pure controlled component. Visual treatment is intentionally weighty:
 *   * amber background when ON to flag "this is a high-risk action",
 *   * an accompanying warning band that only appears when ON so users
 *     reading the form for the first time aren't desensitised to it,
 *   * disabled state respects the parent form's running flag so the
 *     state can't change mid-run.
 *
 * The actual switch is built from a hidden checkbox + a styled label so
 * it stays accessible (keyboard space-bar toggles, screen readers see
 * "checkbox" with its label and aria-describedby). No headless-ui import
 * needed; we already keep the dashboard dependency surface tight.
 */
function AutoSendToggle({
  enabled,
  disabled,
  onChange,
}: {
  enabled: boolean;
  disabled: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <div
      className={`rounded-lg border px-4 py-3 transition ${
        enabled
          ? "border-[var(--warm)] bg-amber-50"
          : "border-[var(--line)] bg-white/60"
      }`}
    >
      <label className="flex cursor-pointer items-start gap-3">
        <span className="relative inline-flex shrink-0 items-center">
          <input
            aria-describedby="auto-send-helper"
            checked={enabled}
            className="peer sr-only"
            disabled={disabled}
            onChange={(event) => onChange(event.target.checked)}
            type="checkbox"
          />
          {/* Track */}
          <span
            aria-hidden="true"
            className={`block h-6 w-11 rounded-full transition ${
              enabled ? "bg-[var(--warm)]" : "bg-stone-300"
            } peer-disabled:opacity-50`}
          />
          {/* Thumb */}
          <span
            aria-hidden="true"
            className={`absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${
              enabled ? "translate-x-5" : "translate-x-0"
            }`}
          />
        </span>
        <span className="min-w-0">
          <span className="block text-sm font-bold text-[var(--text)]">
            Fully Automated Mode (Auto-Send Pitches)
          </span>
          <span
            className="mt-1 block text-xs leading-snug text-[var(--muted)]"
            id="auto-send-helper"
          >
            When enabled, the worker emails and WhatsApps every high-fit and
            mid-fit lead using the AI-generated pitch as soon as it is
            produced. There is no human review step.
          </span>
        </span>
      </label>
      {enabled ? (
        <div
          aria-live="polite"
          className="mt-3 flex items-start gap-2 rounded-md border border-amber-300 bg-amber-100/70 px-3 py-2 text-xs font-semibold leading-snug text-amber-900"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>
            Warning: This will automatically send the AI-generated email and
            WhatsApp pitch without human review. Confirm SMTP and WhatsApp
            credentials are configured before launching a real run; otherwise
            attempts will be recorded as dry-runs.
          </span>
        </div>
      ) : null}
    </div>
  );
}
