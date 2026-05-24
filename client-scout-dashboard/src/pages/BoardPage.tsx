import { DragEvent, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Flame,
  History,
  LayoutDashboard,
  MessageCircle,
  Sparkles,
  Trophy,
} from "lucide-react";
import { Link } from "react-router-dom";
import { ApiSession, apiClient } from "../api/client";
import { BoardCard, PipelineBoard } from "../lib/types";
import { PainGrid } from "../components/PainGrid";
import { useToast } from "../components/Toast";
import { formatDate, scoreBucket, scoreBucketTone } from "../lib/utils";

/**
 * BoardPage - drag-and-drop pipeline board (UI-overhaul rev).
 *
 * Functional contract is identical to the previous version: 4 columns,
 * `getBoard()` for data, optimistic-ish drop -> updateLeadSales mutation,
 * 30 s revalidation, board endpoint ships pain_flags so PainGrid renders
 * without a per-card detail fetch.
 *
 * Visual changes:
 *   * Page header with breadcrumbs handled by AppShell, plus a metric
 *     strip showing column totals as proper Linear-style metric cards.
 *   * Columns sit on a quiet zinc background, get an accent rail at the
 *     top in the column's signal color, and use the `kanban-card` CSS
 *     class so hover/drag effects match the global design language.
 *   * Empty columns get a small icon + helper text instead of a stark
 *     dashed grey box, matching the redesigned table empty state.
 *
 * Why we don't use a virtualised list inside the column scroller:
 *   * The board endpoint caps each column at `column_limit` (default 50),
 *     so the worst case is ~200 cards in the DOM. That's well inside what
 *     the browser can paint at 60fps without windowing.
 */

type ColumnKey = "hot" | "follow_ups" | "stale" | "won";

interface ColumnDef {
  key: ColumnKey;
  title: string;
  description: string;
  icon: typeof Flame;
  // Tailwind classes for the column accent rail + icon chip. We don't
  // re-use scoreBucketTone here because the columns express urgency, not
  // score, so a separate vocabulary keeps the visuals honest.
  accentRail: string;
  iconChip: string;
  // Status the drop target sets. Some columns are read-only (e.g. Hot is
  // derived from score buckets, so we treat dropping there as "mark new").
  dropStatus: string;
}

const COLUMNS: ColumnDef[] = [
  {
    key: "hot",
    title: "Hot",
    description: "Top agency-fit leads waiting for first contact",
    icon: Flame,
    accentRail: "from-rose-400 to-rose-500",
    iconChip: "bg-rose-50 text-rose-600",
    dropStatus: "new",
  },
  {
    key: "follow_ups",
    title: "Awaiting follow-up",
    description: "Reply or follow-up due today",
    icon: MessageCircle,
    accentRail: "from-amber-400 to-amber-500",
    iconChip: "bg-amber-50 text-amber-600",
    dropStatus: "contacted",
  },
  {
    key: "stale",
    title: "Going stale",
    description: "Contacted, no reply in 7+ days",
    icon: History,
    accentRail: "from-zinc-300 to-zinc-400",
    iconChip: "bg-zinc-100 text-zinc-500",
    dropStatus: "contacted",
  },
  {
    key: "won",
    title: "Recently won",
    description: "Closed-won in the last 14 days",
    icon: Trophy,
    accentRail: "from-emerald-400 to-emerald-500",
    iconChip: "bg-emerald-50 text-emerald-600",
    dropStatus: "won",
  },
];

interface BoardPageProps {
  session: ApiSession;
}

