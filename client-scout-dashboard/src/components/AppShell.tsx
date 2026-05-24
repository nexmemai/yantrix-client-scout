import { useEffect, useMemo, useState } from "react";
import { useLocation, NavLink } from "react-router-dom";
import {
  ChevronLeft,
  LayoutList,
  LogOut,
  PanelLeftClose,
  PanelLeftOpen,
  Settings2,
  Sparkles,
  Trello,
} from "lucide-react";
import { LayoutList, LogOut, Settings2, Trello } from "lucide-react";
import { NavLink } from "react-router-dom";

interface AppShellProps {
  onSignOut: () => void;
  children: React.ReactNode;
  /**
   * Optional slot for top-bar elements (command palette trigger, profile
   * menu, etc.). Rendered in the top-bar to the right of the breadcrumb.
   * menu, etc.). Rendered to the right of the page heading on wide layouts.
   */
  headerExtras?: React.ReactNode;
}

/**
 * AppShell - sidebar + top-bar layout for the redesigned dashboard.
 *
 * Layout in three regions:
 *
 *   ┌──────────┬─────────────────────────────────────────────┐
 *   │ sidebar  │ topbar  (breadcrumb · search · profile)     │
 *   │ (256px / │─────────────────────────────────────────────│
 *   │  72px)   │                                             │
 *   │          │             routed page content              │
 *   └──────────┴─────────────────────────────────────────────┘
 *
 * Sidebar
 *   * Two states: expanded (256px) and collapsed (72px icon rail).
 *   * Persisted to localStorage so refresh remembers the operator's
 *     preference. The `data-sidebar` attribute on the root drives the CSS
 *     grid track widths.
 *   * Auto-collapses on viewport <= 1024px so dense data tables get a
 *     bigger canvas on laptops without the operator having to fiddle.
 *
 * Topbar
 *   * Breadcrumbs derived from the current pathname so we don't have to
 *     plumb them from each page. `/leads/{uuid}` shows "Leads ›
 *     {Lead detail}", which is enough context for a 3-level app.
 *   * `headerExtras` slot is what the previous shell passed - we keep that
 *     contract so the CommandPalette button still lives there.
 *
 * What we deliberately did NOT do:
 *   * No animated layout swap (Framer Motion etc.). The collapse already
 *     uses a CSS grid transition; adding more libraries for one button
 *     wasn't worth the bundle weight.
 *   * No sidebar-overlay drawer for mobile. The app is internal-only and
 *     the existing media query falls back to a stacked single column,
 *     which has been adequate.
 */

const STORAGE_KEY = "scout.sidebar.collapsed";

const navItems: Array<{
  to: string;
  label: string;
  description: string;
  icon: typeof LayoutList;
}> = [
  {
    to: "/leads",
    label: "Leads",
    description: "Pipeline table",
    icon: LayoutList,
  },
  {
    to: "/board",
    label: "Pipeline",
    description: "Kanban board",
    icon: Trello,
  },
  {
    to: "/configs",
    label: "Niche configs",
    description: "Scoring rules",
    icon: Settings2,
  },
];

