
import { z } from "zod";
import { apiRequest } from "./client";

const evaluationSchema = z.object({
  accuracy: z.number(),
  macro_f1: z.number(),
  correct: z.number(),
  total: z.number(),
  classes: z.array(z.string()),
  dataset_version: z.string(),
  run_id: z.string(),
  selected_at: z.string(),
  evaluated_at: z.string(),
  confusion_matrix: z.object({
    labels: z.array(z.string()),
    matrix: z.array(z.array(z.number())),
    rows: z.string(),
    columns: z.string(),
  }),
  per_class: z.record(
    z.string(),
    z.object({
      precision: z.number(),
      recall: z.number(),
      f1: z.number(),
      support: z.number(),
      predicted: z.number(),
    }),
  ),
  examples: z.record(
    z.string(),
    z.object({
      correct: z.array(z.object({
        annotation_id: z.number(),
        confidence: z.number(),
        correct: z.boolean(),
        predicted_label: z.string(),
        relative_path: z.string(),
        source_image_id: z.number(),
        true_label: z.string(),
      })),
      errors: z.array(z.object({
        annotation_id: z.number(),
        confidence: z.number(),
        correct: z.boolean(),
        predicted_label: z.string(),
        relative_path: z.string(),
        source_image_id: z.number(),
        true_label: z.string(),
      })),
    }),
  ),
});

const responseSchema = z.discriminatedUnion(
  "locked",
  [
    z.object({
      locked: z.literal(true),
      message: z.string(),
      selection: z.object({
        runId: z.string(),
        runName: z.string(),
        selectedAt: z.string(),
      }),
    }),

    z.object({
      locked: z.literal(false),
      selection: z.object({
        runId: z.string(),
        runName: z.string(),
        selectedAt: z.string(),
      }),
      evaluation: evaluationSchema,
    }),
  ],
);

export type EvaluationResponse =
  z.infer<typeof responseSchema>;

export async function getEvaluation() {
  return apiRequest(
    "/evaluation",
    responseSchema,
  );

