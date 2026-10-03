import { z } from "zod";

const SelectionSchema = z.object({
  run_id: z.string(),
  run_name: z.string(),
  selected_at: z.string(),
  test_opened: z.boolean(),
  selected_metric_value: z.number(),
  valid_runs: z.number(),
});

export type Selection = z.infer<typeof SelectionSchema>;

export async function getSelection(): Promise<Selection> {
  const response = await fetch("/api/evaluation/selection");

  if (!response.ok) {
    throw new Error("No se pudo obtener la selección.");
  }

  return SelectionSchema.parse(await response.json());
}

const EvaluationSelectionSchema = z.object({
  runId: z.string(),
  runName: z.string(),
  selectedAt: z.string(),
});

const PerClassMetricSchema = z.object({
  precision: z.number(),
  recall: z.number(),
  f1: z.number(),
  support: z.number(),
  predicted: z.number(),
});

const ExampleSchema = z.object({
  annotation_id: z.number(),
  confidence: z.number(),
  correct: z.boolean(),
  predicted_label: z.string(),
  relative_path: z.string(),
  source_image_id: z.number(),
  true_label: z.string(),
});

const ClassExamplesSchema = z.object({
  correct: z.array(ExampleSchema),
  errors: z.array(ExampleSchema),
});

const ConfusionMatrixSchema = z.object({
  labels: z.array(z.string()),
  matrix: z.array(z.array(z.number())),
  rows: z.string(),
  columns: z.string(),
});

const TestEvaluationSchema = z.object({
  accuracy: z.number(),
  macro_f1: z.number(),
  correct: z.number(),
  total: z.number(),
  classes: z.array(z.string()),
  dataset_version: z.string(),
  run_id: z.string(),
  selected_at: z.string(),
  evaluated_at: z.string(),
  confusion_matrix: ConfusionMatrixSchema,
  per_class: z.record(z.string(), PerClassMetricSchema),
  examples: z.record(z.string(), ClassExamplesSchema),
});

const LockedEvaluationSchema = z.object({
  locked: z.literal(true),
  message: z.string(),
  selection: EvaluationSelectionSchema,
});

const UnlockedEvaluationSchema = z.object({
  locked: z.literal(false),
  selection: EvaluationSelectionSchema,
  evaluation: TestEvaluationSchema,
});

const EvaluationResponseSchema = z.discriminatedUnion("locked", [
  LockedEvaluationSchema,
  UnlockedEvaluationSchema,
]);

export type EvaluationResponse = z.infer<typeof EvaluationResponseSchema>;

export async function getEvaluation(): Promise<EvaluationResponse> {
  const response = await fetch("/api/evaluation");

  if (!response.ok) {
    throw new Error("No se pudo obtener la evaluación.");
  }

  return EvaluationResponseSchema.parse(await response.json());
}
