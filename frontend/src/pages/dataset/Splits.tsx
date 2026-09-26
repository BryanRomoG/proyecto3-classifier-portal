import { QualityStatusBadge } from "@/components/dataset/QualityStatusBadge";
import { ErrorState } from "@/components/ui/ErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { useValidatedFetch } from "@/hooks/useValidatedFetch";
import { splitsReportSchema } from "@/lib/contracts/schemas";

const SPLIT_LABELS = { train: "Train", val: "Val", test: "Test" } as const;
type SplitKey = keyof typeof SPLIT_LABELS;
const SPLIT_KEYS = Object.keys(SPLIT_LABELS) as SplitKey[];

/**
 * Splits: distribución de clases por partición y resultado del leakage
 * check, leído de GET /split-report (backend, SPEC-PIPE-001/APP-07) — ya no
 * del mock estático de contracts/splits.json (ver contracts/README.md,
 * "Reconciliación con APP-07"). La reproducibilidad (mismo seed -> mismos
 * IDs) se prueba corriendo el pipeline dos veces, no desde aquí — este
 * contrato solo expone el resultado ya calculado.
 */
export function SplitsPage() {
  const report = useValidatedFetch("/split-report", splitsReportSchema);

  return (
    <main className="flex-1 px-6 py-6 lg:px-10 lg:py-8">
      <div className="mx-auto flex max-w-6xl flex-col gap-6">
        <header>
          <h1 className="text-xl font-semibold text-ink">Splits</h1>
          <p className="mt-1 text-sm text-ink-muted">
            Distribución por clase y chequeo de fuga entre train/val/test.
          </p>
        </header>

        {report.status === "loading" && <Skeleton className="h-64" />}

        {report.status === "error" && (
          <ErrorState
            title="No se pudo cargar la información de splits."
            message={report.message}
            onRetry={report.reload}
          />
        )}

        {report.status === "success" && (
          <div className="flex flex-col gap-6">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              {SPLIT_KEYS.map((key) => (
                <div
                  key={key}
                  className="rounded-2xl border border-border bg-surface p-5 shadow-card"
                >
                  <p className="text-sm text-ink-muted">{SPLIT_LABELS[key]}</p>
                  <p className="mt-1 text-2xl font-semibold text-ink">
                    {report.data.totals[key].toLocaleString("es")}
                  </p>
                  <p className="text-xs text-ink-muted">
                    proporción configurada: {(report.data.proportions[key] * 100).toFixed(0)}%
                  </p>
                </div>
              ))}
            </div>

            <div className="overflow-x-auto rounded-2xl border border-border bg-surface shadow-card">
              <table className="w-full min-w-[480px] text-left text-sm">
                <thead className="bg-sidebar text-xs uppercase text-ink-muted">
                  <tr>
                    <th className="px-4 py-3 font-medium">Clase</th>
                    {SPLIT_KEYS.map((key) => (
                      <th key={key} className="px-4 py-3 font-medium">
                        {SPLIT_LABELS[key]}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {Object.keys(report.data.class_distribution.train).map((className) => (
                    <tr key={className}>
                      <td className="px-4 py-3 font-medium text-ink">{className}</td>
                      {SPLIT_KEYS.map((key) => (
                        <td key={key} className="px-4 py-3 text-ink-muted">
                          {report.data.class_distribution[key][className] ?? 0}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="rounded-2xl border border-border bg-surface p-5 shadow-card">
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-medium text-ink">Leakage check</p>
                <QualityStatusBadge status={report.data.leakage_check.status} />
              </div>
              <p className="mt-2 text-sm text-ink-muted">
                {report.data.leakage_check.leaked_pairs} pares con fuga ·{" "}
                {report.data.leakage_check.near_duplicate_pairs_same_split}/
                {report.data.leakage_check.near_duplicate_pairs_checked} pares near-duplicate
                confirmados en el mismo split.
              </p>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
