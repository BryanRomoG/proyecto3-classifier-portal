import { z } from "zod";
import { getJson, postJson } from "./client";

export const trainingJobSchema = z.object({
  id: z.number(),
  status: z.enum(["queued", "running", "completed", "failed"]),
  optimizer: z.string(),
  batchSize: z.number(),
  epochs: z.number(),
  learningRate: z.number(),
  imageSize: z.number(),
  hiddenLayers: z.string(),
  dropout: z.number(),
  trainerJobId: z.string().nullable(),
  mlflowRunId: z.string().nullable(),
  datasetVersion: z.string().nullable(),
  qualityGateStatus: z.string().nullable(),
  manifestSha256: z.string().nullable(),
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

/** Release, compuerta de calidad y manifiesto 70/20/10 que usará el entrenamiento. */
export const trainingProvenanceSchema = z.object({
  dataset_version: z.string(),
  quality_gate_status: z.string(),
  manifest_sha256: z.string(),
  manifest_proportions: z.string(),
  classes: z.array(z.string()),
  split_counts: z.record(z.string(), z.record(z.string(), z.number())),
  test_isolated: z.boolean(),
});

export type TrainingJob = z.infer<typeof trainingJobSchema>;
export type TrainingProvenance = z.infer<typeof trainingProvenanceSchema>;

export interface TrainingConfigInput {
  optimizer: string;
  batchSize: number;
  epochs: number;
  learningRate: number;
  imageSize: number;
  hiddenLayers: number[];
  dropout: number;
  datasetVersion?: string;
}

export async function createTrainingJob(config: TrainingConfigInput) {
  return postJson("/training/jobs", config, createTrainingResponseSchema);
}

export async function getTrainingJob(id: number) {
  return getJson(`/training/jobs/${id}`, trainingJobSchema);
}

export async function getLatestTrainingJob() {
  return getJson("/training/jobs/latest", trainingJobSchema);
}

export async function getTrainingProvenance() {
  return getJson("/training/provenance", trainingProvenanceSchema);
}

/** Releases del Proyecto 2: aprobado (compuerta pass) y con manifiesto 70/20/10 derivado. */
export const trainingReleasesSchema = z.object({
  current_version: z.string().nullable(),
  manifest_dataset_version: z.string().nullable(),
  releases: z.array(
    z.object({
      version: z.string(),
      quality_status: z.string(),
      content_hash: z.string().nullable(),
      released_at: z.string().nullable(),
      approved: z.boolean(),
      has_manifest: z.boolean(),
      trainable: z.boolean(),
    })
  ),
});

export type TrainingReleases = z.infer<typeof trainingReleasesSchema>;

export async function getTrainingReleases() {
  return getJson("/training/releases", trainingReleasesSchema);
}
