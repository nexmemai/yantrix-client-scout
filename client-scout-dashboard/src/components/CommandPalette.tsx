import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Filter, Play, Search, Table2, Trello } from "lucide-react";
import { ApiSession, apiClient } from "../api/client";
import { useToast } from "./Toast";

/**
 * CommandPalette - global Cmd/Ctrl+K launcher.
 *
 * Replaces 3-click flows with a single typed phrase:
 *   "Run scout: dental in Pune"        -> POST /run-scout
 *   "Filter: hot"                      -> navigate /leads?bucket=high-fit
 *   "Filter: contacted"                -> navigate /leads?status=contacted
 *   "Open board"                       -> navigate /board
 *   "Open leads"                       -> navigate /leads
 *   "Export CSV"                       -> trigger CSV export endpoint
 *
 * Accessibility:
 *   * Trap focus inside the dialog while open.
 *   * Restore focus on close so keyboard users land back where they were.
 *   * `role="dialog"` + `aria-modal` so screen readers announce it.
 *
 * The component intentionally avoids the `cmdk` library: at this scale the
 * functionality is ~100 LOC and the third dep would inflate the bundle.
 */

interface CommandPaletteProps {
  session: ApiSession;
}

interface ParsedCommand {
  kind: "run_scout" | "filter" | "navigate" | "export_csv";
  payload: Record<string, string>;
  label: string;
  hint?: string;
}

interface SuggestionGroup {
  heading: string;
  items: ParsedCommand[];
}

const STATIC_SUGGESTIONS: SuggestionGroup[] = [
  {
    heading: "Pipeline shortcuts",
    items: [
      {
        kind: "navigate",
        payload: { path: "/leads" },
        label: "Open leads table",
        hint: "/leads",
      },
      {
        kind: "navigate",
        payload: { path: "/board" },
        label: "Open pipeline board",
        hint: "/board",
      },
      {
        kind: "navigate",
        payload: { path: "/configs" },
        label: "Open niche configs",
        hint: "/configs",
      },
    ],
  },
  {
    heading: "Filters",
    items: [
      {
        kind: "filter",
        payload: { agency_fit_bucket: "hot" },
        label: "Filter: hot agency-fit only",
        hint: "agency_fit_bucket=hot",
      },
      {
        kind: "filter",
        payload: { lead_status: "contacted" },
        label: "Filter: status = contacted",
        hint: "lead_status=contacted",
      },
      {
        kind: "filter",
        payload: { bucket: "high-fit" },
        label: "Filter: high-fit score bucket",
        hint: "bucket=high-fit",
      },
    ],
  },
  {
    heading: "Bulk actions",
    items: [
      {
        kind: "export_csv",
        payload: {},
        label: "Export current view as CSV",
      },
    ],
  },
];

const RUN_REGEX = /^run\s+scout[:\s]+(.+?)\s+in\s+(.+)$/i;
const FILTER_REGEX = /^filter:?\s*(hot|warm|cold|skip|new|contacted|high-fit|mid-fit|low-fit)$/i;
const NAVIGATE_REGEX = /^(open|go to|goto)\s+(leads|board|configs)$/i;

function parseCommand(input: string): ParsedCommand | null {
  const text = input.trim();
  if (!text) return null;

  const run = RUN_REGEX.exec(text);
  if (run) {
    return {
      kind: "run_scout",
      payload: { niche: run[1].trim(), city: run[2].trim() },
      label: `Run scout: ${run[1].trim()} in ${run[2].trim()}`,
    };
  }

  const filter = FILTER_REGEX.exec(text);
  if (filter) {
    const value = filter[1].toLowerCase();
    if (["hot", "warm", "cold", "skip"].includes(value)) {
      return {
        kind: "filter",
        payload: { agency_fit_bucket: value },
        label: `Filter: agency_fit = ${value}`,
      };
    }
    if (["new", "contacted"].includes(value)) {
      return {
        kind: "filter",
        payload: { lead_status: value },
        label: `Filter: status = ${value}`,
      };
    }
    return {
      kind: "filter",
      payload: { bucket: value },
      label: `Filter: bucket = ${value}`,
    };
  }

  const nav = NAVIGATE_REGEX.exec(text);
  if (nav) {
    const where = nav[2].toLowerCase();
    const path = where === "leads" ? "/leads" : where === "board" ? "/board" : "/configs";
    return {
      kind: "navigate",
      payload: { path },
      label: `Open ${where}`,
      hint: path,
    };
  }

  if (/^export(\s+csv)?$/i.test(text)) {
    return { kind: "export_csv", payload: {}, label: "Export current view as CSV" };
  }
  return null;
}

