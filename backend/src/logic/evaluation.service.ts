import fs from 'node:fs/promises';
import path from 'node:path';

import { env } from '../config/env.js';
import { NotFoundError, ValidationError } from './errors.js';

/**
 * Evaluation (T3-3.5 / rúbrica 4.4, 6.3): candidato, métricas, matriz, ejemplos con imagen y
 * predicciones por muestra, leídos de los reportes commiteados del clasificador. Nada de esto
 * se revela antes de que la selección cierre y el test se abra (`selection.test_opened`).
 */

const REPORTS_DIR = path.resolve(process.cwd(), env.CLASSIFIER_REPORTS_DIR);
const DATA_ROOT = path.resolve(process.cwd(), env.CLASSIFIER_DATA_ROOT);
const PREDICTIONS_CSV = 'test_predictions.csv';

interface SelectionReport {
  run_id: string;
  run_name: string;
  selected_at: string;
  test_opened: boolean;
  selected_metric_value: number;
  valid_runs: number;
}

interface ExampleRow {
  annotation_id: number;
  confidence: number;
  correct: boolean;
  predicted_label: string;
  relative_path: string;
  source_image_id: number;
  true_label: string;
}

interface TestEvaluation {
  accuracy: number;
  macro_f1: number;
  correct: number;
  total: number;
  classes: string[];
  dataset_version: string;
  manifest_sha256: string;
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
  examples: Record<string, { correct: ExampleRow[]; errors: ExampleRow[] }>;
}

export interface PredictionRow {
  annotationId: number;
  sourceImageId: number;
  relativePath: string;
  trueLabel: string;
  predictedLabel: string;
  correct: boolean;
  confidence: number;
  probabilities: Record<string, number>;
  imageUrl: string;
}

async function readText(filename: string): Promise<string> {
  return fs.readFile(path.join(REPORTS_DIR, filename), 'utf8');
}

async function readJson<T>(filename: string): Promise<T> {
  return JSON.parse(await readText(filename)) as T;
}

export function cropImagePath(annotationId: number): string {
  return `/evaluation/crops/${annotationId}`;
}

export async function getSelection() {
  return readJson<SelectionReport>('selection.json');
}

async function requireOpenedTest(): Promise<void> {
  const selection = await getSelection();
  if (!selection.test_opened) {
    throw new ValidationError(
      'Las predicciones de test permanecen bloqueadas hasta cerrar la selección del modelo.',
    );
  }
}

function withImage(row: ExampleRow) {
  return { ...row, imageUrl: cropImagePath(row.annotation_id) };
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
      locked: true as const,
      message: 'La evaluación final permanece bloqueada hasta cerrar la selección del modelo.',
      selection: {
        runId: selection.run_id,
        runName: selection.run_name,
        selectedAt: selection.selected_at,
      },
    };
  }

  const evaluation = await readJson<TestEvaluation>('test_evaluation.json');
  const examples = Object.fromEntries(
    Object.entries(evaluation.examples ?? {}).map(([label, group]) => [
      label,
      { correct: group.correct.map(withImage), errors: group.errors.map(withImage) },
    ]),
  );

  return {
    locked: false as const,
    selection: {
      runId: selection.run_id,
      runName: selection.run_name,
      selectedAt: selection.selected_at,
    },
    manifest: {
      datasetVersion: evaluation.dataset_version,
      sha256: evaluation.manifest_sha256,
    },
    evaluation: { ...evaluation, examples },
  };
}

function parsePredictions(csv: string): PredictionRow[] {
  const [header = '', ...lines] = csv.split(/\r?\n/).filter((line) => line.trim() !== '');
  const columns = header.split(',');
  const probabilityColumns = columns.filter((column) => column.startsWith('prob_'));
  return lines.map((line) => {
    const cells = line.split(',');
    const record = Object.fromEntries(columns.map((column, index) => [column, cells[index] ?? '']));
    const annotationId = Number(record.annotation_id);
    return {
      annotationId,
      sourceImageId: Number(record.source_image_id),
      relativePath: record.relative_path ?? '',
      trueLabel: record.true_label ?? '',
      predictedLabel: record.predicted_label ?? '',
      correct: record.correct === 'True',
      confidence: Number(record.confidence),
      probabilities: Object.fromEntries(
        probabilityColumns.map((column) => [column.slice('prob_'.length), Number(record[column])]),
      ),
      imageUrl: cropImagePath(annotationId),
    };
  });
}

/** Una fila por recorte de test: etiqueta real, predicha, confianza y probabilidades. */
export async function getPredictions(): Promise<PredictionRow[]> {
  await requireOpenedTest();
  return parsePredictions(await readText(PREDICTIONS_CSV));
}

/** El CSV tal como está commiteado, para exportarlo y auditarlo. */
export async function getPredictionsCsv(): Promise<string> {
  await requireOpenedTest();
  return readText(PREDICTIONS_CSV);
}

/**
 * Imagen del recorte de un ejemplo de test. Solo se sirven recortes listados en las
 * predicciones, resueltos dentro de la raíz de datos: nunca una ruta arbitraria.
 */
export async function getTestCropImage(
  annotationId: number,
): Promise<{ contentType: string; body: Buffer }> {
  const rows = await getPredictions();
  const row = rows.find((candidate) => candidate.annotationId === annotationId);
  if (!row) {
    throw new NotFoundError(`El recorte ${annotationId} no está en el test.`);
  }
  const file = path.resolve(DATA_ROOT, row.relativePath);
  if (!file.startsWith(DATA_ROOT + path.sep)) {
    throw new NotFoundError(`El recorte ${annotationId} no está en el test.`);
  }
  try {
    return { contentType: 'image/png', body: await fs.readFile(file) };
  } catch {
    throw new NotFoundError(`No se encontró la imagen del recorte ${annotationId}.`);
  }
}
