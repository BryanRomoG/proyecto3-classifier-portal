import { z } from 'zod';
import {
  createTrainingJob,
  getLatestTrainingJob,
  getTrainingJob,
} from '../data/repositories/training.repository.js';
import { runTrainingJob } from './training.worker.js';

export const trainingConfigSchema = z.object({
  optimizer: z.enum(['Adam', 'SGD', 'AdamW']),
  batchSize: z.number().int().min(1).max(512),
  epochs: z.number().int().min(1).max(500),
  learningRate: z.number().positive().max(10),
  imageSize: z.number().int().min(32).max(2048),
  dropout: z.number().min(0).max(1),
});

export type TrainingConfig = z.infer<typeof trainingConfigSchema>;

export async function createTrainingRun(input: TrainingConfig): Promise<number> {
  const config = trainingConfigSchema.parse(input);

  const jobId = await createTrainingJob({
    status: 'queued',
    optimizer: config.optimizer,
    batchSize: config.batchSize,
    epochs: config.epochs,
    learningRate: config.learningRate,
    imageSize: config.imageSize,
    dropout: config.dropout,
    currentEpoch: 0,
    progress: 0,
    logs: 'Training job creado y encolado.',
  });

  // IMPORTANTE:
  // No esperamos a que termine.
  // El request HTTP puede responder inmediatamente.
  setImmediate(() => {
    void runTrainingJob(jobId);
  });

  return jobId;
}

export async function getTrainingRun(id: number) {
  return getTrainingJob(id);
}

export async function getLatestTrainingRun() {
  return getLatestTrainingJob();
}
