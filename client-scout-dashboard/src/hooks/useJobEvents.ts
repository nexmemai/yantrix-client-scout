import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiClient, ApiSession } from "../api/client";
import { JobStatus } from "../lib/types";

/**
 * Real-time job tracking for one DiscoveryJob.
 *
 * Strategy:
 *   1. Open an EventSource against /api/v1/jobs/{id}/events for instant
 *      progress without 4-second polling.
 *   2. If SSE is unsupported (older browsers / corp proxies that strip
 *      `text/event-stream`), or fails repeatedly, transparently fall back
 *      to TanStack Query polling so the UI never appears frozen.
 *   3. Surface terminal states ("completed" / "failed") via the onJobFailed
 *      and onJobCompleted callbacks so the page can fire toasts and
 *      invalidate dependent queries (the leads list, in our case).
 *
 * Auth note: EventSource cannot send custom headers, so the bearer token
 * is appended as ?token= and validated server-side. Keep this hook in sync
 * with the SSE auth contract in app/api/jobs.py.
 */

export type JobEventType =
  | "job_queued"
  | "stage_started"
  | "stage_progress"
  | "stage_completed"
  | "stage_failed"
  | "job_completed"
  | "job_failed"
  | "stream_error";

export interface JobEvent {
  type: JobEventType;
  job_id: string;
  stage: string | null;
  data: Record<string, unknown>;
  ts: string;
}

export interface UseJobEventsOptions {
  session: ApiSession;
  jobId: string | null;
  /** Called once when the job reaches `completed`. */
  onJobCompleted?: (event: JobEvent) => void;
  /** Called once when the job reaches `failed` or the SSE stream errors fatally. */
  onJobFailed?: (event: JobEvent) => void;
}

export interface UseJobEventsResult {
  /** Latest server-known status, derived from events or the polling fallback. */
  job: JobStatus | null;
  /** Last raw event received (for debug overlays). */
  lastEvent: JobEvent | null;
  /**
   * Active transport. "sse" means events are streaming live; "polling" means
   * we've fallen back; "idle" means no jobId is being tracked.
   */
  transport: "sse" | "polling" | "idle";
  /**
   * True when the current connection is degraded (one or more SSE retries
   * failed) but we're still trying. The UI uses this to nudge a banner.
   */
  isDegraded: boolean;
}

const SSE_RETRY_BACKOFF_MS = [1_000, 2_000, 4_000, 8_000] as const;
const POLLING_FALLBACK_INTERVAL_MS = 4_000;
const MAX_SSE_RETRIES_BEFORE_FALLBACK = SSE_RETRY_BACKOFF_MS.length;

function buildSseUrl(session: ApiSession, jobId: string): string {
  // Production: same-origin Nginx proxy at /api. Vite dev: respect
  // VITE_API_BASE_URL, defaulting to relative paths so the dev proxy works.
  const isProd = !import.meta.env.DEV;
  const base = isProd ? "" : session.apiBaseUrl || import.meta.env.VITE_API_BASE_URL || "";
  const path = `/api/v1/jobs/${encodeURIComponent(jobId)}/events`;
  // Token MUST go on the URL because EventSource has no header API.
  const tokenParam = `?token=${encodeURIComponent(session.token)}`;
  if (!base) return `${path}${tokenParam}`;
  const trimmed = base.endsWith("/") ? base.slice(0, -1) : base;
  return `${trimmed}${path}${tokenParam}`;
}

/**
 * Project the known fields of a worker event onto the JobStatus shape so
 * the rest of the dashboard can keep reading a single source of truth.
 */
function applyEventToJob(prev: JobStatus | null, event: JobEvent, jobId: string): JobStatus {
  const base: JobStatus = prev ?? {
    id: jobId,
    query: "",
    city: null,
    source: "google_maps",
    niche: null,
    status: "queued",
    total_discovered: 0,
    total_audited: 0,
    total_scored: 0,
    total_pitched: 0,
    error_message: null,
    started_at: null,
    created_at: event.ts,
    updated_at: event.ts,
    last_updated_at: event.ts,
    completed_at: null,
  };

  const data = event.data ?? {};
  const next: JobStatus = {
    ...base,
    updated_at: event.ts,
    last_updated_at: event.ts,
  };

  if (typeof data.niche === "string") next.niche = data.niche;
  if (typeof data.city === "string") next.city = data.city;

  if (event.type === "job_queued") {
    next.status = "queued";
  } else if (event.type === "stage_started" || event.type === "stage_progress") {
    next.status = "running";
    if (typeof data.discovered === "number") next.total_discovered = data.discovered;
  } else if (event.type === "stage_completed") {
    next.status = "running";
    if (event.stage === "discovery" && typeof data.discovered === "number") {
      next.total_discovered = data.discovered;
    }
  } else if (event.type === "job_completed") {
    next.status = "completed";
    next.completed_at = event.ts;
    if (typeof data.discovered === "number") next.total_discovered = data.discovered;
    if (typeof data.audited === "number") next.total_audited = data.audited;
    if (typeof data.scored === "number") next.total_scored = data.scored;
    if (typeof data.pitched === "number") next.total_pitched = data.pitched;
  } else if (event.type === "job_failed") {
    next.status = "failed";
    next.completed_at = event.ts;
    if (typeof data.error === "string") next.error_message = data.error;
  }

  return next;
}