export function BoardPage({ session }: BoardPageProps) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [hoverColumn, setHoverColumn] = useState<ColumnKey | null>(null);

  const boardQuery = useQuery<PipelineBoard, Error>({
    queryKey: ["leads", "board"],
    queryFn: () => apiClient.getBoard(session),
    refetchInterval: 30_000,
  });

  // Surface errors through the global toast layer to match the rest of the app.
  useEffect(() => {
    if (boardQuery.error) {
      toast.error("Failed to load board", boardQuery.error.message);
    }
  }, [boardQuery.error, toast]);

  const moveLead = useMutation({
    mutationFn: ({ leadId, status }: { leadId: string; status: string }) =>
      apiClient.updateLeadSales(session, leadId, { lead_status: status }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["leads", "board"] });
      queryClient.invalidateQueries({ queryKey: ["leads"] });
      toast.success("Lead moved", "Board updated.");
    },
    onError: (error: unknown) => {
      // Refetch to snap the card back if it was optimistically moved.
      queryClient.invalidateQueries({ queryKey: ["leads", "board"] });
      toast.error(
        "Could not move lead",
        error instanceof Error ? error.message : "Unknown error",
      );
    },
  });

  const totals = useMemo(() => {
    const data = boardQuery.data;
    return {
      hot: data?.hot.length ?? 0,
      follow_ups: data?.follow_ups.length ?? 0,
      stale: data?.stale.length ?? 0,
      won: data?.won.length ?? 0,
    };
  }, [boardQuery.data]);

  return (
    <div className="grid gap-5">
      <PageHeader
        totals={totals}
        isFetching={boardQuery.isFetching && !boardQuery.isLoading}
      />

      <div className="grid gap-3 lg:grid-cols-2 xl:grid-cols-4">
        {COLUMNS.map((column) => (
          <BoardColumn
            key={column.key}
            column={column}
            cards={boardQuery.data?.[column.key] ?? []}
            isLoading={boardQuery.isLoading && !boardQuery.data}
            total={totals[column.key]}
            isOver={hoverColumn === column.key}
            draggingId={draggingId}
            onCardDragStart={(id) => setDraggingId(id)}
            onCardDragEnd={() => {
              setDraggingId(null);
              setHoverColumn(null);
            }}
            onColumnDragOver={(event) => {
              event.preventDefault();
              setHoverColumn(column.key);
            }}
            onColumnDragLeave={() => {
              if (hoverColumn === column.key) setHoverColumn(null);
            }}
            onColumnDrop={(event) => {
              event.preventDefault();
              const leadId = event.dataTransfer.getData("text/plain") || draggingId;
              if (!leadId) return;
              moveLead.mutate({ leadId, status: column.dropStatus });
            }}
          />
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page header - title, subtitle, metric strip
// ---------------------------------------------------------------------------

function PageHeader({
  totals,
  isFetching,
}: {
  totals: Record<ColumnKey, number>;
  isFetching: boolean;
}) {
  // Total deal-pipeline width in cards (not value) - quick health metric.
  const total = totals.hot + totals.follow_ups + totals.stale + totals.won;

  return (
    <section className="grid gap-4">
      {/* Title row */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-400">
            <LayoutDashboard className="h-3.5 w-3.5" />
            Pipeline
          </div>
          <h1 className="mt-1 text-[28px] font-bold tracking-tight text-zinc-900">
            Pipeline board
          </h1>
          <p className="mt-1 max-w-xl text-sm leading-relaxed text-zinc-500">
            Drag leads between columns to advance their status. Pain density
            and deal value sit on every card so you can triage at a glance.
          </p>
        </div>
        {isFetching ? (
          <span className="pill pill-zinc">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
            </span>
            Refreshing
          </span>
        ) : null}
      </div>

      {/* Metric strip. Each card mirrors the column accents so the eye can
          jump from a number to its column without re-reading a label. */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard
          label="Hot"
          value={totals.hot}
          icon={<Flame className="h-4 w-4" />}
          chipClass="bg-rose-50 text-rose-600"
        />
        <MetricCard
          label="Follow-ups due"
          value={totals.follow_ups}
          icon={<MessageCircle className="h-4 w-4" />}
          chipClass="bg-amber-50 text-amber-600"
        />
        <MetricCard
          label="Going stale"
          value={totals.stale}
          icon={<History className="h-4 w-4" />}
          chipClass="bg-zinc-100 text-zinc-500"
        />
        <MetricCard
          label="Won this fortnight"
          value={totals.won}
          icon={<Trophy className="h-4 w-4" />}
          chipClass="bg-emerald-50 text-emerald-600"
          trend={total > 0 ? `${Math.round((totals.won / total) * 100)}% of board` : undefined}
        />
      </div>
    </section>
  );
}

function MetricCard({
  label,
  value,
  icon,
  chipClass,
  trend,
}: {
  label: string;
  value: number;
  icon: React.ReactNode;
  chipClass: string;
  trend?: string;
}) {
  return (
    <div className="metric-card flex items-start justify-between gap-3">
      <div>
        <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-zinc-400">
          {label}
        </div>
        <div className="mt-1.5 text-[28px] font-bold leading-none tracking-tight tabular-nums text-zinc-900">
          {value}
        </div>
        {trend ? (
          <div className="mt-1.5 text-[11px] font-medium text-zinc-500">{trend}</div>
        ) : null}
      </div>
      <span
        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px] ${chipClass}`}
      >
        {icon}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Columns
// ---------------------------------------------------------------------------

interface BoardColumnProps {
  column: ColumnDef;
  cards: BoardCard[];
  isLoading: boolean;
  total: number;
  isOver: boolean;
  draggingId: string | null;
  onCardDragStart: (id: string) => void;
  onCardDragEnd: () => void;
  onColumnDragOver: (event: DragEvent<HTMLDivElement>) => void;
  onColumnDragLeave: () => void;
  onColumnDrop: (event: DragEvent<HTMLDivElement>) => void;
}

function BoardColumn({
  column,
  cards,
  isLoading,
  total,
  isOver,
  draggingId,
  onCardDragStart,
  onCardDragEnd,
  onColumnDragOver,
  onColumnDragLeave,
  onColumnDrop,
}: BoardColumnProps) {
  const Icon = column.icon;

  return (
    <div
      role="region"
      aria-label={column.title}
      data-over={isOver ? "true" : undefined}
      onDragOver={onColumnDragOver}
      onDragLeave={onColumnDragLeave}
      onDrop={onColumnDrop}
      // The kanban-column CSS hook owns the drag-over state so the visual
      // language stays consistent with the rest of the design system. The
      // local class layer below adds layout + the gradient accent rail.
      className={`kanban-column surface relative flex min-h-[480px] flex-col gap-3 overflow-hidden p-3 transition-all duration-200 ${
        isOver ? "ring-2 ring-emerald-300/70" : ""
      }`}
    >
      {/* Top accent rail. Subtle gradient that ties the column to its
          metric card without screaming. */}
      <div
        aria-hidden
        className={`absolute inset-x-0 top-0 h-[3px] bg-gradient-to-r ${column.accentRail}`}
      />

      <header className="flex items-start justify-between gap-2 pt-1">
        <div className="flex min-w-0 items-start gap-2.5">
          <span
            className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-[8px] ${column.iconChip}`}
          >
            <Icon className="h-3.5 w-3.5" />
          </span>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <div className="text-sm font-semibold tracking-tight text-zinc-900">
                {column.title}
              </div>
              <span className="pill pill-zinc tabular-nums">{total}</span>
            </div>
            <div className="mt-0.5 truncate text-[11px] leading-relaxed text-zinc-500">
              {column.description}
            </div>
          </div>
        </div>
      </header>

      <div className="grid gap-2 overflow-y-auto pr-1">
        {isLoading ? (
          // Three skeleton placeholders so the column doesn't suddenly
          // grow in height when cards arrive.
          <>
            <div className="skeleton h-20 w-full" />
            <div className="skeleton h-20 w-full" />
            <div className="skeleton h-20 w-full" />
          </>
        ) : cards.length === 0 ? (
          <EmptyColumnState columnTitle={column.title} />
        ) : (
          cards.map((card) => (
            <Card
              key={card.id}
              card={card}
              isDragging={draggingId === card.id}
              onDragStart={onCardDragStart}
              onDragEnd={onCardDragEnd}
            />
          ))
        )}
      </div>
    </div>
  );
}

/**
 * Empty column state.
 *
 * The previous string ("Empty column. Drop a lead here to advance it.")
 * doubled up information already implied by the column itself. The
 * redesign keeps it terse and adds a soft sparkle icon so empty doesn't
 * read as broken.
 */
function EmptyColumnState({ columnTitle }: { columnTitle: string }) {
  return (
    <div className="my-auto flex flex-col items-center gap-2 rounded-[10px] border border-dashed border-zinc-200 bg-white/50 px-4 py-6 text-center">
      <span className="flex h-9 w-9 items-center justify-center rounded-full bg-zinc-100 text-zinc-400">
        <Sparkles className="h-4 w-4" />
      </span>
      <div className="text-[12px] font-semibold text-zinc-700">No leads here</div>
      <div className="text-[11px] leading-relaxed text-zinc-400">
        Drop a card to move it into <span className="text-zinc-600">{columnTitle}</span>.
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Cards
// ---------------------------------------------------------------------------

interface CardProps {
  card: BoardCard;
  isDragging: boolean;
  onDragStart: (id: string) => void;
  onDragEnd: () => void;
}

function Card({ card, isDragging, onDragStart, onDragEnd }: CardProps) {
  const bucket = scoreBucket(card.overall_score);
  return (
    <Link
      to={`/leads/${card.id}`}
      draggable
      data-dragging={isDragging ? "true" : undefined}
      onDragStart={(event) => {
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", card.id);
        onDragStart(card.id);
      }}
      onDragEnd={onDragEnd}
      // kanban-card owns the depth/transform; this layer adds layout + a
      // subtle border stripe on the leading edge so each card has a clear
      // start point in the column.
      className="kanban-card group relative block cursor-grab overflow-hidden p-3 text-sm active:cursor-grabbing"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-[13.5px] font-semibold text-zinc-900">
            {card.name}
          </div>
          <div className="mt-0.5 truncate text-[11.5px] text-zinc-500">
            {card.category ?? "Unknown"} · {card.city ?? "—"}
          </div>
        </div>
        <span className={`pill ${scoreBucketTone(bucket)} shrink-0`}>{bucket}</span>
      </div>

      <div className="mt-3 flex items-center justify-between gap-2">
        <PainGrid flags={card.pain_flags ?? undefined} count={card.pain_count ?? undefined} />
        {card.estimated_deal_value ? (
          <div className="rounded-md bg-emerald-50 px-1.5 py-0.5 text-[11px] font-bold tabular-nums text-emerald-700">
            ₹{card.estimated_deal_value.toLocaleString("en-IN")}
          </div>
        ) : null}
      </div>

      <div className="mt-2 flex items-center justify-between text-[10.5px] text-zinc-400">
        <span>{formatDate(card.created_at)}</span>
        <span className="rounded border border-zinc-200 bg-white px-1.5 py-[1px] font-semibold uppercase tracking-[0.04em] text-zinc-500">
          {card.lead_status}
        </span>
      </div>
    </Link>
  );
}
