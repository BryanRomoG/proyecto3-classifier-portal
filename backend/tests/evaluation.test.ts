import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

import { beforeEach, describe, expect, it, vi } from 'vitest';

const root = path.join(os.tmpdir(), `evaluation-test-${process.pid}`);

vi.mock('../src/config/env.js', () => ({
  env: {
    CLASSIFIER_REPORTS_DIR: path.join(os.tmpdir(), `evaluation-test-${process.pid}`, 'reports'),
    CLASSIFIER_DATA_ROOT: path.join(os.tmpdir(), `evaluation-test-${process.pid}`),
  },
}));

import { NotFoundError, ValidationError } from '../src/logic/errors.js';
import {
  getEvaluation,
  getPredictions,
  getPredictionsCsv,
  getTestCropImage,
} from '../src/logic/evaluation.service.js';

const CSV = [
  'annotation_id,source_image_id,relative_path,true_label,predicted_label,correct,confidence,prob_car,prob_person',
  '12,3,data/processed/crops/car/12.png,car,car,True,0.99,0.99,0.01',
  '56,39,data/processed/crops/person/56.png,person,car,False,0.89,0.89,0.11',
].join('\n');

async function writeReports(testOpened: boolean) {
  const reports = path.join(root, 'reports');
  await fs.mkdir(reports, { recursive: true });
  await fs.writeFile(
    path.join(reports, 'selection.json'),
    JSON.stringify({ run_id: 'run-1', run_name: 'r03', selected_at: 't', test_opened: testOpened }),
  );
  await fs.writeFile(
    path.join(reports, 'test_evaluation.json'),
    JSON.stringify({
      accuracy: 0.5,
      dataset_version: 'v1.0.0',
      manifest_sha256: 'abc123',
      examples: {
        person: {
          correct: [],
          errors: [
            {
              annotation_id: 56,
              relative_path: 'data/processed/crops/person/56.png',
              true_label: 'person',
              predicted_label: 'car',
              confidence: 0.89,
            },
          ],
        },
      },
    }),
  );
  await fs.writeFile(path.join(reports, 'test_predictions.csv'), CSV);
  const crop = path.join(root, 'data/processed/crops/person');
  await fs.mkdir(crop, { recursive: true });
  await fs.writeFile(path.join(crop, '56.png'), Buffer.from([0x89, 0x50, 0x4e, 0x47]));
}

/**
 * T3-3.5 / rúbrica 4.4, 6.3: Evaluation consulta y exporta las predicciones por muestra y
 * muestra los recortes de aciertos y errores, solo después de abrir el test.
 */
describe('Evaluation', () => {
  beforeEach(async () => {
    await fs.rm(root, { recursive: true, force: true });
  });

  it('expone las predicciones por muestra con su recorte', async () => {
    await writeReports(true);

    const rows = await getPredictions();

    expect(rows).toHaveLength(2);
    expect(rows[1]).toMatchObject({
      annotationId: 56,
      trueLabel: 'person',
      predictedLabel: 'car',
      correct: false,
      confidence: 0.89,
      probabilities: { car: 0.89, person: 0.11 },
      imageUrl: '/evaluation/crops/56',
    });
    expect(await getPredictionsCsv()).toBe(CSV);
  });

  it('agrega la imagen a los ejemplos y la versión del manifiesto', async () => {
    await writeReports(true);

    const result = await getEvaluation();

    expect(result.locked).toBe(false);
    if (result.locked) return;
    expect(result.manifest).toEqual({ datasetVersion: 'v1.0.0', sha256: 'abc123' });
    expect(result.evaluation.examples.person.errors[0].imageUrl).toBe('/evaluation/crops/56');
  });

  it('sirve solo recortes del test listados en las predicciones', async () => {
    await writeReports(true);

    const image = await getTestCropImage(56);

    expect(image.contentType).toBe('image/png');
    expect(image.body.length).toBe(4);
    await expect(getTestCropImage(999)).rejects.toBeInstanceOf(NotFoundError);
  });

  it('no revela predicciones ni recortes antes de abrir el test', async () => {
    await writeReports(false);

    await expect(getPredictions()).rejects.toBeInstanceOf(ValidationError);
    await expect(getPredictionsCsv()).rejects.toBeInstanceOf(ValidationError);
    await expect(getTestCropImage(56)).rejects.toBeInstanceOf(ValidationError);
  });
});
