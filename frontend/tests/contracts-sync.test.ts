import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  qualityReportSchema,
  splitsReportSchema,
  versionsReportSchema,
} from "../src/lib/contracts/schemas";

/**
 * `frontend/public/contracts/*.json` is a served COPY of the source of
 * truth at `/contracts` (repo root) — the frontend can't fetch a path
 * outside `public/` at runtime, so the copy has to exist. Nothing enforces
 * automatically that the two stay identical, which is exactly how
 * `quality.json` drifted after the APP-01 merge conflict resolution: the
 * fix landed in `/contracts/quality.json` but nobody re-copied it into
 * `frontend/public/contracts/quality.json`, so the app kept serving the
 * stale shape (spatial_bias, null threshold/observed, extra metadata
 * fields) that the real pipeline's Pydantic model rejects.
 *
 * This test fails loudly the next time that happens, for any of the three
 * contracts, and also fails if the served copy stops validating against
 * our own Zod schemas.
 */
const PROJECT_ROOT = process.env.PROJECT_ROOT ?? path.resolve(__dirname, "../..");

function readJson(relativePath: string): unknown {
  const fullPath = path.join(PROJECT_ROOT, relativePath);
  return JSON.parse(fs.readFileSync(fullPath, "utf-8"));
}

const CONTRACTS = [
  { name: "quality.json", schema: qualityReportSchema },
  { name: "splits.json", schema: splitsReportSchema },
  { name: "versions.json", schema: versionsReportSchema },
] as const;

describe("contracts/*.json y frontend/public/contracts/*.json deben coincidir", () => {
  it.each(CONTRACTS)(
    "$name: la copia pública es idéntica al contrato fuente y valida con su esquema Zod",
    ({ name, schema }) => {
      const source = readJson(`contracts/${name}`);
      const served = readJson(`frontend/public/contracts/${name}`);

      expect(served).toEqual(source);
      expect(() => schema.parse(served)).not.toThrow();
    }
  );
});
