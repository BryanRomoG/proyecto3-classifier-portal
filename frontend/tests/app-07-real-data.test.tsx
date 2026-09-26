import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AnalyzersPage } from "../src/pages/dataset/Analyzers";
import { CopilotPage } from "../src/pages/dataset/Copilot";
import { OverviewPage } from "../src/pages/dataset/Overview";
import { SettingsPage } from "../src/pages/dataset/Settings";
import { SplitsPage } from "../src/pages/dataset/Splits";
import { VersionsPage } from "../src/pages/dataset/Versions";

/**
 * APP-07 — reemplaza los mocks estáticos de contracts/*.json por las rutas
 * reales del backend (SPEC-PIPE-001). Dos cosas a cubrir que APP-02/APP-05
 * no probaban porque todavía no existían:
 *
 * - Cada pantalla de solo lectura pide su ruta real (/quality-report,
 *   /split-report, /version-history) y NO /contracts/*.json — si alguien
 *   revierte el hook a `useContractFetch` por error, esto falla.
 * - Settings persiste de verdad: el botón "Guardar" manda un PUT a
 *   /quality-policy con el conjunto COMPLETO de checks (spec regla 5), y
 *   refleja tanto el éxito como un rechazo del backend (p. ej. bajar
 *   min_images_per_class de 300, spec regla 6).
 *
 * Copilot (APP-10) ya no entra en el describe.each de arriba: a diferencia
 * de las otras cinco pantallas, deja de hacer fetch al montar -- ahora es un
 * chat real que solo llama a POST /copilot-api/query cuando el usuario manda una
 * pregunta (ver Copilot.tsx y lib/api/copilot.ts). Sus propios tests están
 * más abajo, junto a los de Settings.
 */

const QUALITY_REPORT_FIXTURE = {
  dataset_version: "v-test-1",
  generated_at: "2026-09-17T00:00:00Z",
  overall_status: "fail",
  dataset_summary: { total_images: 1, total_bounding_boxes: 1, total_categories: 1 },
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
  ],
};

const SPLIT_REPORT_FIXTURE = {
  dataset_version: "v-test-1",
  generated_at: "2026-09-17T00:00:00Z",
  seed: 42,
  proportions: { train: 0.7, val: 0.15, test: 0.15 },
  tolerance: 0.02,
  totals: { images: 10, train: 7, val: 2, test: 1 },
  class_distribution: { train: {}, val: {}, test: {} },
  leakage_check: {
    status: "pass",
    leaked_pairs: 0,
    near_duplicate_pairs_checked: 0,
    near_duplicate_pairs_same_split: 0,
  },
  reproducibility_check: { status: "pass", note: "ok" },
};

const VERSION_HISTORY_FIXTURE = {
  current_version: "v1.0.0",
  versions: [
    {
      version: "v1.0.0",
      released_at: "2026-09-17T00:00:00Z",
      content_hash: "sha256:abc",
      quality_status: "pass",
      environments: {
        dev: { provider: "minio", status: "synced", synced_at: null },
        prod: { provider: "minio", status: "synced", synced_at: null },
      },
      diff_from_previous: null,
    },
  ],
};

