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

const versionSchema = z.object({
  version: z.string(),
  runId: z.string(),
  runName: z.string().nullable(),
  checkpointSha256: z.string().nullable(),
  datasetVersion: z.string().nullable(),
  manifestSha256: z.string().nullable(),
  testMetrics: z.record(z.string(), z.number().nullable()).nullable(),
  dependencies: z.record(z.string(), z.string()).nullable(),
  split: z.unknown().nullable(),
  published: z.boolean(),
  bucket: z.string().nullable(),
  s3Uri: z.string(),
  objects: z.array(
    z.object({
      name: z.string(),
      key: z.string(),
      size: z.number(),
      versionId: z.string().nullable(),
      sha256: z.string().nullable(),
    })
  ),
  cardMarkdown: z.string(),
  recordedAt: z.string(),
  verifiedWith: z.string(),
  selected: z.boolean(),
});

export type ModelVersion = z.infer<typeof versionSchema>;

/** Versiones semánticas publicadas en S3 (registros leídos con HeadObject). */
export async function getVersions() {
  return apiRequest("/models/versions", z.object({ versions: z.array(versionSchema) }));
}
