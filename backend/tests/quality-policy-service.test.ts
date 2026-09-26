import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { load } from 'js-yaml';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { ValidationError } from '../src/logic/errors.js';
import { getQualityPolicy, updateQualityPolicy } from '../src/logic/quality-policy.service.js';

/**
 * Pruebas asociadas a SPEC-PIPE-001.
 * Trazabilidad: features/pipeline-contracts.feature → src/logic/quality-policy.service.ts
 *
 * Usa un `quality.yaml` real en un directorio temporal -- no mockea `fs` -- para
 * probar exactamente lo que hace `dataset_quality.quality_gate.runner` del lado
 * de la pipeline: leer el archivo tal cual, y (para el PUT) escribirlo de vuelta.
 */

const SAMPLE_YAML = `min_images_per_class:
  label: Minimum images per class
  threshold: 300
  severity: fail
  comparison: min
  unit: images
class_imbalance:
  label: Class imbalance ratio
  threshold: 3.0
  severity: warn
  comparison: max
  unit: majority/minority ratio
`;

let policyPath: string;
let dir: string;

beforeEach(async () => {
  dir = await mkdtemp(path.join(tmpdir(), 'quality-policy-'));
  policyPath = path.join(dir, 'quality.yaml');
  await writeFile(policyPath, SAMPLE_YAML, 'utf-8');
});

afterEach(async () => {
  await rm(dir, { recursive: true, force: true });
});

describe('SPEC-PIPE-001 - getQualityPolicy', () => {
  it('lee y parsea quality.yaml a la forma esperada', async () => {
    const policy = await getQualityPolicy(policyPath);

    expect(policy.min_images_per_class).toEqual({
      label: 'Minimum images per class',
      threshold: 300,
      severity: 'fail',
      comparison: 'min',
      unit: 'images',
    });
  });
});

describe('SPEC-PIPE-001 - updateQualityPolicy', () => {
  it('escribe la política mergeada de vuelta al archivo en disco', async () => {
    await updateQualityPolicy(
      {
        min_images_per_class: { threshold: 300, severity: 'fail' },
        class_imbalance: { threshold: 5.0, severity: 'fail' },
      },
      policyPath,
    );

    const onDisk = load(await readFile(policyPath, 'utf-8')) as Record<string, unknown>;
    expect(onDisk.class_imbalance).toMatchObject({ threshold: 5.0, severity: 'fail' });
  });

  it('la siguiente lectura ve el cambio -- exactamente lo que leería la pipeline en su próxima corrida', async () => {
    await updateQualityPolicy(
      {
        min_images_per_class: { threshold: 300, severity: 'fail' },
        class_imbalance: { threshold: 5.0, severity: 'fail' },
      },
      policyPath,
    );

    const reread = await getQualityPolicy(policyPath);
    expect(reread.class_imbalance.threshold).toBe(5.0);
  });

  it('una edición inválida se rechaza y el archivo en disco no cambia', async () => {
    const before = await readFile(policyPath, 'utf-8');

    await expect(
      updateQualityPolicy(
        {
          min_images_per_class: { threshold: 100, severity: 'fail' }, // < 300, inválido
          class_imbalance: { threshold: 5.0, severity: 'fail' },
        },
        policyPath,
      ),
    ).rejects.toBeInstanceOf(ValidationError);

    const after = await readFile(policyPath, 'utf-8');
    expect(after).toBe(before);
  });
});
