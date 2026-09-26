import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { qualityReportSchema } from "../src/lib/contracts/schemas";
import { AnalyzersPage } from "../src/pages/dataset/Analyzers";
import { OverviewPage } from "../src/pages/dataset/Overview";
import { SettingsPage } from "../src/pages/dataset/Settings";

/**
 * APP-05 — cubre lo que APP-02 (dataset-routes.test.tsx) no probaba porque
 * las pantallas todavía no lo implementaban:
 * - Overview: los 5 datos que pide el Acceptance Criteria (total de
 *   imágenes, cajas, categorías, checks fallidos, estado del gate), y que
 *   NINGUNO está hardcodeado (Agent Test de APP-05: cambiar el contrato
 *   cambia lo que se ve).
 * - Analyzers: la pestaña Spatial Bias existe y es seleccionable aunque
 *   `quality.json` ya no traiga ese check (se quitó en la reconciliación
 *   con DQ-02) — debe mostrar un estado honesto de "no disponible", no
 *   datos inventados ni un crash.
 * - Settings: los campos de threshold/severity son editables (ya no
 *   `disabled`), sin pretender persistir el cambio contra un backend real.
 */

function mockFetchOnce(body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: async () => body,
      } as Response)
    )
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const BASE_QUALITY_REPORT = {
  dataset_version: "v-test-1",
  generated_at: "2026-09-17T00:00:00Z",
  overall_status: "fail",
  dataset_summary: {
    total_images: 111,
    total_bounding_boxes: 222,
    total_categories: 3,
  },
  checks: [
    {
      id: "min_images_per_class",
      label: "Minimum images per class",
      severity: "fail",
      status: "fail",
      threshold: 300,
      observed: 214,
      unit: "images",
      details: {},
      offending_samples: [],
    },
    {
      id: "class_imbalance",
      label: "Class imbalance ratio",
      severity: "warn",
      status: "warn",
      threshold: 3.0,
      observed: 4.2,
      unit: "majority/minority ratio",
      details: {},
      offending_samples: [],
    },
    {
      id: "small_objects",
      label: "Small objects (< 32x32 px)",
      severity: "warn",
      status: "pass",
      threshold: 40.0,
      observed: 18.6,
      unit: "percent",
      details: {},
      offending_samples: [],
    },
    {
      id: "duplicates",
      label: "Duplicates / near-duplicates (pHash)",
      severity: "fail",
      status: "pass",
      threshold: 5,
      observed: 2,
      unit: "count",
      details: {},
      offending_samples: [],
    },
    {
      id: "invalid_boxes",
      label: "Invalid / degenerate bounding boxes",
      severity: "fail",
      status: "fail",
      threshold: 0,
      observed: 3,
      unit: "count",
      details: {},
      offending_samples: [{ image_id: "img_00001", annotation_id: "ann_00001" }],
    },
  ],
};

describe("Overview (APP-05)", () => {
  it("muestra total de imágenes, cajas, categorías, checks fallidos y estado del gate", async () => {
    mockFetchOnce(BASE_QUALITY_REPORT);

    render(
      <MemoryRouter>
        <OverviewPage />
      </MemoryRouter>
    );

    expect(await screen.findByText("111")).toBeInTheDocument();
    expect(screen.getByText("222")).toBeInTheDocument();
    expect(screen.getByText("3", { exact: true })).toBeInTheDocument();
    // 2 checks con status "fail" en el fixture (min_images_per_class, invalid_boxes).
    expect(screen.getByText("2", { exact: true })).toBeInTheDocument();
    expect(screen.getAllByText(/fail/i).length).toBeGreaterThan(0);
  });

  it("no tiene ninguna cifra hardcodeada: cambia con el contrato (Agent Test)", async () => {
    mockFetchOnce({
      ...BASE_QUALITY_REPORT,
      dataset_summary: { total_images: 9001, total_bounding_boxes: 9002, total_categories: 9 },
      checks: [BASE_QUALITY_REPORT.checks[0]], // solo 1 check, y falla -> 1 "failed"
    });

    render(
      <MemoryRouter>
        <OverviewPage />
      </MemoryRouter>
    );

    expect(await screen.findByText("9001")).toBeInTheDocument();
    expect(screen.getByText("9002")).toBeInTheDocument();
    expect(screen.getByText("9", { exact: true })).toBeInTheDocument();
    expect(screen.getByText("1", { exact: true })).toBeInTheDocument();
  });
});

describe("Analyzers (APP-05)", () => {
  it("muestra las 5 pestañas requeridas, incluida Spatial Bias, y Spatial Bias no inventa datos", async () => {
    mockFetchOnce(BASE_QUALITY_REPORT);

    render(
      <MemoryRouter>
        <AnalyzersPage />
      </MemoryRouter>
    );

    expect(await screen.findByRole("button", { name: /small objects/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /class imbalance/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /duplicates/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /invalid.*bounding boxes/i })).toBeInTheDocument();
    const spatialBiasTab = screen.getByRole("button", { name: /spatial bias/i });
    expect(spatialBiasTab).toBeInTheDocument();

    fireEvent.click(spatialBiasTab);

    expect(await screen.findByText(/no (est[aá] disponible|hay datos)/i)).toBeInTheDocument();
    // Nunca debe mostrar un badge pass/warn/fail para un check que no existe.
    expect(screen.queryByText(/^pass$/i)).not.toBeInTheDocument();
  });
});

describe("qualityReportSchema (APP-05 review fix)", () => {
  it("acepta dataset_summary: null, no solo ausente (Pydantic serializa None como null)", () => {
    // Cuando evaluate_policy() corre sin un CocoDataset (el caso normal hasta
    // que exista APP-07), el pipeline real produce "dataset_summary": null en
    // el JSON — Pydantic no omite el campo, lo serializa como null. El
    // esquema debe aceptar esta salida real, no solo la ausencia de la llave.
    const payloadWithNullSummary = {
      ...BASE_QUALITY_REPORT,
      dataset_summary: null,
    };

    const result = qualityReportSchema.safeParse(payloadWithNullSummary);

    expect(result.success).toBe(true);
  });
});

// APP-07: Settings ya no lee contracts/quality.json (un reporte de una
// corrida) sino /quality-policy (la política editable, misma forma plana
// que pipeline/quality.yaml — ver lib/contracts/schemas.ts). Este fixture
// es intencionalmente distinto de BASE_QUALITY_REPORT.
const BASE_QUALITY_POLICY = {
  min_images_per_class: {
    label: "Minimum images per class",
    threshold: 300,
    severity: "fail",
    comparison: "min",
    unit: "images",
  },
  class_imbalance: {
    label: "Class imbalance ratio",
    threshold: 3.0,
    severity: "warn",
    comparison: "max",
    unit: "majority/minority ratio",
  },
};

describe("Settings (APP-05)", () => {
  it("permite editar threshold y severity (ya no están deshabilitados)", async () => {
    mockFetchOnce(BASE_QUALITY_POLICY);

    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>
    );

    const thresholdInput = (await screen.findAllByLabelText(/umbral/i))[0] as HTMLInputElement;
    expect(thresholdInput).not.toBeDisabled();

    fireEvent.change(thresholdInput, { target: { value: "999" } });
    expect(thresholdInput.value).toBe("999");

    const severitySelect = screen.getAllByLabelText(/severidad/i)[0] as HTMLSelectElement;
    expect(severitySelect).not.toBeDisabled();
    fireEvent.change(severitySelect, { target: { value: "warn" } });
    expect(severitySelect.value).toBe("warn");
  });
});
