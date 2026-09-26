import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import qualityFixture from "../public/contracts/quality.json";
import splitsFixture from "../public/contracts/splits.json";
import versionsFixture from "../public/contracts/versions.json";
import { App } from "../src/App";

/**
 * Smoke test del "Agent Test" de APP-02: arrancar la app y navegar a las
 * seis pantallas de Dataset Quality sin 404, rutas vacías ni crashes.
 *
 * Desde APP-07 las pantallas ya no leen `public/contracts/*.json` sino las
 * rutas reales del backend (SPEC-PIPE-001: /quality-report, /split-report,
 * /version-history, /quality-policy — ver contracts/README.md,
 * "Reconciliación con APP-07"). Los fixtures de quality/splits/versions
 * siguen siendo el contenido real de `public/contracts/*.json` (importado
 * tal cual); `POLICY_FIXTURE` es la forma que expone `/quality-policy`
 * (mapeo plano `check_id -> {label, threshold, severity, comparison,
 * unit}`, la misma que tiene `pipeline/quality.yaml` en disco), a mano
 * porque ese endpoint no tiene un equivalente JSON estático servido por el
 * frontend.
 */
const POLICY_FIXTURE = {
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

const ROUTE_BODIES: Record<string, unknown> = {
  "quality-report": qualityFixture,
  "split-report": splitsFixture,
  "version-history": versionsFixture,
  "quality-policy": POLICY_FIXTURE,
};

function mockContractsFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      const routeName = Object.keys(ROUTE_BODIES).find((name) => url.includes(name));
      if (!routeName) {
        return Promise.resolve({
          ok: false,
          status: 404,
          json: async () => ({}),
        } as Response);
      }
      const body = ROUTE_BODIES[routeName];
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => body,
      } as Response);
    })
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const DATASET_ROUTES: { path: string; heading: RegExp }[] = [
  { path: "/overview", heading: /^overview$/i },
  { path: "/analyzers", heading: /^analyzers$/i },
  { path: "/splits", heading: /^splits$/i },
  { path: "/versions", heading: /^versions$/i },
  { path: "/copilot", heading: /^copilot$/i },
  { path: "/settings", heading: /^settings$/i },
];

describe("APP-02 - seis pantallas de Dataset Quality", () => {
  it.each(DATASET_ROUTES)(
    "la ruta $path renderiza su título y no muestra un error de contrato",
    async ({ path: routePath, heading }) => {
      mockContractsFetch();

      render(
        <MemoryRouter initialEntries={[routePath]}>
          <App />
        </MemoryRouter>
      );

      expect(await screen.findByRole("heading", { level: 1, name: heading })).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /reintentar/i })).not.toBeInTheDocument();
    }
  );

  it("el nav de Dataset Quality navega entre las seis pantallas sin recargar", async () => {
    mockContractsFetch();

    render(
      <MemoryRouter initialEntries={["/overview"]}>
        <App />
      </MemoryRouter>
    );

    expect(
      await screen.findByRole("heading", { level: 1, name: /^overview$/i })
    ).toBeInTheDocument();

    for (const { heading } of DATASET_ROUTES.slice(1)) {
      const label = heading.source.replace(/[$^]/g, "");
      fireEvent.click(screen.getByRole("link", { name: new RegExp(label, "i") }));
      // Navegación secuencial pantalla por pantalla, a propósito: cada click
      // depende del DOM que dejó el anterior.
      expect(await screen.findByRole("heading", { level: 1, name: heading })).toBeInTheDocument();
    }
  });
});
