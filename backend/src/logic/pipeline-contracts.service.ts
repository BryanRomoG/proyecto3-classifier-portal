/**
 * SPEC-PIPE-001 — Lee los contratos de Data Quality (`quality.json`,
 * `splits.json`, `versions.json`) tal como los deja la pipeline Python en
 * `pipeline/data/interim/` (ver `env.PIPELINE_OUTPUT_DIR`) -- la salida real
 * de los stages `quality_gate`/`split`/`release` de `pipeline/dvc.yaml`, NO
 * `contracts/` (repo root), que sigue siendo el mock versionado de
 * APP-01/APP-05 y que ningún stage de la pipeline real toca (corrección de
 * revisión, Mau, PR de APP-07 -- ver contracts/README.md).
 *
 * A propósito NO se re-valida el contenido contra un esquema aquí: la forma
 * ya está garantizada por los modelos Pydantic `extra="forbid"` del lado de
 * la pipeline (`quality_gate.models.QualityReport`, `splits.models.SplitResult`,
 * `copilot.contracts.VersionsReport`), y el frontend ya valida lo que recibe
 * con Zod (`frontend/src/lib/contracts/schemas.ts`). Duplicar esa validación
 * aquí en TypeScript solo arriesgaría que las dos copias del esquema se
 * desincronicen sin que nada lo detecte — este endpoint es un paso a través
 * (leer el archivo, parsear JSON, devolverlo), no una tercera fuente de
 * verdad sobre la forma del contrato.
 */

import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { env } from '../config/env.js';
import { NotFoundError } from './errors.js';

async function readContractJson(filename: string, pipelineOutputDir: string): Promise<unknown> {
  const filePath = path.join(pipelineOutputDir, filename);

  let raw: string;
  try {
    raw = await readFile(filePath, 'utf-8');
  } catch (error) {
    if (isEnoent(error)) {
      throw new NotFoundError(
        `${filename} no existe todavía en ${pipelineOutputDir} — corre la pipeline (dvc repro) primero.`,
      );
    }
    throw error;
  }

  return JSON.parse(raw);
}

function isEnoent(error: unknown): boolean {
  return (
    error instanceof Error && 'code' in error && (error as NodeJS.ErrnoException).code === 'ENOENT'
  );
}

/**
 * Reporte actual del Quality Gate — `pipeline/data/interim/quality.json`.
 *
 * `pipelineOutputDir` por defecto es `env.PIPELINE_OUTPUT_DIR`; el parámetro
 * existe para poder probar esta función contra un directorio temporal sin
 * fingir variables de entorno (ver `tests/pipeline-contracts.test.ts`).
 */
export async function getQualityReport(
  pipelineOutputDir: string = env.PIPELINE_OUTPUT_DIR,
): Promise<unknown> {
  return readContractJson('quality.json', pipelineOutputDir);
}

/** Reporte actual de splits train/val/test — `pipeline/data/interim/splits.json`. */
export async function getSplitReport(
  pipelineOutputDir: string = env.PIPELINE_OUTPUT_DIR,
): Promise<unknown> {
  return readContractJson('splits.json', pipelineOutputDir);
}

/** Línea de tiempo de versiones del dataset — `pipeline/data/interim/versions.json`. */
export async function getVersionHistory(
  pipelineOutputDir: string = env.PIPELINE_OUTPUT_DIR,
): Promise<unknown> {
  return readContractJson('versions.json', pipelineOutputDir);
}
