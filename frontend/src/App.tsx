import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClientProvider } from "@tanstack/react-query";
import { queryClient } from "./lib/query-client";
import { AppShell } from "./components/layout/AppShell";
import { OverviewPage } from "./pages/OverviewPage";
import { ProjectPage } from "./pages/ProjectPage";
import { InsightsPage } from "./pages/InsightsPage";
import { AgentsPage } from "./pages/AgentsPage";
import { KnowledgePage } from "./pages/KnowledgePage";
import { SettingsPage } from "./pages/SettingsPage";
import { ActionsPage } from "./pages/ActionsPage";
import { ChannelPage } from "./pages/ChannelPage";

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<ChannelPage />} />
            <Route path="overview" element={<OverviewPage />} />
            <Route path="project" element={<ProjectPage />} />
            <Route path="insights" element={<InsightsPage />} />
            <Route path="agents" element={<AgentsPage />} />
            <Route path="actions" element={<ActionsPage />} />
            <Route path="knowledge" element={<KnowledgePage />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
