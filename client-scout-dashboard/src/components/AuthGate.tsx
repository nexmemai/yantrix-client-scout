import { LockKeyhole, Server } from "lucide-react";
import { FormEvent, ReactNode, useEffect, useState } from "react";
import { ApiSession } from "../api/client";

const STORAGE_KEY = "yantrix-client-scout-dashboard-session";

function defaultApiBaseUrl() {
  return import.meta.env.VITE_API_BASE_URL || window.location.origin;
}

function isLocalhostApiFromRemoteBrowser(baseUrl: string) {
  return (
    window.location.hostname !== "localhost" &&
    window.location.hostname !== "127.0.0.1" &&
    /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?/i.test(baseUrl)
  );
}

interface AuthGateProps {
  children: (session: ApiSession, clearSession: () => void) => ReactNode;
}

export function AuthGate({ children }: AuthGateProps) {
  const [session, setSession] = useState<ApiSession | null>(null);
  const [baseUrl, setBaseUrl] = useState(defaultApiBaseUrl());
  const [token, setToken] = useState("");

  useEffect(() => {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return;
    try {
      const saved = JSON.parse(raw) as ApiSession;
      if (saved.baseUrl && saved.token) {
        if (isLocalhostApiFromRemoteBrowser(saved.baseUrl)) {
          const migrated = { ...saved, baseUrl: defaultApiBaseUrl() };
          window.localStorage.setItem(STORAGE_KEY, JSON.stringify(migrated));
          setSession(migrated);
        } else {
          setSession(saved);
        }
      }
    } catch {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  }, []);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const nextSession = { baseUrl, token };
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(nextSession));
    setSession(nextSession);
  };

  const clearSession = () => {
    window.localStorage.removeItem(STORAGE_KEY);
    setSession(null);
    setToken("");
  };

  if (session) {
    return <>{children(session, clearSession)}</>;
  }

  return (
    <main className="min-h-screen px-5 py-8 sm:px-8">
      <div className="mx-auto grid max-w-5xl gap-8 lg:grid-cols-[1.1fr_0.9fr]">
        <section className="surface section-band flex min-h-[320px] flex-col justify-between">
          <div>
            <div className="mb-6 inline-flex items-center gap-3 rounded-full border border-[var(--line)] bg-white/80 px-4 py-2 text-sm font-semibold text-[var(--muted)]">
              <LockKeyhole className="h-4 w-4 text-[var(--accent)]" />
              Internal console
            </div>
            <h1 className="max-w-xl text-4xl font-extrabold tracking-tight text-[var(--text)]">
              Yantrix Client Scout
            </h1>
            <p className="mt-4 max-w-xl text-sm leading-6 text-[var(--muted)]">
              Lead discovery, website audits, scoring, and pitch review in one internal workspace.
            </p>
          </div>
          <div className="mt-8 grid gap-3 sm:grid-cols-3">
            {[
              ["Lead queue", "Triage by city, niche, score, and freshness."],
              ["Audit readout", "Scan conversion gaps without opening raw JSON."],
              ["Config edits", "Tune weight presets and prompt templates in place."],
            ].map(([title, copy]) => (
              <div key={title} className="surface-strong p-4">
                <div className="text-sm font700 font-semibold">{title}</div>
                <div className="mt-2 text-xs leading-5 text-[var(--muted)]">{copy}</div>
              </div>
            ))}
          </div>
        </section>

        <section className="surface-strong p-6 sm:p-7">
          <div className="mb-5 flex items-center gap-3 text-sm font-semibold text-[var(--muted)]">
            <Server className="h-4 w-4 text-[var(--warm)]" />
            API session
          </div>
          <form className="space-y-4" onSubmit={submit}>
            <label className="block">
              <div className="mb-2 text-sm font-semibold">API base URL</div>
              <input
                className="field"
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                placeholder={defaultApiBaseUrl()}
              />
            </label>
            <label className="block">
              <div className="mb-2 text-sm font-semibold">Shared token</div>
              <input
                className="field"
                value={token}
                onChange={(event) => setToken(event.target.value)}
                placeholder="internal token"
                type="password"
              />
            </label>
            <button className="button button-primary h-11 w-full px-4 text-sm font-semibold" type="submit" disabled={!token.trim()}>
              Open Dashboard
            </button>
          </form>
        </section>
      </div>
    </main>
  );
}
