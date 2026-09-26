import { describe, expect, it } from 'vitest';
import { ValidationError } from '../src/logic/errors.js';
import {
  applyQualityPolicyUpdate,
  type QualityPolicyFile,
} from '../src/logic/quality-policy.builder.js';

/**
 * Pruebas asociadas a SPEC-PIPE-001.
 * Trazabilidad: features/pipeline-contracts.feature → src/logic/quality-policy.builder.ts
 */

function baseFile(overrides: Partial<QualityPolicyFile> = {}): QualityPolicyFile {
  return {
    min_images_per_class: {
      label: 'Minimum images per class',
      threshold: 300,
      severity: 'fail',
      comparison: 'min',
      unit: 'images',
    },
    class_imbalance: {
      label: 'Class imbalance ratio',
      threshold: 3.0,
      severity: 'warn',
      comparison: 'max',
      unit: 'majority/minority ratio',
    },
    ...overrides,
  };
}

describe('SPEC-PIPE-001 - applyQualityPolicyUpdate', () => {
  it('aplica threshold y severity nuevos a un check existente', () => {
    const current = baseFile();

    const merged = applyQualityPolicyUpdate(current, {
      min_images_per_class: { threshold: 300, severity: 'fail' },
      class_imbalance: { threshold: 4.5, severity: 'fail' },
    });

    expect(merged.class_imbalance).toEqual({
      label: 'Class imbalance ratio',
      threshold: 4.5,
      severity: 'fail',
      comparison: 'max',
      unit: 'majority/minority ratio',
    });
  });

  it('conserva label, comparison y unit sin tocarlos', () => {
    const current = baseFile();

    const merged = applyQualityPolicyUpdate(current, {
      min_images_per_class: { threshold: 350, severity: 'fail' },
      class_imbalance: { threshold: 3.0, severity: 'warn' },
    });

    expect(merged.min_images_per_class.label).toBe('Minimum images per class');
    expect(merged.min_images_per_class.comparison).toBe('min');
    expect(merged.min_images_per_class.unit).toBe('images');
  });

  it('rechaza cuando falta un check que sí existe en la política actual', () => {
    const current = baseFile();

    expect(() =>
      applyQualityPolicyUpdate(current, {
        min_images_per_class: { threshold: 300, severity: 'fail' },
        // class_imbalance omitido a propósito
      }),
    ).toThrow(ValidationError);
  });

  it('rechaza cuando la actualización trae un check que no existe en disco', () => {
    const current = baseFile();

    expect(() =>
      applyQualityPolicyUpdate(current, {
        min_images_per_class: { threshold: 300, severity: 'fail' },
        class_imbalance: { threshold: 3.0, severity: 'warn' },
        spatial_bias: { threshold: 50, severity: 'warn' },
      }),
    ).toThrow(ValidationError);
  });

  it('rechaza un threshold no finito (NaN/Infinity)', () => {
    const current = baseFile();

    expect(() =>
      applyQualityPolicyUpdate(current, {
        min_images_per_class: { threshold: 300, severity: 'fail' },
        class_imbalance: { threshold: Number.POSITIVE_INFINITY, severity: 'warn' },
      }),
    ).toThrow(ValidationError);
  });

  it('rechaza una severity fuera de warn/fail', () => {
    const current = baseFile();

    expect(() =>
      applyQualityPolicyUpdate(current, {
        min_images_per_class: { threshold: 300, severity: 'fail' },
        // @ts-expect-error -- probando justamente el valor inválido en runtime
        class_imbalance: { threshold: 3.0, severity: 'critical' },
      }),
    ).toThrow(ValidationError);
  });

  it('rechaza bajar min_images_per_class por debajo de 300', () => {
    const current = baseFile();

    expect(() =>
      applyQualityPolicyUpdate(current, {
        min_images_per_class: { threshold: 299, severity: 'fail' },
        class_imbalance: { threshold: 3.0, severity: 'warn' },
      }),
    ).toThrow(ValidationError);
  });

  it('rechaza cambiar min_images_per_class.severity a warn', () => {
    const current = baseFile();

    expect(() =>
      applyQualityPolicyUpdate(current, {
        min_images_per_class: { threshold: 300, severity: 'warn' },
        class_imbalance: { threshold: 3.0, severity: 'warn' },
      }),
    ).toThrow(ValidationError);
  });

  it('acepta subir min_images_per_class por encima de 300', () => {
    const current = baseFile();

    const merged = applyQualityPolicyUpdate(current, {
      min_images_per_class: { threshold: 500, severity: 'fail' },
      class_imbalance: { threshold: 3.0, severity: 'warn' },
    });

    expect(merged.min_images_per_class.threshold).toBe(500);
  });

  it('nunca escribe nada si una sola regla falla: el merge no es parcial', () => {
    const current = baseFile();

    try {
      applyQualityPolicyUpdate(current, {
        min_images_per_class: { threshold: 300, severity: 'fail' },
        class_imbalance: { threshold: Number.NaN, severity: 'warn' },
      });
    } catch {
      // esperado
    }

    // La política original nunca se mutó -- applyQualityPolicyUpdate no toca `current`.
    expect(current.class_imbalance.threshold).toBe(3.0);
  });
});
