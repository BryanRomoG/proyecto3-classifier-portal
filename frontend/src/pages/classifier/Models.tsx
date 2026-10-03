import { useCallback, useEffect, useState } from "react";
import { getModels, type Model, selectModel } from "@/lib/api/models";

export function ModelsPage() {
  const [models, setModels] = useState<Model[]>([]);

  const [loading, setLoading] = useState(true);

  const [error, setError] = useState<string | null>(null);

  const [selecting, setSelecting] = useState<string | null>(null);

  const loadModels = useCallback(async () => {
    try {
      const response = await getModels();

      setModels(response.models);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudieron cargar los modelos.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadModels();
  }, [loadModels]);

  async function handleSelect(runId: string) {
    setSelecting(runId);
    setError(null);

    try {
      /*
       * Esto NO solo cambia el estado visual.
       *
       * El backend guarda el run_id y a partir de ese
       * momento el artifact model.pt utilizado es el de
       * este run.
       */
      await selectModel(runId);

      await loadModels();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo seleccionar el modelo.");
    } finally {
      setSelecting(null);
    }
  }

  if (loading) {
    return <main className="p-8">Cargando modelos...</main>;
  }

  return (
    <main className="flex-1 p-8">
      <div className="mx-auto max-w-7xl">
        <header className="mb-6">
          <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
            Model Registry
          </p>

          <h1 className="text-2xl font-semibold text-ink">Models</h1>

          <p className="mt-1 text-sm text-ink-muted">
            Versiones publicadas y trazabilidad de los artefactos de MLflow.
          </p>
        </header>

        {error && (
          <div className="mb-5 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            {error}
          </div>
        )}

        <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-card">
          <table className="w-full text-left text-sm">
            <thead className="bg-canvas">
              <tr>
                <th className="px-4 py-3">Version</th>

                <th className="px-4 py-3">Run ID</th>

                <th className="px-4 py-3">Dataset</th>

                <th className="px-4 py-3">Val accuracy</th>

                <th className="px-4 py-3">Optimizer</th>

                <th className="px-4 py-3">Status</th>

                <th className="px-4 py-3">Actions</th>
              </tr>
            </thead>

            <tbody>
              {models.map((model) => (
                <tr key={model.runId} className="border-t border-border">
                  <td className="px-4 py-4">
                    <div className="font-medium">{model.version}</div>

                    <div className="text-xs text-ink-muted">{model.runName}</div>

                    {model.selected && (
                      <span className="mt-1 inline-block rounded-full bg-status-success-soft px-2 py-0.5 text-xs font-medium text-status-success">
                        Seleccionado
                      </span>
                    )}
                  </td>

                  <td className="px-4 py-4">
                    <code className="text-xs">{model.runId}</code>
                  </td>

                  <td className="px-4 py-4">{model.datasetVersion ?? "-"}</td>

                  <td className="px-4 py-4">
                    {model.accuracy === null ? "-" : `${(model.accuracy * 100).toFixed(2)}%`}
                  </td>

                  <td className="px-4 py-4">{model.optimizer ?? "-"}</td>

                  <td className="px-4 py-4">{model.status}</td>

                  <td className="px-4 py-4">
                    <div className="flex gap-2">
                      <button
                        type="button"
                        disabled={model.selected || selecting !== null}
                        onClick={() => void handleSelect(model.runId)}
                        className="rounded-lg bg-accent-lilac px-3 py-2 text-xs font-medium text-white disabled:opacity-50"
                      >
                        {selecting === model.runId
                          ? "Seleccionando..."
                          : model.selected
                            ? "Seleccionado"
                            : "Seleccionar"}
                      </button>

                      <a
                        href={`/api/models/${model.runId}/download`}
                        className="rounded-lg border border-border px-3 py-2 text-xs font-medium text-ink hover:bg-canvas"
                      >
                        Descargar
                      </a>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="mt-6 rounded-xl border border-border bg-surface p-5 shadow-card">
          <h2 className="font-semibold text-ink">Trazabilidad</h2>

          <p className="mt-2 text-sm text-ink-muted">Cada modelo mantiene la relación:</p>

          <div className="mt-4 flex flex-wrap items-center gap-2 text-sm">
            <span className="rounded-lg bg-canvas px-3 py-2">Dataset</span>

            <span>→</span>

            <span className="rounded-lg bg-canvas px-3 py-2">Run ID</span>

            <span>→</span>

            <span className="rounded-lg bg-canvas px-3 py-2">model.pt</span>

            <span>→</span>

            <span className="rounded-lg bg-canvas px-3 py-2">Inference</span>
          </div>
        </div>
      </div>
    </main>
  );
}
