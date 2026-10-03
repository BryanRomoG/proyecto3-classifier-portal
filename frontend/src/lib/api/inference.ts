import { z } from "zod";
import { imageUploadResponseSchema } from "../../types/schemas";
import { apiRequest, jsonBody } from "./client";

const modelUsedSchema = z.object({
  runId: z.string().min(1),
  runName: z.string().min(1),
  checkpointSha256: z.string().regex(/^[0-9a-f]{64}$/),
});

export const inferenceResultSchema = z.object({
  model: modelUsedSchema,
  predictedClass: z.string().min(1),
  confidence: z.number().min(0).max(1),
  probabilities: z.record(z.string(), z.number().min(0).max(1)),
});

export const queueInferenceResponseSchema = z.object({
  inference: inferenceResultSchema,
  queuedImage: imageUploadResponseSchema,
});

export type InferenceResult = z.infer<typeof inferenceResultSchema>;
export type QueueInferenceResponse = z.infer<typeof queueInferenceResponseSchema>;

function imageForm(file: File): FormData {
  const formData = new FormData();
  formData.append("file", file);
  return formData;
}

export function inferImage(file: File): Promise<InferenceResult> {
  return apiRequest("/inference/image", inferenceResultSchema, {
    method: "POST",
    body: imageForm(file),
  });
}

export function inferCrop(annotationId: number): Promise<InferenceResult> {
  return apiRequest("/inference/crop", inferenceResultSchema, {
    method: "POST",
    ...jsonBody({ annotationId }),
  });
}

export function queueImage(file: File): Promise<QueueInferenceResponse> {
  return apiRequest("/inference/image/queue", queueInferenceResponseSchema, {
    method: "POST",
    body: imageForm(file),
  });
}

export function queueCrop(annotationId: number): Promise<QueueInferenceResponse> {
  return apiRequest("/inference/crop/queue", queueInferenceResponseSchema, {
    method: "POST",
    ...jsonBody({ annotationId }),
  });
}
