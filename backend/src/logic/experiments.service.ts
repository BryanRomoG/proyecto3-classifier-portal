import { getArtifactUrl, getClassifierRun, getClassifierRuns } from '../data/mlflow.client.js';

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

function value(params: Record<string, string>, key: string): string | null {
  return params[key] ?? null;
}

function metric(metrics: Record<string, number>, key: string): number | null {
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

    optimizer: value(run.data.params, 'optimizer') ?? '-',
    batchSize: value(run.data.params, 'batch_size'),
    epochs: value(run.data.params, 'max_epochs'),
    learningRate: value(run.data.params, 'learning_rate'),
    imageSize: value(run.data.params, 'image_size'),
    dropout: value(run.data.params, 'dropout'),

    bestValAccuracy: metric(run.data.metrics, 'best_val_accuracy'),

    bestValLoss: metric(run.data.metrics, 'best_val_loss'),

    bestEpoch: metric(run.data.metrics, 'best_epoch'),

    datasetVersion: run.data.tags.dataset_version ?? null,

    startTime: run.info.start_time,
    endTime: run.info.end_time ?? null,

    curvesUrl: getArtifactUrl(run.info.run_id, 'curves.png'),
  };
}

export async function listExperiments(): Promise<ExperimentRow[]> {
  const runs = await getClassifierRuns();

  return runs.map(toRow);
}

export async function getExperiment(runId: string): Promise<ExperimentRow> {
  const run = await getClassifierRun(runId);

  return toRow(run);
}
