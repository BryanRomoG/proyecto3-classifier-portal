import { z } from "zod";

/**
 * Zod schemas for the shared data contracts defined in `/contracts` at the
 * repo root (see `contracts/README.md`). These mirror `quality.json`,
 * `splits.json` and `versions.json` exactly — if the shape of those files
 * changes (once Data Quality / MLOps produce them for real), update these
 * schemas first; every screen that reads a contract goes through one of
 * these, so a shape mismatch surfaces as a readable error instead of a
 * silent `undefined` in the UI.
 */

const severitySchema = z.enum(["warn", "fail"]);
const checkStatusSchema = z.enum(["pass", "warn", "fail"]);

export type Severity = z.infer<typeof severitySchema>;

export const qualityCheckSchema = z.object({
  id: z.string(),
  label: z.string(),
  severity: severitySchema,
  status: checkStatusSchema,
  threshold: z.number(),
  observed: z.number(),
  unit: z.string(),
  details: z.record(z.string(), z.unknown()),
  offending_samples: z.array(z.record(z.string(), z.unknown())),
});

// APP-05: dataset-level totals for the Overview screen. Mirrors the real
// `QualityReport.dataset_summary` (pipeline), which stays `None` until a
// full `CocoDataset` is evaluated — see `contracts/README.md`,
// "Reconciliación con APP-05". Pydantic serializes that `None` as a literal
// JSON `null` (it does not omit the key), so the field must accept `null`
// as well as being absent — `.optional()` alone only allows the key to be
// missing, and rejects a real `dataset_summary: null` payload. Review fix,
// see the test in app-05-dashboard.test.tsx.
export const datasetSummarySchema = z.object({
  total_images: z.number(),
  total_bounding_boxes: z.number(),
  total_categories: z.number(),
});

export const qualityReportSchema = z.object({
  dataset_version: z.string(),
  generated_at: z.string(),
  overall_status: checkStatusSchema,
  dataset_summary: datasetSummarySchema.nullish(),
  checks: z.array(qualityCheckSchema),
});

export type QualityCheck = z.infer<typeof qualityCheckSchema>;
export type QualityDatasetSummary = z.infer<typeof datasetSummarySchema>;
export type QualityReport = z.infer<typeof qualityReportSchema>;

const splitCountsSchema = z.object({
  train: z.number(),
  val: z.number(),
  test: z.number(),
});

export const splitsReportSchema = z.object({
  dataset_version: z.string(),
  generated_at: z.string(),
  seed: z.number(),
  proportions: splitCountsSchema,
  tolerance: z.number(),
  totals: z.object({
    images: z.number(),
    train: z.number(),
    val: z.number(),
    test: z.number(),
  }),
  class_distribution: z.object({
    train: z.record(z.string(), z.number()),
    val: z.record(z.string(), z.number()),
    test: z.record(z.string(), z.number()),
  }),
  leakage_check: z.object({
    status: checkStatusSchema,
    leaked_pairs: z.number(),
    near_duplicate_pairs_checked: z.number(),
    near_duplicate_pairs_same_split: z.number(),
  }),
  reproducibility_check: z.object({
    status: checkStatusSchema,
    note: z.string(),
  }),
});

export type SplitsReport = z.infer<typeof splitsReportSchema>;

const environmentStatusSchema = z.object({
  provider: z.string(),
  status: z.string(),
  synced_at: z.string().nullable(),
});

export const datasetVersionSchema = z.object({
  version: z.string(),
  released_at: z.string(),
  content_hash: z.string(),
  quality_status: checkStatusSchema,
  environments: z.object({
    dev: environmentStatusSchema,
    prod: environmentStatusSchema,
  }),
  diff_from_previous: z
    .object({
      images_added: z.number(),
      boxes_added: z.number(),
      classes_left_minimum: z.array(z.string()),
      small_object_ratio_change_pct: z.number(),
    })
    .nullable(),
});

export const versionsReportSchema = z.object({
  current_version: z.string(),
  versions: z.array(datasetVersionSchema),
});

export type DatasetVersion = z.infer<typeof datasetVersionSchema>;
export type VersionsReport = z.infer<typeof versionsReportSchema>;

// APP-07: política real de la quality gate, leída de `pipeline/quality.yaml`
// a través de `GET /quality-policy` (backend, SPEC-PIPE-001) — no la última
// corrida (`qualityReportSchema` arriba), sino la configuración editable que
// usa la SIGUIENTE corrida. Misma forma plana `check_id -> {...}` que tiene
// el YAML en disco (ver backend/specs/pipeline-contracts.spec.md, regla 3):
// sin envoltura de nivel superior, a diferencia de `qualityCheckSchema`
// (que además trae `id`/`status`/`observed`, campos de un reporte ya
// corrido, que la política no tiene).
export const qualityPolicyCheckSchema = z.object({
  label: z.string(),
  threshold: z.number(),
  severity: severitySchema,
  comparison: z.enum(["min", "max"]),
  unit: z.string(),
});

export const qualityPolicySchema = z.record(z.string(), qualityPolicyCheckSchema);

export type QualityPolicyCheck = z.infer<typeof qualityPolicyCheckSchema>;
export type QualityPolicy = z.infer<typeof qualityPolicySchema>;

// APP-10: respuesta del Dataset Copilot (POST /query contra el servicio
// `copilot`, pipeline/src/dataset_quality/copilot/http_app.py). Mirrors
// `CopilotAnswer` (agent.py) exactamente: `dataset_version` es `None` en el
// JSON cuando el agente respondió sin invocar ninguna tool que trajera esa
// versión, así que acepta `null`, no solo ausencia de la clave.
export const copilotAnswerSchema = z.object({
  answer: z.string(),
  dataset_version: z.string().nullable(),
  tools_used: z.array(z.string()),
});

export type CopilotAnswer = z.infer<typeof copilotAnswerSchema>;
