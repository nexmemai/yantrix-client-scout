import { Route, Navigate, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { AuthGate } from "./components/AuthGate";
import { CommandPalette } from "./components/CommandPalette";
import { BoardPage } from "./pages/BoardPage";
import { ConfigsPage } from "./pages/ConfigsPage";
import { LeadDetailPage } from "./pages/LeadDetailPage";
import { LeadsPage } from "./pages/LeadsPage";

export default function App() {
  return (
    <AuthGate>
      {(session, clearSession) => (
        <AppShell onSignOut={clearSession} headerExtras={<CommandPalette session={session} />}>
          <Routes>
            <Route path="/" element={<Navigate replace to="/leads" />} />
            <Route path="/leads" element={<LeadsPage session={session} />} />
            <Route path="/leads/:leadId" element={<LeadDetailPage session={session} />} />
            <Route path="/board" element={<BoardPage session={session} />} />
            <Route path="/configs" element={<ConfigsPage session={session} />} />
          </Routes>
        </AppShell>
      )}
    </AuthGate>
  );
}
