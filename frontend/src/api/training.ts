import { z } from "zod";
import { getJson, postJson } from "./client";

export const trainingJobSchema = z.object({
  id: z.number(),
  status: z.enum([
    "queued",
    "running",
    "completed",
    "failed",
  ]),
  optimizer: z.string(),
  batchSize: z.number(),
  epochs: z.number(),
  learningRate: z.number(),
  imageSize: z.number(),
  dropout: z.number(),
  currentEpoch: z.number(),
  progress: z.number(),
  logs: z.string(),
  errorMessage: z.string().nullable(),
  createdAt: z.string(),
  startedAt: z.string().nullable(),
  finishedAt: z.string().nullable(),
});

export const createTrainingResponseSchema = z.object({
  id: z.number(),
  status: z.enum(["queued", "running"]),
});

export type TrainingJob = z.infer<typeof trainingJobSchema>;

export async function createTrainingJob(config: {
  optimizer: string;
  batchSize: number;
  epochs: number;
  learningRate: number;
  imageSize: number;
  dropout: number;
}) {
  return postJson(
    "/training/jobs",
    config,
    createTrainingResponseSchema,
  );
}

export async function getTrainingJob(id: number) {
  return getJson(
    `/training/jobs/${id}`,
    trainingJobSchema,
  );
}

export async function getLatestTrainingJob() {
  return getJson(
    "/training/jobs/latest",
    trainingJobSchema,
  );
}
