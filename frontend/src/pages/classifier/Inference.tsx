import { CheckCircle2, ImagePlus, LoaderCircle, ScanSearch } from "lucide-react";
import { type ChangeEvent, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { validateImageFile } from "@/lib/api/images";
import {
  type InferenceResult,
  inferCrop,
  inferImage,
  queueCrop,
  queueImage,
} from "@/lib/api/inference";

type PendingAction = "infer" | "queue" | null;

function parseAnnotationId(raw: string | null): number | null {
  if (raw === null || !/^\d+$/.test(raw)) return null;
  const id = Number(raw);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}

function messageFrom(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

const percent = (value: number) => `${(value * 100).toFixed(1)}%`;

export function Inference() {
  const [searchParams, setSearchParams] = useSearchParams();
  const rawAnnotationId = searchParams.get("annotationId");
  const annotationId = useMemo(() => parseAnnotationId(rawAnnotationId), [rawAnnotationId]);
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [result, setResult] = useState<InferenceResult | null>(null);
  const [pending, setPending] = useState<PendingAction>(null);
  const [error, setError] = useState<string | null>(null);
  const [queuedImageId, setQueuedImageId] = useState<number | null>(null);

  useEffect(() => {
    if (!file) {
      setPreviewUrl(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const hasSource = file !== null || annotationId !== null;

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const nextFile = event.target.files?.[0] ?? null;
    if (!nextFile) return;
    const validationError = validateImageFile(nextFile);
    if (validationError) {
      event.target.value = "";
      setFile(null);
      setError(validationError);
      return;
    }
    setFile(nextFile);
    setResult(null);
    setQueuedImageId(null);
    setError(null);
  }

  async function handleInference() {
    if (!hasSource || pending) return;
    setPending("infer");
    setError(null);
    setQueuedImageId(null);
    try {
      setResult(file ? await inferImage(file) : await inferCrop(annotationId as number));
    } catch (requestError) {
      setResult(null);
      setError(messageFrom(requestError, "No se pudo ejecutar la inferencia."));
    } finally {
      setPending(null);
    }
  }

  async function handleQueue() {
    if (!result || !hasSource || pending) return;
    setPending("queue");
    setError(null);
    try {
      const response = file ? await queueImage(file) : await queueCrop(annotationId as number);
      setResult(response.inference);
      setQueuedImageId(response.queuedImage.id);
    } catch (requestError) {
      setError(messageFrom(requestError, "No se pudo enviar la imagen a la cola."));
    } finally {
      setPending(null);
    }
  }

  function useUploadedImageOnly() {
    const next = new URLSearchParams(searchParams);
    next.delete("annotationId");
    setSearchParams(next, { replace: true });
    setResult(null);
    setQueuedImageId(null);
    setError(null);
  }

  const probabilities = result
    ? Object.entries(result.probabilities).sort(([, left], [, right]) => right - left)
    : [];

  return (
    <main className="flex-1 p-6 md:p-8">
      <div className="mx-auto max-w-6xl">
        <header className="mb-6">
          <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
            Clasificador en producción
          </p>
          <h1 className="text-2xl font-semibold text-ink">Inference</h1>
          <p className="mt-1 text-sm text-ink-muted">
            Clasifica una imagen nueva o un recorte del portal con el modelo seleccionado.
          </p>
        </header>

        {error && (
          <div
            role="alert"
            className="mb-5 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700"
          >
            {error}
          </div>
        )}
        {rawAnnotationId !== null && annotationId === null && (
          <div
            role="alert"
            className="mb-5 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800"
          >
            El parámetro annotationId debe ser un entero positivo. Selecciona una imagen nueva.
          </div>
        )}

        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
          <section className="rounded-xl border border-border bg-surface p-5 shadow-card">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="font-semibold text-ink">Origen de la imagen</h2>
                <p className="mt-1 text-sm text-ink-muted">JPEG, PNG o WebP, máximo 5 MiB.</p>
              </div>
              {annotationId && !file && (
                <span className="rounded-full bg-accent-lilac-soft px-3 py-1 text-xs font-medium text-accent-lilac">
                  Recorte del portal
                </span>
              )}
            </div>

            {annotationId && !file && (
              <div className="mt-5 rounded-xl border border-accent-lilac/30 bg-accent-lilac-soft p-5 text-center">
                <ScanSearch className="mx-auto h-9 w-9 text-accent-lilac" aria-hidden="true" />
                <p className="mt-3 font-medium text-ink">Anotación #{annotationId}</p>
                <p className="mt-1 text-sm text-ink-muted">
                  Se recortará la caja guardada usando sus coordenadas originales.
                </p>
                <button
                  type="button"
                  onClick={useUploadedImageOnly}
                  className="mt-3 text-sm font-medium text-accent-lilac hover:underline"
                >
                  Usar una imagen nueva
                </button>
              </div>
            )}

            {previewUrl && (
              <div className="mt-5 overflow-hidden rounded-xl border border-border bg-canvas">
                <img
                  src={previewUrl}
                  alt={`Vista previa de ${file?.name ?? "imagen"}`}
                  className="h-64 w-full object-contain"
                />
              </div>
            )}

            {(!annotationId || file) && (
              <label className="mt-5 flex cursor-pointer flex-col items-center rounded-xl border-2 border-dashed border-border-strong bg-canvas px-5 py-8 text-center hover:border-accent-lilac">
                <ImagePlus className="h-8 w-8 text-accent-lilac" aria-hidden="true" />
                <span className="mt-2 text-sm font-medium text-ink">
                  {file ? "Cambiar imagen" : "Seleccionar imagen"}
                </span>
                <span className="mt-1 max-w-full truncate text-xs text-ink-muted">
                  {file?.name ?? "Ningún archivo seleccionado"}
                </span>
                <input
                  aria-label="Seleccionar imagen para inferencia"
                  className="sr-only"
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  onChange={handleFileChange}
                />
              </label>
            )}

            <button
              type="button"
              onClick={() => void handleInference()}
              disabled={!hasSource || pending !== null}
              className="mt-5 flex w-full items-center justify-center gap-2 rounded-lg bg-accent-lilac px-4 py-3 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
            >
              {pending === "infer" && (
                <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
              )}
              {pending === "infer" ? "Ejecutando inferencia..." : "Ejecutar inferencia"}
            </button>
            {(file || annotationId) && (
              <p className="mt-2 text-center text-xs text-ink-muted">
                Origen: {file?.name ?? `Anotación #${annotationId}`}
              </p>
            )}
          </section>

          <section
            aria-live="polite"
            className="rounded-xl border border-border bg-surface p-5 shadow-card"
          >
            <h2 className="font-semibold text-ink">Resultado</h2>
            {!result && pending !== "infer" && (
              <div className="flex min-h-64 flex-col items-center justify-center text-center text-sm text-ink-muted">
                <ScanSearch className="mb-3 h-9 w-9 text-ink-faint" aria-hidden="true" />
                El resultado validado aparecerá aquí.
              </div>
            )}
            {pending === "infer" && (
              <div className="flex min-h-64 flex-col items-center justify-center text-sm text-ink-muted">
                <LoaderCircle
                  className="mb-3 h-8 w-8 animate-spin text-accent-lilac"
                  aria-hidden="true"
                />
                Procesando con el modelo seleccionado...
              </div>
            )}

            {result && (
              <div className="mt-5">
                <div className="grid grid-cols-2 gap-3">
                  <ResultMetric label="Clase" value={result.predictedClass} tone="mint" />
                  <ResultMetric label="Confianza" value={percent(result.confidence)} tone="lilac" />
                </div>

                <div className="mt-5">
                  <h3 className="text-sm font-semibold text-ink">Probabilidades</h3>
                  <div className="mt-3 space-y-3">
                    {probabilities.map(([className, probability]) => (
                      <div key={className}>
                        <div className="mb-1 flex justify-between text-sm">
                          <span className="capitalize text-ink">{className}</span>
                          <span className="font-medium text-ink">{percent(probability)}</span>
                        </div>
                        <div className="h-2 overflow-hidden rounded-full bg-canvas">
                          <div
                            className="h-full rounded-full bg-accent-lilac"
                            style={{ width: percent(probability) }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <dl className="mt-5 rounded-lg border border-border bg-canvas p-4 text-sm">
                  <ModelField label="Modelo usado" value={result.model.runName} />
                  <ModelField label="Run ID" value={result.model.runId} mono />
                  {result.model.checkpointSha256 && (
                    <ModelField
                      label="Checkpoint"
                      value={result.model.checkpointSha256}
                      mono
                      truncate
                    />
                  )}
                </dl>

                {queuedImageId === null ? (
                  <button
                    type="button"
                    onClick={() => void handleQueue()}
                    disabled={pending !== null}
                    className="mt-5 flex w-full items-center justify-center gap-2 rounded-lg border border-accent-lilac px-4 py-3 text-sm font-semibold text-accent-lilac disabled:opacity-50"
                  >
                    {pending === "queue" && (
                      <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" />
                    )}
                    {pending === "queue" ? "Enviando a la cola..." : "Enviar a cola de anotación"}
                  </button>
                ) : (
                  <div
                    role="status"
                    className="mt-5 rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800"
                  >
                    <div className="flex items-center gap-2 font-medium">
                      <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                      Imagen añadida a la cola
                    </div>
                    <Link
                      className="mt-2 inline-block font-medium underline"
                      to={`/annotate/${queuedImageId}?queue=${queuedImageId}`}
                    >
                      Abrir para anotar
                    </Link>
                  </div>
                )}
              </div>
            )}
          </section>
        </div>
      </div>
    </main>
  );
}

function ResultMetric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "mint" | "lilac";
}) {
  return (
    <div
      className={`rounded-xl p-4 ${tone === "mint" ? "bg-accent-mint-soft" : "bg-accent-lilac-soft"}`}
    >
      <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold capitalize text-ink">{value}</p>
    </div>
  );
}

function ModelField({
  label,
  value,
  mono = false,
  truncate = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
  truncate?: boolean;
}) {
  return (
    <div className="mt-2 flex first:mt-0 justify-between gap-4">
      <dt className="text-ink-muted">{label}</dt>
      <dd
        title={value}
        className={`text-right text-ink ${mono ? "font-mono text-xs" : "font-medium"} ${truncate ? "max-w-48 truncate" : "break-all"}`}
      >
        {value}
      </dd>
    </div>
  );
}
