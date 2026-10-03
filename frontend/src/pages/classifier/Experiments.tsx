import { useEffect, useMemo, useState } from "react";
import { type Experiment, getExperiments } from "@/lib/api/experiments";
import { resolveBackendUrl } from "@/lib/api/images";

type SortKey =
  | "runName"
  | "optimizer"
  | "batchSize"
  | "epochs"
  | "learningRate"
  | "imageSize"
  | "hiddenLayers"
  | "dropout"
  | "bestValAccuracy"
  | "bestValLoss"
  | "bestEpoch";

const COLUMNS: { key: SortKey; label: string }[] = [
  { key: "runName", label: "Run" },
  { key: "optimizer", label: "Optimizer" },
  { key: "batchSize", label: "Batch" },
  { key: "epochs", label: "Max epochs" },
  { key: "learningRate", label: "LR" },
  { key: "imageSize", label: "Imagen" },
  { key: "hiddenLayers", label: "Capas ocultas" },
  { key: "dropout", label: "Dropout" },
  { key: "bestValAccuracy", label: "Val acc" },
  { key: "bestValLoss", label: "Val loss" },
  { key: "bestEpoch", label: "Mejor época" },
];

const NUMERIC: SortKey[] = [
  "batchSize",
  "epochs",
  "learningRate",
  "imageSize",
  "dropout",
  "bestValAccuracy",
  "bestValLoss",
  "bestEpoch",
];

function sortValue(run: Experiment, key: SortKey): number | string {
  const raw = run[key];
  if (raw === null || raw === undefined) return NUMERIC.includes(key) ? -Infinity : "";
  return NUMERIC.includes(key) ? Number(raw) : String(raw);
}

function format(value: number | null, digits = 4): string {
  return value === null ? "—" : value.toFixed(digits);
}

