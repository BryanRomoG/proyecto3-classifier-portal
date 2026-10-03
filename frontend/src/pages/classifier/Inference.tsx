
import {
  useEffect,
  useRef,
  useState,
} from "react";

import {
  predictImage,
  type InferenceResult,
} from "@/lib/api/inference";

interface PortalImage {
  id: string | number;
  name: string;
  url: string;
}

interface ImagesResponse {
  images?: Array<{
    id: string | number;
    originalName?: string | null;
    fileName?: string | null;
    name?: string | null;
    url?: string | null;
    publicUrl?: string | null;
    objectUrl?: string | null;
    src?: string | null;
  }>;
}

export function InferencePage() {
  const fileInputRef =
    useRef<HTMLInputElement | null>(
      null,
    );

  const [
    portalImages,
    setPortalImages,
  ] = useState<PortalImage[]>([]);

  const [
    selectedImage,
    setSelectedImage,
  ] = useState<PortalImage | null>(
    null,
  );

  const [
    preview,
    setPreview,
  ] = useState<string | null>(
    null,
  );

  const [
    selectedFile,
    setSelectedFile,
  ] = useState<File | null>(
    null,
  );

  const [
    result,
    setResult,
  ] = useState<InferenceResult | null>(
    null,
  );

  const [
    loading,
    setLoading,
  ] = useState(false);

  const [
    loadingImages,
    setLoadingImages,
  ] = useState(true);

  const [
    sendingToQueue,
    setSendingToQueue,
  ] = useState(false);

  const [
    message,
    setMessage,
  ] = useState("");

  const [
    error,
    setError,
  ] = useState("");

  useEffect(() => {
    void loadPortalImages();
  }, []);

  async function loadPortalImages() {
    try {
      setLoadingImages(true);

      const response =
        await fetch("/api/images");

      if (!response.ok) {
        throw new Error(
          "No se pudieron cargar las imágenes.",
        );
      }

      const data: ImagesResponse =
        await response.json();

      const images: PortalImage[] =
        (data.images ?? [])
          .map((image) => {
            const url =
              image.url ??
              image.publicUrl ??
              image.objectUrl ??
              image.src;

            if (!url) {
              return null;
            }

            return {
              id: image.id,
              name:
                image.originalName ??
                image.fileName ??
                image.name ??
                `image-${image.id}`,
              url,
            };
          })
          .filter(
            (
              image,
            ): image is PortalImage =>
              image !== null,
          );

      setPortalImages(images);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Error al cargar las imágenes.",
      );
    } finally {
      setLoadingImages(false);
    }
  }

  function selectPortalImage(
    image: PortalImage,
  ) {
    setSelectedImage(image);
    setSelectedFile(null);
    setPreview(image.url);
    setResult(null);
    setMessage("");
    setError("");
  }

  function selectLocalFile(
    file: File,
  ) {
    if (
      ![
        "image/jpeg",
        "image/png",
        "image/webp",
      ].includes(file.type)
    ) {
      setError(
        "Solo se permiten imágenes JPG, PNG o WebP.",
      );

      return;
    }

    if (
      file.size >
      10 * 1024 * 1024
    ) {
      setError(
        "La imagen no puede superar los 10 MB.",
      );

      return;
    }

    setSelectedFile(file);
    setSelectedImage(null);
    setPreview(
      URL.createObjectURL(file),
    );
    setResult(null);
    setMessage("");
    setError("");
  }

  async function runInference() {
    let file = selectedFile;

  
    if (!file && selectedImage) {
      const response =
        await fetch(selectedImage.url);

      if (!response.ok) {
        setError(
          "No se pudo obtener la imagen del portal.",
        );

        return;
      }

      const blob =
        await response.blob();

      file = new File(
        [blob],
        selectedImage.name,
        {
          type:
            blob.type ||
            "image/jpeg",
        },
      );
    }

    if (!file) {
      setError(
        "Selecciona una imagen primero.",
      );

      return;
    }

    try {
      setLoading(true);
      setError("");
      setMessage("");
      setResult(null);

      const prediction =
        await predictImage(file);

      setResult(prediction);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "No se pudo ejecutar la inferencia.",
      );
    } finally {
      setLoading(false);
    }
  }

  async function sendToAnnotationQueue() {
    if (!result) {
      return;
    }

    /*
     * La cola de anotación necesita una imagen
     * que exista en el portal.
     *
     * Si la imagen fue seleccionada desde el
     * portal, utilizamos directamente su ID.
     */
    if (!selectedImage) {
      setError(
        "Para enviar a la cola de anotación, "
        + "primero sube la imagen al portal o "
        + "selecciónala desde las imágenes existentes.",
      );

      return;
    }

    try {
      setSendingToQueue(true);
      setError("");
      setMessage("");

      const categoriesResponse =
        await fetch(
          "/api/categories",
        );

      if (!categoriesResponse.ok) {
        throw new Error(
          "No se pudieron cargar las categorías.",
        );
      }

      const categoriesData =
        await categoriesResponse.json();

      const category =
        categoriesData.categories?.find(
          (
            item: {
              id: number;
              name: string;
            },
          ) =>
            item.name.toLowerCase() ===
            result.predictedClass.toLowerCase(),
        );

      if (!category) {
        throw new Error(
          `No existe la categoría "${result.predictedClass}" en el portal.`,
        );
      }

      /*
       * Creamos una anotación REAL.
       *

       */
      const response =
        await fetch(
          `/api/images/${selectedImage.id}/annotations`,
          {
            method: "POST",

            headers: {
              "Content-Type":
                "application/json",
            },

            body: JSON.stringify({
              categoryId:
                category.id,

              /*
              
               */
              x: 0,
              y: 0,
              width: 1,
              height: 1,
            }),
          },
        );

      const data =
        await response.json();

      if (!response.ok) {
        throw new Error(
          data.error ??
            "No se pudo crear la anotación.",
        );
      }

      setMessage(
        `Elemento enviado a la cola de anotación. ID: ${data.annotation?.id ?? "creado"}`,
      );
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "No se pudo enviar a la cola.",
      );
    } finally {
      setSendingToQueue(false);
    }
  }

  return (
    <main className="flex-1 p-8">
      <div className="mx-auto max-w-7xl">
        <header className="mb-6">
          <p className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
            Classifier
          </p>

          <h1 className="text-2xl font-semibold text-ink">
            Inference
          </h1>

          <p className="mt-1 text-sm text-ink-muted">
            Ejecuta inferencia usando el modelo
            seleccionado.
          </p>
        </header>

        {error && (
          <div className="mb-5 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            {error}
          </div>
        )}

        {message && (
          <div className="mb-5 rounded-lg border border-green-200 bg-green-50 p-4 text-sm text-green-700">
            {message}
          </div>
        )}

        <div className="grid gap-6 lg:grid-cols-[1fr_1fr]">
          <section className="rounded-xl border border-border bg-surface p-5 shadow-card">
            <h2 className="font-semibold text-ink">
              Imagen
            </h2>

            <div className="mt-4">
              <button
                type="button"
                onClick={() =>
                  fileInputRef.current?.click()
                }
                className="rounded-lg border border-border px-4 py-2 text-sm font-medium hover:bg-canvas"
              >
                Subir imagen nueva
              </button>

              <input
                ref={fileInputRef}
                type="file"
                accept="image/jpeg,image/png,image/webp"
                className="hidden"
                onChange={(event) => {
                  const file =
                    event.target.files?.[0];

                  if (file) {
                    selectLocalFile(file);
                  }

                  event.target.value = "";
                }}
              />
            </div>

            {preview && (
              <div className="mt-5 overflow-hidden rounded-xl border border-border">
                <img
                  src={preview}
                  alt="Imagen para inferencia"
                  className="max-h-[500px] w-full object-contain"
                />
              </div>
            )}

            <button
              type="button"
              onClick={() =>
                void runInference()
              }
              disabled={
                loading ||
                (!selectedFile &&
                  !selectedImage)
              }
              className="mt-5 w-full rounded-lg bg-accent-lilac px-4 py-3 text-sm font-medium text-white disabled:opacity-50"
            >
              {loading
                ? "Ejecutando modelo..."
                : "Ejecutar inferencia"}
            </button>
          </section>

          <section className="rounded-xl border border-border bg-surface p-5 shadow-card">
            <h2 className="font-semibold text-ink">
              Imágenes del portal
            </h2>

            {loadingImages ? (
              <p className="mt-4 text-sm text-ink-muted">
                Cargando...
              </p>
            ) : portalImages.length ===
              0 ? (
              <p className="mt-4 text-sm text-ink-muted">
                No hay imágenes disponibles.
              </p>
            ) : (
              <div className="mt-4 grid max-h-[500px] gap-3 overflow-y-auto">
                {portalImages.map(
                  (image) => (
                    <button
                      type="button"
                      key={image.id}
                      onClick={() =>
                        selectPortalImage(
                          image,
                        )
                      }
                      className={`flex items-center gap-3 rounded-lg border p-2 text-left ${
                        selectedImage?.id ===
                        image.id
                          ? "border-accent-lilac bg-canvas"
                          : "border-border"
                      }`}
                    >
                      <img
                        src={image.url}
                        alt={image.name}
                        className="h-16 w-20 rounded object-cover"
                      />

                      <span className="truncate text-sm">
                        {image.name}
                      </span>
                    </button>
                  ),
                )}
              </div>
            )}
          </section>
        </div>

        {result && (
          <section className="mt-6 rounded-xl border border-border bg-surface p-5 shadow-card">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <p className="text-xs uppercase tracking-wide text-ink-muted">
                  Predicción
                </p>

                <h2 className="mt-1 text-3xl font-bold text-ink">
                  {result.predictedClass}
                </h2>

                <p className="mt-1 text-sm text-ink-muted">
                  Confianza:{" "}
                  {(result.confidence * 100).toFixed(
                    2,
                  )}
                  %
                </p>
              </div>

              <div className="text-right text-xs text-ink-muted">
                <div>
                  Modelo:{" "}
                  <strong>
                    {result.modelVersion}
                  </strong>
                </div>

                <div className="mt-1">
                  Run ID:{" "}
                  <code>
                    {result.runId}
                  </code>
                </div>
              </div>
            </div>

            <div className="mt-6 space-y-3">
              {result.predictions.map(
                (prediction) => (
                  <div
                    key={prediction.className}
                  >
                    <div className="mb-1 flex justify-between text-sm">
                      <span>
                        {prediction.className}
                      </span>

                      <span>
                        {(
                          prediction.probability *
                          100
                        ).toFixed(2)}
                        %
                      </span>
                    </div>

                    <div className="h-2 overflow-hidden rounded-full bg-canvas">
                      <div
                        className="h-full rounded-full bg-accent-lilac"
                        style={{
                          width: `${prediction.probability * 100}%`,
                        }}
                      />
                    </div>
                  </div>
                ),
              )}
            </div>

            {selectedImage && (
              <button
                type="button"
                onClick={() =>
                  void sendToAnnotationQueue()
                }
                disabled={
                  sendingToQueue
                }
                className="mt-6 rounded-lg border border-border px-4 py-3 text-sm font-medium hover:bg-canvas disabled:opacity-50"
              >
                {sendingToQueue
                  ? "Enviando..."
                  : "Enviar a cola de anotación"}
              </button>
            )}
          </section>
        )}
      </div>
    </main>
  );
}

