import { z } from "zod";
import { apiRequest } from "./client";

const experimentSchema = z.object({
  runId: z.string(),
  runName: z.string(),
  status: z.string(),
  /** Válida según las reglas de `list-runs`; null si el backend no pudo saberlo. */
  valid: z.boolean().nullable(),
  invalidReasons: z.array(z.string()),
  optimizer: z.string(),
  batchSize: z.string().nullable(),
  epochs: z.string().nullable(),
  learningRate: z.string().nullable(),
  imageSize: z.string().nullable(),
  hiddenLayers: z.string().nullable(),
  dropout: z.string().nullable(),
  bestValAccuracy: z.number().nullable(),
  bestValLoss: z.number().nullable(),
  bestEpoch: z.number().nullable(),
  stoppedEpoch: z.number().nullable(),
  datasetVersion: z.string().nullable(),
  manifestSha256: z.string().nullable(),
  startTime: z.number(),
  endTime: z.number().nullable(),
  /** Ruta del backend (`/experiments/<id>/curves`); se resuelve con `resolveBackendUrl`. */
  curvesUrl: z.string(),
});

const experimentsResponseSchema = z.object({
  experiments: z.array(experimentSchema),
});

export type Experiment = z.infer<typeof experimentSchema>;

export async function getExperiments() {
  return apiRequest("/experiments", experimentsResponseSchema);
}

export async function getExperiment(runId: string) {
  return apiRequest(`/experiments/${runId}`, experimentSchema);
}
