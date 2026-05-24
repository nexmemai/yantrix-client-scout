import { DragEvent, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Flame, History, MessageCircle, Trophy } from "lucide-react";
import { Link } from "react-router-dom";
import { ApiSession, apiClient } from "../api/client";
import { BoardCard, PipelineBoard } from "../lib/types";
import { PainGrid } from "../components/PainGrid";
import { useToast } from "../components/Toast";
import { formatDate, scoreBucket, scoreBucketTone } from "../lib/utils";

/**
 * BoardPage - drag-and-drop pipeline board.
 *
 * Four columns map to lead urgency:
 *   * Hot              -> agency_fit_bucket=hot AND lead_status=new
 *   * Awaiting follow-up -> follow_up_at <= now AND status in {contacted,replied,meeting_set}
 *   * Stale            -> contacted but no recent touch (server filters >7 days)
 *   * Won              -> status=won updated within 14 days
 *
 * Drag semantics (intentionally minimal, no third-party DnD library):
 *   * Each card is `draggable`. Dropping on a column fires an optimistic
 *     `updateLeadSales` PATCH and TanStack Query revalidates the board.
 *   * On error we snap the card back via `invalidateQueries` so the wire
 *     state always wins — no local rollback book-keeping.
 *
 * Why we render `BoardCard.pain_flags` directly: the backend ships the dict
 * on the board endpoint specifically to avoid a per-card detail fetch, so
 * the density grid shows up the moment the board renders.
 */

type ColumnKey = "hot" | "follow_ups" | "stale" | "won";

interface ColumnDef {
  key: ColumnKey;
  title: string;
  description: string;
  icon: typeof Flame;
  accent: string;
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
    accent: "text-[var(--danger)]",
    dropStatus: "new",
  },
  {
    key: "follow_ups",
    title: "Awaiting follow-up",
    description: "Reply or follow-up due today",
    icon: MessageCircle,
    accent: "text-[var(--warm)]",
    dropStatus: "contacted",
  },
  {
    key: "stale",
    title: "Going stale",
    description: "Contacted, no reply in 7+ days",
    icon: History,
    accent: "text-[var(--muted)]",
    dropStatus: "contacted",
  },
  {
    key: "won",
    title: "Recently won",
    description: "Closed-won in the last 14 days",
    icon: Trophy,
    accent: "text-[var(--accent)]",
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
    <div className="grid gap-4">
      <section className="surface section-band">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="text-2xl font-extrabold">Pipeline board</div>
            <div className="mt-1 text-sm text-[var(--muted)]">
              Drag leads between columns to advance their status. Pain density at a glance.
            </div>
          </div>
          {boardQuery.isFetching ? (
            <div className="text-xs font-semibold text-[var(--muted)]">Refreshing…</div>
          ) : null}
        </div>
      </section>

      <div className="grid gap-3 xl:grid-cols-4 lg:grid-cols-2">
        {COLUMNS.map((column) => (
          <BoardColumn
            key={column.key}
            column={column}
            cards={boardQuery.data?.[column.key] ?? []}
            isLoading={boardQuery.isLoading && !boardQuery.data}
            total={totals[column.key]}
            isOver={hoverColumn === column.key}
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

interface BoardColumnProps {
  column: ColumnDef;
  cards: BoardCard[];
  isLoading: boolean;
  total: number;
  isOver: boolean;
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
      onDragOver={onColumnDragOver}
      onDragLeave={onColumnDragLeave}
      onDrop={onColumnDrop}
      className={`surface flex min-h-[420px] flex-col gap-3 p-3 transition ${
        isOver ? "ring-2 ring-[var(--accent)]/60" : ""
      }`}
    >
      <header className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Icon className={`h-4 w-4 ${column.accent}`} />
            <div className="text-sm font-bold">{column.title}</div>
            <span className="rounded-full bg-white/70 px-2 py-[1px] text-[11px] font-bold text-[var(--muted)]">
              {total}
            </span>
          </div>
          <div className="mt-1 text-xs text-[var(--muted)]">{column.description}</div>
        </div>
      </header>

      <div className="grid gap-2 overflow-y-auto pr-1">
        {isLoading ? (
          <div className="text-xs text-[var(--muted)]">Loading…</div>
        ) : cards.length === 0 ? (
          <div className="rounded-md border border-dashed border-[var(--line)] p-3 text-xs text-[var(--muted)]">
            Empty column. Drop a lead here to advance it.
          </div>
        ) : (
          cards.map((card) => (
            <Card key={card.id} card={card} onDragStart={onCardDragStart} onDragEnd={onCardDragEnd} />
          ))
        )}
      </div>
    </div>
  );
}

interface CardProps {
  card: BoardCard;
  onDragStart: (id: string) => void;
  onDragEnd: () => void;
}

function Card({ card, onDragStart, onDragEnd }: CardProps) {
  const bucket = scoreBucket(card.overall_score);
  return (
    <Link
      to={`/leads/${card.id}`}
      draggable
      onDragStart={(event) => {
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", card.id);
        onDragStart(card.id);
      }}
      onDragEnd={onDragEnd}
      className="surface-strong block cursor-grab rounded-md border border-[var(--line)] p-2.5 text-sm transition hover:border-[var(--accent)]/60 active:cursor-grabbing"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate font-semibold">{card.name}</div>
          <div className="truncate text-xs text-[var(--muted)]">
            {card.category ?? "Unknown"} · {card.city ?? "—"}
          </div>
        </div>
        <span className={`rounded-full px-2 py-[1px] text-[10px] font-bold ${scoreBucketTone(bucket)}`}>
          {bucket}
        </span>
      </div>

      <div className="mt-2 flex items-center justify-between gap-2">
        <PainGrid flags={card.pain_flags ?? undefined} count={card.pain_count ?? undefined} />
        {card.estimated_deal_value ? (
          <div className="text-[11px] font-semibold text-[var(--accent)]">
            ₹{card.estimated_deal_value.toLocaleString("en-IN")}
          </div>
        ) : null}
      </div>

      <div className="mt-1.5 flex items-center justify-between text-[11px] text-[var(--muted)]">
        <span>created {formatDate(card.created_at)}</span>
        <span className="rounded border border-[var(--line)] px-1.5 py-[1px] font-semibold uppercase">
          {card.lead_status}
        </span>
      </div>
    </Link>
  );
}
