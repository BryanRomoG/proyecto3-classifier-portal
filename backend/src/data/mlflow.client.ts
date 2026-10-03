````ts
const MLFLOW_BASE_URL =
  process.env.MLFLOW_TRACKING_URI ?? "http://localhost:5000";

const EXPERIMENT_NAME = "t3-classifier";

interface MlflowExperiment {
  experiment_id: string;
  name: string;
  lifecycle_stage: string;
}

interface MlflowRun {
  info: {
    run_id: string;
    run_name?: string;
    status: string;
    start_time: number;
    end_time?: number;
  };

  data: {
    params: Record<string, string>;
    metrics: Record<string, number>;
    tags: Record<string, string>;
  };
}

interface SearchRunsResponse {
  runs: MlflowRun[];
  next_page_token?: string;
}

async function mlflowRequest<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`${MLFLOW_BASE_URL}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    const text = await response.text();

    throw new Error(
      `MLflow respondió ${response.status}: ${text}`,
    );
  }

  return (await response.json()) as T;
}

export async function getClassifierExperiment(): Promise<MlflowExperiment> {
  const query = new URLSearchParams({
    name: EXPERIMENT_NAME,
  });

  const response = await mlflowRequest<{
    experiments: MlflowExperiment[];
  }>(`/api/2.0/mlflow/experiments/get-by-name?${query}`);

  const experiment = response.experiments?.[0];

  if (!experiment) {
    throw new Error(
      `No existe el experimento de MLflow "${EXPERIMENT_NAME}".`,
    );
  }

  return experiment;
}

export async function getClassifierRuns(): Promise<MlflowRun[]> {
  const experiment = await getClassifierExperiment();

  const response = await mlflowRequest<SearchRunsResponse>(
    "/api/2.0/mlflow/runs/search",
    {
      method: "POST",
      body: JSON.stringify({
        experiment_ids: [experiment.experiment_id],
        filter:
          "attributes.status = 'FINISHED'",
        order_by: [
          "attributes.start_time DESC",
        ],
        max_results: 100,
      }),
    },
  );

  return response.runs;
}

export async function getClassifierRun(
  runId: string,
): Promise<MlflowRun> {
  const query = new URLSearchParams({
    run_id: runId,
  });

  const response = await mlflowRequest<{
    run: MlflowRun;
  }>(
    `/api/2.0/mlflow/runs/get?${query}`,
  );

  return response.run;
}

export function getArtifactUrl(
  runId: string,
  artifactPath: string,
): string {
  const query = new URLSearchParams({
    run_id: runId,
    path: artifactPath,
  });

  return `${MLFLOW_BASE_URL}/get-artifact?${query}`;
}

export async function getArtifact(
  runId: string,
  artifactPath: string,
): Promise<Response> {
  const response = await fetch(
    getArtifactUrl(runId, artifactPath),
  );

  if (!response.ok) {
    throw new Error(
      `No se pudo obtener el artefacto ${artifactPath}.`,
    );
  }

  return response;
}

---

# 2. Servicio de Experiments

Crea:

```text
backend/src/logic/experiments.service.ts
````

````ts
import {
  getArtifactUrl,
  getClassifierRun,
  getClassifierRuns,
} from "../data/mlflow.client.js";

export interface ExperimentRow {
  runId: string;
  runName: string;
  status: string;
  optimizer: string;
  batchSize: string | null;
  epochs: string | null;
  learningRate: string | null;
  imageSize: string | null;
  dropout: string | null;
  bestValAccuracy: number | null;
  bestValLoss: number | null;
  bestEpoch: number | null;
  datasetVersion: string | null;
  startTime: number;
  endTime: number | null;
  curvesUrl: string | null;
}

function value(
  params: Record<string, string>,
  key: string,
): string | null {
  return params[key] ?? null;
}

function metric(
  metrics: Record<string, number>,
  key: string,
): number | null {
  return metrics[key] ?? null;
}

function toRow(run: {
  info: {
    run_id: string;
    run_name?: string;
    status: string;
    start_time: number;
    end_time?: number;
  };
  data: {
    params: Record<string, string>;
    metrics: Record<string, number>;
    tags: Record<string, string>;
  };
}): ExperimentRow {
  return {
    runId: run.info.run_id,
    runName: run.info.run_name ?? run.info.run_id,
    status: run.info.status,

    optimizer: value(run.data.params, "optimizer") ?? "-",
    batchSize: value(run.data.params, "batch_size"),
    epochs: value(run.data.params, "max_epochs"),
    learningRate: value(run.data.params, "learning_rate"),
    imageSize: value(run.data.params, "image_size"),
    dropout: value(run.data.params, "dropout"),

    bestValAccuracy: metric(
      run.data.metrics,
      "best_val_accuracy",
    ),

    bestValLoss: metric(
      run.data.metrics,
      "best_val_loss",
    ),

    bestEpoch: metric(
      run.data.metrics,
      "best_epoch",
    ),

    datasetVersion:
      run.data.tags.dataset_version ?? null,

    startTime: run.info.start_time,
    endTime: run.info.end_time ?? null,

    curvesUrl: getArtifactUrl(
      run.info.run_id,
      "curves.png",
    ),
  };
}

