/**
 * SPEC-PIPE-001 — Reglas puras de negocio para editar la política de la
 * Quality Gate (`pipeline/quality.yaml`) desde Settings.
 *
 * Función pura, sin I/O, para poder probarla sin tocar el sistema de
 * archivos (mismo patrón que `dashboard.builder.ts`).
 */

import { ValidationError } from './errors.js';

export type Severity = 'warn' | 'fail';

/** Un check tal como vive en `quality.yaml` (y como lo valida Pydantic con `extra="forbid"`). */
export type QualityPolicyCheck = {
  label: string;
  threshold: number;
  severity: Severity;
  comparison: 'min' | 'max';
  unit: string;
};

/** El archivo completo: mapeo plano `check_id -> QualityPolicyCheck`, igual que en disco. */
export type QualityPolicyFile = Record<string, QualityPolicyCheck>;

/** Lo único que Settings puede editar por check: threshold y severity. */
export type QualityPolicyEdit = { threshold: number; severity: Severity };

/** Body esperado de `PUT /quality-policy`. */
export type QualityPolicyUpdateInput = Record<string, QualityPolicyEdit>;

const MIN_IMAGES_CHECK_ID = 'min_images_per_class';
const MIN_IMAGES_THRESHOLD_FLOOR = 300;

/**
 * Aplica una edición de Settings sobre la política actual y devuelve la
 * política completa resultante, lista para escribirse a disco.
 *
 * Reglas (espejo de `QualityPolicy`/`QualityPolicyCheck` en
 * `pipeline/src/dataset_quality/quality_gate/models.py`):
 *
 * 1. El conjunto de ids editados debe ser EXACTAMENTE el mismo que ya existe
 *    en la política actual — Settings edita checks existentes, no agrega ni
 *    quita ninguno (eso sigue siendo alcance de Data Quality, no de la Web
 *    App).
 * 2. `threshold` debe ser un número finito.
 * 3. `severity` debe ser `"warn"` o `"fail"`.
 * 4. `min_images_per_class` debe seguir teniendo `severity: "fail"` y
 *    `threshold >= 300` — el mismo invariante que
 *    `QualityPolicy.require_minimum_images_policy` exige del lado de la
 *    pipeline. Sin este chequeo, Settings podría guardar una política que la
 *    pipeline real rechazaría al cargarla.
 * 5. `label`, `comparison` y `unit` de cada check se conservan tal cual
 *    estaban — Settings nunca los toca, así que no hay forma de que una
 *    edición corrompa esos campos.
 *
 * Lanza `ValidationError` (400 en la capa UI) con un mensaje específico ante
 * cualquier violación; nunca escribe nada a medias.
 */
export function applyQualityPolicyUpdate(
  current: QualityPolicyFile,
  update: QualityPolicyUpdateInput,
): QualityPolicyFile {
  const currentIds = new Set(Object.keys(current));
  const updateIds = new Set(Object.keys(update));

  const missing = [...currentIds].filter((id) => !updateIds.has(id));
  if (missing.length > 0) {
    throw new ValidationError(
      `Faltan checks en la actualización: ${missing.join(', ')}. Settings debe enviar todos los checks existentes.`,
    );
  }

  const unknown = [...updateIds].filter((id) => !currentIds.has(id));
  if (unknown.length > 0) {
    throw new ValidationError(
      `Checks desconocidos en la actualización: ${unknown.join(', ')}. Settings no puede agregar checks nuevos.`,
    );
  }

  const merged: QualityPolicyFile = {};
  for (const id of currentIds) {
    // El chequeo de missing/unknown de arriba ya garantiza que ambas llaves
    // existen; el guard es solo para que TypeScript (noUncheckedIndexedAccess)
    // lo sepa también, sin recurrir a `!`.
    const edit = update[id];
    const existing = current[id];
    if (edit === undefined || existing === undefined) {
      throw new ValidationError(`Falta información para el check "${id}".`);
    }

    if (!Number.isFinite(edit.threshold)) {
      throw new ValidationError(`threshold inválido para "${id}": debe ser un número finito.`);
    }
    if (edit.severity !== 'warn' && edit.severity !== 'fail') {
      throw new ValidationError(`severity inválida para "${id}": debe ser "warn" o "fail".`);
    }

    merged[id] = {
      ...existing,
      threshold: edit.threshold,
      severity: edit.severity,
    };
  }

  const minImages = merged[MIN_IMAGES_CHECK_ID];
  if (minImages !== undefined) {
    if (minImages.severity !== 'fail') {
      throw new ValidationError(`${MIN_IMAGES_CHECK_ID}.severity debe ser "fail".`);
    }
    if (minImages.threshold < MIN_IMAGES_THRESHOLD_FLOOR) {
      throw new ValidationError(
        `${MIN_IMAGES_CHECK_ID}.threshold debe ser mayor o igual a ${MIN_IMAGES_THRESHOLD_FLOOR}.`,
      );
    }
  }

  return merged;
}
