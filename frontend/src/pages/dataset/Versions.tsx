import { QualityStatusBadge } from "@/components/dataset/QualityStatusBadge";
import { ErrorState } from "@/components/ui/ErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { useValidatedFetch } from "@/hooks/useValidatedFetch";
import { type DatasetVersion, versionsReportSchema } from "@/lib/contracts/schemas";

/**
 * Versions: línea de tiempo de versiones semánticas, diff entre versión
 * actual y anterior, y estado DEV/PROD por versión — leído de
 * GET /version-history (backend, SPEC-PIPE-001/APP-07), ya no del mock
 * estático de contracts/versions.json (ver contracts/README.md,
 * "Reconciliación con APP-07").
 */
export function VersionsPage() {
  const report = useValidatedFetch("/version-history", versionsReportSchema);

  return (
    <main className="flex-1 px-6 py-6 lg:px-10 lg:py-8">
      <div className="mx-auto flex max-w-6xl flex-col gap-6">
        <header>
          <h1 className="text-xl font-semibold text-ink">Versions</h1>
          <p className="mt-1 text-sm text-ink-muted">
            Historial de releases, estado DEV/PROD y diferencias entre versiones.
          </p>
        </header>

        {report.status === "loading" && <Skeleton className="h-64" />}

        {report.status === "error" && (
          <ErrorState
            title="No se pudo cargar el historial de versiones."
            message={report.message}
            onRetry={report.reload}
          />
        )}

        {report.status === "success" && (
          <ol className="flex flex-col gap-4">
            {[...report.data.versions].reverse().map((version) => (
              <VersionCard
                key={version.version}
                version={version}
                isCurrent={version.version === report.data.current_version}
              />
            ))}
          </ol>
        )}
      </div>
    </main>
  );
}

function VersionCard({ version, isCurrent }: { version: DatasetVersion; isCurrent: boolean }) {
  return (
    <li className="rounded-2xl border border-border bg-surface p-5 shadow-card">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <p className="text-base font-semibold text-ink">{version.version}</p>
          {isCurrent && (
            <span className="rounded-full bg-accent-lilac-soft px-2 py-0.5 text-xs font-medium text-accent-lilac">
              Actual
            </span>
          )}
        </div>
        <QualityStatusBadge status={version.quality_status} />
      </div>

      <p className="mt-1 text-xs text-ink-muted">
        {new Date(version.released_at).toLocaleString("es")} ·{" "}
        <span className="font-mono">{version.content_hash.slice(0, 19)}…</span>
      </p>

      <div className="mt-3 flex flex-wrap gap-4 text-xs text-ink-muted">
        <span>
          DEV ({version.environments.dev.provider}): {version.environments.dev.status}
        </span>
        <span>
          PROD ({version.environments.prod.provider}): {version.environments.prod.status}
        </span>
      </div>

      {version.diff_from_previous && (
        <div className="mt-3 border-t border-border pt-3 text-xs text-ink-muted">
          <p className="font-medium text-ink">Diff vs. versión anterior</p>
          <p className="mt-1">
            +{version.diff_from_previous.images_added} imágenes · +
            {version.diff_from_previous.boxes_added} cajas ·{" "}
            {version.diff_from_previous.small_object_ratio_change_pct >= 0 ? "+" : ""}
            {version.diff_from_previous.small_object_ratio_change_pct}% objetos pequeños
          </p>
          {version.diff_from_previous.classes_left_minimum.length > 0 && (
            <p className="mt-1 text-red-700">
              Clases que salieron del mínimo:{" "}
              {version.diff_from_previous.classes_left_minimum.join(", ")}
            </p>
          )}
        </div>
      )}
    </li>
  );
}
