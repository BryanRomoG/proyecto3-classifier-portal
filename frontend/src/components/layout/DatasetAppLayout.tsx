import type { ReactNode } from "react";
import { DatasetNav } from "./DatasetNav";

/**
 * Shell compartido por las seis pantallas de Dataset Quality (Overview,
 * Analyzers, Splits, Versions, Copilot, Settings). Mismo patrón que
 * `AppLayout` del Portal de Anotación, con su propio nav (`DatasetNav`)
 * porque son dos productos distintos dentro del mismo frontend.
 */
export function DatasetAppLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col bg-canvas lg:flex-row">
      <DatasetNav />
      <div className="flex min-w-0 flex-1 flex-col">{children}</div>
    </div>
  );
}
