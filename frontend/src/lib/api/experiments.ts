
import { z } from "zod";
import { apiRequest } from "./client";

const experimentSchema = z.object({
  runId: z.string(),
  runName: z.string(),
  status: z.string(),
  optimizer: z.string(),
  batchSize: z.string().nullable(),
  epochs: z.string().nullable(),
  learningRate: z.string().nullable(),
  imageSize: z.string().nullable(),
  dropout: z.string().nullable(),
  bestValAccuracy: z.number().nullable(),
  bestValLoss: z.number().nullable(),
  bestEpoch: z.number().nullable(),
  datasetVersion: z.string().nullable(),
  startTime: z.number(),
  endTime: z.number().nullable(),
  curvesUrl: z.string().nullable(),
});

const experimentsResponseSchema = z.object({
  experiments: z.array(experimentSchema),
});

export type Experiment = z.infer<
  typeof experimentSchema
>;

export async function getExperiments() {
  return apiRequest(
    "/experiments",
    experimentsResponseSchema,
  );
}

export async function getExperiment(
  runId: string,
) {
  return apiRequest(
    `/experiments/${runId}`,
    experimentSchema,
  );
}

