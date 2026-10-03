import { useEffect, useState } from "react";
import { type EvaluationResponse, getEvaluation } from "@/lib/api/evaluation";

export function EvaluationPage() {
  const [data, setData] = useState<EvaluationResponse | null>(null);

  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        setData(await getEvaluation());
      } catch (err) {
        setError(err instanceof Error ? err.message : "No se pudo cargar la evaluación.");
      }
    }

    void load();
  }, []);

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

        <section className="grid gap-4 md:grid-cols-4">
          <Metric label="Accuracy" value={`${(evaluation.accuracy * 100).toFixed(2)}%`} />

          <Metric label="Macro F1" value={`${(evaluation.macro_f1 * 100).toFixed(2)}%`} />

          <Metric label="Correct" value={`${evaluation.correct}/${evaluation.total}`} />

          <Metric label="Dataset" value={evaluation.dataset_version} />
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
          <h2 className="mb-4 font-semibold text-ink">Test examples</h2>

          <div className="grid gap-6 md:grid-cols-2">
            {Object.entries(evaluation.examples).map(([className, examples]) => (
              <div key={className}>
                <h3 className="mb-3 font-medium">{className}</h3>

                <div className="space-y-2">
                  {examples.correct.slice(0, 5).map((example) => (
                    <div key={example.annotation_id} className="rounded-lg bg-canvas p-3 text-sm">
                      <div className="font-medium">{example.predicted_label}</div>

                      <div className="text-xs text-ink-muted">
                        Confidence: {(example.confidence * 100).toFixed(2)}%
                      </div>

                      <div className="text-xs text-ink-faint">{example.relative_path}</div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
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
