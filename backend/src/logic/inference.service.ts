
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import crypto from "node:crypto";

import {
  getSelectedModel,
} from "./models.service.js";

const INFERENCE_SERVICE_URL =
  process.env.INFERENCE_SERVICE_URL ??
  "http://localhost:8000";

const MAX_IMAGE_SIZE =
  10 * 1024 * 1024;

const ALLOWED_TYPES = new Set([
  "image/jpeg",
  "image/png",
  "image/webp",
]);

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

interface PythonInferenceResponse {
  predictions: Prediction[];
  predicted_class: string;
  confidence: number;
}

function validateImage(
  buffer: Buffer,
  contentType: string,
) {
  if (!ALLOWED_TYPES.has(contentType)) {
    throw new Error(
      "Solo se permiten imágenes JPG, PNG o WebP.",
    );
  }

  if (buffer.length > MAX_IMAGE_SIZE) {
    throw new Error(
      "La imagen no puede superar los 10 MB.",
    );
  }
}

async function callInferenceService(
  imageBuffer: Buffer,
  contentType: string,
): Promise<PythonInferenceResponse> {
  const form = new FormData();

  const blob = new Blob(
    [imageBuffer],
    {
      type: contentType,
    },
  );

  form.append(
    "file",
    blob,
    `inference-${crypto.randomUUID()}.jpg`,
  );

  const response = await fetch(
    `${INFERENCE_SERVICE_URL}/predict`,
    {
      method: "POST",
      body: form,
    },
  );

  if (!response.ok) {
    const message =
      await response.text();

    throw new Error(
      `El servicio de inferencia respondió ${response.status}: ${message}`,
    );
  }

  return (await response.json()) as PythonInferenceResponse;
}

export async function predictImage(
  imageBuffer: Buffer,
  contentType: string,
): Promise<InferenceResult> {
  validateImage(
    imageBuffer,
    contentType,
  );


  const selected =
    await getSelectedModel();

  if (!selected) {
    throw new Error(
      "No hay un modelo seleccionado para inferencia.",
    );
  }

  /*
   * El servicio Python obtiene el model.pt
   * correspondiente al run seleccionado.
   */
  const prediction =
    await callInferenceService(
      imageBuffer,
      contentType,
    );

  return {
    runId: selected.runId,

    modelVersion:
      selected.runName,

    predictions:
      prediction.predictions,

    predictedClass:
      prediction.predicted_class,

    confidence:
      prediction.confidence,
  };
}


