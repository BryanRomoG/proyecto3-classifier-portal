/**
 * SPEC-PIPE-001 — Lee y escribe `pipeline/quality.yaml` (ver
 * `env.QUALITY_POLICY_PATH`): la política real que
 * `dataset_quality.quality_gate.runner` carga en cada corrida de la Quality
 * Gate (`dvc repro`). Escribir aquí es, literalmente, lo que hace que "la
 * siguiente corrida del gate use el nuevo valor" (Agent Test de APP-07) —
 * no hay ninguna capa intermedia de caché ni de "aplicar cambios" aparte:
 * el archivo en disco ES la política.
 */

import { readFile, writeFile } from 'node:fs/promises';
// js-yaml no tiene export default en su build ESM -- ver dist/js-yaml.mjs --
// así que se importa por nombre.
import { dump, load } from 'js-yaml';
import { env } from '../config/env.js';
import {
  applyQualityPolicyUpdate,
  type QualityPolicyFile,
  type QualityPolicyUpdateInput,
} from './quality-policy.builder.js';

async function readQualityPolicyFile(policyPath: string): Promise<QualityPolicyFile> {
  const raw = await readFile(policyPath, 'utf-8');
  const parsed = load(raw);
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    throw new Error(`${policyPath} no tiene la forma esperada (mapeo de checks).`);
  }
  return parsed as QualityPolicyFile;
}

/**
 * `GET /quality-policy` — la política completa, tal como está en disco ahora
 * mismo.
 *
 * `policyPath` por defecto es `env.QUALITY_POLICY_PATH`; el parámetro existe
 * para poder probar esta función contra un archivo temporal (ver
 * `tests/quality-policy-service.test.ts`).
 */
export async function getQualityPolicy(
  policyPath: string = env.QUALITY_POLICY_PATH,
): Promise<QualityPolicyFile> {
  return readQualityPolicyFile(policyPath);
}

/**
 * `PUT /quality-policy` — valida la edición contra la política actual
 * (`applyQualityPolicyUpdate`, ver ese módulo para las reglas) y, solo si
 * pasa, la escribe de vuelta a `quality.yaml`. Devuelve la política ya
 * mergeada.
 */
export async function updateQualityPolicy(
  update: QualityPolicyUpdateInput,
  policyPath: string = env.QUALITY_POLICY_PATH,
): Promise<QualityPolicyFile> {
  const current = await readQualityPolicyFile(policyPath);
  const merged = applyQualityPolicyUpdate(current, update);
  await writeFile(policyPath, dump(merged), 'utf-8');
  return merged;
}
