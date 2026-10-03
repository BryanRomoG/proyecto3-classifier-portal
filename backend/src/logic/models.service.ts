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

interface ReleaseRecord {
  version: string;
  bucket: string | null;
  s3_uri: string;
  run_id: string;
  run_name: string | null;
  checkpoint_sha256: string | null;
  dataset: { dataset_version?: string; manifest_sha256?: string } | null;
  test_metrics: Record<string, number | null> | null;
  dependencies: Record<string, string> | null;
  split: Record<string, unknown> | null;
  objects: Record<
    string,
    { key: string; size: number; version_id: string | null; sha256: string | null }
  >;
  card_markdown: string;
  recorded_at: string;
  verified_with: string;
}

const RELEASES_DIR = path.resolve(process.cwd(), env.CLASSIFIER_REPORTS_DIR, 'releases');

/**
 * Versiones semánticas publicadas del modelo (T3-3.7 / rúbrica 5.3, 6.4). Cada una sale de un
 * registro creado con `release-record`, que lee de S3 cada objeto del paquete (HeadObject);
 * una versión cuyos objetos no están en el bucket nunca llega a tener registro, así que esta
 * lista no puede mostrar como publicado algo inexistente. No son runs de MLflow: cada versión
 * apunta al run del que salió.
 */
export async function listVersions() {
  let files: string[] = [];
  try {
    files = (await fs.readdir(RELEASES_DIR)).filter((name) => name.endsWith('.json'));
  } catch {
    return [];
  }
  const selected = await readSelectedModel();
  const records = await Promise.all(
    files.map(
      async (name) =>
        JSON.parse(await fs.readFile(path.join(RELEASES_DIR, name), 'utf8')) as ReleaseRecord,
    ),
  );
  return records
    .sort((a, b) => b.version.localeCompare(a.version, undefined, { numeric: true }))
    .map((record) => ({
      version: record.version,
      runId: record.run_id,
      runName: record.run_name,
      checkpointSha256: record.checkpoint_sha256,
      datasetVersion: record.dataset?.dataset_version ?? null,
      manifestSha256: record.dataset?.manifest_sha256 ?? null,
      testMetrics: record.test_metrics,
      dependencies: record.dependencies,
      split: record.split,
      published: Object.keys(record.objects).length > 0,
      bucket: record.bucket,
      s3Uri: record.s3_uri,
      objects: Object.entries(record.objects).map(([name, object]) => ({
        name,
        key: object.key,
        size: object.size,
        versionId: object.version_id,
        sha256: object.sha256,
      })),
      cardMarkdown: record.card_markdown,
      recordedAt: record.recorded_at,
      verifiedWith: record.verified_with,
      selected: selected?.runId === record.run_id,
    }));
}
