import { z } from 'zod';

/**
 * SPEC-PIPE-001 / SPEC-VALID-001 — Forma del body de `PUT /quality-policy`.
 *
 * Solo valida la FORMA (un mapeo no vacío de check_id -> {threshold,
 * severity}), igual que el resto de esquemas de frontera HTTP del proyecto.
 * Las reglas de NEGOCIO (que el conjunto de ids coincida con la política
 * actual, que `min_images_per_class` siga siendo válido) viven en
 * `quality-policy.builder.ts`, porque necesitan la política actual para
 * evaluarse — no son una propiedad del body por sí solo.
 */
const qualityPolicyEditSchema = z.object({
  threshold: z.number({ message: 'threshold debe ser un número.' }).finite({
    message: 'threshold debe ser un número finito.',
  }),
  severity: z.enum(['warn', 'fail'], { message: 'severity debe ser "warn" o "fail".' }),
});

export const qualityPolicyUpdateSchema = z
  .record(z.string().min(1), qualityPolicyEditSchema)
  .refine((checks) => Object.keys(checks).length > 0, {
    message: 'Debe enviarse al menos un check.',
  });

export type QualityPolicyUpdateBody = z.infer<typeof qualityPolicyUpdateSchema>;