export async function listExperiments(): Promise<ExperimentRow[]> {
  const runs = await getClassifierRuns();

  return runs.map(toRow);
}

export async function getExperiment(
  runId: string,
): Promise<ExperimentRow> {
  const run = await getClassifierRun(runId);

  return toRow(run);
}

---

# 3. Servicio de Evaluation

Aquí hay una regla importante del ticket:

> **No enseñar resultados del test antes de cerrar la selección.**

Por eso el endpoint no debería simplemente devolver `test_evaluation.json` siempre.

Crea:

```text
backend/src/logic/evaluation.service.ts
````

````ts
import fs from "node:fs/promises";
import path from "node:path";

const REPORTS_DIR = path.resolve(
  process.cwd(),
  "../pipeline/reports/classifier",
);

interface SelectionReport {
  run_id: string;
  run_name: string;
  selected_at: string;
  test_opened: boolean;
  selected_metric_value: number;
  valid_runs: number;
}

interface TestEvaluation {
  accuracy: number;
  macro_f1: number;
  correct: number;
  total: number;
  classes: string[];
  dataset_version: string;
  run_id: string;
  selected_at: string;
  evaluated_at: string;
  confusion_matrix: {
    labels: string[];
    matrix: number[][];
    rows: string;
    columns: string;
  };
  per_class: Record<
    string,
    {
      precision: number;
      recall: number;
      f1: number;
      support: number;
      predicted: number;
    }
  >;
  examples: Record<
    string,
    {
      correct: Array<{
        annotation_id: number;
        confidence: number;
        correct: boolean;
        predicted_label: string;
        relative_path: string;
        source_image_id: number;
        true_label: string;
      }>;
      errors: Array<{
        annotation_id: number;
        confidence: number;
        correct: boolean;
        predicted_label: string;
        relative_path: string;
        source_image_id: number;
        true_label: string;
      }>;
    }
  >;
}

async function readJson<T>(filename: string): Promise<T> {
  const content = await fs.readFile(
    path.join(REPORTS_DIR, filename),
    "utf8",
  );

  return JSON.parse(content) as T;
}

export async function getSelection() {
  return readJson<SelectionReport>(
    "selection.json",
  );
}

export async function getEvaluation() {
  const selection = await getSelection();

  /*
   * Protección del criterio T3-3.5:
   * el test solamente se expone después de que la selección
   * fue cerrada.
   */
  if (!selection.test_opened) {
    return {
      locked: true,
      message:
        "La evaluación final permanece bloqueada hasta cerrar la selección del modelo.",
      selection: {
        runId: selection.run_id,
        runName: selection.run_name,
        selectedAt: selection.selected_at,
      },
    };
  }

  const evaluation =
    await readJson<TestEvaluation>(
      "test_evaluation.json",
    );

  return {
    locked: false,
    selection: {
      runId: selection.run_id,
      runName: selection.run_name,
      selectedAt: selection.selected_at,
    },
    evaluation,
  };
}

---

# 4. Servicio de Models

Aquí hacemos algo importante para **T3-3.7**: la versión seleccionada no es solamente texto de UI.

El backend guarda cuál `run_id` está seleccionado y el endpoint de descarga obtiene **el `model.pt` de ese run**.

Crea:

```text
backend/src/logic/models.service.ts
````

````ts
import fs from "node:fs/promises";
import path from "node:path";

import {
  getArtifact,
  getArtifactUrl,
  getClassifierRun,
  getClassifierRuns,
} from "../data/mlflow.client.js";

const REPORTS_DIR = path.resolve(
  process.cwd(),
  "../pipeline/reports/classifier",
);

const SELECTED_MODEL_FILE = path.join(
  REPORTS_DIR,
  "selected-model.json",
);

interface SelectedModel {
  runId: string;
  selectedAt: string;
}

async function readSelectedModel(): Promise<SelectedModel | null> {
  try {
    const content = await fs.readFile(
      SELECTED_MODEL_FILE,
      "utf8",
    );

    return JSON.parse(content) as SelectedModel;
  } catch {
    return null;
  }
}

async function writeSelectedModel(
  model: SelectedModel,
): Promise<void> {
  await fs.writeFile(
    SELECTED_MODEL_FILE,
    JSON.stringify(model, null, 2),
    "utf8",
  );
}

export async function listModels() {
  const runs = await getClassifierRuns();
  const selected = await readSelectedModel();

  return Promise.all(
    runs.map(async (run) => {
      const model = await getClassifierRun(
        run.info.run_id,
      );

      return {
        runId: run.info.run_id,
        runName:
          run.info.run_name ??
          run.info.run_id,

        version:
          run.data.tags.model_version ??
          run.data.tags.grid_run ??
          run.info.run_id.slice(0, 8),

        datasetVersion:
          run.data.tags.dataset_version ??
          null,

        accuracy:
          run.data.metrics.best_val_accuracy ??
          null,

        status: run.info.status,

        selected:
          selected?.runId === run.info.run_id,

        modelUrl: getArtifactUrl(
          run.info.run_id,
          "model.pt",
        ),

        curvesUrl: getArtifactUrl(
          run.info.run_id,
          "curves.png",
        ),

        checkpointSha256:
          run.data.tags.checkpoint_sha256 ??
          null,

        optimizer:
          run.data.params.optimizer ??
          null,

        learningRate:
          run.data.params.learning_rate ??
          null,
      };
    }),
  );
}