export function ExperimentsPage() {
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [optimizer, setOptimizer] = useState("all");
  const [validity, setValidity] = useState("valid");
  const [sortKey, setSortKey] = useState<SortKey>("bestValAccuracy");
  const [descending, setDescending] = useState(true);
  const [compare, setCompare] = useState<string[]>([]);
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

  const optimizers = useMemo(
    () => [...new Set(experiments.map((run) => run.optimizer))].sort(),
    [experiments]
  );
  const validCount = experiments.filter((run) => run.valid === true).length;

  const shown = useMemo(() => {
    const filtered = experiments.filter(
      (run) =>
        (optimizer === "all" || run.optimizer === optimizer) &&
        (validity === "all" || run.valid === true)
    );
    return [...filtered].sort((a, b) => {
      const left = sortValue(a, sortKey);
      const right = sortValue(b, sortKey);
      const order = left < right ? -1 : left > right ? 1 : 0;
      return descending ? -order : order;
    });
  }, [experiments, optimizer, validity, sortKey, descending]);

  const compared = experiments.filter((run) => compare.includes(run.runId));

  function toggleSort(key: SortKey) {
    if (key === sortKey) {
      setDescending(!descending);
    } else {
      setSortKey(key);
      setDescending(NUMERIC.includes(key));
    }
  }

  function toggleCompare(runId: string) {
    setCompare((current) =>
      current.includes(runId) ? current.filter((id) => id !== runId) : [...current, runId]
    );
  }

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
            Corridas reales del experimento t3-classifier: {validCount} válidas de{" "}
            {experiments.length} (mismas reglas que <code>list-runs</code>).
          </p>
        </header>

        <div className="mb-4 flex flex-wrap items-center gap-3">
          <select
            value={validity}
            onChange={(event) => setValidity(event.target.value)}
            className="rounded-lg border border-border bg-surface px-3 py-2 text-sm"
          >
            <option value="valid">Solo válidas</option>
            <option value="all">Todas (incluye inválidas)</option>
          </select>

          <select
            value={optimizer}
            onChange={(event) => setOptimizer(event.target.value)}
            className="rounded-lg border border-border bg-surface px-3 py-2 text-sm"
          >
            <option value="all">Todos los optimizers</option>
            {optimizers.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>

          <span className="text-sm text-ink-muted">{shown.length} runs</span>
          <span className="text-xs text-ink-faint">
            Clic en una columna para ordenar · marca casillas para comparar
          </span>
        </div>

        <div className="overflow-x-auto rounded-xl border border-border bg-surface shadow-card">
          <table className="w-full text-left text-sm">
            <thead className="bg-canvas text-xs uppercase text-ink-muted">
              <tr>
                <th className="px-3 py-3">Comparar</th>
                <th className="px-3 py-3">Estado</th>
                {COLUMNS.map((column) => (
                  <th key={column.key} className="px-3 py-3">
                    <button
                      type="button"
                      onClick={() => toggleSort(column.key)}
                      className="uppercase hover:text-ink"
                    >
                      {column.label}
                      {sortKey === column.key ? (descending ? " ▼" : " ▲") : ""}
                    </button>
                  </th>
                ))}
                <th />
              </tr>
            </thead>

            <tbody>
              {shown.map((run) => (
                <tr key={run.runId} className="border-t border-border">
                  <td className="px-3 py-3">
                    <input
                      type="checkbox"
                      aria-label={`Comparar ${run.runName}`}
                      checked={compare.includes(run.runId)}
                      onChange={() => toggleCompare(run.runId)}
                    />
                  </td>
                  <td className="px-3 py-3">
                    <ValidityBadge run={run} />
                  </td>
                  <td className="px-3 py-3 font-medium text-ink">
                    {run.runName}
                    <code className="block text-xs text-ink-faint">{run.runId.slice(0, 8)}</code>
                  </td>
                  <td className="px-3 py-3">{run.optimizer}</td>
                  <td className="px-3 py-3">{run.batchSize ?? "—"}</td>
                  <td className="px-3 py-3">{run.epochs ?? "—"}</td>
                  <td className="px-3 py-3">{run.learningRate ?? "—"}</td>
                  <td className="px-3 py-3">{run.imageSize ?? "—"}</td>
                  <td className="px-3 py-3">{run.hiddenLayers ?? "—"}</td>
                  <td className="px-3 py-3">{run.dropout ?? "—"}</td>
                  <td className="px-3 py-3">{format(run.bestValAccuracy)}</td>
                  <td className="px-3 py-3">{format(run.bestValLoss)}</td>
                  <td className="px-3 py-3">{run.bestEpoch ?? "—"}</td>
                  <td className="px-3 py-3">
                    <button
                      type="button"
                      onClick={() => setSelectedRun(run)}
                      className="text-accent-lilac hover:underline"
                    >
                      Ver
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {compared.length >= 2 && (
          <section className="mt-6 overflow-x-auto rounded-xl border border-border bg-surface p-5 shadow-card">
            <h2 className="mb-3 font-semibold text-ink">Comparación ({compared.length} runs)</h2>
            <table className="text-sm">
              <tbody>
                {COLUMNS.map((column) => (
                  <tr key={column.key} className="border-b border-border">
                    <th className="py-2 pr-6 text-left text-ink-muted">{column.label}</th>
                    {compared.map((run) => {
                      const value = run[column.key];
                      return (
                        <td key={run.runId} className="py-2 pr-6">
                          {typeof value === "number" ? format(value) : (value ?? "—")}
                        </td>
                      );
                    })}
                  </tr>
                ))}
                <tr>
                  <th className="py-2 pr-6 text-left text-ink-muted">Curvas</th>
                  {compared.map((run) => (
                    <td key={run.runId} className="py-2 pr-6">
                      <img
                        src={resolveBackendUrl(run.curvesUrl)}
                        alt={`Curvas ${run.runName}`}
                        className="w-64 rounded border border-border"
                        loading="lazy"
                      />
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </section>
        )}

        {selectedRun && (
          <section className="mt-6 rounded-xl border border-border bg-surface p-5 shadow-card">
            <div className="flex items-start justify-between">
              <div>
                <h2 className="font-semibold text-ink">{selectedRun.runName}</h2>
                <code className="text-xs text-ink-muted">{selectedRun.runId}</code>
              </div>
              <ValidityBadge run={selectedRun} />
            </div>

            {selectedRun.invalidReasons.length > 0 && (
              <p className="mt-2 text-sm text-red-700">
                No cuenta: {selectedRun.invalidReasons.join("; ")}
              </p>
            )}

            <dl className="mt-4 grid gap-2 text-sm sm:grid-cols-3">
              <Detail label="Estado MLflow" value={selectedRun.status} />
              <Detail label="Dataset" value={selectedRun.datasetVersion ?? "—"} />
              <Detail
                label="Manifiesto"
                value={
                  selectedRun.manifestSha256 ? `${selectedRun.manifestSha256.slice(0, 12)}…` : "—"
                }
              />
              <Detail label="Mejor época" value={String(selectedRun.bestEpoch ?? "—")} />
              <Detail label="Época de parada" value={String(selectedRun.stoppedEpoch ?? "—")} />
              <Detail label="Val accuracy" value={format(selectedRun.bestValAccuracy)} />
            </dl>

            <div className="mt-4">
              <p className="mb-2 text-sm font-medium text-ink">Curvas de train / validación</p>
              <img
                src={resolveBackendUrl(selectedRun.curvesUrl)}
                alt={`Curvas de ${selectedRun.runName}`}
                className="max-w-full rounded-lg border border-border"
              />
            </div>
          </section>
        )}
      </div>
    </main>
  );
}

function ValidityBadge({ run }: { run: Experiment }) {
  if (run.valid === null) {
    return <span className="text-xs text-ink-faint">sin dato</span>;
  }
  return run.valid ? (
    <span className="rounded-full bg-green-50 px-2 py-0.5 text-xs font-medium text-green-700">
      válida
    </span>
  ) : (
    <span
      title={run.invalidReasons.join("; ")}
      className="rounded-full bg-red-50 px-2 py-0.5 text-xs font-medium text-red-700"
    >
      inválida
    </span>
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
