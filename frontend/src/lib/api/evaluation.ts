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
  imageUrl: z.string(),
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
  manifest_sha256: z.string(),
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
  manifest: z.object({ datasetVersion: z.string(), sha256: z.string() }),
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

const PredictionSchema = z.object({
  annotationId: z.number(),
  sourceImageId: z.number(),
  relativePath: z.string(),
  trueLabel: z.string(),
  predictedLabel: z.string(),
  correct: z.boolean(),
  confidence: z.number(),
  probabilities: z.record(z.string(), z.number()),
  imageUrl: z.string(),
});

export type Prediction = z.infer<typeof PredictionSchema>;

/** Predicciones por muestra del test (consulta para auditoría). */
export async function getPredictions(): Promise<Prediction[]> {
  const response = await fetch("/api/evaluation/predictions");

  if (!response.ok) {
    throw new Error("No se pudieron obtener las predicciones por muestra.");
  }

  return z.object({ predictions: z.array(PredictionSchema) }).parse(await response.json())
    .predictions;
}

/** Descarga del CSV de predicciones tal como está commiteado. */
export const PREDICTIONS_CSV_URL = "/api/evaluation/predictions.csv";

/** URL del navegador para una ruta del backend (`/evaluation/crops/56` -> `/api/...`). */
export function apiUrl(path: string): string {
  return `/api${path}`;
}
