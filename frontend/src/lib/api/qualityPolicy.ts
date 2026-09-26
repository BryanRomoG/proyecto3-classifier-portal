import { type QualityPolicy, qualityPolicySchema, type Severity } from "../contracts/schemas";
import { apiRequest, jsonBody } from "./client";

/**
 * Única escritura de todo APP-07 (ver backend/specs/pipeline-contracts.spec.md,
 * regla 4): edita threshold/severity por check en pipeline/quality.yaml a
 * través de PUT /quality-policy. El body debe traer TODOS los checks que ya
 * existen en el archivo, no solo los editados — el caller (Settings.tsx)
 * arma ese objeto completo antes de llamar aquí.
 */
export type QualityPolicyUpdateBody = Record<string, { threshold: number; severity: Severity }>;

export function updateQualityPolicy(body: QualityPolicyUpdateBody): Promise<QualityPolicy> {
  return apiRequest("/quality-policy", qualityPolicySchema, {
    method: "PUT",
    ...jsonBody(body),
  });
}
