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
      className="pointer-events-none fixed bottom-4 right-4 z-50 flex max-w-sm flex-col gap-2"
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

  const { Icon, accent } = variantStyle(toast.variant);
  return (
    <div
      role="status"
      className={`pointer-events-auto flex items-start gap-3 rounded-lg border bg-white/95 px-3 py-2.5 shadow-lg backdrop-blur ${accent}`}
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold leading-tight">{toast.title}</div>
        {toast.description ? (
          <div className="mt-1 text-xs leading-snug text-[var(--muted)] break-words">
            {toast.description}
          </div>
        ) : null}
      </div>
      <button
        aria-label="Dismiss"
        className="rounded p-1 text-[var(--muted)] transition hover:bg-black/5"
        onClick={() => onDismiss(toast.id)}
        type="button"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

function variantStyle(variant: ToastVariant): { Icon: typeof Info; accent: string } {
  switch (variant) {
    case "success":
      return { Icon: CheckCircle2, accent: "border-[var(--accent)] text-[var(--accent)]" };
    case "warning":
      return { Icon: AlertTriangle, accent: "border-[var(--warm)] text-[var(--warm)]" };
    case "error":
      return { Icon: AlertTriangle, accent: "border-[var(--danger)] text-[var(--danger)]" };
    case "info":
    default:
      return { Icon: Info, accent: "border-[var(--line)] text-[var(--accent)]" };
  }
}
