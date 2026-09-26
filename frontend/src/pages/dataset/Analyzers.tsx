import { useState } from "react";
import { QualityStatusBadge } from "@/components/dataset/QualityStatusBadge";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { useValidatedFetch } from "@/hooks/useValidatedFetch";
import { type QualityCheck, qualityReportSchema } from "@/lib/contracts/schemas";

/**
 * Analyzers: un tab por analizador de calidad (Tier 2 del pipeline), leído
 * de GET /quality-report (backend, SPEC-PIPE-001/APP-07) — ya no del mock
 * estático de contracts/quality.json (ver contracts/README.md,
 * "Reconciliación con APP-07"). Solo se listan los checks que representan
 * analizadores propiamente (se excluye min_images_per_class, que es la
 * política de la quality gate, no un analizador — ver Splits/Overview).
 *
 * "spatial_bias" está en esta lista porque el AC de APP-05 pide la pestaña,
 * pero no está en el `quality.json` real desde la reconciliación con
 * DQ-02 (contracts/README.md: "no está definido en la política de DQ-02").
 * La pestaña se muestra igual — es una pestaña más de este arreglo fijo, no
 * algo derivado de qué checks trajo el contrato — pero cuando no hay un
 * check que la respalde muestra un estado honesto de "no disponible" en
 * vez de inventar datos. Ver `ANALYZER_LABELS` / `SPATIAL_BIAS_ID` abajo.
 */
const ANALYZER_IDS = [
  "small_objects",
  "class_imbalance",
  "duplicates",
  "invalid_boxes",
  "spatial_bias",
] as const;

const SPATIAL_BIAS_ID = "spatial_bias";

const ANALYZER_LABELS: Record<(typeof ANALYZER_IDS)[number], string> = {
  small_objects: "Small objects (< 32x32 px)",
  class_imbalance: "Class imbalance ratio",
  duplicates: "Duplicates / near-duplicates (pHash)",
  invalid_boxes: "Invalid / degenerate bounding boxes",
  spatial_bias: "Spatial bias",
};

export function AnalyzersPage() {
  const report = useValidatedFetch("/quality-report", qualityReportSchema);
  const [activeId, setActiveId] = useState<string>(ANALYZER_IDS[0]);

  return (
    <main className="flex-1 px-6 py-6 lg:px-10 lg:py-8">
      <div className="mx-auto flex max-w-6xl flex-col gap-6">
        <header>
          <h1 className="text-xl font-semibold text-ink">Analyzers</h1>
          <p className="mt-1 text-sm text-ink-muted">
            Objetos pequeños, desbalance de clases, duplicados, cajas inválidas y sesgo espacial.
          </p>
        </header>

        {report.status === "loading" && <Skeleton className="h-64" />}

        {report.status === "error" && (
          <ErrorState
            title="No se pudieron cargar los analizadores."
            message={report.message}
            onRetry={report.reload}
          />
        )}

        {report.status === "success" && (
          <AnalyzersTabs checks={report.data.checks} activeId={activeId} onChange={setActiveId} />
        )}
      </div>
    </main>
  );
}

function AnalyzersTabs({
  checks,
  activeId,
  onChange,
}: {
  checks: QualityCheck[];
  activeId: string;
  onChange: (id: string) => void;
}) {
  // Las pestañas son siempre las 5 de ANALYZER_IDS (AC de APP-05), no
  // "las que trajo el contrato" — así "Spatial Bias" sigue siendo
  // seleccionable aunque quality.json no tenga ese check.
  const activeCheck = checks.find((c) => c.id === activeId);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap gap-2 border-b border-border pb-2">
        {ANALYZER_IDS.map((id) => (
          <button
            key={id}
            type="button"
            onClick={() => onChange(id)}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
              activeId === id
                ? "bg-accent-lilac-soft text-accent-lilac"
                : "text-ink-muted hover:bg-sidebar hover:text-ink"
            }`}
          >
            {checks.find((c) => c.id === id)?.label ?? ANALYZER_LABELS[id]}
          </button>
        ))}
      </div>

      {activeId === SPATIAL_BIAS_ID && !activeCheck ? (
        <SpatialBiasUnavailable />
      ) : activeCheck ? (
        <AnalyzerDetail check={activeCheck} />
      ) : (
        <EmptyState hasFilters={false} />
      )}
    </div>
  );
}

function SpatialBiasUnavailable() {
  return (
    <div className="rounded-2xl border border-dashed border-border-strong bg-surface p-5 text-center shadow-card">
      <p className="text-sm font-medium text-ink">Spatial bias no está disponible todavía</p>
      <p className="mt-1 text-sm text-ink-muted">
        Este check no forma parte de la política actual de Data Quality (<code>quality.yaml</code>,
        DQ-02) — ver <code>contracts/README.md</code>. Cuando se agregue con un umbral real, esta
        pestaña va a mostrar sus datos sin cambios adicionales aquí.
      </p>
    </div>
  );
}

function AnalyzerDetail({ check }: { check: QualityCheck }) {
  return (
    <div className="rounded-2xl border border-border bg-surface p-5 shadow-card">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-base font-semibold text-ink">{check.label}</h2>
        <QualityStatusBadge status={check.status} />
      </div>

      {check.observed !== null && check.threshold !== null && (
        <p className="mt-2 text-sm text-ink-muted">
          Observado <span className="font-medium text-ink">{check.observed}</span> {check.unit} ·
          umbral <span className="font-medium text-ink">{check.threshold}</span> {check.unit}
        </p>
      )}

      <p className="mt-4 text-sm font-medium text-ink">Muestras ofensoras</p>
      {check.offending_samples.length === 0 ? (
        <p className="mt-1 text-sm text-ink-muted">Ninguna reportada.</p>
      ) : (
        <ul className="mt-2 space-y-1 text-xs text-ink-muted">
          {check.offending_samples.map((sample) => (
            <li key={JSON.stringify(sample)} className="rounded-lg bg-sidebar px-3 py-2 font-mono">
              {JSON.stringify(sample)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
