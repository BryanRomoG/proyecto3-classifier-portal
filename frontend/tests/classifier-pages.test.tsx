import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EvaluationPage } from "../src/pages/classifier/Evaluation";
import { ExperimentsPage } from "../src/pages/classifier/Experiments";
import { ModelsPage } from "../src/pages/classifier/Models";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function respond(body: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: async () => body } as Response);
}

function run(id: string, name: string, accuracy: number, valid: boolean, reasons: string[] = []) {
  return {
    runId: id,
    runName: name,
    status: "FINISHED",
    valid,
    invalidReasons: reasons,
    optimizer: "adam",
    batchSize: "32",
    epochs: "15",
    learningRate: "0.0003",
    imageSize: "128",
    hiddenLayers: "[256]",
    dropout: "0.3",
    bestValAccuracy: accuracy,
    bestValLoss: 0.1,
    bestEpoch: 5,
    stoppedEpoch: 9,
    datasetVersion: "v1.0.0",
    manifestSha256: "394743403f8a",
    startTime: 1,
    endTime: 2,
    curvesUrl: `/experiments/${id}/curves`,
  };
}

describe("Experiments (rúbrica 3.3, 6.2)", () => {
  it("muestra solo las válidas por defecto, ordena por columna y sirve curvas del backend", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        respond({
          experiments: [
            run("a", "r02-sgd", 0.93, true),
            run("b", "r06-epochs25", 0.98, false, ["identical final weights to run r01-base"]),
            run("c", "r03-adamw", 0.98, true),
          ],
        })
      )
    );

    render(<ExperimentsPage />);

    await screen.findByText("r03-adamw");
    expect(screen.queryByText("r06-epochs25")).not.toBeInTheDocument();
    expect(screen.getByText(/2 válidas de\s+3/)).toBeInTheDocument();

    const rows = () => screen.getAllByRole("row").slice(1);
    expect(within(rows()[0] as HTMLElement).getByText("r03-adamw")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Val acc/ }));
    expect(within(rows()[0] as HTMLElement).getByText("r02-sgd")).toBeInTheDocument();

    fireEvent.change(screen.getByDisplayValue("Solo válidas"), { target: { value: "all" } });
    expect(screen.getByText("r06-epochs25")).toBeInTheDocument();
    expect(screen.getByText("inválida")).toHaveAttribute(
      "title",
      "identical final weights to run r01-base"
    );

    fireEvent.click(screen.getAllByRole("button", { name: "Ver" })[0] as HTMLElement);
    const curves = await screen.findByAltText(/Curvas de/);
    expect(curves.getAttribute("src")).toMatch(/\/experiments\/.+\/curves$/);
    expect(curves.getAttribute("src")).not.toContain("mlflow");
  });
});

describe("Evaluation (rúbrica 4.4, 6.3)", () => {
  it("muestra el manifiesto, ejemplos con imagen incluido el error y exporta predicciones", async () => {
    const example = {
      annotation_id: 56,
      confidence: 0.89,
      correct: false,
      predicted_label: "car",
      relative_path: "data/processed/crops/person/56.png",
      source_image_id: 39,
      true_label: "person",
      imageUrl: "/evaluation/crops/56",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url.endsWith("/evaluation/predictions")) {
          return respond({
            predictions: [
              {
                annotationId: 56,
                sourceImageId: 39,
                relativePath: example.relative_path,
                trueLabel: "person",
                predictedLabel: "car",
                correct: false,
                confidence: 0.89,
                probabilities: { car: 0.89, person: 0.11 },
                imageUrl: "/evaluation/crops/56",
              },
            ],
          });
        }
        return respond({
          locked: false,
          selection: { runId: "run-1", runName: "r03", selectedAt: "t" },
          manifest: { datasetVersion: "v1.0.0", sha256: "394743403f8a263b" },
          evaluation: {
            accuracy: 0.989,
            macro_f1: 0.989,
            correct: 94,
            total: 95,
            classes: ["car", "person"],
            dataset_version: "v1.0.0",
            manifest_sha256: "394743403f8a263b",
            run_id: "run-1",
            selected_at: "t",
            evaluated_at: "t",
            confusion_matrix: {
              labels: ["car", "person"],
              matrix: [
                [54, 0],
                [1, 40],
              ],
              rows: "true",
              columns: "predicted",
            },
            per_class: {},
            examples: { person: { correct: [], errors: [example] } },
          },
        });
      })
    );

    render(<EvaluationPage />);

    expect(await screen.findByText("394743403f8a…")).toBeInTheDocument();
    expect(screen.getByText("Errores (1)")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getAllByAltText("Recorte 56")[0]).toHaveAttribute(
        "src",
        "/api/evaluation/crops/56"
      )
    );
    expect(screen.getByRole("link", { name: "Exportar CSV" })).toHaveAttribute(
      "href",
      "/api/evaluation/predictions.csv"
    );
  });
});

describe("Models (rúbrica 5.3, 6.4)", () => {
  it("separa las versiones publicadas en S3 de los runs y muestra VersionId y tarjeta", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url.endsWith("/models/versions")) {
          return respond({
            versions: [
              {
                version: "v1.0.0",
                runId: "run-1",
                runName: "r03-adamw",
                checkpointSha256: "fe1c",
                datasetVersion: "v1.0.0",
                manifestSha256: "394743403f8a263b",
                testMetrics: { accuracy: 0.9894, macro_f1: 0.9892 },
                dependencies: null,
                split: null,
                published: true,
                bucket: "dataset-releases-prod-1",
                s3Uri: "s3://dataset-releases-prod-1/t3-classifier/v1.0.0/",
                objects: [
                  {
                    name: "model.pt",
                    key: "t3-classifier/v1.0.0/model.pt",
                    size: 45304323,
                    versionId: "ep8YrgAJQz3E",
                    sha256: "fe1c2370cb9d811d",
                  },
                ],
                cardMarkdown: "# Model card v1.0.0",
                recordedAt: "2026-10-03T00:00:00Z",
                verifiedWith: "HeadObject",
                selected: true,
              },
            ],
          });
        }
        return respond({ models: [] });
      })
    );

    render(<ModelsPage />);

    expect(await screen.findByText("v1.0.0", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByText("publicada en S3")).toBeInTheDocument();
    expect(screen.getByText("ep8YrgAJQz3E")).toBeInTheDocument();
    expect(screen.getByText("Runs candidatos de MLflow")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Ver tarjeta" }));
    expect(screen.getByText("# Model card v1.0.0")).toBeInTheDocument();
  });
});
