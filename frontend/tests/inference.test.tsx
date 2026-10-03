import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Inference } from "../src/pages/classifier/Inference";

const INFERENCE = {
  model: {
    runId: "run-real-123",
    runName: "resnet18-release",
    checkpointSha256: "a".repeat(64),
  },
  predictedClass: "car",
  confidence: 0.875,
  probabilities: { car: 0.875, person: 0.125 },
};

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

beforeEach(() => {
  vi.stubGlobal("URL", {
    ...URL,
    createObjectURL: vi.fn(() => "blob:preview"),
    revokeObjectURL: vi.fn(),
  });
});

describe("Inference T3-4.1", () => {
  it("usa annotationId del query param, muestra la respuesta real y encola el recorte", async () => {
    const fetchMock = vi.fn((url: string, _init?: RequestInit) => {
      if (url.endsWith("/inference/crop/queue")) {
        return Promise.resolve({
          ok: true,
          status: 201,
          json: async () => ({
            inference: INFERENCE,
            queuedImage: {
              id: 91,
              filename: "annotation-42.jpg",
              storageKey: "images/annotation-42.jpg",
              width: 120,
              height: 80,
            },
          }),
        } as Response);
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => INFERENCE } as Response);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter initialEntries={["/inference?annotationId=42"]}>
        <Inference />
      </MemoryRouter>
    );

    expect(screen.getByText("Anotación #42")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Ejecutar inferencia" }));

    expect(await screen.findAllByText("87.5%")).toHaveLength(2);
    expect(screen.getByText("resnet18-release")).toBeInTheDocument();
    expect(screen.getByText("run-real-123")).toBeInTheDocument();
    const inferenceCall = fetchMock.mock.calls[0];
    expect(inferenceCall).toBeDefined();
    expect(JSON.parse(inferenceCall?.[1]?.body as string)).toEqual({ annotationId: 42 });

    fireEvent.click(screen.getByRole("button", { name: "Enviar a cola de anotación" }));
    expect(await screen.findByText("Imagen añadida a la cola")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Abrir para anotar" })).toHaveAttribute(
      "href",
      "/annotate/91?queue=91"
    );
    const queueCall = fetchMock.mock.calls[1];
    expect(queueCall).toBeDefined();
    expect(JSON.parse(queueCall?.[1]?.body as string)).toEqual({ annotationId: 42 });
  });

  it("envía una imagen nueva como multipart en el campo file", async () => {
    const fetchMock = vi.fn((_url: string, _init?: RequestInit) =>
      Promise.resolve({ ok: true, status: 200, json: async () => INFERENCE } as Response)
    );
    vi.stubGlobal("fetch", fetchMock);
    render(
      <MemoryRouter>
        <Inference />
      </MemoryRouter>
    );

    const file = new File(["image"], "street.webp", { type: "image/webp" });
    fireEvent.change(screen.getByLabelText("Seleccionar imagen para inferencia"), {
      target: { files: [file] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Ejecutar inferencia" }));

    expect(await screen.findAllByText("87.5%")).toHaveLength(2);
    const requestCall = fetchMock.mock.calls[0];
    expect(requestCall).toBeDefined();
    const [url, init] = requestCall ?? [];
    expect(init).toBeDefined();
    expect(url).toContain("/api/inference/image");
    expect(init?.body).toBeInstanceOf(FormData);
    const formData = init?.body as FormData;
    expect(formData.get("file")).toBe(file);
    expect((init?.headers as Record<string, string> | undefined)?.["Content-Type"]).toBeUndefined();
  });

  it("muestra errores HTTP y no conserva un resultado anterior", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({
          ok: false,
          status: 503,
          json: async () => ({ error: "El servicio de inferencia no está disponible." }),
        } as Response)
      )
    );
    render(
      <MemoryRouter initialEntries={["/inference?annotationId=8"]}>
        <Inference />
      </MemoryRouter>
    );

    fireEvent.click(screen.getByRole("button", { name: "Ejecutar inferencia" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "El servicio de inferencia no está disponible."
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Ejecutar inferencia" })).toBeEnabled()
    );
    expect(screen.queryByText("Enviar a cola de anotación")).not.toBeInTheDocument();
  });
});
