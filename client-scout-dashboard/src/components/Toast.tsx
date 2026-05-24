import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Info, X } from "lucide-react";

/**
 * Lightweight toast system for surfacing async failures (SSE drops, ARQ
 * worker errors, mutation rejections) without pulling in a heavy library.
 *
 * Usage:
 *   const toast = useToast();
 *   toast.error("Job failed", "DNS resolution timed out for 12 leads");
 */

export type ToastVariant = "info" | "success" | "warning" | "error";

interface ToastRecord {
  id: number;
  variant: ToastVariant;
  title: string;
  description?: string;
  durationMs: number;
}

interface ToastApi {
  show: (variant: ToastVariant, title: string, description?: string, durationMs?: number) => void;
  info: (title: string, description?: string, durationMs?: number) => void;
  success: (title: string, description?: string, durationMs?: number) => void;
  warning: (title: string, description?: string, durationMs?: number) => void;
  error: (title: string, description?: string, durationMs?: number) => void;
  dismiss: (id: number) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

const DEFAULT_DURATION_MS: Record<ToastVariant, number> = {
  info: 4_000,
  success: 4_000,
  warning: 6_000,
  // Errors stay long enough to read a stack-ish description.
  error: 8_000,
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastRecord[]>([]);
  const idRef = useRef(0);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const show = useCallback(
    (variant: ToastVariant, title: string, description?: string, durationMs?: number) => {
      const id = ++idRef.current;
      const ms = durationMs ?? DEFAULT_DURATION_MS[variant];
      setToasts((prev) => [...prev, { id, variant, title, description, durationMs: ms }]);
    },
    [],
  );

  const api = useMemo<ToastApi>(
    () => ({
      show,
      info: (t, d, ms) => show("info", t, d, ms),
      success: (t, d, ms) => show("success", t, d, ms),
      warning: (t, d, ms) => show("warning", t, d, ms),
      error: (t, d, ms) => show("error", t, d, ms),
      dismiss,
    }),
    [show, dismiss],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  const ctx = useContext(ToastContext);
  if (ctx === null) {
    throw new Error("useToast must be used inside a <ToastProvider>");
  }
  return ctx;
}

// ---------------------------------------------------------------------------
// Internal rendering
// ---------------------------------------------------------------------------

function ToastViewport({
  toasts,
  onDismiss,
}: {
  toasts: ToastRecord[];
  onDismiss: (id: number) => void;
}) {
  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed bottom-5 right-5 z-50 flex max-w-sm flex-col gap-2.5"
    >
      {toasts.map((toast) => (
        <ToastCard key={toast.id} toast={toast} onDismiss={onDismiss} />
      ))}
    </div>
  );
}

function ToastCard({ toast, onDismiss }: { toast: ToastRecord; onDismiss: (id: number) => void }) {
  // Auto-dismiss after the configured duration. We track the timeout in a
  // ref so unmount cancels it cleanly (e.g. user closed the tab).
  const dismissRef = useRef(onDismiss);
  useEffect(() => {
    dismissRef.current = onDismiss;
  }, [onDismiss]);

  useEffect(() => {
    const handle = window.setTimeout(() => dismissRef.current(toast.id), toast.durationMs);
    return () => window.clearTimeout(handle);
  }, [toast.id, toast.durationMs]);

  const { Icon, accentBar, iconBg, iconColor, titleColor } = variantStyle(toast.variant);
  return (
    <div
      role="status"
      // Glass card with a vertical accent strip in the variant color, an
      // icon chip, and a dark-on-light text stack. The whole element
      // animates in via the slide-up keyframe so multi-toast bursts
      // stagger nicely instead of popping all at once.
      className="pointer-events-auto relative flex items-start gap-3 overflow-hidden rounded-[12px] border border-[var(--line-strong)] bg-white/85 px-3.5 py-3 pl-4 shadow-[var(--shadow-lg)] backdrop-blur-md animate-slide-up"
    >
      {/* Variant accent strip - functions as the colour key without
          drowning the rest of the card in tinted background. */}
      <span aria-hidden className={`absolute inset-y-0 left-0 w-[3px] ${accentBar}`} />

      <span
        className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-[8px] ${iconBg} ${iconColor}`}
      >
        <Icon className="h-3.5 w-3.5" />
      </span>

      <div className="min-w-0 flex-1">
        <div className={`text-[13.5px] font-semibold leading-tight ${titleColor}`}>
          {toast.title}
        </div>
        {toast.description ? (
          <div className="mt-1 break-words text-[12px] leading-snug text-zinc-500">
            {toast.description}
          </div>
        ) : null}
      </div>

      <button
        aria-label="Dismiss"
        className="rounded-md p-1 text-zinc-400 transition-colors hover:bg-zinc-100 hover:text-zinc-700"
        onClick={() => onDismiss(toast.id)}
        type="button"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

function variantStyle(variant: ToastVariant): {
  Icon: typeof Info;
  accentBar: string;
  iconBg: string;
  iconColor: string;
  titleColor: string;
} {
  switch (variant) {
    case "success":
      return {
        Icon: CheckCircle2,
        accentBar: "bg-emerald-500",
        iconBg: "bg-emerald-50",
        iconColor: "text-emerald-600",
        titleColor: "text-zinc-900",
      };
    case "warning":
      return {
        Icon: AlertTriangle,
        accentBar: "bg-amber-500",
        iconBg: "bg-amber-50",
        iconColor: "text-amber-600",
        titleColor: "text-zinc-900",
      };
    case "error":
      return {
        Icon: AlertTriangle,
        accentBar: "bg-rose-500",
        iconBg: "bg-rose-50",
        iconColor: "text-rose-600",
        titleColor: "text-zinc-900",
      };
    case "info":
    default:
      return {
        Icon: Info,
        accentBar: "bg-zinc-300",
        iconBg: "bg-zinc-100",
        iconColor: "text-zinc-600",
        titleColor: "text-zinc-900",
      };
  }
}
