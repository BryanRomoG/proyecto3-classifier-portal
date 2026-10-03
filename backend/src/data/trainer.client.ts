import { env } from '../config/env.js';

/**
 * Cliente del servicio `trainer` (pipeline/src/dataset_quality/classifier/jobs_app.py),
 * que entrena de verdad con el mismo código del clasificador.
 *
 * Devuelve el status HTTP junto al cuerpo para que la capa Logic decida: un 422 (config
 * inválida) o 409 (compuerta de calidad / manifiesto) se rechazan antes de crear el
 * trabajo en la base de datos.
 */

export interface TrainerConfig {
  optimizer: string;
  batch_size: number;
  max_epochs: number;
  learning_rate: number;
  image_size: number;
  hidden_layers: number[];
  dropout: number;
}

export interface TrainerFieldError {
  field: string;
  message: string;
}

export interface TrainerProvenance {
  dataset_version: string;
  quality_gate_status: string;
  manifest_sha256: string;
  manifest_proportions: string;
  classes: string[];
  split_counts: Record<string, Record<string, number>>;
  test_isolated: boolean;
}

export interface TrainerJobView {
  job_id: string;
  state: 'queued' | 'running' | 'finished' | 'failed';
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  run_id: string | null;
  epoch: number;
  max_epochs: number;
  progress: number;
  last_metrics: Record<string, number> | null;
  best_epoch: number | null;
  best_val_accuracy: number | null;
  error: string | null;
  log_tail: string;
  provenance: TrainerProvenance | null;
}

export interface TrainerResponse<T> {
  status: number;
  body: T & { error?: string; errors?: TrainerFieldError[] };
}

async function trainerRequest<T>(path: string, init?: RequestInit): Promise<TrainerResponse<T>> {
  let response: Response;
  try {
    response = await fetch(`${env.TRAINER_URL}${path}`, init);
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    throw new Error(`No se pudo conectar con el servicio trainer (${env.TRAINER_URL}): ${reason}`);
  }
  const text = await response.text();
  const body = (text ? JSON.parse(text) : {}) as TrainerResponse<T>['body'];
  return { status: response.status, body };
}

export function createTrainerJob(config: TrainerConfig) {
  return trainerRequest<TrainerJobView>('/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ config }),
  });
}

export function getTrainerJob(jobId: string) {
  return trainerRequest<TrainerJobView>(`/jobs/${encodeURIComponent(jobId)}`);
}

export function getTrainerProvenance() {
  return trainerRequest<TrainerProvenance>('/provenance');
}
