import { randomUUID } from 'node:crypto';

import { env } from '../config/env.js';
import { ValidationError } from './errors.js';
import {
  type PythonInferenceResponse,
  pythonInferenceResponseSchema,
} from './inference.validation.js';

export interface ClassifierInferenceRequest {
  buffer: Buffer;
  mimeType: string;
  runId: string;
}

export interface ClassifierInferenceClientOptions {
  baseUrl: string;
  timeoutMs: number;
  fetchImpl?: typeof fetch;
}

/** Cliente para el único servicio de inferencia configurado por el servidor. */
export function createClassifierInferenceClient(options: ClassifierInferenceClientOptions) {
  const fetchImpl = options.fetchImpl ?? fetch;
  const predictUrl = new URL('/predict', options.baseUrl).toString();

  return async (request: ClassifierInferenceRequest): Promise<PythonInferenceResponse> => {
    const form = new FormData();
    // Copia a un ArrayBuffer propio: con los tipos de Node 26, Buffer puede
    // respaldarse en SharedArrayBuffer y no satisface directamente BlobPart.
    const bytes = Uint8Array.from(request.buffer);
    form.append('file', new Blob([bytes], { type: request.mimeType }), randomUUID());
    form.append('runId', request.runId);

    let response: Response;
    try {
      response = await fetchImpl(predictUrl, {
        method: 'POST',
        body: form,
        signal: AbortSignal.timeout(options.timeoutMs),
      });
    } catch (error) {
      throw new Error('El servicio interno de inferencia no está disponible.', { cause: error });
    }

    if (!response.ok) {
      throw new Error(`El servicio interno de inferencia respondió ${response.status}.`);
    }

    const parsed = pythonInferenceResponseSchema.safeParse(await response.json());
    if (!parsed.success) {
      throw new ValidationError('El servicio interno devolvió una predicción inválida.');
    }

    return parsed.data;
  };
}

export const requestClassifierInference = createClassifierInferenceClient({
  baseUrl: env.CLASSIFIER_INFERENCE_URL,
  timeoutMs: env.CLASSIFIER_INFERENCE_TIMEOUT_MS,
});
