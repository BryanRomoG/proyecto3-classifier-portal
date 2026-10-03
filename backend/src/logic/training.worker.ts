import { getTrainingJob, updateTrainingJob } from '../data/repositories/training.repository.js';
import { getTrainerJob, type TrainerJobView } from '../data/trainer.client.js';

/**
 * El entrenamiento real corre en el servicio `trainer` como proceso aparte, fuera del
 * request HTTP. Aquí solo se refleja su estado en `training_jobs` (MariaDB): cada lectura
 * de un trabajo sin terminar lo sincroniza, así que el progreso, los logs y el error
 * persisten al recargar la página.
 */

const STATUS: Record<TrainerJobView['state'], 'queued' | 'running' | 'completed' | 'failed'> = {
  queued: 'queued',
  running: 'running',
  finished: 'completed',
  failed: 'failed',
};

const MAX_LOG_LENGTH = 16000;

export function trainerViewToJobUpdate(view: TrainerJobView) {
  const logs =
    view.log_tail.length > MAX_LOG_LENGTH ? view.log_tail.slice(-MAX_LOG_LENGTH) : view.log_tail;
  return {
    status: STATUS[view.state],
    currentEpoch: view.epoch,
    progress: view.progress,
    mlflowRunId: view.run_id,
    ...(logs ? { logs } : {}),
    errorMessage: view.error ? view.error.slice(0, 2000) : null,
    startedAt: view.started_at ? new Date(view.started_at) : null,
    finishedAt: view.finished_at ? new Date(view.finished_at) : null,
  };
}

export async function syncTrainingJob(jobId: number): Promise<void> {
  const job = await getTrainingJob(jobId);
  if (!job?.trainerJobId || job.status === 'completed' || job.status === 'failed') {
    return;
  }
  const { status, body } = await getTrainerJob(job.trainerJobId);
  if (status === 404) {
    await updateTrainingJob(jobId, {
      status: 'failed',
      errorMessage: 'El trabajo ya no existe en el servicio trainer.',
    });
    return;
  }
  if (status !== 200) {
    return; // trainer momentáneamente no disponible: se reintenta en la siguiente lectura
  }
  await updateTrainingJob(jobId, trainerViewToJobUpdate(body));
}
