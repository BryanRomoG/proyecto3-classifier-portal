import { z } from "zod";
import { apiRequest, jsonBody } from "./client";

const modelSchema = z.object({
  runId: z.string(),
  runName: z.string(),
  version: z.string(),
  datasetVersion: z.string().nullable(),
  accuracy: z.number().nullable(),
  status: z.string(),
  selected: z.boolean(),
  modelUrl: z.string(),
  curvesUrl: z.string(),
  checkpointSha256: z.string().nullable(),
  optimizer: z.string().nullable(),
  learningRate: z.string().nullable(),
});

const modelsResponseSchema = z.object({
  models: z.array(modelSchema),
});

const selectedModelSchema = z.object({
  runId: z.string(),
  runName: z.string(),
  artifactUrl: z.string(),
  selectedAt: z.string(),
  datasetVersion: z.string().nullable(),
  checkpointSha256: z.string().nullable(),
});

export type Model = z.infer<typeof modelSchema>;

export async function getModels() {
  return apiRequest("/models", modelsResponseSchema);
}

export async function selectModel(runId: string) {
  return apiRequest(`/models/${runId}/select`, selectedModelSchema, {
    method: "POST",
    ...jsonBody({}),
  });
}

export async function getSelectedModel() {
  return apiRequest("/models/selected", selectedModelSchema);
}