export async function selectModel(
  runId: string,
) {
  const run = await getClassifierRun(runId);

  if (run.info.status !== "FINISHED") {
    throw new Error(
      "Solo se puede seleccionar un run terminado.",
    );
  }

  await writeSelectedModel({
    runId,
    selectedAt: new Date().toISOString(),
  });

  return {
    runId,
    runName:
      run.info.run_name ?? runId,
    artifactUrl: getArtifactUrl(
      runId,
      "model.pt",
    ),
  };
}

export async function getSelectedModel() {
  const selected = await readSelectedModel();

  if (!selected) {
    return null;
  }

  const run = await getClassifierRun(
    selected.runId,
  );

  return {
    runId: selected.runId,

    runName:
      run.info.run_name ??
      selected.runId,

    artifactUrl: getArtifactUrl(
      selected.runId,
      "model.pt",
    ),

    selectedAt: selected.selectedAt,

    datasetVersion:
      run.data.tags.dataset_version ??
      null,

    checkpointSha256:
      run.data.tags.checkpoint_sha256 ??
      null,
  };
}

export async function downloadSelectedModel(
  runId: string,
) {
  const response = await getArtifact(
    runId,
    "model.pt",
  );

  return response;
}

---

# 5. Exportar los servicios

Modifica:

```text
backend/src/logic/index.ts
````

Agrega:

```ts
export {
  getExperiment,
  listExperiments,
} from "./experiments.service.js";

export {
  getEvaluation,
  getSelection,
} from "./evaluation.service.js";

export {
  downloadSelectedModel,
  getSelectedModel,
  listModels,
  selectModel,
} from "./models.service.js";
```

---

# 6. Agregar rutas al `server.ts`

En los imports de:

```text
backend/src/ui/server.ts
```

agrega:

```ts
getExperiment,
listExperiments,
getEvaluation,
getSelection,
listModels,
selectModel,
getSelectedModel,
downloadSelectedModel,
```

Después agrega estas rutas.

### Experiments

```ts
app.get("/experiments", async (_req, res) => {
  try {
    const experiments = await listExperiments();

    res.status(200).json({
      experiments,
    });
  } catch (error) {
    sendError(
      res,
      error,
      "No se pudieron obtener los experimentos.",
    );
  }
});

app.get("/experiments/:runId", async (req, res) => {
  try {
    const experiment = await getExperiment(
      req.params.runId,
    );

    res.status(200).json(experiment);
  } catch (error) {
    sendError(
      res,
      error,
      "No se pudo obtener el run.",
    );
  }
});
```

### Evaluation

```ts
app.get("/evaluation", async (_req, res) => {
  try {
    const evaluation = await getEvaluation();

    res.status(200).json(evaluation);
  } catch (error) {
    sendError(
      res,
      error,
      "No se pudo obtener la evaluación.",
    );
  }
});

app.get("/evaluation/selection", async (_req, res) => {
  try {
    const selection = await getSelection();

    res.status(200).json(selection);
  } catch (error) {
    sendError(
      res,
      error,
      "No se pudo obtener la selección.",
    );
  }
});
```

### Models

```ts
app.get("/models", async (_req, res) => {
  try {
    const models = await listModels();

    res.status(200).json({
      models,
    });
  } catch (error) {
    sendError(
      res,
      error,
      "No se pudieron obtener los modelos.",
    );
  }
});

app.get("/models/selected", async (_req, res) => {
  try {
    const model = await getSelectedModel();

    if (!model) {
      res.status(404).json({
        error: "No hay un modelo seleccionado.",
      });
      return;
    }

    res.status(200).json(model);
  } catch (error) {
    sendError(
      res,
      error,
      "No se pudo obtener el modelo seleccionado.",
    );
  }
});

app.post("/models/:runId/select", async (req, res) => {
  try {
    const model = await selectModel(
      req.params.runId,
    );

    res.status(200).json(model);
  } catch (error) {
    sendError(
      res,
      error,
      "No se pudo seleccionar el modelo.",
    );
  }
});

