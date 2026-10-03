
import fs from "node:fs/promises";
import path from "node:path";

const REPORTS_DIR = path.resolve(
  process.cwd(),
  "../pipeline/reports/classifier",
);

interface SelectionReport {
  run_id: string;
  run_name: string;
  selected_at: string;
  test_opened: boolean;
  selected_metric_value: number;
  valid_runs: number;
}

interface TestEvaluation {
  accuracy: number;
  macro_f1: number;
  correct: number;
  total: number;
  classes: string[];
  dataset_version: string;
  run_id: string;
  selected_at: string;
  evaluated_at: string;
  confusion_matrix: {
    labels: string[];
    matrix: number[][];
    rows: string;
    columns: string;
  };
  per_class: Record<
    string,
    {
      precision: number;
      recall: number;
      f1: number;
      support: number;
      predicted: number;
    }
  >;
  examples: Record<
    string,
    {
      correct: Array<{
        annotation_id: number;
        confidence: number;
        correct: boolean;
        predicted_label: string;
        relative_path: string;
        source_image_id: number;
        true_label: string;
      }>;
      errors: Array<{
        annotation_id: number;
        confidence: number;
        correct: boolean;
        predicted_label: string;
        relative_path: string;
        source_image_id: number;
        true_label: string;
      }>;
    }
  >;
}

async function readJson<T>(filename: string): Promise<T> {
  const content = await fs.readFile(
    path.join(REPORTS_DIR, filename),
    "utf8",
  );

  return JSON.parse(content) as T;
}

export async function getSelection() {
  return readJson<SelectionReport>(
    "selection.json",
  );
}

export async function getEvaluation() {
  const selection = await getSelection();

  /*
   * Protección del criterio T3-3.5:
   * el test solamente se expone después de que la selección
   * fue cerrada.
   */
  if (!selection.test_opened) {
    return {
      locked: true,
      message:
        "La evaluación final permanece bloqueada hasta cerrar la selección del modelo.",
      selection: {
        runId: selection.run_id,
        runName: selection.run_name,
        selectedAt: selection.selected_at,
      },
    };
  }

  const evaluation =
    await readJson<TestEvaluation>(
      "test_evaluation.json",
    );

  return {
    locked: false,
    selection: {
      runId: selection.run_id,
      runName: selection.run_name,
      selectedAt: selection.selected_at,
    },
    evaluation,
  };
}

