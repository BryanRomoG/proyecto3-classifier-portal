import { useState } from "react";
import { ErrorState } from "@/components/ui/ErrorState";
import { Skeleton } from "@/components/ui/Skeleton";
import { useValidatedFetch } from "@/hooks/useValidatedFetch";
import { type QualityPolicyUpdateBody, updateQualityPolicy } from "@/lib/api/qualityPolicy";
import {
  type QualityPolicyCheck,
  qualityPolicySchema,
  type Severity,
} from "@/lib/contracts/schemas";

type Edits = Record<string, { threshold: string; severity: Severity }>;

type SaveState =
  | { status: "idle" }
  | { status: "saving" }
  | { status: "success" }
  | { status: "error"; message: string };

/**
 * Settings: muestra y permite editar los umbrales/severidad de cada check
 * de la quality gate (AC de APP-05: "Quality thresholds can be displayed
 * and edited"). A diferencia de la versión de APP-05, esta lee y escribe la
 * política REAL: GET /quality-policy trae pipeline/quality.yaml tal cual
 * (no el último reporte — ver `qualityPolicySchema` en lib/contracts/schemas.ts),
 * y el botón "Guardar" hace PUT /quality-policy (backend, SPEC-PIPE-001),
 * que sobrescribe ese mismo archivo. No hay ninguna otra copia de por
 * medio: la siguiente corrida de la quality gate (`dvc repro`) lee este
 * archivo y usa los valores nuevos — así es como esta pantalla afecta la
 * siguiente corrida (Agent Test de APP-07). Ver contracts/README.md,
 * "Reconciliación con APP-07".
 */
export function SettingsPage() {
  const policy = useValidatedFetch("/quality-policy", qualityPolicySchema);
  const [edits, setEdits] = useState<Edits>({});
  const [saveState, setSaveState] = useState<SaveState>({ status: "idle" });

  const editedValue = (checkId: string, check: QualityPolicyCheck) =>
    edits[checkId] ?? {
      threshold: String(check.threshold),
      severity: check.severity,
    };

  const setThreshold = (checkId: string, check: QualityPolicyCheck, value: string) => {
    setSaveState({ status: "idle" });
    setEdits((prev) => ({
      ...prev,
      [checkId]: { ...editedValue(checkId, check), threshold: value },
    }));
  };

  const setSeverity = (checkId: string, check: QualityPolicyCheck, value: Severity) => {
    setSaveState({ status: "idle" });
    setEdits((prev) => ({
      ...prev,
      [checkId]: { ...editedValue(checkId, check), severity: value },
    }));
  };

  const hasEdits = Object.keys(edits).length > 0;

  const handleSave = async () => {
    if (policy.status !== "success") return;

    // PUT /quality-policy exige el conjunto EXACTO de checks que ya existen
    // en quality.yaml (spec regla 5: ni falta uno ni sobra uno) — por eso el
    // body se arma con TODOS los checks del policy actual, usando el valor
    // editado si lo hay y si no el valor tal como está, nunca solo los que
    // se tocaron.
    const body: QualityPolicyUpdateBody = Object.fromEntries(
      Object.entries(policy.data).map(([checkId, check]) => {
        const edited = edits[checkId];
        return [
          checkId,
          {
            threshold: edited ? Number(edited.threshold) : check.threshold,
            severity: edited ? edited.severity : check.severity,
          },
        ];
      })
    );

    setSaveState({ status: "saving" });
    try {
      await updateQualityPolicy(body);
      setSaveState({ status: "success" });
      setEdits({});
      policy.reload();
    } catch (err) {
      // ApiError (client.ts) extiende Error, así que su .message ya trae el
      // motivo real del backend (400 por min_images_per_class < 300, checks
      // faltantes/desconocidos, etc.) — no hace falta distinguirlo aparte.
      const message = err instanceof Error ? err.message : "No se pudo guardar la política.";
      setSaveState({ status: "error", message });
    }
  };

  return (
    <main className="flex-1 px-6 py-6 lg:px-10 lg:py-8">
      <div className="mx-auto flex max-w-6xl flex-col gap-6">
        <header>
          <h1 className="text-xl font-semibold text-ink">Settings</h1>
          <p className="mt-1 text-sm text-ink-muted">
            Umbrales y severidad por check de la quality gate.
          </p>
        </header>

        {policy.status === "loading" && <Skeleton className="h-64" />}

        {policy.status === "error" && (
          <ErrorState
            title="No se pudo cargar la configuración."
            message={policy.message}
            onRetry={policy.reload}
          />
        )}

        {policy.status === "success" && (
          <div className="rounded-2xl border border-border bg-surface shadow-card">
            <div className="border-b border-border bg-status-pending-soft px-5 py-3 text-xs text-status-pending">
              Los cambios de esta pantalla se guardan en <code>pipeline/quality.yaml</code> — el
              mismo archivo que lee la siguiente corrida de la quality gate (<code>dvc repro</code>
              ). Nada se escribe hasta que presionas "Guardar".
            </div>
            <ul className="divide-y divide-border">
              {Object.entries(policy.data).map(([checkId, check]) => {
                const current = editedValue(checkId, check);
                return (
                  <li
                    key={checkId}
                    className="flex flex-wrap items-center justify-between gap-4 px-5 py-4"
                  >
                    <div>
                      <p className="text-sm font-medium text-ink">{check.label}</p>
                      <p className="text-xs text-ink-muted">id: {checkId}</p>
                    </div>
                    <div className="flex items-center gap-3">
                      <label className="flex items-center gap-1.5 text-xs text-ink-muted">
                        Umbral
                        <input
                          type="text"
                          value={current.threshold}
                          onChange={(event) => setThreshold(checkId, check, event.target.value)}
                          className="w-20 rounded-lg border border-border bg-surface px-2 py-1 text-sm text-ink"
                        />
                      </label>
                      <label className="flex items-center gap-1.5 text-xs text-ink-muted">
                        Severidad
                        <select
                          value={current.severity}
                          onChange={(event) =>
                            setSeverity(checkId, check, event.target.value as Severity)
                          }
                          className="rounded-lg border border-border bg-surface px-2 py-1 text-sm text-ink"
                        >
                          <option value="warn">warn</option>
                          <option value="fail">fail</option>
                        </select>
                      </label>
                    </div>
                  </li>
                );
              })}
            </ul>
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-5 py-4">
              <p className="text-xs" aria-live="polite">
                {saveState.status === "success" && (
                  <span className="font-medium text-status-done">Cambios guardados.</span>
                )}
                {saveState.status === "error" && (
                  <span className="font-medium text-red-700">{saveState.message}</span>
                )}
              </p>
              <button
                type="button"
                onClick={handleSave}
                disabled={!hasEdits || saveState.status === "saving"}
                className="rounded-lg bg-accent-lilac px-3 py-1.5 text-sm font-medium text-white shadow-sm transition-colors hover:bg-accent-lilac/90 disabled:cursor-not-allowed disabled:bg-border disabled:text-ink-faint disabled:shadow-none"
              >
                {saveState.status === "saving" ? "Guardando…" : "Guardar"}
              </button>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