app.get("/models/:runId/download", async (req, res) => {
  try {
    const response =
      await downloadSelectedModel(
        req.params.runId,
      );

    const contentType =
      response.headers.get("content-type") ??
      "application/octet-stream";

    res.setHeader(
      "Content-Type",
      contentType,
    );

    res.setHeader(
      "Content-Disposition",
      `attachment; filename="model-${req.params.runId}.pt"`,
    );

    const buffer = Buffer.from(
      await response.arrayBuffer(),
    );

    res.status(200).send(buffer);
  } catch (error) {
    sendError(
      res,
      error,
      "No se pudo descargar el modelo.",
    );
  }
});
```

---

# 7. Frontend: API de Experiments

Crea:

```text
frontend/src/lib/api/experiments.ts
```

````ts
import { z } from "zod";
import { apiRequest } from "./client";

const experimentSchema = z.object({
  runId: z.string(),
  runName: z.string(),
  status: z.string(),
  optimizer: z.string(),
  batchSize: z.string().nullable(),
  epochs: z.string().nullable(),
  learningRate: z.string().nullable(),
  imageSize: z.string().nullable(),
  dropout: z.string().nullable(),
  bestValAccuracy: z.number().nullable(),
  bestValLoss: z.number().nullable(),
  bestEpoch: z.number().nullable(),
  datasetVersion: z.string().nullable(),
  startTime: z.number(),
  endTime: z.number().nullable(),
  curvesUrl: z.string().nullable(),
});

const experimentsResponseSchema = z.object({
  experiments: z.array(experimentSchema),
});

export type Experiment = z.infer<
  typeof experimentSchema
>;

export async function getExperiments() {
  return apiRequest(
    "/experiments",
    experimentsResponseSchema,
  );
}

export async function getExperiment(
  runId: string,
) {
  return apiRequest(
    `/experiments/${runId}`,
    experimentSchema,
  );
}

---

# 8. Página Experiments

Crea/reemplaza:

```text
frontend/src/pages/classifier/Experiments.tsx
````

````tsx
import { useEffect, useMemo, useState } from "react";
import {
  getExperiments,
  type Experiment,
} from "@/lib/api/experiments";

