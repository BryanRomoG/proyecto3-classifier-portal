
export interface Prediction {
  className: string;
  probability: number;
}

export interface InferenceResult {
  runId: string;
  modelVersion: string;
  predictions: Prediction[];
  predictedClass: string;
  confidence: number;
}

export async function predictImage(
  file: File,
): Promise<InferenceResult> {
  const formData = new FormData();

  formData.append(
    "file",
    file,
  );

  const response = await fetch(
    "/api/inference",
    {
      method: "POST",
      body: formData,
    },
  );

  const data =
    await response.json();

  if (!response.ok) {
    throw new Error(
      data.error ??
        "No se pudo ejecutar la inferencia.",
    );
  }

  return data as InferenceResult;
}

