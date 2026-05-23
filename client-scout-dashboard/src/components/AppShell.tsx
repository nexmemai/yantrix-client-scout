import { LayoutList, LogOut, Settings2, Trello } from "lucide-react";
import { NavLink } from "react-router-dom";

interface AppShellProps {
  onSignOut: () => void;
  children: React.ReactNode;
  /**
   * Optional slot for top-bar elements (command palette trigger, profile
   * menu, etc.). Rendered to the right of the page heading on wide layouts.
   */
  headerExtras?: React.ReactNode;
}

const navItems = [
  { to: "/leads", label: "Leads", icon: LayoutList },
  { to: "/board", label: "Pipeline board", icon: Trello },
  { to: "/configs", label: "Niche Configs", icon: Settings2 },
];

export function AppShell({ onSignOut, children, headerExtras }: AppShellProps) {
  return (
    <div className="app-shell">
      <aside className="sidebar-surface flex flex-col justify-between px-4 py-4 sm:px-5">
        <div>
          <div className="mb-8 border-b border-[var(--line)] pb-5">
            <div className="text-[11px] font-bold uppercase tracking-wide text-[var(--muted)]">
              Yantrix Labs
            </div>
            <div className="mt-2 text-xl font-extrabold">Client Scout</div>
            <div className="mt-2 text-sm leading-6 text-[var(--muted)]">
              Internal lead operations console
            </div>
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
