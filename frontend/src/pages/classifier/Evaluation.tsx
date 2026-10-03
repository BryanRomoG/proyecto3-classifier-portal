import { useEffect, useMemo, useState } from "react";
import {
  apiUrl,
  type EvaluationResponse,
  getEvaluation,
  getPredictions,
  PREDICTIONS_CSV_URL,
  type Prediction,
} from "@/lib/api/evaluation";

export function EvaluationPage() {
  const [data, setData] = useState<EvaluationResponse | null>(null);
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [filter, setFilter] = useState("errors");

  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const evaluation = await getEvaluation();
        setData(evaluation);
        if (!evaluation.locked) {
          setPredictions(await getPredictions());
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "No se pudo cargar la evaluación.");
      }
    }

    void load();
  }, []);

  const shown = useMemo(() => {
    if (filter === "all") return predictions;
    if (filter === "errors") return predictions.filter((row) => !row.correct);
    return predictions.filter((row) => row.trueLabel === filter);
  }, [predictions, filter]);

  if (error) {
    return (
      <main className="p-8">
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-700">{error}</div>
      </main>
    );
  }

  if (!data) {
    return <main className="p-8">Cargando evaluación...</main>;
  }

  if (data.locked) {
    return (
      <main className="flex-1 p-8">
        <div className="mx-auto max-w-4xl">
          <div className="rounded-2xl border border-amber-200 bg-amber-50 p-8">
            <p className="text-xs font-semibold uppercase tracking-wide text-amber-700">
              Test bloqueado
            </p>

            <h1 className="mt-2 text-2xl font-semibold text-amber-950">
              La evaluación final todavía no está disponible
            </h1>

            <p className="mt-3 text-sm text-amber-800">
              Primero debe cerrarse la selección del modelo candidato. Los resultados del test
              permanecen ocultos hasta ese momento.
            </p>

            <div className="mt-5 rounded-lg bg-white/70 p-4 text-sm">
              <div>
                Candidato seleccionado:
                <strong className="ml-2">{data.selection.runName}</strong>
              </div>

              <div className="mt-1">
                Run ID:
                <code className="ml-2">{data.selection.runId}</code>
              </div>
            </div>
          </div>
        </div>
      </main>
    );
  }

  const evaluation = data.evaluation;

  return (
    <main className="flex-1 p-8">
      <div className="mx-auto max-w-7xl">
        <header className="mb-6">
          <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
            Final evaluation
          </p>

          <h1 className="text-2xl font-semibold text-ink">Evaluation</h1>

          <p className="mt-1 text-sm text-ink-muted">
            Evaluación final del candidato seleccionado.
          </p>
        </header>

        <section className="mb-6 rounded-xl border border-border bg-surface p-5 shadow-card">
          <p className="text-xs text-ink-muted">Candidato seleccionado</p>

          <h2 className="mt-1 font-semibold text-ink">{data.selection.runName}</h2>

          <code className="mt-1 block text-xs text-ink-muted">{data.selection.runId}</code>
        </section>

        <section className="grid gap-4 md:grid-cols-5">
          <Metric label="Accuracy" value={`${(evaluation.accuracy * 100).toFixed(2)}%`} />

          <Metric label="Macro F1" value={`${(evaluation.macro_f1 * 100).toFixed(2)}%`} />

          <Metric label="Correct" value={`${evaluation.correct}/${evaluation.total}`} />

          <Metric label="Dataset" value={evaluation.dataset_version} />

          <Metric label="Manifiesto 70/20/10" value={`${data.manifest.sha256.slice(0, 12)}…`} />
        </section>

        <section className="mt-6 rounded-xl border border-border bg-surface p-5 shadow-card">
          <h2 className="mb-4 font-semibold text-ink">Confusion matrix</h2>

          <table className="border-collapse text-center text-sm">
            <tbody>
              <tr>
                <th className="border border-border p-3" />
                {evaluation.confusion_matrix.labels.map((label) => (
                  <th key={label} className="border border-border p-3">
                    Pred. {label}
                  </th>
                ))}
              </tr>

              {evaluation.confusion_matrix.matrix.map((row, rowIndex) => (
                <tr key={evaluation.confusion_matrix.labels[rowIndex]}>
                  <th className="border border-border p-3">
                    Real {evaluation.confusion_matrix.labels[rowIndex]}
                  </th>

                  {row.map((value, columnIndex) => (
                    <td
                      key={`${evaluation.confusion_matrix.labels[rowIndex]}-${evaluation.confusion_matrix.labels[columnIndex]}`}
                      className="border border-border p-4 font-semibold"
                    >
                      {value}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="mt-6 rounded-xl border border-border bg-surface p-5 shadow-card">
          <h2 className="mb-4 font-semibold text-ink">Metrics by class</h2>

          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="py-3">Class</th>
                <th>Precision</th>
                <th>Recall</th>
                <th>F1</th>
                <th>Support</th>
              </tr>
            </thead>

            <tbody>
              {Object.entries(evaluation.per_class).map(([className, metrics]) => (
                <tr key={className} className="border-b border-border">
                  <td className="py-3 font-medium">{className}</td>

                  <td>{(metrics.precision * 100).toFixed(2)}%</td>

                  <td>{(metrics.recall * 100).toFixed(2)}%</td>

                  <td>{(metrics.f1 * 100).toFixed(2)}%</td>

                  <td>{metrics.support}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="mt-6 rounded-xl border border-border bg-surface p-5 shadow-card">
          <h2 className="mb-1 font-semibold text-ink">Ejemplos del test</h2>
          <p className="mb-4 text-sm text-ink-muted">
            Recortes reales del split de test: aciertos con mayor confianza y todos los errores.
          </p>

          <div className="grid gap-6 md:grid-cols-2">
            {Object.entries(evaluation.examples).map(([className, examples]) => (
              <div key={className}>
                <h3 className="mb-3 font-medium">Clase real: {className}</h3>

                <p className="mb-2 text-xs font-medium uppercase text-red-700">
                  Errores ({examples.errors.length})
                </p>
                <div className="mb-4 grid grid-cols-3 gap-3">
                  {examples.errors.length === 0 && (
                    <p className="col-span-3 text-sm text-ink-muted">Sin errores en esta clase.</p>
                  )}
                  {examples.errors.map((example) => (
                    <ExampleCard key={example.annotation_id} example={example} wrong />
                  ))}
                </div>

                <p className="mb-2 text-xs font-medium uppercase text-green-700">Aciertos</p>
                <div className="grid grid-cols-3 gap-3">
                  {examples.correct.slice(0, 6).map((example) => (
                    <ExampleCard key={example.annotation_id} example={example} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="mt-6 rounded-xl border border-border bg-surface p-5 shadow-card">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="font-semibold text-ink">Predicciones por muestra</h2>
              <p className="text-sm text-ink-muted">
                Las {predictions.length} predicciones del test congelado, para auditoría.
              </p>
            </div>
            <div className="flex items-center gap-3">
              <select
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
                className="rounded-lg border border-border bg-surface px-3 py-2 text-sm"
              >
                <option value="errors">Solo errores</option>
                <option value="all">Todas</option>
                {evaluation.classes.map((name) => (
                  <option key={name} value={name}>
                    Clase real: {name}
                  </option>
                ))}
              </select>
              <a
                href={PREDICTIONS_CSV_URL}
                download
                className="rounded-lg border border-border px-3 py-2 text-sm font-medium text-ink hover:bg-canvas"
              >
                Exportar CSV
              </a>
            </div>
          </div>

          <div className="max-h-96 overflow-auto">
            <table className="w-full text-left text-sm">
              <thead className="sticky top-0 bg-surface">
                <tr className="border-b border-border">
                  <th className="py-2">Recorte</th>
                  <th>Anotación</th>
                  <th>Real</th>
                  <th>Predicha</th>
                  <th>Confianza</th>
                  <th>Resultado</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((row) => (
                  <tr key={row.annotationId} className="border-b border-border">
                    <td className="py-2">
                      <img
                        src={apiUrl(row.imageUrl)}
                        alt={`Recorte ${row.annotationId}`}
                        className="h-12 w-12 rounded object-cover"
                        loading="lazy"
                      />
                    </td>
                    <td>{row.annotationId}</td>
                    <td>{row.trueLabel}</td>
                    <td>{row.predictedLabel}</td>
                    <td>{(row.confidence * 100).toFixed(2)}%</td>
                    <td className={row.correct ? "text-green-700" : "font-medium text-red-700"}>
                      {row.correct ? "acierto" : "error"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-5 shadow-card">
      <p className="text-xs text-ink-muted">{label}</p>

      <strong className="mt-1 block text-xl text-ink">{value}</strong>
    </div>
  );
}

function ExampleCard({
  example,
  wrong = false,
}: {
  example: {
    annotation_id: number;
    true_label: string;
    predicted_label: string;
    confidence: number;
    imageUrl: string;
  };
  wrong?: boolean;
}) {
  return (
    <figure
      className={`overflow-hidden rounded-lg border ${wrong ? "border-red-300 bg-red-50" : "border-border bg-canvas"}`}
    >
      <img
        src={apiUrl(example.imageUrl)}
        alt={`Recorte ${example.annotation_id}`}
        className="aspect-square w-full object-cover"
        loading="lazy"
      />
      <figcaption className="p-2 text-xs">
        <div className="font-medium">
          Real {example.true_label} → Pred. {example.predicted_label}
        </div>
        <div className="text-ink-muted">
          {(example.confidence * 100).toFixed(1)}% · #{example.annotation_id}
        </div>
      </figcaption>
    </figure>
  );
}
