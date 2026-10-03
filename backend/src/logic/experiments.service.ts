import { getArtifact, getClassifierRun, getClassifierRuns } from '../data/mlflow.client.js';
import { getTrainerRuns, type TrainerRunValidity } from '../data/trainer.client.js';

export interface ExperimentRow {
  runId: string;
  runName: string;
  status: string;
  /** Válida según las reglas de `list-runs` (servicio trainer); null si no se pudo saber. */
  valid: boolean | null;
  invalidReasons: string[];
  optimizer: string;
  batchSize: string | null;
  epochs: string | null;
  learningRate: string | null;
  imageSize: string | null;
  hiddenLayers: string | null;
  dropout: string | null;
  bestValAccuracy: number | null;
  bestValLoss: number | null;
  bestEpoch: number | null;
  stoppedEpoch: number | null;
  datasetVersion: string | null;
  manifestSha256: string | null;
  startTime: number;
  endTime: number | null;
  /** Ruta del backend (no la URL interna de MLflow, que el navegador no resuelve). */
  curvesUrl: string;
}

interface MlflowRunLike {
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

function value(params: Record<string, string>, key: string): string | null {
  return params[key] ?? null;
}

function metric(metrics: Record<string, number>, key: string): number | null {
  return metrics[key] ?? null;
}

export function curvesPath(runId: string): string {
  return `/experiments/${encodeURIComponent(runId)}/curves`;
}

export function toRow(run: MlflowRunLike, validity?: TrainerRunValidity): ExperimentRow {
  return {
    runId: run.info.run_id,
    runName: run.info.run_name ?? run.info.run_id,
    status: run.info.status,
    valid: validity ? validity.valid : null,
    invalidReasons: validity?.invalid_reasons ?? [],

    optimizer: value(run.data.params, 'optimizer') ?? '-',
    batchSize: value(run.data.params, 'batch_size'),
    epochs: value(run.data.params, 'max_epochs'),
    learningRate: value(run.data.params, 'learning_rate'),
    imageSize: value(run.data.params, 'image_size'),
    hiddenLayers: value(run.data.params, 'hidden_layers'),
    dropout: value(run.data.params, 'dropout'),

    bestValAccuracy: metric(run.data.metrics, 'best_val_accuracy'),
    bestValLoss: metric(run.data.metrics, 'best_val_loss'),
    bestEpoch: metric(run.data.metrics, 'best_epoch'),
    stoppedEpoch: metric(run.data.metrics, 'stopped_epoch'),

    datasetVersion: run.data.tags.dataset_version ?? null,
    manifestSha256: run.data.tags.manifest_sha256 ?? null,

    startTime: run.info.start_time,
    endTime: run.info.end_time ?? null,

    curvesUrl: curvesPath(run.info.run_id),
  };
}

async function validityByRun(): Promise<Map<string, TrainerRunValidity>> {
  try {
    const { status, body } = await getTrainerRuns();
    if (status !== 200) {
      return new Map();
    }
    return new Map(body.runs.map((row) => [row.run_id, row]));
  } catch {
    return new Map(); // trainer no disponible: validez desconocida (null), nunca inventada
  }
}

export async function listExperiments(): Promise<ExperimentRow[]> {
  const [runs, validity] = await Promise.all([
    getClassifierRuns({ finishedOnly: false }),
    validityByRun(),
  ]);

  return runs.map((run) => toRow(run, validity.get(run.info.run_id)));
}

export async function getExperiment(runId: string): Promise<ExperimentRow> {
  const [run, validity] = await Promise.all([getClassifierRun(runId), validityByRun()]);

  return toRow(run, validity.get(runId));
}

/** PNG de curvas de train/val de una corrida, leído de MLflow por el backend. */
export async function getRunCurves(runId: string): Promise<{ contentType: string; body: Buffer }> {
  const response = await getArtifact(runId, 'curves.png');
  return {
    contentType: response.headers.get('content-type') ?? 'image/png',
    body: Buffer.from(await response.arrayBuffer()),
  };
}
