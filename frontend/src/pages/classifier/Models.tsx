import { useCallback, useEffect, useState } from "react";
import {
  getModels,
  getVersions,
  type Model,
  type ModelVersion,
  selectModel,
} from "@/lib/api/models";

function formatBytes(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}

function percent(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${(value * 100).toFixed(2)}%`;
}

export function ModelsPage() {
  const [versions, setVersions] = useState<ModelVersion[]>([]);
  const [models, setModels] = useState<Model[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selecting, setSelecting] = useState<string | null>(null);
  const [openCard, setOpenCard] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [versionsResponse, modelsResponse] = await Promise.all([getVersions(), getModels()]);
      setVersions(versionsResponse.versions);
      setModels(modelsResponse.models);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudieron cargar los modelos.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleSelect(runId: string) {
    setSelecting(runId);
    setError(null);

    try {
      /*
       * No solo cambia el estado visual: el backend guarda el run y, desde ese momento,
       * Inference carga el model.pt de ese run (verificando su SHA-256).
       */
      await selectModel(runId);
      await load();
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
            Versiones semánticas publicadas en S3 (cada una apunta al run de MLflow del que salió)
            y, aparte, los runs candidatos de MLflow.
          </p>
        </header>

        {error && (
          <div className="mb-5 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            {error}
          </div>
        )}

        <section className="mb-8">
          <h2 className="mb-3 text-lg font-semibold text-ink">Versiones publicadas</h2>

          {versions.length === 0 && (
            <p className="text-sm text-ink-muted">Todavía no hay versiones publicadas.</p>
          )}

          <div className="space-y-4">
            {versions.map((version) => (
              <article
                key={version.version}
                className="rounded-xl border border-border bg-surface p-5 shadow-card"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-xl font-semibold text-ink">{version.version}</span>
                      <span className="rounded-full bg-green-50 px-2 py-0.5 text-xs font-medium text-green-700">
                        publicada en S3
                      </span>
                      {version.selected && (
                        <span className="rounded-full bg-status-success-soft px-2 py-0.5 text-xs font-medium text-status-success">
                          en uso para inferencia
                        </span>
                      )}
                    </div>
                    <p className="mt-1 text-sm text-ink-muted">
                      Run <strong>{version.runName ?? "—"}</strong>{" "}
                      <code className="text-xs">{version.runId}</code>
                    </p>
                  </div>

                  <div className="flex gap-2">
                    <button
                      type="button"
                      disabled={version.selected || selecting !== null}
                      onClick={() => void handleSelect(version.runId)}
                      className="rounded-lg bg-accent-lilac px-3 py-2 text-xs font-medium text-white disabled:opacity-50"
                    >
                      {selecting === version.runId
                        ? "Seleccionando..."
                        : version.selected
                          ? "En uso"
                          : "Usar para inferencia"}
                    </button>
                    <a
                      href={`/api/models/${version.runId}/download`}
                      className="rounded-lg border border-border px-3 py-2 text-xs font-medium text-ink hover:bg-canvas"
                    >
                      Descargar model.pt
                    </a>
                    <button
                      type="button"
                      onClick={() =>
                        setOpenCard(openCard === version.version ? null : version.version)
                      }
                      className="rounded-lg border border-border px-3 py-2 text-xs font-medium text-ink hover:bg-canvas"
                    >
                      {openCard === version.version ? "Ocultar tarjeta" : "Ver tarjeta"}
                    </button>
                  </div>
                </div>

                <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-4">
                  <Detail label="Versión del dataset" value={version.datasetVersion ?? "—"} />
                  <Detail
                    label="Manifiesto 70/20/10"
                    value={version.manifestSha256 ? `${version.manifestSha256.slice(0, 12)}…` : "—"}
                  />
                  <Detail label="Accuracy en test" value={percent(version.testMetrics?.accuracy)} />
                  <Detail label="F1 macro en test" value={percent(version.testMetrics?.macro_f1)} />
                </dl>

                <p className="mt-4 text-xs text-ink-muted">
                  <code>{version.s3Uri}</code> · verificado con {version.verifiedWith} el{" "}
                  {new Date(version.recordedAt).toLocaleString()}
                </p>

                <div className="mt-2 overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead className="text-ink-muted">
                      <tr>
                        <th className="py-1">Objeto</th>
                        <th>Tamaño</th>
                        <th>VersionId (S3)</th>
                        <th>SHA-256</th>
                      </tr>
                    </thead>
                    <tbody>
                      {version.objects.map((object) => (
                        <tr key={object.name} className="border-t border-border">
                          <td className="py-1 font-medium">{object.name}</td>
                          <td>{formatBytes(object.size)}</td>
                          <td>
                            <code>{object.versionId ?? "—"}</code>
                          </td>
                          <td>
                            <code>{object.sha256 ? `${object.sha256.slice(0, 16)}…` : "—"}</code>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {version.dependencies && (
                  <p className="mt-3 text-xs text-ink-muted">
                    Dependencias:{" "}
                    {Object.entries(version.dependencies)
                      .map(([name, pin]) => `${name}==${pin}`)
                      .join(", ")}
                  </p>
                )}

                {openCard === version.version && (
                  <pre className="mt-4 max-h-96 overflow-auto whitespace-pre-wrap rounded-lg bg-canvas p-4 text-xs text-ink">
                    {version.cardMarkdown}
                  </pre>
                )}
              </article>
            ))}
          </div>
        </section>

        <section>
          <h2 className="mb-1 text-lg font-semibold text-ink">Runs candidatos de MLflow</h2>
          <p className="mb-3 text-sm text-ink-muted">
            Runs terminados del experimento t3-classifier. No son versiones publicadas: cualquiera
            puede usarse para inferencia, pero solo las versiones de arriba están en S3.
          </p>

          <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-card">
            <table className="w-full text-left text-sm">
              <thead className="bg-canvas">
                <tr>
                  <th className="px-4 py-3">Run</th>
                  <th className="px-4 py-3">Run ID</th>
                  <th className="px-4 py-3">Dataset</th>
                  <th className="px-4 py-3">Val accuracy</th>
                  <th className="px-4 py-3">Optimizer</th>
                  <th className="px-4 py-3">Acciones</th>
                </tr>
              </thead>

              <tbody>
                {models.map((model) => (
                  <tr key={model.runId} className="border-t border-border">
                    <td className="px-4 py-4">
                      <div className="font-medium">{model.runName}</div>
                      {model.selected && (
                        <span className="mt-1 inline-block rounded-full bg-status-success-soft px-2 py-0.5 text-xs font-medium text-status-success">
                          en uso para inferencia
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-4">
                      <code className="text-xs">{model.runId}</code>
                    </td>
                    <td className="px-4 py-4">{model.datasetVersion ?? "—"}</td>
                    <td className="px-4 py-4">{percent(model.accuracy)}</td>
                    <td className="px-4 py-4">{model.optimizer ?? "—"}</td>
                    <td className="px-4 py-4">
                      <div className="flex gap-2">
                        <button
                          type="button"
                          disabled={model.selected || selecting !== null}
                          onClick={() => void handleSelect(model.runId)}
                          className="rounded-lg border border-border px-3 py-2 text-xs font-medium text-ink hover:bg-canvas disabled:opacity-50"
                        >
                          {selecting === model.runId ? "Seleccionando..." : "Usar para inferencia"}
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
        </section>
      </div>
    </main>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-ink-muted">{label}</dt>
      <dd className="font-medium text-ink">{value}</dd>
    </div>
  );
}
