import { getTrainingJob, updateTrainingJob } from '../data/repositories/training.repository.js';

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

async function appendLog(jobId: number, message: string): Promise<void> {
  const job = await getTrainingJob(jobId);

  if (!job) {
    return;
  }

  const timestamp = new Date().toISOString();

  const newLogs = [job.logs, `[${timestamp}] ${message}`].filter(Boolean).join('\n');

  await updateTrainingJob(jobId, {
    logs: newLogs,
  });
}

export async function runTrainingJob(jobId: number): Promise<void> {
  const job = await getTrainingJob(jobId);

  if (!job) {
    return;
  }

  try {
    await updateTrainingJob(jobId, {
      status: 'running',
      startedAt: new Date(),
      currentEpoch: 0,
      progress: 0,
    });

    await appendLog(jobId, `Iniciando entrenamiento con ${job.optimizer}.`);

    await appendLog(
      jobId,
      `Batch size=${job.batchSize}, learning rate=${job.learningRate}, image size=${job.imageSize}.`,
    );

    for (let epoch = 1; epoch <= job.epochs; epoch += 1) {
      /*
       * Simula el trabajo de entrenamiento real.
       *
       * En el siguiente ticket esta sección puede sustituirse
       * por la ejecución real del pipeline/classifier.
       *
       * Lo importante para T3-2.3 es que el trabajo ocurre
       * después de responder el HTTP y su estado se persiste.
       */
      await sleep(1000);

      const progress = Math.round((epoch / job.epochs) * 100);

      await updateTrainingJob(jobId, {
        currentEpoch: epoch,
        progress,
      });

      await appendLog(jobId, `Epoch ${epoch}/${job.epochs} completado. Progress=${progress}%.`);
    }

    await appendLog(jobId, 'Entrenamiento completado correctamente.');

    await updateTrainingJob(jobId, {
      status: 'completed',
      progress: 100,
      currentEpoch: job.epochs,
      finishedAt: new Date(),
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Error desconocido';

    await appendLog(jobId, `ERROR: ${message}`);

    await updateTrainingJob(jobId, {
      status: 'failed',
      errorMessage: message,
      finishedAt: new Date(),
    });
  }
}
