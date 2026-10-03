import type { Readable } from 'node:stream';

import sharp from 'sharp';

import { env } from '../config/env.js';
import { findAnnotationById, findImageById, getImageObjectStream } from '../data/index.js';
import { requestClassifierInference } from './classifier-inference.client.js';
import { NotFoundError, ValidationError } from './errors.js';
import {
  type UploadImageInput,
  type UploadImageResult,
  uploadImage,
} from './image-upload.service.js';
import { validateImageUpload } from './image-upload.validation.js';
import { getSelectedModel } from './models.service.js';

export interface InferenceFile {
  filename: string;
  mimeType: string;
  sizeBytes: number;
  buffer: Buffer;
}

export interface InferenceResult {
  model: {
    runId: string;
    runName: string;
    checkpointSha256: string;
  };
  predictedClass: string;
  confidence: number;
  probabilities: Record<string, number>;
}

export interface QueuedInferenceResult {
  inference: InferenceResult;
  queuedImage: UploadImageResult;
}

interface SelectedModelForInference {
  runId: string;
  runName: string;
  checkpointSha256: string | null;
}

export interface InferenceDependencies {
  getSelectedModel: () => Promise<SelectedModelForInference | null>;
  predict: typeof requestClassifierInference;
  findAnnotationById: typeof findAnnotationById;
  findImageById: typeof findImageById;
  getImageObjectStream: typeof getImageObjectStream;
  uploadImage: (input: UploadImageInput) => Promise<UploadImageResult>;
}

function validateFile(file: InferenceFile): void {
  if (
    !validateImageUpload(
      { mimeType: file.mimeType, sizeBytes: file.sizeBytes },
      env.MAX_UPLOAD_SIZE_BYTES,
    ).success
  ) {
    throw new ValidationError('La imagen no cumple con los requisitos de carga.');
  }

  if (file.buffer.length !== file.sizeBytes) {
    throw new ValidationError('El tamaño declarado de la imagen no coincide con sus bytes.');
  }
}

async function streamToBuffer(stream: Readable, maximumBytes: number): Promise<Buffer> {
  const chunks: Buffer[] = [];
  let total = 0;
  for await (const chunk of stream) {
    const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    total += bytes.length;
    if (total > maximumBytes) {
      stream.destroy();
      throw new ValidationError('La imagen excede el tamaño máximo permitido.');
    }
    chunks.push(bytes);
  }
  return Buffer.concat(chunks, total);
}

export function createInferenceService(dependencies: InferenceDependencies) {
  async function inferFile(file: InferenceFile): Promise<InferenceResult> {
    validateFile(file);
    const model = await dependencies.getSelectedModel();
    if (!model) {
      throw new NotFoundError('No hay un modelo seleccionado para inferencia.');
    }

    const prediction = await dependencies.predict({
      buffer: file.buffer,
      mimeType: file.mimeType,
      runId: model.runId,
    });

    if (prediction.model.runId !== model.runId) {
      throw new ValidationError('El servicio interno no utilizó el modelo seleccionado.');
    }

    if (model.checkpointSha256 && prediction.model.checkpointSha256 !== model.checkpointSha256) {
      throw new ValidationError('El checkpoint utilizado no coincide con el modelo seleccionado.');
    }

    return prediction;
  }

  async function getAnnotationCrop(annotationId: number): Promise<InferenceFile> {
    const annotation = await dependencies.findAnnotationById(annotationId);
    if (!annotation) throw new NotFoundError('La anotación no existe.');

    const image = await dependencies.findImageById(annotation.imageId);
    if (!image) throw new NotFoundError('La imagen de la anotación no existe.');

    const source = await streamToBuffer(
      await dependencies.getImageObjectStream(image.storageKey),
      env.MAX_UPLOAD_SIZE_BYTES,
    );
    const left = Math.max(0, Math.floor(annotation.bboxX));
    const top = Math.max(0, Math.floor(annotation.bboxY));
    const right = Math.min(image.width, Math.ceil(annotation.bboxX + annotation.bboxWidth));
    const bottom = Math.min(image.height, Math.ceil(annotation.bboxY + annotation.bboxHeight));
    if (right <= left || bottom <= top) {
      throw new ValidationError('La anotación no contiene un recorte válido.');
    }

    let buffer: Buffer;
    try {
      buffer = await sharp(source)
        .extract({ left, top, width: right - left, height: bottom - top })
        .png()
        .toBuffer();
    } catch {
      throw new ValidationError('No se pudo extraer el recorte de la anotación.');
    }

    return {
      filename: `annotation-${annotationId}.png`,
      mimeType: 'image/png',
      sizeBytes: buffer.length,
      buffer,
    };
  }

  async function inferImage(file: InferenceFile): Promise<InferenceResult> {
    return inferFile(file);
  }

  async function inferCrop(annotationId: number): Promise<InferenceResult> {
    return inferFile(await getAnnotationCrop(annotationId));
  }

  async function queueImage(file: InferenceFile): Promise<QueuedInferenceResult> {
    const inference = await inferFile(file);
    const queuedImage = await dependencies.uploadImage(file);
    return { inference, queuedImage };
  }

  async function queueCrop(annotationId: number): Promise<QueuedInferenceResult> {
    const crop = await getAnnotationCrop(annotationId);
    const inference = await inferFile(crop);
    const queuedImage = await dependencies.uploadImage(crop);
    return { inference, queuedImage };
  }

  return { inferImage, inferCrop, queueImage, queueCrop };
}

const inferenceService = createInferenceService({
  getSelectedModel,
  predict: requestClassifierInference,
  findAnnotationById,
  findImageById,
  getImageObjectStream,
  uploadImage,
});

export const { inferImage, inferCrop, queueImage, queueCrop } = inferenceService;
