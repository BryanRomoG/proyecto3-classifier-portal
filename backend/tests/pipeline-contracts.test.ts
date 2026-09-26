import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { env } from '../src/config/env.js';
import { NotFoundError } from '../src/logic/errors.js';
import {
  getQualityReport,
  getSplitReport,
  getVersionHistory,
} from '../src/logic/pipeline-contracts.service.js';

/**
 * Pruebas asociadas a SPEC-PIPE-001.
 * Trazabilidad: features/pipeline-contracts.feature → src/logic/pipeline-contracts.service.ts
 *
 * A propósito NO apuntan a `contracts/` real: cada prueba arma su propio
 * directorio temporal, para que estas pruebas no dependan de que la pipeline
 * ya haya corrido ni de dónde esté el repo en el entorno de CI.
 */

let dir: string;

beforeEach(async () => {
  dir = await mkdtemp(path.join(tmpdir(), 'pipeline-contracts-'));
});

afterEach(async () => {
  await rm(dir, { recursive: true, force: true });
});

describe('SPEC-PIPE-001 - lectura de contratos', () => {
  it('getQualityReport devuelve el JSON tal cual está en quality.json', async () => {
    const payload = { dataset_version: 'v-test', overall_status: 'pass', checks: [] };
    await writeFile(path.join(dir, 'quality.json'), JSON.stringify(payload), 'utf-8');

    await expect(getQualityReport(dir)).resolves.toEqual(payload);
  });

  it('getSplitReport devuelve el JSON tal cual está en splits.json', async () => {
    const payload = { dataset_version: 'v-test', seed: 42 };
    await writeFile(path.join(dir, 'splits.json'), JSON.stringify(payload), 'utf-8');

    await expect(getSplitReport(dir)).resolves.toEqual(payload);
  });

  it('getVersionHistory devuelve el JSON tal cual está en versions.json', async () => {
    const payload = { current_version: 'v-test', versions: [] };
    await writeFile(path.join(dir, 'versions.json'), JSON.stringify(payload), 'utf-8');

    await expect(getVersionHistory(dir)).resolves.toEqual(payload);
  });

  it('lanza NotFoundError con mensaje explícito si el archivo no existe todavía', async () => {
    await expect(getQualityReport(dir)).rejects.toBeInstanceOf(NotFoundError);
    await expect(getQualityReport(dir)).rejects.toThrow(/quality.json/);
  });

  it('refleja un cambio en el archivo sin necesidad de reiniciar nada (Agent Test de APP-07)', async () => {
    const filePath = path.join(dir, 'quality.json');
    await writeFile(filePath, JSON.stringify({ overall_status: 'fail' }), 'utf-8');
    await expect(getQualityReport(dir)).resolves.toMatchObject({ overall_status: 'fail' });

    await writeFile(filePath, JSON.stringify({ overall_status: 'pass' }), 'utf-8');
    await expect(getQualityReport(dir)).resolves.toMatchObject({ overall_status: 'pass' });
  });
});

describe('SPEC-PIPE-001 - PIPELINE_OUTPUT_DIR apunta a la salida real de la pipeline', () => {
  it('el default resuelve a pipeline/data/interim, no a contracts/ (el mock versionado)', () => {
    // Corrección de revisión (Mau, PR de APP-07): pipeline/dvc.yaml escribe
    // quality.json/splits.json/versions.json en pipeline/data/interim/ (ver
    // los stages quality_gate/split/release, campo `outs`) -- nunca en
    // contracts/, que sigue siendo el mock versionado de APP-01/APP-05 y que
    // ningún stage de la pipeline real toca. Antes de esta corrección,
    // env.CONTRACTS_DIR apuntaba por defecto a `../contracts`: correr
    // `dvc repro` nunca cambiaba lo que la Web App mostraba, sin importar
    // cuántas veces se corriera (el Agent Test de APP-07 fallaba en la
    // práctica). Si esto vuelve a apuntar a contracts/, este test lo
    // atrapa.
    const resolved = path.resolve(process.cwd(), env.PIPELINE_OUTPUT_DIR);
    const expectedSuffix = path.join('pipeline', 'data', 'interim');

    expect(resolved.endsWith(expectedSuffix)).toBe(true);
    expect(path.basename(resolved)).not.toBe('contracts');
  });
});
