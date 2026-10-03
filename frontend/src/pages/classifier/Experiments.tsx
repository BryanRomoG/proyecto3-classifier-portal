import { useEffect, useMemo, useState } from "react";
import { type Experiment, getExperiments } from "@/lib/api/experiments";

export function ExperimentsPage() {
  const [experiments, setExperiments] = useState<Experiment[]>([]);

  const [optimizer, setOptimizer] = useState("all");

  const [selectedRun, setSelectedRun] = useState<Experiment | null>(null);

  const [loading, setLoading] = useState(true);

  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const response = await getExperiments();

        setExperiments(response.experiments);
      } catch (err) {
        setError(err instanceof Error ? err.message : "No se pudieron cargar los experiments.");
      } finally {
        setLoading(false);
      }
    }

    void load();
  }, []);

  const filtered = useMemo(() => {
    if (optimizer === "all") {
      return experiments;
    }

    return experiments.filter(
      (experiment) => experiment.optimizer.toLowerCase() === optimizer.toLowerCase()
    );
  }, [experiments, optimizer]);

  if (loading) {
    return (
      <main className="p-8">
        <p>Cargando experimentos de MLflow...</p>
      </main>
    );
  }

  if (error) {
    return (
      <main className="p-8">
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-700">{error}</div>
      </main>
    );
  }

  return (
    <main className="flex-1 p-8">
      <div className="mx-auto max-w-7xl">
        <header className="mb-6">
          <span className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
            MLflow
          </span>

          <h1 className="text-2xl font-semibold text-ink">Experiments</h1>

          <p className="mt-1 text-sm text-ink-muted">
            Corridas reales del experimento t3-classifier.
          </p>
        </header>

        <div className="mb-5 flex gap-3">
          <select
            value={optimizer}
            onChange={(event) => setOptimizer(event.target.value)}
            className="rounded-lg border border-border bg-surface px-3 py-2 text-sm"
          >
            <option value="all">Todos los optimizers</option>
            <option value="adam">Adam</option>
            <option value="adamw">AdamW</option>
            <option value="sgd">SGD</option>
          </select>

          <span className="rounded-lg bg-canvas px-3 py-2 text-sm text-ink-muted">
            {filtered.length} runs
          </span>
        </div>

        <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-card">
          <table className="w-full text-left text-sm">
            <thead className="bg-canvas">
              <tr>
                <th className="px-4 py-3">Run</th>

                <th className="px-4 py-3">Optimizer</th>

                <th className="px-4 py-3">Epochs</th>

                <th className="px-4 py-3">LR</th>

                <th className="px-4 py-3">Val accuracy</th>

                <th className="px-4 py-3">Val loss</th>

                <th className="px-4 py-3">Dataset</th>

                <th />
              </tr>
            </thead>

            <tbody>
              {filtered.map((run) => (
                <tr key={run.runId} className="border-t border-border">
                  <td className="px-4 py-3">
                    <button
                      type="button"
                      className="font-medium text-accent-lilac hover:underline"
                      onClick={() => setSelectedRun(run)}
                    >
                      {run.runName}
                    </button>

                    <div className="text-xs text-ink-faint">{run.runId}</div>
                  </td>

                  <td className="px-4 py-3">{run.optimizer}</td>

                  <td className="px-4 py-3">{run.epochs ?? "-"}</td>

                  <td className="px-4 py-3">{run.learningRate ?? "-"}</td>

                  <td className="px-4 py-3">
                    {run.bestValAccuracy === null
                      ? "-"
                      : `${(run.bestValAccuracy * 100).toFixed(2)}%`}
                  </td>

                  <td className="px-4 py-3">
                    {run.bestValLoss === null ? "-" : run.bestValLoss.toFixed(4)}
                  </td>

                  <td className="px-4 py-3">{run.datasetVersion ?? "-"}</td>

                  <td className="px-4 py-3">
                    <a
                      href={run.curvesUrl ?? "#"}
                      target="_blank"
                      rel="noreferrer"
                      className="text-accent-lilac hover:underline"
                    >
                      Curves
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {selectedRun && (
          <div className="mt-6 rounded-xl border border-border bg-surface p-5 shadow-card">
            <div className="mb-4 flex items-start justify-between">
              <div>
                <h2 className="font-semibold text-ink">{selectedRun.runName}</h2>

                <p className="mt-1 text-xs text-ink-muted">Run ID: {selectedRun.runId}</p>
              </div>

              <button
                type="button"
                onClick={() => setSelectedRun(null)}
                className="text-sm text-ink-muted"
              >
                Cerrar
              </button>
            </div>

            <div className="grid gap-4 md:grid-cols-3">
              <Metric
                label="Best val accuracy"
                value={
                  selectedRun.bestValAccuracy === null
                    ? "-"
                    : `${(selectedRun.bestValAccuracy * 100).toFixed(2)}%`
                }
              />

              <Metric
                label="Best val loss"
                value={selectedRun.bestValLoss === null ? "-" : selectedRun.bestValLoss.toFixed(4)}
              />

              <Metric label="Best epoch" value={selectedRun.bestEpoch?.toString() ?? "-"} />
            </div>

            {selectedRun.curvesUrl && (
              <div className="mt-5">
                <h3 className="mb-2 font-medium text-ink">Training curves</h3>

                <img
                  src={selectedRun.curvesUrl}
                  alt={`Curvas de ${selectedRun.runName}`}
                  className="max-w-full rounded-lg border border-border"
                />
              </div>
            )}
          </div>
        )}
      </div>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-canvas p-4">
      <p className="text-xs text-ink-muted">{label}</p>

      <strong className="mt-1 block text-lg text-ink">{value}</strong>
    </div>
  );
}