export function useJobEvents({
  session,
  jobId,
  onJobCompleted,
  onJobFailed,
}: UseJobEventsOptions): UseJobEventsResult {
  const queryClient = useQueryClient();
  const [job, setJob] = useState<JobStatus | null>(null);
  const [lastEvent, setLastEvent] = useState<JobEvent | null>(null);
  const [transport, setTransport] = useState<"sse" | "polling" | "idle">("idle");
  const [isDegraded, setIsDegraded] = useState(false);

  // Keep the latest callbacks in refs so we don't tear down the EventSource
  // every time a parent re-renders with a new arrow-function reference.
  const onCompletedRef = useRef(onJobCompleted);
  const onFailedRef = useRef(onJobFailed);
  useEffect(() => { onCompletedRef.current = onJobCompleted; }, [onJobCompleted]);
  useEffect(() => { onFailedRef.current = onJobFailed; }, [onJobFailed]);

  // Track whether SSE is the active transport for this jobId. Used to
  // disable polling while SSE is healthy.
  const useSseRef = useRef(true);
  const terminalReachedRef = useRef(false);

  // Reset state when the job we're tracking changes.
  useEffect(() => {
    setJob(null);
    setLastEvent(null);
    setIsDegraded(false);
    useSseRef.current = true;
    terminalReachedRef.current = false;
    setTransport(jobId ? "sse" : "idle");
  }, [jobId]);

  // ── Polling fallback (TanStack Query, only enabled if SSE is off) ──────
  const pollingQuery = useQuery({
    queryKey: ["jobs", jobId, "polling-fallback"],
    queryFn: () => apiClient.getJob(session, jobId as string),
    enabled: Boolean(jobId) && transport === "polling",
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return POLLING_FALLBACK_INTERVAL_MS;
      return data.status === "completed" || data.status === "failed"
        ? false
        : POLLING_FALLBACK_INTERVAL_MS;
    },
  });

  useEffect(() => {
    if (!pollingQuery.data) return;
    setJob(pollingQuery.data);
    if (pollingQuery.data.status === "completed" && !terminalReachedRef.current) {
      terminalReachedRef.current = true;
      onCompletedRef.current?.({
        type: "job_completed",
        job_id: pollingQuery.data.id,
        stage: "pipeline",
        data: {},
        ts: pollingQuery.data.completed_at ?? new Date().toISOString(),
      });
    } else if (pollingQuery.data.status === "failed" && !terminalReachedRef.current) {
      terminalReachedRef.current = true;
      onFailedRef.current?.({
        type: "job_failed",
        job_id: pollingQuery.data.id,
        stage: "pipeline",
        data: { error: pollingQuery.data.error_message ?? "Job failed" },
        ts: pollingQuery.data.completed_at ?? new Date().toISOString(),
      });
    }
  }, [pollingQuery.data]);

  // ── SSE primary path ──────────────────────────────────────────────────
  useEffect(() => {
    if (!jobId || !useSseRef.current) return;
    if (typeof window === "undefined" || typeof window.EventSource === "undefined") {
      // No native SSE: skip directly to polling.
      useSseRef.current = false;
      setTransport("polling");
      return;
    }

    let cancelled = false;
    let source: EventSource | null = null;
    let retryAttempt = 0;
    let reconnectTimer: number | null = null;

    const handleEvent = (raw: MessageEvent) => {
      if (cancelled) return;
      try {
        const parsed = JSON.parse(raw.data) as JobEvent;
        setLastEvent(parsed);
        setJob((prev) => applyEventToJob(prev, parsed, jobId));

        if (parsed.type === "job_completed" && !terminalReachedRef.current) {
          terminalReachedRef.current = true;
          onCompletedRef.current?.(parsed);
          // Trigger downstream cache invalidations the same way polling did.
          queryClient.invalidateQueries({ queryKey: ["leads"] });
          queryClient.invalidateQueries({ queryKey: ["jobs"] });
          source?.close();
        } else if (parsed.type === "job_failed" && !terminalReachedRef.current) {
          terminalReachedRef.current = true;
          onFailedRef.current?.(parsed);
          queryClient.invalidateQueries({ queryKey: ["jobs"] });
          source?.close();
        }
      } catch {
        // A malformed payload is non-fatal; the next message will drive the UI.
      }
    };

    const connect = () => {
      if (cancelled) return;
      const url = buildSseUrl(session, jobId);
      source = new EventSource(url, { withCredentials: false });

      source.onopen = () => {
        if (cancelled) return;
        retryAttempt = 0;
        setIsDegraded(false);
        setTransport("sse");
      };

      // Generic message handler covers events that aren't installed via
      // explicit addEventListener (older proxies sometimes drop the
      // `event:` line, in which case the browser delivers as 'message').
      source.onmessage = handleEvent;
      // Server emits `event: <type>` for each payload; subscribe to the
      // ones that drive UI state explicitly so behaviour is testable.
      const eventTypes: JobEventType[] = [
        "job_queued",
        "stage_started",
        "stage_progress",
        "stage_completed",
        "stage_failed",
        "job_completed",
        "job_failed",
        "stream_error",
      ];
      for (const type of eventTypes) {
        source.addEventListener(type, handleEvent as EventListener);
      }

      source.onerror = () => {
        if (cancelled || terminalReachedRef.current) return;
        // EventSource auto-retries with its own backoff, but it does not
        // expose a "tried N times" hook. We close + reopen so we control
        // the retry counter and can promote to polling after enough
        // failures.
        source?.close();
        source = null;
        retryAttempt += 1;
        setIsDegraded(true);

        if (retryAttempt >= MAX_SSE_RETRIES_BEFORE_FALLBACK) {
          useSseRef.current = false;
          setTransport("polling");
          return;
        }

        const delay = SSE_RETRY_BACKOFF_MS[
          Math.min(retryAttempt - 1, SSE_RETRY_BACKOFF_MS.length - 1)
        ];
        reconnectTimer = window.setTimeout(connect, delay);
      };
    };

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      source?.close();
      source = null;
    };
  }, [jobId, session, queryClient]);

  return { job, lastEvent, transport, isDegraded };
}