export function ExperimentsPage() {
  const [experiments, setExperiments] = useState<
    Experiment[]
  >([]);

  const [optimizer, setOptimizer] =
    useState("all");

  const [selectedRun, setSelectedRun] =
    useState<Experiment | null>(null);

  const [loading, setLoading] =
    useState(true);

  const [error, setError] =
    useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const response =
          await getExperiments();

        setExperiments(
          response.experiments,
        );
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : "No se pudieron cargar los experiments.",
        );
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
      (experiment) =>
        experiment.optimizer.toLowerCase() ===
        optimizer.toLowerCase(),
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
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-700">
          {error}
        </div>
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

          <h1 className="text-2xl font-semibold text-ink">
            Experiments
          </h1>

          <p className="mt-1 text-sm text-ink-muted">
            Corridas reales del experimento
            t3-classifier.
          </p>
        </header>

        <div className="mb-5 flex gap-3">
          <select
            value={optimizer}
            onChange={(event) =>
              setOptimizer(event.target.value)
            }
            className="rounded-lg border border-border bg-surface px-3 py-2 text-sm"
          >
            <option value="all">
              Todos los optimizers
            </option>
            <option value="adam">
              Adam
            </option>
            <option value="adamw">
              AdamW
            </option>
            <option value="sgd">
              SGD
            </option>
          </select>

          <span className="rounded-lg bg-canvas px-3 py-2 text-sm text-ink-muted">
            {filtered.length} runs
          </span>
        </div>

        <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-card">
          <table className="w-full text-left text-sm">
            <thead className="bg-canvas">
              <tr>
                <th className="px-4 py-3">
                  Run
                </th>

                <th className="px-4 py-3">
                  Optimizer
                </th>

                <th className="px-4 py-3">
                  Epochs
                </th>

                <th className="px-4 py-3">
                  LR
                </th>

                <th className="px-4 py-3">
                  Val accuracy
                </th>

                <th className="px-4 py-3">
                  Val loss
                </th>

                <th className="px-4 py-3">
                  Dataset
                </th>

                <th />
              </tr>
            </thead>

            <tbody>
              {filtered.map((run) => (
                <tr
                  key={run.runId}
                  className="border-t border-border"
                >
                  <td className="px-4 py-3">
                    <button
                      type="button"
                      className="font-medium text-accent-lilac hover:underline"
                      onClick={() =>
                        setSelectedRun(run)
                      }
                    >
                      {run.runName}
                    </button>

                    <div className="text-xs text-ink-faint">
                      {run.runId}
                    </div>
                  </td>

                  <td className="px-4 py-3">
                    {run.optimizer}
                  </td>

                  <td className="px-4 py-3">
                    {run.epochs ?? "-"}
                  </td>

                  <td className="px-4 py-3">
                    {run.learningRate ?? "-"}
                  </td>

                  <td className="px-4 py-3">
                    {run.bestValAccuracy ===
                    null
                      ? "-"
                      : `${(
                          run.bestValAccuracy *
                          100
                        ).toFixed(2)}%`}
                  </td>

                  <td className="px-4 py-3">
                    {run.bestValLoss === null
                      ? "-"
                      : run.bestValLoss.toFixed(
                          4,
                        )}
                  </td>

                  <td className="px-4 py-3">
                    {run.datasetVersion ??
                      "-"}
                  </td>

                  <td className="px-4 py-3">
                    <a
                      href={
                        run.curvesUrl ?? "#"
                      }
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
                <h2 className="font-semibold text-ink">
                  {selectedRun.runName}
                </h2>

                <p className="mt-1 text-xs text-ink-muted">
                  Run ID:{" "}
                  {selectedRun.runId}
                </p>
              </div>

              <button
                type="button"
                onClick={() =>
                  setSelectedRun(null)
                }
                className="text-sm text-ink-muted"
              >
                Cerrar
              </button>
            </div>

            <div className="grid gap-4 md:grid-cols-3">
              <Metric
                label="Best val accuracy"
                value={
                  selectedRun.bestValAccuracy ===
                  null
                    ? "-"
                    : `${(
                        selectedRun.bestValAccuracy *
                        100
                      ).toFixed(2)}%`
                }
              />

              <Metric
                label="Best val loss"
                value={
                  selectedRun.bestValLoss ===
                  null
                    ? "-"
                    : selectedRun.bestValLoss.toFixed(
                        4,
                      )
                }
              />

              <Metric
                label="Best epoch"
                value={
                  selectedRun.bestEpoch?.toString() ??
                  "-"
                }
              />
            </div>

            {selectedRun.curvesUrl && (
              <div className="mt-5">
                <h3 className="mb-2 font-medium text-ink">
                  Training curves
                </h3>

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

function Metric({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-lg bg-canvas p-4">
      <p className="text-xs text-ink-muted">
        {label}
      </p>

      <strong className="mt-1 block text-lg text-ink">
        {value}
      </strong>
    </div>
  );
}

---

# 9. API de Evaluation

Crea:

```text
frontend/src/lib/api/evaluation.ts
````

````ts
import { z } from "zod";
import { apiRequest } from "./client";

const evaluationSchema = z.object({
  accuracy: z.number(),
  macro_f1: z.number(),
  correct: z.number(),
  total: z.number(),
  classes: z.array(z.string()),
  dataset_version: z.string(),
  run_id: z.string(),
  selected_at: z.string(),
  evaluated_at: z.string(),
  confusion_matrix: z.object({
    labels: z.array(z.string()),
    matrix: z.array(z.array(z.number())),
    rows: z.string(),
    columns: z.string(),
  }),
  per_class: z.record(
    z.string(),
    z.object({
      precision: z.number(),
      recall: z.number(),
      f1: z.number(),
      support: z.number(),
      predicted: z.number(),
    }),
  ),
  examples: z.record(
    z.string(),
    z.object({
      correct: z.array(z.object({
        annotation_id: z.number(),
        confidence: z.number(),
        correct: z.boolean(),
        predicted_label: z.string(),
        relative_path: z.string(),
        source_image_id: z.number(),
        true_label: z.string(),
      })),
      errors: z.array(z.object({
        annotation_id: z.number(),
        confidence: z.number(),
        correct: z.boolean(),
        predicted_label: z.string(),
        relative_path: z.string(),
        source_image_id: z.number(),
        true_label: z.string(),
      })),
    }),
  ),
});

const responseSchema = z.discriminatedUnion(
  "locked",
  [
    z.object({
      locked: z.literal(true),
      message: z.string(),
      selection: z.object({
        runId: z.string(),
        runName: z.string(),
        selectedAt: z.string(),
      }),
    }),

    z.object({
      locked: z.literal(false),
      selection: z.object({
        runId: z.string(),
        runName: z.string(),
        selectedAt: z.string(),
      }),
      evaluation: evaluationSchema,
    }),
  ],
);

export type EvaluationResponse =
  z.infer<typeof responseSchema>;

export async function getEvaluation() {
  return apiRequest(
    "/evaluation",
    responseSchema,
  );
}

---

# 10. Página Evaluation

Crea/reemplaza:

```text
frontend/src/pages/classifier/Evaluation.tsx
````

````tsx
import { useEffect, useState } from "react";
import {
  getEvaluation,
  type EvaluationResponse,
} from "@/lib/api/evaluation";

export function EvaluationPage() {
  const [data, setData] =
    useState<EvaluationResponse | null>(
      null,
    );

  const [error, setError] =
    useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        setData(await getEvaluation());
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : "No se pudo cargar la evaluación.",
        );
      }
    }

    void load();
  }, []);

  if (error) {
    return (
      <main className="p-8">
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-700">
          {error}
        </div>
      </main>
    );
  }

  if (!data) {
    return (
      <main className="p-8">
        Cargando evaluación...
      </main>
    );
  }

  if (data.locked) {
    return (
      <main className="flex-1 p-8">
        <div className="mx-auto max-w-4xl">
          <div className="rounded-2xl border border-amber-200 bg-amber-50 p-8">
            <p className="text-xs font-semibold uppercase tracking-wide text-amber-700">
              Test bloqueado
            </p>

            <h1 className="mt-2 text-2xl font-semibold text-amber-950">
              La evaluación final todavía no está disponible
            </h1>

            <p className="mt-3 text-sm text-amber-800">
              Primero debe cerrarse la selección del
              modelo candidato. Los resultados del test
              permanecen ocultos hasta ese momento.
            </p>

            <div className="mt-5 rounded-lg bg-white/70 p-4 text-sm">
              <div>
                Candidato seleccionado:
                <strong className="ml-2">
                  {data.selection.runName}
                </strong>
              </div>

              <div className="mt-1">
                Run ID:
                <code className="ml-2">
                  {data.selection.runId}
                </code>
              </div>
            </div>
          </div>
        </div>
      </main>
    );
  }

  const evaluation = data.evaluation;

  return (
    <main className="flex-1 p-8">
      <div className="mx-auto max-w-7xl">
        <header className="mb-6">
          <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
            Final evaluation
          </p>

          <h1 className="text-2xl font-semibold text-ink">
            Evaluation
          </h1>

          <p className="mt-1 text-sm text-ink-muted">
            Evaluación final del candidato seleccionado.
          </p>
        </header>

        <section className="mb-6 rounded-xl border border-border bg-surface p-5 shadow-card">
          <p className="text-xs text-ink-muted">
            Candidato seleccionado
          </p>

          <h2 className="mt-1 font-semibold text-ink">
            {data.selection.runName}
          </h2>

          <code className="mt-1 block text-xs text-ink-muted">
            {data.selection.runId}
          </code>
        </section>

        <section className="grid gap-4 md:grid-cols-4">
          <Metric
            label="Accuracy"
            value={`${(
              evaluation.accuracy * 100
            ).toFixed(2)}%`}
          />

          <Metric
            label="Macro F1"
            value={`${(
              evaluation.macro_f1 * 100
            ).toFixed(2)}%`}
          />

          <Metric
            label="Correct"
            value={`${evaluation.correct}/${evaluation.total}`}
          />

          <Metric
            label="Dataset"
            value={evaluation.dataset_version}
          />
        </section>

        <section className="mt-6 rounded-xl border border-border bg-surface p-5 shadow-card">
          <h2 className="mb-4 font-semibold text-ink">
            Confusion matrix
          </h2>

          <table className="border-collapse text-center text-sm">
            <tbody>
              <tr>
                <th className="border border-border p-3" />
                {evaluation.confusion_matrix.labels.map(
                  (label) => (
                    <th
                      key={label}
                      className="border border-border p-3"
                    >
                      Pred. {label}
                    </th>
                  ),
                )}
              </tr>

              {evaluation.confusion_matrix.matrix.map(
                (row, rowIndex) => (
                  <tr
                    key={
                      evaluation.confusion_matrix
                        .labels[rowIndex]
                    }
                  >
                    <th className="border border-border p-3">
                      Real{" "}
                      {
                        evaluation
                          .confusion_matrix
                          .labels[rowIndex]
                      }
                    </th>

                    {row.map((value, columnIndex) => (
                      <td
                        key={`${rowIndex}-${columnIndex}`}
                        className="border border-border p-4 font-semibold"
                      >
                        {value}
                      </td>
                    ))}
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </section>

        <section className="mt-6 rounded-xl border border-border bg-surface p-5 shadow-card">
          <h2 className="mb-4 font-semibold text-ink">
            Metrics by class
          </h2>

          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="py-3">
                  Class
                </th>
                <th>Precision</th>
                <th>Recall</th>
                <th>F1</th>
                <th>Support</th>
              </tr>
            </thead>

            <tbody>
              {Object.entries(
                evaluation.per_class,
              ).map(([className, metrics]) => (
                <tr
                  key={className}
                  className="border-b border-border"
                >
                  <td className="py-3 font-medium">
                    {className}
                  </td>

                  <td>
                    {(metrics.precision * 100).toFixed(
                      2,
                    )}
                    %
                  </td>

                  <td>
                    {(metrics.recall * 100).toFixed(
                      2,
                    )}
                    %
                  </td>

                  <td>
                    {(metrics.f1 * 100).toFixed(2)}%
                  </td>

                  <td>
                    {metrics.support}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="mt-6 rounded-xl border border-border bg-surface p-5 shadow-card">
          <h2 className="mb-4 font-semibold text-ink">
            Test examples
          </h2>

          <div className="grid gap-6 md:grid-cols-2">
            {Object.entries(
              evaluation.examples,
            ).map(([className, examples]) => (
              <div key={className}>
                <h3 className="mb-3 font-medium">
                  {className}
                </h3>

                <div className="space-y-2">
                  {examples.correct
                    .slice(0, 5)
                    .map((example) => (
                      <div
                        key={example.annotation_id}
                        className="rounded-lg bg-canvas p-3 text-sm"
                      >
                        <div className="font-medium">
                          {example.predicted_label}
                        </div>

                        <div className="text-xs text-ink-muted">
                          Confidence:{" "}
                          {(
                            example.confidence *
                            100
                          ).toFixed(2)}
                          %
                        </div>

                        <div className="text-xs text-ink-faint">
                          {example.relative_path}
                        </div>
                      </div>
                    ))}
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </main>
  );
}

function Metric({
  label,
  value,
}: {
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-surface p-5 shadow-card">
      <p className="text-xs text-ink-muted">
        {label}
      </p>

      <strong className="mt-1 block text-xl text-ink">
        {value}
      </strong>
    </div>
  );
}
---

# 11. API de Models

Crea:

```text
frontend/src/lib/api/models.ts
````

````ts
import { z } from "zod";
import {
  apiRequest,
  jsonBody,
} from "./client";

const modelSchema = z.object({
  runId: z.string(),
  runName: z.string(),
  version: z.string(),
  datasetVersion: z.string().nullable(),
  accuracy: z.number().nullable(),
  status: z.string(),
  selected: z.boolean(),
  modelUrl: z.string(),
  curvesUrl: z.string(),
  checkpointSha256: z.string().nullable(),
  optimizer: z.string().nullable(),
  learningRate: z.string().nullable(),
});

const modelsResponseSchema = z.object({
  models: z.array(modelSchema),
});

const selectedModelSchema = z.object({
  runId: z.string(),
  runName: z.string(),
  artifactUrl: z.string(),
  selectedAt: z.string(),
  datasetVersion: z.string().nullable(),
  checkpointSha256: z.string().nullable(),
});

export type Model = z.infer<
  typeof modelSchema
>;

export async function getModels() {
  return apiRequest(
    "/models",
    modelsResponseSchema,
  );
}

export async function selectModel(
  runId: string,
) {
  return apiRequest(
    `/models/${runId}/select`,
    selectedModelSchema,
    {
      method: "POST",
      ...jsonBody({}),
    },
  );
}

export async function getSelectedModel() {
  return apiRequest(
    "/models/selected",
    selectedModelSchema,
  );
}

---

# 12. Página Models

Reemplaza:

```text
frontend/src/pages/classifier/Models.tsx
````

````tsx
import { useEffect, useState } from "react";
import {
  getModels,
  selectModel,
  type Model,
} from "@/lib/api/models";

export function ModelsPage() {
  const [models, setModels] = useState<Model[]>(
    [],
  );

  const [loading, setLoading] =
    useState(true);

  const [error, setError] =
    useState<string | null>(null);

  const [selecting, setSelecting] =
    useState<string | null>(null);

  async function loadModels() {
    try {
      const response = await getModels();

      setModels(response.models);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "No se pudieron cargar los modelos.",
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadModels();
  }, []);

  async function handleSelect(
    runId: string,
  ) {
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
      setError(
        err instanceof Error
          ? err.message
          : "No se pudo seleccionar el modelo.",
      );
    } finally {
      setSelecting(null);
    }
  }

  if (loading) {
    return (
      <main className="p-8">
        Cargando modelos...
      </main>
    );
  }

  return (
    <main className="flex-1 p-8">
      <div className="mx-auto max-w-7xl">
        <header className="mb-6">
          <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
            Model Registry
          </p>

          <h1 className="text-2xl font-semibold text-ink">
            Models
          </h1>

          <p className="mt-1 text-sm text-ink-muted">
            Versiones publicadas y trazabilidad de los
            artefactos de MLflow.
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
                <th className="px-4 py-3">
                  Version
                </th>

                <th className="px-4 py-3">
                  Run ID
                </th>

                <th className="px-4 py-3">
                  Dataset
                </th>

                <th className="px-4 py-3">
                  Val accuracy
                </th>

                <th className="px-4 py-3">
                  Optimizer
                </th>

                <th className="px-4 py-3">
                  Status
                </th>

                <th className="px-4 py-3">
                  Actions
                </th>
              </tr>
            </thead>

            <tbody>
              {models.map((model) => (
                <tr
                  key={model.runId}
                  className="border-t border-border"
                >
                  <td className="px-4 py-4">
                    <div className="font-medium">
                      {model.version}
                    </div>

                    <div className="text-xs text-ink-muted">
                      {model.runName}
                    </div>

                    {model.selected && (
                      <span className="mt-1 inline-block rounded-full bg-status-success-soft px-2 py-0.5 text-xs font-medium text-status-success">
                        Seleccionado
                      </span>
                    )}
                  </td>

                  <td className="px-4 py-4">
                    <code className="text-xs">
                      {model.runId}
                    </code>
                  </td>

                  <td className="px-4 py-4">
                    {model.datasetVersion ?? "-"}
                  </td>

                  <td className="px-4 py-4">
                    {model.accuracy === null
                      ? "-"
                      : `${(
                          model.accuracy * 100
                        ).toFixed(2)}%`}
                  </td>

                  <td className="px-4 py-4">
                    {model.optimizer ?? "-"}
                  </td>

                  <td className="px-4 py-4">
                    {model.status}
                  </td>

                  <td className="px-4 py-4">
                    <div className="flex gap-2">
                      <button
                        type="button"
                        disabled={
                          model.selected ||
                          selecting !== null
                        }
                        onClick={() =>
                          void handleSelect(
                            model.runId,
                          )
                        }
                        className="rounded-lg bg-accent-lilac px-3 py-2 text-xs font-medium text-white disabled:opacity-50"
                      >
                        {selecting ===
                        model.runId
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
          <h2 className="font-semibold text-ink">
            Trazabilidad
          </h2>

          <p className="mt-2 text-sm text-ink-muted">
            Cada modelo mantiene la relación:
          </p>

          <div className="mt-4 flex flex-wrap items-center gap-2 text-sm">
            <span className="rounded-lg bg-canvas px-3 py-2">
              Dataset
            </span>

            <span>→</span>

            <span className="rounded-lg bg-canvas px-3 py-2">
              Run ID
            </span>

            <span>→</span>

            <span className="rounded-lg bg-canvas px-3 py-2">
              model.pt
            </span>

            <span>→</span>

            <span className="rounded-lg bg-canvas px-3 py-2">
              Inference
            </span>
          </div>
        </div>
      </div>
    </main>
  );
}

---

# 13. Agregar las tres páginas al `App.tsx`

En tu `frontend/src/App.tsx` agrega:

```ts
import { ExperimentsPage } from "@/pages/classifier/Experiments";
import { EvaluationPage } from "@/pages/classifier/Evaluation";
import { ModelsPage } from "@/pages/classifier/Models";
````

Y dentro de `<Routes>`:

```tsx
<Route
  path="/experiments"
  element={
    <AppLayout>
      <ExperimentsPage />
    </AppLayout>
  }
/>

<Route
  path="/evaluation"
  element={
    <AppLayout>
      <EvaluationPage />
    </AppLayout>
  }
/>

<Route
  path="/models"
  element={
    <AppLayout>
      <ModelsPage />
    </AppLayout>
  }
/>
```

---

# 14. Variable de MLflow

En el backend `.env` agrega:

```env
MLFLOW_TRACKING_URI=http://localhost:5000
```

Si estás usando Docker Compose, el backend debe usar:

```env
MLFLOW_TRACKING_URI=http://mlflow:5000
```

porque dentro de Docker `localhost` sería el propio contenedor del backend.

Tu `docker-compose.yml` ya tiene MLflow en:

```text
mlflow:5000
```

y el proyecto ya tiene el experimento `t3-classifier` con las corridas y artefactos reales.

---

# 15. IMPORTANTE para T3-3.7

Hay una cosa que quiero que tengas clara.

Cuando haces:

```text
Models
   ↓
Seleccionar r03
```

**no solamente cambia el texto de "Seleccionado".**

El backend guarda:

```json
{
  "runId": "44725ac6b1704fed8b06bc4f846651d8",
  "selectedAt": "..."
}
```

y el artefacto real queda:

```text
MLflow
└── t3-classifier
    └── 44725ac6b1704fed8b06bc4f846651d8
        └── artifacts
            └── model.pt
```

Si después seleccionas otro:

```text
Models
   ↓
Seleccionar r02
```

el `runId` cambia y:

```text
/model.pt
```

se obtiene del **nuevo run**.

Eso es lo que permite cumplir:

> "Cambiar la versión seleccionada cambia el artefacto cargado, no solo el texto en pantalla."

---

## 16. Qué puedes demostrar para cada ticket

### T3-3.4 — Experiments

Entra:

```text
/experiments
```

Debe aparecer:

```text
r01-base
r02-sgd
r03-adamw-lr1e-4
r04-batch64
r05-batch16
r07-img96
r08-img160-dropout0
r09-linear-head
r10-deep-head-dropout05
r11-epochs4
```

Y al abrir:

```text
r03-adamw-lr1e-4
```

aparece el mismo:

```text
run_id:
44725ac6b1704fed8b06bc4f846651d8
```

y sus curvas salen del artefacto de ese mismo run.

---

### T3-3.5 — Evaluation

Entra:

```text
/evaluation
```

La página identifica:

```text
Candidato seleccionado
r03-adamw-lr1e-4

Run ID
44725ac6b1704fed8b06bc4f846651d8
```

y después muestra:

* Accuracy
* Macro F1
* Confusion Matrix
* métricas por clase
* ejemplos reales del test

Pero solamente cuando:

```json
"test_opened": true
```

Esto coincide con la estructura actual de `selection.json`.

---

### T3-3.7 — Models

Entra:

```text
/models
```

Puedes:

```text
Seleccionar
Descargar
```

y cada modelo mantiene:

```text
Dataset version
      ↓
Run ID
      ↓
model.pt
```

Así tienes trazabilidad real hasta MLflow.

---

### Una corrección importante respecto a lo que te pasé antes

En el código anterior de T3-2.3 te propuse crear una tabla `training_jobs` en MariaDB. **No la vuelvas a crear copiando aquel código sin revisar el estado actual del repo**, porque el ZIP que acabas de subir es una versión diferente y no contiene todavía esos cambios. Para estos tickets, primero integra T3-2.3 en esta rama y después añade T3-3.4/3.5/3.7 encima.

También, para **T3-3.4**, si tu profesor exige literalmente que las curvas se obtengan de MLflow y no de `pipeline/reports/classifier/mlflow_runs.json`, usa el cliente anterior: las curvas salen de `/get-artifact` con el `run_id`, no de datos hardcodeados.
