import { Readable } from 'node:stream';

import sharp from 'sharp';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../src/config/env.js', () => ({
  env: {
    MAX_UPLOAD_SIZE_BYTES: 5 * 1024 * 1024,
    CLASSIFIER_INFERENCE_URL: 'http://classifier-inference:8300',
    CLASSIFIER_INFERENCE_TIMEOUT_MS: 30_000,
  },
}));
vi.mock('../src/data/index.js', () => ({
  findAnnotationById: vi.fn(),
  findImageById: vi.fn(),
  getImageObjectStream: vi.fn(),
}));
vi.mock('../src/logic/models.service.js', () => ({ getSelectedModel: vi.fn() }));
vi.mock('../src/logic/image-upload.service.js', () => ({ uploadImage: vi.fn() }));

import { createClassifierInferenceClient } from '../src/logic/classifier-inference.client.js';
import {
  createInferenceService,
  type InferenceDependencies,
} from '../src/logic/inference.service.js';

const model = {
  runId: 'run-selected',
  runName: 'candidate-r07',
  checkpointSha256: 'a'.repeat(64),
};
const prediction = {
  model,
  predictedClass: 'car',
  confidence: 0.8,
  probabilities: { car: 0.8, person: 0.2 },
};
const queuedImage = {
  id: 41,
  filename: 'new.png',
  storageKey: 'images/real-object',
  width: 2,
  height: 2,
};

function dependencies(overrides: Partial<InferenceDependencies> = {}): InferenceDependencies {
  return {
    getSelectedModel: vi.fn().mockResolvedValue(model),
    predict: vi.fn().mockResolvedValue(prediction),
    findAnnotationById: vi.fn(),
    findImageById: vi.fn(),
    getImageObjectStream: vi.fn(),
    uploadImage: vi.fn().mockResolvedValue(queuedImage),
    ...overrides,
  };
}

describe('T3-4.1 - inferencia backend', () => {
  beforeEach(() => vi.clearAllMocks());

  it('envía los bytes y el run seleccionado al servicio Python interno', async () => {
    const deps = dependencies();
    const service = createInferenceService(deps);
    const buffer = Buffer.from('real image bytes');

    await expect(
      service.inferImage({
        filename: 'sample.png',
        mimeType: 'image/png',
        sizeBytes: buffer.length,
        buffer,
      }),
    ).resolves.toEqual(prediction);

    expect(deps.predict).toHaveBeenCalledWith({
      buffer,
      mimeType: 'image/png',
      runId: 'run-selected',
    });
  });

  it('encola exactamente los mismos bytes reutilizando uploadImage', async () => {
    const deps = dependencies();
    const service = createInferenceService(deps);
    const file = {
      filename: 'new.png',
      mimeType: 'image/png',
      sizeBytes: 5,
      buffer: Buffer.from('bytes'),
    };

    await expect(service.queueImage(file)).resolves.toEqual({
      inference: prediction,
      queuedImage,
    });
    expect(deps.uploadImage).toHaveBeenCalledOnce();
    expect(deps.uploadImage).toHaveBeenCalledWith(file);
  });

  it('extrae el recorte real y usa esos mismos bytes para inferir y encolar', async () => {
    const source = await sharp({
      create: { width: 4, height: 4, channels: 3, background: '#336699' },
    })
      .png()
      .toBuffer();
    const deps = dependencies({
      findAnnotationById: vi.fn().mockResolvedValue({
        id: 9,
        imageId: 3,
        categoryId: 1,
        bboxX: 1,
        bboxY: 1,
        bboxWidth: 2,
        bboxHeight: 2,
        area: 4,
        iscrowd: false,
        category: { id: 1, name: 'car', color: '#fff000' },
      }),
      findImageById: vi.fn().mockResolvedValue({
        id: 3,
        filename: 'source.png',
        storageKey: 'images/source',
        mimeType: 'image/png',
        width: 4,
        height: 4,
        sizeBytes: source.length,
        status: 'completed',
        createdAt: new Date(),
        updatedAt: new Date(),
      }),
      getImageObjectStream: vi.fn().mockResolvedValue(Readable.from(source)),
    });

    await createInferenceService(deps).queueCrop(9);

    const predictionInput = vi.mocked(deps.predict).mock.calls[0]?.[0];
    const uploadInput = vi.mocked(deps.uploadImage).mock.calls[0]?.[0];
    expect(predictionInput?.buffer.equals(uploadInput?.buffer ?? Buffer.alloc(0))).toBe(true);
    expect(uploadInput?.filename).toBe('annotation-9.png');
    expect(uploadInput?.mimeType).toBe('image/png');
    await expect(sharp(uploadInput?.buffer).metadata()).resolves.toMatchObject({
      width: 2,
      height: 2,
    });
  });

  it('rechaza antes de inferir si el tamaño declarado no coincide con los bytes', async () => {
    const deps = dependencies();
    await expect(
      createInferenceService(deps).inferImage({
        filename: 'bad.png',
        mimeType: 'image/png',
        sizeBytes: 99,
        buffer: Buffer.from('short'),
      }),
    ).rejects.toThrow('no coincide');
    expect(deps.predict).not.toHaveBeenCalled();
  });

  it('rechaza una respuesta que haya usado un run distinto del seleccionado', async () => {
    const deps = dependencies({
      predict: vi.fn().mockResolvedValue({
        ...prediction,
        model: { ...model, runId: 'different-run' },
      }),
    });
    const buffer = Buffer.from('bytes');

    await expect(
      createInferenceService(deps).inferImage({
        filename: 'sample.png',
        mimeType: 'image/png',
        sizeBytes: buffer.length,
        buffer,
      }),
    ).rejects.toThrow('modelo seleccionado');
    expect(deps.uploadImage).not.toHaveBeenCalled();
  });

  it('construye siempre /predict desde configuración y no desde el request', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(prediction), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );
    const client = createClassifierInferenceClient({
      baseUrl: 'http://classifier-inference:8300/internal/base',
      timeoutMs: 1_000,
      fetchImpl,
    });

    await client({ buffer: Buffer.from('x'), mimeType: 'image/png', runId: 'selected-run' });

    expect(fetchImpl).toHaveBeenCalledWith(
      'http://classifier-inference:8300/predict',
      expect.objectContaining({ method: 'POST' }),
    );
    const form = fetchImpl.mock.calls[0]?.[1]?.body as FormData;
    expect(form.get('runId')).toBe('selected-run');
    expect(form.get('file')).toBeInstanceOf(Blob);
  });
});