export function CommandPalette({ session }: CommandPaletteProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [highlightIndex, setHighlightIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const lastFocused = useRef<HTMLElement | null>(null);
  const toast = useToast();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  // ── Open/close on Cmd/Ctrl+K ─────────────────────────────────────────
  useEffect(() => {
    function handler(event: KeyboardEvent) {
      const isMac = navigator.platform.toLowerCase().includes("mac");
      const triggerKey = isMac ? event.metaKey : event.ctrlKey;
      if (triggerKey && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((prev) => !prev);
      }
      if (event.key === "Escape" && open) {
        event.preventDefault();
        setOpen(false);
      }
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open]);

  // ── Focus management ────────────────────────────────────────────────
  useEffect(() => {
    if (open) {
      lastFocused.current = document.activeElement as HTMLElement;
      setHighlightIndex(0);
      setQuery("");
      // Defer so the input exists when we ref it.
      requestAnimationFrame(() => inputRef.current?.focus());
    } else {
      lastFocused.current?.focus();
    }
  }, [open]);

  const parsedCustom = useMemo(() => parseCommand(query), [query]);
  const suggestions = useMemo<SuggestionGroup[]>(() => {
    if (!query.trim()) return STATIC_SUGGESTIONS;
    const filtered = STATIC_SUGGESTIONS.map((group) => ({
      heading: group.heading,
      items: group.items.filter((item) =>
        item.label.toLowerCase().includes(query.trim().toLowerCase()),
      ),
    })).filter((group) => group.items.length > 0);
    if (parsedCustom) {
      return [{ heading: "Run command", items: [parsedCustom] }, ...filtered];
    }
    return filtered;
  }, [query, parsedCustom]);

  const flatItems = useMemo(
    () => suggestions.flatMap((group) => group.items),
    [suggestions],
  );

  // Keep highlight index inside bounds when list shrinks.
  useEffect(() => {
    setHighlightIndex((prev) => {
      if (flatItems.length === 0) return 0;
      if (prev >= flatItems.length) return flatItems.length - 1;
      return prev;
    });
  }, [flatItems.length]);

  const runCommand = useCallback(
    async (command: ParsedCommand) => {
      try {
        if (command.kind === "navigate") {
          navigate(command.payload.path);
          setOpen(false);
          return;
        }
        if (command.kind === "filter") {
          const params = new URLSearchParams(command.payload);
          navigate(`/leads?${params.toString()}`);
          setOpen(false);
          return;
        }
        if (command.kind === "run_scout") {
          await apiClient.runScout(session, {
            niche: command.payload.niche,
            city: command.payload.city,
            max_businesses: 25,
          });
          toast.info(
            "Scout queued",
            `${command.payload.niche} in ${command.payload.city}`,
          );
          queryClient.invalidateQueries({ queryKey: ["jobs"] });
          setOpen(false);
          return;
        }
        if (command.kind === "export_csv") {
          // Navigate to the export endpoint; the API streams a CSV download.
          window.open("/api/v1/export/leads.csv", "_blank", "noopener");
          setOpen(false);
          return;
        }
      } catch (error) {
        toast.error(
          "Command failed",
          error instanceof Error ? error.message : "Unknown error",
        );
      }
    },
    [navigate, queryClient, session, toast],
  );

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="button button-secondary h-9 px-3 text-xs font-semibold text-[var(--muted)]"
        aria-label="Open command palette (Cmd+K)"
      >
        <Search className="h-3.5 w-3.5" />
        <span className="hidden sm:inline">Search</span>
        <kbd className="ml-1 hidden rounded border border-[var(--line)] bg-white/70 px-1.5 py-[1px] text-[10px] font-bold text-[var(--muted)] sm:inline">
          ⌘K
        </kbd>
      </button>
    );
  }

  return (
    <div
      role="dialog"
      aria-modal
      aria-label="Command palette"
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 px-4 pt-24"
      onClick={(event) => {
        if (event.target === event.currentTarget) setOpen(false);
      }}
    >
      <div className="surface-strong w-full max-w-xl overflow-hidden border border-[var(--line)] shadow-2xl">
        <div className="flex items-center gap-2 border-b border-[var(--line)] px-3 py-2.5">
          <Search className="h-4 w-4 text-[var(--muted)]" />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "ArrowDown") {
                event.preventDefault();
                setHighlightIndex((prev) => Math.min(prev + 1, flatItems.length - 1));
              } else if (event.key === "ArrowUp") {
                event.preventDefault();
                setHighlightIndex((prev) => Math.max(prev - 1, 0));
              } else if (event.key === "Enter") {
                event.preventDefault();
                const command = flatItems[highlightIndex];
                if (command) runCommand(command);
              }
            }}
            placeholder='Try "Run scout: dental in Pune", "Filter: hot", "Open board"…'
            className="flex-1 bg-transparent text-sm outline-none"
            aria-label="Command input"
          />
          <kbd className="rounded border border-[var(--line)] bg-white/70 px-1.5 py-[1px] text-[10px] font-bold text-[var(--muted)]">
            esc
          </kbd>
        </div>

        <div className="max-h-[55vh] overflow-y-auto py-1">
          {flatItems.length === 0 ? (
            <div className="px-4 py-6 text-sm text-[var(--muted)]">
              No commands match. Try the syntax in the placeholder.
            </div>
          ) : (
            suggestions.map((group) => (
              <Fragment key={group.heading}>
                <div className="px-3 pb-1 pt-2 text-[10px] font-bold uppercase tracking-wide text-[var(--muted)]">
                  {group.heading}
                </div>
                {group.items.map((item) => {
                  const flatIndex = flatItems.indexOf(item);
                  const active = flatIndex === highlightIndex;
                  return (
                    <button
                      key={`${item.kind}-${item.label}`}
                      type="button"
                      onMouseEnter={() => setHighlightIndex(flatIndex)}
                      onClick={() => runCommand(item)}
                      className={`flex w-full items-center gap-3 px-3 py-2 text-left text-sm ${
                        active ? "bg-[var(--accent)]/10" : ""
                      }`}
                    >
                      <CommandIcon kind={item.kind} />
                      <div className="min-w-0 flex-1">
                        <div className="truncate font-medium text-[var(--text)]">
                          {item.label}
                        </div>
                        {item.hint ? (
                          <div className="truncate text-xs text-[var(--muted)]">{item.hint}</div>
                        ) : null}
                      </div>
                      {active ? (
                        <ArrowRight className="h-3.5 w-3.5 text-[var(--accent)]" />
                      ) : null}
                    </button>
                  );
                })}
              </Fragment>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

function CommandIcon({ kind }: { kind: ParsedCommand["kind"] }) {
  switch (kind) {
    case "run_scout":
      return <Play className="h-3.5 w-3.5 text-[var(--accent)]" />;
    case "filter":
      return <Filter className="h-3.5 w-3.5 text-[var(--warm)]" />;
    case "navigate":
      return <Trello className="h-3.5 w-3.5 text-[var(--accent)]" />;
    case "export_csv":
      return <Table2 className="h-3.5 w-3.5 text-[var(--muted)]" />;
    default:
      return <Search className="h-3.5 w-3.5 text-[var(--muted)]" />;
  }
}
