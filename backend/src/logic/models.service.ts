import fs from 'node:fs/promises';
import path from 'node:path';

import { env } from '../config/env.js';
import { getArtifact, getClassifierRun, getClassifierRuns } from '../data/mlflow.client.js';
import { ValidationError } from './errors.js';
import { curvesPath } from './experiments.service.js';

/** Rutas del backend: el navegador no resuelve la URL interna de MLflow (mlflow:5000). */
function downloadPath(runId: string): string {
  return `/models/${encodeURIComponent(runId)}/download`;
}

const SELECTED_MODEL_FILE = path.resolve(process.cwd(), env.SELECTED_MODEL_PATH);

interface SelectedModel {
  runId: string;
  selectedAt: string;
}

async function readSelectedModel(): Promise<SelectedModel | null> {
  try {
    const content = await fs.readFile(SELECTED_MODEL_FILE, 'utf8');

    return JSON.parse(content) as SelectedModel;
  } catch {
    return null;
  }
}

async function writeSelectedModel(model: SelectedModel): Promise<void> {
  await fs.mkdir(path.dirname(SELECTED_MODEL_FILE), { recursive: true });
  await fs.writeFile(SELECTED_MODEL_FILE, JSON.stringify(model, null, 2), 'utf8');
}

export async function listModels() {
  const runs = await getClassifierRuns();
  const selected = await readSelectedModel();

  return runs.map((run) => {
    return {
      runId: run.info.run_id,
      runName: run.info.run_name ?? run.info.run_id,

      version: run.data.tags.model_version ?? run.data.tags.grid_run ?? run.info.run_id.slice(0, 8),

      datasetVersion: run.data.tags.dataset_version ?? null,

      accuracy: run.data.metrics.best_val_accuracy ?? null,

      status: run.info.status,

      selected: selected?.runId === run.info.run_id,

      modelUrl: downloadPath(run.info.run_id),

      curvesUrl: curvesPath(run.info.run_id),

      checkpointSha256: run.data.tags.checkpoint_sha256 ?? null,

      optimizer: run.data.params.optimizer ?? null,

      learningRate: run.data.params.learning_rate ?? null,
    };
  });
}

export async function selectModel(runId: string) {
  const run = await getClassifierRun(runId);

  if (run.info.status !== 'FINISHED') {
    throw new ValidationError(
      `El run ${runId} está ${run.info.status}: solo se puede usar un run terminado (FINISHED).`,
    );
  }

  await writeSelectedModel({
    runId,
    selectedAt: new Date().toISOString(),
  });

  return {
    runId,
    runName: run.info.run_name ?? runId,
    artifactUrl: downloadPath(runId),
  };
}

export async function getSelectedModel() {
  const selected = await readSelectedModel();

  if (!selected) {
    return null;
  }

  const run = await getClassifierRun(selected.runId);

  return {
    runId: selected.runId,

    runName: run.info.run_name ?? selected.runId,

    artifactUrl: downloadPath(selected.runId),

    selectedAt: selected.selectedAt,

    datasetVersion: run.data.tags.dataset_version ?? null,

    checkpointSha256: run.data.tags.checkpoint_sha256 ?? null,
  };
}

export async function downloadSelectedModel(runId: string) {
  const response = await getArtifact(runId, 'model.pt');

  return response;
}
