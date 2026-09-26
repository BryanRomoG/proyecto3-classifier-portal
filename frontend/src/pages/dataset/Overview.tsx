import { QualityStatusBadge } from "@/components/dataset/QualityStatusBadge";
import { ErrorState } from "@/components/ui/ErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { useValidatedFetch } from "@/hooks/useValidatedFetch";
import { type QualityReport, qualityReportSchema } from "@/lib/contracts/schemas";

/**
 * Overview: estado del quality gate y resumen de checks, leído de
 * GET /quality-report (backend, SPEC-PIPE-001/APP-07), que a su vez sirve
 * contracts/quality.json tal como lo dejó la pipeline real — ya no el mock
 * estático de APP-01 (ver contracts/README.md, "Reconciliación con APP-07").
 * Ningún número aquí está hardcodeado: todo sale del fetch, así que la
 * siguiente corrida de la pipeline (`dvc repro`) cambia lo que se ve sin
 * tocar este archivo.
 *
 * Las 4 cifras de resumen (imágenes, cajas, categorías, checks fallidos) y
 * el estado del gate son el Acceptance Criteria de APP-05. Las primeras 3
 * salen de `dataset_summary` (ver contracts/README.md, "Reconciliación con
 * APP-05") — es opcional en el contrato porque el pipeline real todavía no
 * siempre lo produce, así que si falta se muestra "—" en vez de inventar un
 * número. "Checks fallidos" se deriva contando `checks` con
 * `status === "fail"`: no necesita su propio campo en el contrato.
 */
export function OverviewPage() {
  const report = useValidatedFetch("/quality-report", qualityReportSchema);

  return (
    <main className="flex-1 px-6 py-6 lg:px-10 lg:py-8">
      <div className="mx-auto flex max-w-6xl flex-col gap-6">
        <header>
          <h1 className="text-xl font-semibold text-ink">Overview</h1>
          <p className="mt-1 text-sm text-ink-muted">
            Estado general de calidad del dataset y su quality gate.
          </p>
        </header>

        {report.status === "loading" && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Skeleton className="h-28" />
            <Skeleton className="h-28" />
            <Skeleton className="h-28" />
          </div>
        )}

        {report.status === "error" && (
          <ErrorState
            title="No se pudo cargar el estado de calidad."
            message={report.message}
            onRetry={report.reload}
          />
        )}

        {report.status === "success" && (
          <div className="flex flex-col gap-6">
            <div className="rounded-2xl border border-border bg-surface p-5 shadow-card">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-sm text-ink-muted">Versión evaluada</p>
                  <p className="mt-1 text-lg font-semibold text-ink">
                    {report.data.dataset_version}
                  </p>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <p className="text-sm text-ink-muted">Estado del gate</p>
                  <QualityStatusBadge status={report.data.overall_status} />
                </div>
              </div>
            </div>

            <DatasetSummaryCards report={report.data} />

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {report.data.checks.map((check) => (
                <div
                  key={check.id}
                  className="rounded-2xl border border-border bg-surface p-5 shadow-card"
                >
                  <div className="flex items-center justify-between gap-2">
                    <p className="text-sm font-medium text-ink">{check.label}</p>
                    <QualityStatusBadge status={check.status} />
                  </div>
                  <p className="mt-2 text-xs text-ink-muted">
                    Severidad configurada: <span className="font-medium">{check.severity}</span>
                  </p>
                  {check.observed !== null && check.threshold !== null && (
                    <p className="mt-1 text-xs text-ink-muted">
                      Observado {check.observed} {check.unit} — umbral {check.threshold}{" "}
                      {check.unit}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </main>
  );
}

const SUMMARY_STAT_LABELS = {
  total_images: "Total images",
  total_bounding_boxes: "Total bounding boxes",
  total_categories: "Categories",
} as const;

function DatasetSummaryCards({ report }: { report: QualityReport }) {
  const failedChecks = report.checks.filter((check) => check.status === "fail").length;

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {(Object.keys(SUMMARY_STAT_LABELS) as (keyof typeof SUMMARY_STAT_LABELS)[]).map((key) => (
        <div key={key} className="rounded-2xl border border-border bg-surface p-5 shadow-card">
          <p className="text-sm text-ink-muted">{SUMMARY_STAT_LABELS[key]}</p>
          <p className="mt-1 text-2xl font-semibold text-ink">
            {report.dataset_summary ? report.dataset_summary[key].toLocaleString("es") : "—"}
          </p>
        </div>
      ))}
      <div className="rounded-2xl border border-border bg-surface p-5 shadow-card">
        <p className="text-sm text-ink-muted">Failed checks</p>
        <p className="mt-1 text-2xl font-semibold text-ink">{failedChecks}</p>
      </div>
    </div>
  );
}