export function AppShell({ onSignOut, children, headerExtras }: AppShellProps) {
  const location = useLocation();

  // Sidebar collapse: persisted, auto-collapses below 1024px wide so the
  // virtualised table doesn't have to fight for horizontal space on a 13"
  // laptop. We initialise from localStorage synchronously to avoid the
  // expanded-then-collapse flash on first paint.
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "1") return true;
    if (stored === "0") return false;
    return window.matchMedia("(max-width: 1024px)").matches;
  });

  useEffect(() => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STORAGE_KEY, collapsed ? "1" : "0");
    }
  }, [collapsed]);

  const breadcrumbs = useMemo(() => buildBreadcrumbs(location.pathname), [location.pathname]);

  return (
    <div className="app-shell" data-sidebar={collapsed ? "collapsed" : "expanded"}>
      <Sidebar
        collapsed={collapsed}
        onToggleCollapsed={() => setCollapsed((prev) => !prev)}
        onSignOut={onSignOut}
      />

      <div className="flex min-w-0 flex-col">
        <Topbar breadcrumbs={breadcrumbs}>{headerExtras}</Topbar>

        <main
          // Slight soft inner padding so the page content doesn't crash into
          // the topbar borders. The min-h here keeps a short page (e.g.
          // empty state) from looking awkwardly anchored to the top.
          className="min-h-[calc(100vh-64px)] min-w-0 px-4 pb-8 pt-5 sm:px-6 lg:px-8"
        >
          <div className="mx-auto w-full max-w-[1400px] animate-fade-in">{children}</div>
        </main>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sidebar
// ---------------------------------------------------------------------------

function Sidebar({
  collapsed,
  onToggleCollapsed,
  onSignOut,
}: {
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onSignOut: () => void;
}) {
  return (
    <aside className="sidebar-surface flex flex-col justify-between py-4">
      <div>
        <BrandMark collapsed={collapsed} />

        <nav className="mt-2 grid gap-1 px-3">
          {navItems.map(({ to, label, description, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              title={collapsed ? label : undefined}
              className={({ isActive }) =>
                [
                  "group relative flex h-10 items-center gap-3 rounded-[10px] px-3 text-sm font-semibold",
                  "transition-all duration-200",
                  isActive
                    ? "bg-emerald-50 text-emerald-700 shadow-[inset_0_0_0_1px_rgba(16,185,129,0.18)]"
                    : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900",
                  collapsed ? "justify-center px-0" : "",
                ].join(" ")
              }
            >
              {({ isActive }) => (
                <>
                  {/* Tiny accent rail when active. Acts like a "you are here"
                      marker that survives the collapsed mode. */}
                  {isActive ? (
                    <span
                      aria-hidden
                      className={`absolute ${
                        collapsed ? "left-0 h-6 w-[3px]" : "left-[-12px] h-6 w-[3px]"
                      } rounded-r-full bg-emerald-500`}
                    />
                  ) : null}

                  <Icon
                    className={`h-4 w-4 shrink-0 transition-colors ${
                      isActive ? "text-emerald-600" : "text-zinc-500 group-hover:text-zinc-800"
                    }`}
                  />

                  {!collapsed && (
                    <span className="flex min-w-0 flex-col leading-tight">
                      <span className="truncate">{label}</span>
                      <span className="truncate text-[11px] font-medium text-zinc-400">
                        {description}
                      </span>
                    </span>
                  )}
                </>
              )}
            </NavLink>
          ))}
        </nav>
      </div>

      <div className="grid gap-2 px-3">
        {/* Collapse toggle. Title attribute mirrors the action so screen
            readers and hover-tooltip users get the same affordance. */}
        <button
          type="button"
          onClick={onToggleCollapsed}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className={`button button-ghost h-9 text-xs font-semibold ${
            collapsed ? "px-0" : "px-3"
          }`}
        >
          {collapsed ? (
            <PanelLeftOpen className="h-4 w-4" />
          ) : (
            <>
              <PanelLeftClose className="h-4 w-4" />
              <span>Collapse</span>
            </>
          )}
        </button>

        <button
          type="button"
          onClick={onSignOut}
          title="Sign out"
          aria-label="Sign out"
          className={`button button-secondary h-10 text-sm ${
            collapsed ? "px-0" : "justify-start px-3"
          }`}
        >
          <LogOut className="h-4 w-4" />
          {!collapsed && <span>Sign out</span>}
        </button>
      </div>
    </aside>
  );
}

function BrandMark({ collapsed }: { collapsed: boolean }) {
const navItems = [
  { to: "/leads", label: "Leads", icon: LayoutList },
  { to: "/board", label: "Pipeline board", icon: Trello },
  { to: "/configs", label: "Niche Configs", icon: Settings2 },
];

export function AppShell({ onSignOut, children, headerExtras }: AppShellProps) {
  return (
    <div
      className={`mb-4 border-b border-[var(--line)] px-4 pb-4 ${
        collapsed ? "px-3 text-center" : ""
      }`}
    >
      <div
        className={`flex items-center gap-2.5 ${
          collapsed ? "justify-center" : ""
        }`}
      >
        {/* Tiny brand mark - emerald gradient square with a sparkle, the
            kind of light "AI flag" that internal SaaS tools use. */}
        <span
          aria-hidden
          className="flex h-9 w-9 items-center justify-center rounded-[10px] bg-gradient-to-br from-emerald-400 to-emerald-600 text-white shadow-[0_4px_14px_-4px_rgba(16,185,129,0.55)]"
        >
          <Sparkles className="h-4 w-4" />
        </span>
        {!collapsed && (
          <div className="min-w-0">
            <div className="truncate text-[10px] font-bold uppercase tracking-[0.14em] text-zinc-400">
              Yantrix Labs
            </div>
            <div className="truncate text-[15px] font-bold tracking-tight text-zinc-900">
              Client Scout
            </div>
          </div>
        )}
      </div>
          <nav className="grid gap-2">
            {navItems.map(({ to, label, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                className={({ isActive }) =>
                  `button h-11 justify-start px-3 text-sm font-semibold ${
                    isActive
                      ? "bg-[var(--accent)] text-white"
                      : "button-secondary"
                  }`
                }
              >
                <Icon className="h-4 w-4" />
                {label}
              </NavLink>
            ))}
          </nav>
        </div>

        <button className="button button-secondary h-11 justify-start px-3 text-sm font-semibold" onClick={onSignOut}>
          <LogOut className="h-4 w-4" />
          Sign out
        </button>
      </aside>

      <main className="min-w-0 px-4 py-4 sm:px-6 sm:py-5">
        {headerExtras ? (
          // Top-bar slot. Sits above the routed page content so command
          // palette / profile controls live in a stable place across pages.
          <div className="mb-3 flex items-center justify-end gap-2">{headerExtras}</div>
        ) : null}
        {children}
      </main>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Topbar
// ---------------------------------------------------------------------------

function Topbar({
  breadcrumbs,
  children,
}: {
  breadcrumbs: Array<{ label: string; to?: string }>;
  children?: React.ReactNode;
}) {
  return (
    <header
      className="sticky top-0 z-20 flex h-14 items-center justify-between gap-3 border-b border-[var(--line)] bg-white/75 px-4 backdrop-blur sm:px-6 lg:px-8"
    >
      <Breadcrumbs items={breadcrumbs} />

      {/* Slot for command palette button + future profile menu. The slot's
          right-aligned wrapper means each consumer can drop arbitrary
          actions in without having to lay them out themselves. */}
      <div className="flex items-center gap-2">{children}</div>
    </header>
  );
}

function Breadcrumbs({ items }: { items: Array<{ label: string; to?: string }> }) {
  return (
    <nav aria-label="Breadcrumb" className="min-w-0 flex-1">
      <ol className="flex items-center gap-1.5 text-sm">
        {items.map((item, index) => {
          const isLast = index === items.length - 1;
          return (
            <li key={`${item.label}-${index}`} className="flex min-w-0 items-center gap-1.5">
              {index > 0 ? (
                <ChevronLeft
                  aria-hidden
                  className="h-3.5 w-3.5 rotate-180 text-zinc-300"
                />
              ) : null}
              {isLast || !item.to ? (
                <span
                  className={`truncate font-semibold ${
                    isLast ? "text-zinc-900" : "text-zinc-500"
                  }`}
                  aria-current={isLast ? "page" : undefined}
                >
                  {item.label}
                </span>
              ) : (
                <NavLink
                  to={item.to}
                  className="truncate font-medium text-zinc-500 transition-colors hover:text-zinc-900"
                >
                  {item.label}
                </NavLink>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const ROUTE_LABELS: Record<string, string> = {
  leads: "Leads",
  board: "Pipeline",
  configs: "Niche configs",
};

function buildBreadcrumbs(pathname: string): Array<{ label: string; to?: string }> {
  // Path -> [{ label, to }] pairs. We always start with "Client Scout"
  // pointing at /leads (the canonical home) so the operator can reset
  // their location with one click from anywhere in the app.
  const segments = pathname.split("/").filter(Boolean);
  const crumbs: Array<{ label: string; to?: string }> = [
    { label: "Client Scout", to: "/leads" },
  ];

  if (segments.length === 0) return crumbs;

  const top = segments[0];
  const topLabel = ROUTE_LABELS[top] ?? top;
  crumbs.push({
    label: topLabel,
    to: segments.length > 1 ? `/${top}` : undefined,
  });

  // Lead detail: /leads/{uuid}. Don't render the raw UUID - show a label
  // that signals "you've drilled into a record" without spilling identifiers.
  if (top === "leads" && segments.length > 1) {
    crumbs.push({ label: "Lead detail" });
  }

  return crumbs;
}