const QUALITY_POLICY_FIXTURE = {
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

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function mockFetchByRoute(bodies: Record<string, unknown>) {
  const fetchMock = vi.fn((url: string) => {
    const routeName = Object.keys(bodies).find((name) => url.includes(name));
    if (!routeName) {
      return Promise.resolve({ ok: false, status: 404, json: async () => ({}) } as Response);
    }
    return Promise.resolve({
      ok: true,
      status: 200,
      json: async () => bodies[routeName],
    } as Response);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe.each([
  { name: "Overview", Page: OverviewPage, route: "quality-report" },
  { name: "Analyzers", Page: AnalyzersPage, route: "quality-report" },
  { name: "Splits", Page: SplitsPage, route: "split-report" },
  { name: "Versions", Page: VersionsPage, route: "version-history" },
])("$name pide datos reales de la pipeline (APP-07)", ({ Page, route }) => {
  it(`hace fetch a /${route}, no a /contracts/*.json`, async () => {
    const fetchMock = mockFetchByRoute({
      "quality-report": QUALITY_REPORT_FIXTURE,
      "split-report": SPLIT_REPORT_FIXTURE,
      "version-history": VERSION_HISTORY_FIXTURE,
    });

    render(
      <MemoryRouter>
        <Page />
      </MemoryRouter>
    );

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());

    const [requestedUrl] = fetchMock.mock.calls[0] as [string];
    expect(requestedUrl).toContain(route);
    expect(requestedUrl).not.toContain("/contracts/");
  });
});

describe("Settings persiste contra /quality-policy (APP-07)", () => {
  it("el botón Guardar está deshabilitado hasta que hay una edición", async () => {
    mockFetchByRoute({ "quality-policy": QUALITY_POLICY_FIXTURE });

    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>
    );

    const saveButton = await screen.findByRole("button", { name: /guardar/i });
    expect(saveButton).toBeDisabled();

    const thresholdInput = screen.getAllByLabelText(/umbral/i)[0] as HTMLInputElement;
    fireEvent.change(thresholdInput, { target: { value: "4.5" } });

    expect(saveButton).not.toBeDisabled();
  });

  it("Guardar manda PUT con TODOS los checks (editados y sin tocar) y muestra éxito", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.includes("quality-policy") && init?.method === "PUT") {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => QUALITY_POLICY_FIXTURE,
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => QUALITY_POLICY_FIXTURE,
      } as Response);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>
    );

    // Solo se edita class_imbalance; min_images_per_class debe ir igual en el body.
    const thresholdInputs = await screen.findAllByLabelText(/umbral/i);
    fireEvent.change(thresholdInputs[1] as HTMLInputElement, { target: { value: "4.5" } });

    fireEvent.click(screen.getByRole("button", { name: /guardar/i }));

    await screen.findByText(/cambios guardados/i);

    const putCall = fetchMock.mock.calls.find(
      ([, init]) => (init as RequestInit | undefined)?.method === "PUT"
    );
    expect(putCall).toBeDefined();
    const putInit = putCall?.[1] as RequestInit;
    const body = JSON.parse(putInit.body as string);
    expect(Object.keys(body).sort()).toEqual(["class_imbalance", "min_images_per_class"]);
    expect(body.class_imbalance).toEqual({ threshold: 4.5, severity: "warn" });
    expect(body.min_images_per_class).toEqual({ threshold: 300, severity: "fail" });
  });

  it("muestra el error del backend cuando el PUT es rechazado (p. ej. min_images_per_class < 300)", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.includes("quality-policy") && init?.method === "PUT") {
        return Promise.resolve({
          ok: false,
          status: 400,
          json: async () => ({ error: "min_images_per_class no puede bajar de 300." }),
        } as Response);
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => QUALITY_POLICY_FIXTURE,
      } as Response);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter>
        <SettingsPage />
      </MemoryRouter>
    );

    const thresholdInput = (await screen.findAllByLabelText(/umbral/i))[0] as HTMLInputElement;
    fireEvent.change(thresholdInput, { target: { value: "100" } });
    fireEvent.click(screen.getByRole("button", { name: /guardar/i }));

    expect(await screen.findByText(/no puede bajar de 300/i)).toBeInTheDocument();
  });
});

describe("Copilot chat real contra POST /copilot-api/query (APP-10)", () => {
  async function askQuestion(question: string) {
    const textbox = screen.getByLabelText(/pregunta para el copilot/i);
    fireEvent.change(textbox, { target: { value: question } });
    fireEvent.click(screen.getByRole("button", { name: /enviar/i }));
  }

  it("manda la pregunta a POST /copilot-api/query y muestra la respuesta con su versión de dataset y tools_used", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      // /copilot-api, no /copilot: ese prefijo colisionaría con la ruta de
      // esta misma pantalla en React Router -- ver el comentario en
      // lib/api/copilot.ts y frontend/docker/nginx.conf (bug real que
      // encontramos probando en vivo: nginx interceptaba /copilot antes de
      // que le tocara a la SPA, y su redirect automático perdía el puerto).
      expect(url).toContain("/copilot-api/query");
      expect(init?.method).toBe("POST");
      return Promise.resolve({
        ok: true,
        status: 200,
        json: async () => ({
          answer: "El release no está bloqueado.",
          dataset_version: "v1.0.0",
          tools_used: ["get_release_status"],
        }),
      } as Response);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter>
        <CopilotPage />
      </MemoryRouter>
    );

    await askQuestion("¿el release está bloqueado?");

    expect(await screen.findByText("El release no está bloqueado.")).toBeInTheDocument();
    expect(screen.getByText(/dataset v1\.0\.0/i)).toBeInTheDocument();
    expect(screen.getByText("get_release_status")).toBeInTheDocument();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({ question: "¿el release está bloqueado?" });
  });

  it("no inventa una versión de dataset cuando el agente respondió sin invocar tools (dataset_version: null)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            answer: "No tengo suficiente información.",
            dataset_version: null,
            tools_used: [],
          }),
        } as Response)
      )
    );

    render(
      <MemoryRouter>
        <CopilotPage />
      </MemoryRouter>
    );

    await askQuestion("¿cuántos elefantes hay en el dataset?");

    expect(await screen.findByText("No tengo suficiente información.")).toBeInTheDocument();
    // La insignia de versión ("dataset v1.0.0", ver ChatBubble en Copilot.tsx)
    // no debe aparecer -- solo el encabezado fijo de la pantalla menciona
    // "Dataset Copilot", que no coincide con este patrón más específico.
    expect(screen.queryByText(/^dataset v/i)).not.toBeInTheDocument();
  });

  it("muestra un mensaje de error corto (nunca un traceback) cuando el provider falla (502)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({
          ok: false,
          status: 502,
          json: async () => ({ error: "El proveedor del Copilot no respondió. Intenta de nuevo." }),
        } as Response)
      )
    );

    render(
      <MemoryRouter>
        <CopilotPage />
      </MemoryRouter>
    );

    await askQuestion("¿está bloqueado el release?");

    expect(
      await screen.findByText("El proveedor del Copilot no respondió. Intenta de nuevo.")
    ).toBeInTheDocument();
  });
});
