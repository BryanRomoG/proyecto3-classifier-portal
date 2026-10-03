import { type ReactNode, useEffect, useState } from "react";
import { ApiError, type ApiFieldError } from "@/api/client";
import {
  createTrainingJob,
  getLatestTrainingJob,
  getTrainingJob,
  getTrainingProvenance,
  type TrainingJob,
  type TrainingProvenance,
} from "@/api/training";

// Valores por defecto del entrenador (pipeline/src/dataset_quality/classifier/config.py).
// Las reglas (rangos, optimizadores, ancho de capas) las aplica el servicio trainer.
const DEFAULT_CONFIG = {
  optimizer: "adam",
  batchSize: 32,
  epochs: 15,
  learningRate: 0.001,
  imageSize: 128,
  hiddenLayers: "256",
  dropout: 0.3,
};

/** "512, 128" -> [512, 128]; vacío -> [] (cabeza lineal). */
function parseHiddenLayers(text: string): number[] {
  return text
    .split(",")
    .map((part) => part.trim())
    .filter((part) => part !== "")
    .map(Number);
}

export function TrainingPage() {
  const [config, setConfig] = useState(DEFAULT_CONFIG);
  const [job, setJob] = useState<TrainingJob | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<ApiFieldError[]>([]);
  const [provenance, setProvenance] = useState<TrainingProvenance | null>(null);
  const [provenanceError, setProvenanceError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    getTrainingProvenance()
      .then((info) => {
        if (!cancelled) setProvenance(info);
      })
      .catch((requestError: unknown) => {
        if (!cancelled) {
          setProvenanceError(
            requestError instanceof Error
              ? requestError.message
              : "No se pudo obtener la procedencia."
          );
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function loadLatestJob() {
      try {
        const latest = await getLatestTrainingJob();

        if (!cancelled) {
          setJob(latest);
        }
      } catch {
        // Es normal que todavía no exista ningún entrenamiento.
      }
    }

    void loadLatestJob();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!job) {
      return;
    }

    if (job.status === "completed" || job.status === "failed") {
      return;
    }

    let cancelled = false;

    const interval = window.setInterval(async () => {
      try {
        const updated = await getTrainingJob(job.id);

        if (!cancelled) {
          setJob(updated);
        }
      } catch (requestError) {
        console.error("No se pudo actualizar el entrenamiento.", requestError);
      }
    }, 1000);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [job]);

  async function handleStartTraining() {
    setStarting(true);
    setError(null);
    setFieldErrors([]);

    try {
      const response = await createTrainingJob({
        ...config,
        hiddenLayers: parseHiddenLayers(config.hiddenLayers),
      });

      const createdJob = await getTrainingJob(response.id);

      setJob(createdJob);
    } catch (requestError) {
      const message =
        requestError instanceof Error
          ? requestError.message
          : "No se pudo iniciar el entrenamiento.";

      setError(message);
      if (requestError instanceof ApiError) {
        setFieldErrors(requestError.fieldErrors);
      }
    } finally {
      setStarting(false);
    }
  }

  const isRunning = job?.status === "queued" || job?.status === "running";
  const gateOpen = provenance?.quality_gate_status === "pass" && provenance.test_isolated;
  const errorFor = (field: string) =>
    fieldErrors
      .filter((item) => item.field === field || item.field.startsWith(`${field}.`))
      .map((item) => item.message)
      .join(" · ") || undefined;

  return (
    <PageShell
      title="Training"
      description="Configura y ejecuta una corrida real de entrenamiento."
    >
      <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
        <section className="rounded-2xl border border-border bg-surface p-5 shadow-card">
          <div className="mb-5">
            <h2 className="text-base font-semibold text-ink">Training configuration</h2>

            <p className="mt-1 text-sm text-ink-muted">
              El servicio trainer valida con las reglas del entrenador, revisa la compuerta de
              calidad y ejecuta el entrenamiento real fuera de la petición; el estado se guarda en
              la base de datos.
            </p>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Optimizer" error={errorFor("optimizer")}>
              <select
                value={config.optimizer}
                disabled={isRunning}
                onChange={(event) =>
                  setConfig({
                    ...config,
                    optimizer: event.target.value,
                  })
                }
                className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink"
              >
                <option value="adam">Adam</option>
                <option value="sgd">SGD</option>
                <option value="adamw">AdamW</option>
              </select>
            </Field>

            <Field label="Batch size" error={errorFor("batchSize")}>
              <input
                className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink"
                type="number"
                min="1"
                value={config.batchSize}
                disabled={isRunning}
                onChange={(event) =>
                  setConfig({
                    ...config,
                    batchSize: Number(event.target.value),
                  })
                }
              />
            </Field>

            <Field label="Max epochs" error={errorFor("epochs")}>
              <input
                className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink"
                type="number"
                min="1"
                value={config.epochs}
                disabled={isRunning}
                onChange={(event) =>
                  setConfig({
                    ...config,
                    epochs: Number(event.target.value),
                  })
                }
              />
            </Field>

            <Field label="Learning rate" error={errorFor("learningRate")}>
              <input
                className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink"
                type="number"
                step="0.0001"
                min="0.000001"
                value={config.learningRate}
                disabled={isRunning}
                onChange={(event) =>
                  setConfig({
                    ...config,
                    learningRate: Number(event.target.value),
                  })
                }
              />
            </Field>

            <Field label="Image size" error={errorFor("imageSize")}>
              <input
                className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink"
                type="number"
                min="32"
                value={config.imageSize}
                disabled={isRunning}
                onChange={(event) =>
                  setConfig({
                    ...config,
                    imageSize: Number(event.target.value),
                  })
                }
              />
            </Field>

            <Field
              label="Hidden layers (anchos separados por coma; vacío = lineal)"
              error={errorFor("hiddenLayers")}
            >
              <input
                className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink"
                type="text"
                value={config.hiddenLayers}
                disabled={isRunning}
                onChange={(event) =>
                  setConfig({
                    ...config,
                    hiddenLayers: event.target.value,
                  })
                }
              />
            </Field>

            <Field label="Dropout" error={errorFor("dropout")}>
              <input
                className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink"
                type="number"
                step="0.05"
                min="0"
                max="1"
                value={config.dropout}
                disabled={isRunning}
                onChange={(event) =>
                  setConfig({
                    ...config,
                    dropout: Number(event.target.value),
                  })
                }
              />
            </Field>
          </div>

          <button
            type="button"
            disabled={starting || isRunning || !gateOpen}
            onClick={() => void handleStartTraining()}
            className="mt-5 rounded-lg bg-accent-lilac px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-accent-lilac/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {starting
              ? "Iniciando..."
              : isRunning
                ? "Entrenamiento en ejecución..."
                : "Iniciar entrenamiento"}
          </button>

          {error && (
            <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              {error}
            </div>
          )}
        </section>

        <aside className="rounded-2xl border border-border bg-surface p-5 shadow-card">
          <p className="text-xs font-medium uppercase tracking-wide text-ink-faint">
            Datos de entrenamiento
          </p>

          {provenance ? (
            <dl className="mt-3 space-y-2 text-sm">
              <Row label="Release" value={provenance.dataset_version} />
              <Row
                label="Quality gate"
                value={provenance.quality_gate_status}
                tone={provenance.quality_gate_status === "pass" ? "ok" : "bad"}
              />
              <Row label="Split" value={provenance.manifest_proportions} />
              <Row label="Manifiesto" value={`${provenance.manifest_sha256.slice(0, 12)}…`} />
              <Row label="Clases" value={provenance.classes.join(", ")} />
              {Object.entries(provenance.split_counts).map(([split, counts]) => (
                <Row
                  key={split}
                  label={split}
                  value={Object.entries(counts)
                    .map(([name, count]) => `${name} ${count}`)
                    .join(" · ")}
                />
              ))}
              <Row
                label="Test aislado"
                value={provenance.test_isolated ? "sí" : "no"}
                tone={provenance.test_isolated ? "ok" : "bad"}
              />
            </dl>
          ) : (
            <p className="mt-2 text-sm text-ink-muted">
              {provenanceError ?? "Cargando procedencia del release..."}
            </p>
          )}

          {provenance && !gateOpen && (
            <p className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              No se puede entrenar: la compuerta de calidad no está en pass o el test no está
              aislado.
            </p>
          )}

          <p className="mt-6 text-xs font-medium uppercase tracking-wide text-ink-faint">Estado</p>

          {job ? (
            <div className="mt-3 space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-sm text-ink-muted">Job</span>

                <span className="font-semibold text-ink">#{job.id}</span>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-sm text-ink-muted">Status</span>

                <StatusBadge status={job.status} />
              </div>

              <div>
                <div className="mb-2 flex justify-between text-sm">
                  <span className="text-ink-muted">Progress</span>

                  <strong className="text-ink">{Math.round(job.progress)}%</strong>
                </div>

                <div className="h-3 overflow-hidden rounded-full bg-canvas">
                  <div
                    className="h-full rounded-full bg-accent-lilac transition-all"
                    style={{
                      width: `${Math.min(100, Math.max(0, job.progress))}%`,
                    }}
                  />
                </div>
              </div>

              {job.mlflowRunId && (
                <div className="flex items-center justify-between text-sm">
                  <span className="text-ink-muted">MLflow run</span>
                  <code className="text-xs text-ink">{job.mlflowRunId.slice(0, 12)}</code>
                </div>
              )}

              <div className="flex items-center justify-between text-sm">
                <span className="text-ink-muted">Epoch</span>

                <span className="font-medium text-ink">
                  {job.currentEpoch} / {job.epochs}
                </span>
              </div>
            </div>
          ) : (
            <p className="mt-2 text-sm text-ink-muted">
              Todavía no hay un entrenamiento registrado.
            </p>
          )}
        </aside>
      </div>

      {job && (
        <section className="rounded-2xl border border-border bg-surface p-5 shadow-card">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h2 className="text-base font-semibold text-ink">Training logs</h2>

              <p className="mt-1 text-sm text-ink-muted">
                Los logs se guardan en MariaDB y sobreviven a una recarga de la página.
              </p>
            </div>

            <span className="text-xs text-ink-faint">Job #{job.id}</span>
          </div>

          <pre className="max-h-80 overflow-auto rounded-xl bg-slate-950 p-4 text-xs leading-6 text-slate-100">
            {job.logs || "Esperando logs..."}
          </pre>

          {job.errorMessage && (
            <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              {job.errorMessage}
            </div>
          )}
        </section>
      )}
    </PageShell>
  );
}

function StatusBadge({ status }: { status: TrainingJob["status"] }) {
  const labels: Record<TrainingJob["status"], string> = {
    queued: "En cola",
    running: "Ejecutando",
    completed: "Completado",
    failed: "Falló",
  };

  return (
    <span className="rounded-full bg-status-pending-soft px-2.5 py-1 text-xs font-medium text-status-pending">
      {labels[status]}
    </span>
  );
}

function Field({ label, error, children }: { label: string; error?: string; children: ReactNode }) {
  return (
    // biome-ignore lint/a11y/noLabelWithoutControl: The input or select is supplied as a nested child.
    <label className="flex flex-col gap-1.5 text-sm">
      <span className="font-medium text-ink">{label}</span>

      {children}

      {error && <span className="text-xs text-red-700">{error}</span>}
    </label>
  );
}

function Row({ label, value, tone }: { label: string; value: string; tone?: "ok" | "bad" }) {
  const color = tone === "ok" ? "text-green-700" : tone === "bad" ? "text-red-700" : "text-ink";
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-ink-muted">{label}</dt>
      <dd className={`text-right font-medium ${color}`}>{value}</dd>
    </div>
  );
}

function PageShell({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <main className="flex-1 px-6 py-6 lg:px-10 lg:py-8">
      <div className="mx-auto flex max-w-6xl flex-col gap-6">
        <header>
          <div className="mb-1 inline-flex rounded-full bg-status-pending-soft px-2 py-0.5 text-xs font-medium text-status-pending">
            T3-2.3
          </div>

          <h1 className="text-xl font-semibold text-ink">{title}</h1>

          <p className="mt-1 text-sm text-ink-muted">{description}</p>
        </header>

        {children}
      </div>
    </main>
  );
}
