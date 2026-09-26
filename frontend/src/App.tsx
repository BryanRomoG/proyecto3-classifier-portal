import { Navigate, Route, Routes } from "react-router-dom";
import { AnnotateScreen } from "@/components/annotate/AnnotateScreen";
import { AppLayout } from "@/components/layout/AppLayout";
import { DatasetAppLayout } from "@/components/layout/DatasetAppLayout";
import { UploadScreen } from "@/components/upload/UploadScreen";
import { DashboardPage } from "@/pages/Dashboard";
import { AnalyzersPage } from "@/pages/dataset/Analyzers";
import { CopilotPage } from "@/pages/dataset/Copilot";
import { OverviewPage } from "@/pages/dataset/Overview";
import { SettingsPage } from "@/pages/dataset/Settings";
import { SplitsPage } from "@/pages/dataset/Splits";
import { VersionsPage } from "@/pages/dataset/Versions";
import { SearchPage } from "@/pages/SearchPage";

export function App(): JSX.Element {
  return (
    <Routes>
      {/* NOTA (APP-02): "/" sigue apuntando al Portal de Anotación (Proyecto 1)
          por ahora, para no romper nada de lo ya construido. Cuando el equipo
          decida que las 6 pantallas de Dataset Quality son la app principal,
          este redirect cambia a "/overview" en un ticket aparte. */}
      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route
        path="/dashboard"
        element={
          <AppLayout>
            <DashboardPage />
          </AppLayout>
        }
      />
      {/* SearchPage se envuelve con AppLayout internamente (no aquí), porque
          necesita pasarle su propio contenido de filtros como sidebarExtra
          — ver SearchPage.tsx. */}
      <Route path="/search" element={<SearchPage />} />
      <Route
        path="/upload"
        element={
          <AppLayout>
            <UploadScreen />
          </AppLayout>
        }
      />
      {/* Annotate es un modo de enfoque de pantalla completa a propósito: sin
          nav global, con su propio botón "Volver". Ver GlobalNav.tsx. */}
      <Route path="/annotate/:imageId" element={<AnnotateScreen />} />

      {/* Las seis pantallas de Dataset Quality (APP-02). Nav propio
          (DatasetAppLayout/DatasetNav), separado del Portal de Anotación. */}
      <Route
        path="/overview"
        element={
          <DatasetAppLayout>
            <OverviewPage />
          </DatasetAppLayout>
        }
      />
      <Route
        path="/analyzers"
        element={
          <DatasetAppLayout>
            <AnalyzersPage />
          </DatasetAppLayout>
        }
      />
      <Route
        path="/splits"
        element={
          <DatasetAppLayout>
            <SplitsPage />
          </DatasetAppLayout>
        }
      />
      <Route
        path="/versions"
        element={
          <DatasetAppLayout>
            <VersionsPage />
          </DatasetAppLayout>
        }
      />
      <Route
        path="/copilot"
        element={
          <DatasetAppLayout>
            <CopilotPage />
          </DatasetAppLayout>
        }
      />
      <Route
        path="/settings"
        element={
          <DatasetAppLayout>
            <SettingsPage />
          </DatasetAppLayout>
        }
      />

      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}
