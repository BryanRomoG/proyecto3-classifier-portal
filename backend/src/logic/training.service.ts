import { z } from 'zod';
import {
  createTrainingJob,
  getLatestTrainingJob,
  getTrainingJob,
} from '../data/repositories/training.repository.js';
import {
  createTrainerJob,
  getTrainerProvenance,
  type TrainerConfig,
  type TrainerFieldError,
} from '../data/trainer.client.js';
import { syncTrainingJob, trainerViewToJobUpdate } from './training.worker.js';

/**
 * Forma del cuerpo que manda la página Training. Solo se comprueban los tipos: las reglas
 * (rangos, optimizadores válidos, ancho de las capas ocultas) son las del entrenador y las
 * aplica el servicio `trainer` con su `TrainingConfig`, para que la UI nunca acepte un valor
 * que el entrenador rechazaría ni muestre un parámetro que el entrenador ignore.
 */
export const trainingConfigSchema = z.object({
  optimizer: z.string().min(1),
  batchSize: z.number(),
  epochs: z.number(),
  learningRate: z.number(),
  imageSize: z.number(),
  hiddenLayers: z.array(z.number()),
  dropout: z.number(),
});

export type TrainingConfig = z.infer<typeof trainingConfigSchema>;

/** El trainer rechazó el trabajo antes de crearlo (422 config inválida, 409 compuerta). */
export class TrainingRejectedError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly errors: TrainerFieldError[] = [],
  ) {
    super(message);
    this.name = 'TrainingRejectedError';
  }
}

const FIELD_NAMES: Record<string, string> = {
  batch_size: 'batchSize',
  max_epochs: 'epochs',
  learning_rate: 'learningRate',
  image_size: 'imageSize',
  hidden_layers: 'hiddenLayers',
};

export function toTrainerConfig(config: TrainingConfig): TrainerConfig {
  return {
    optimizer: config.optimizer.toLowerCase(),
    batch_size: config.batchSize,
    max_epochs: config.epochs,
    learning_rate: config.learningRate,
    image_size: config.imageSize,
    hidden_layers: config.hiddenLayers,
    dropout: config.dropout,
  };
}

/** Nombres de campo del trainer (`batch_size`, `hidden_layers.0`) a los del formulario. */
export function toFormFieldErrors(errors: TrainerFieldError[]): TrainerFieldError[] {
  return errors.map((error) => {
    const [head = '', ...rest] = error.field.split('.');
    const field = [FIELD_NAMES[head] ?? head, ...rest].join('.');
    return { field, message: error.message };
  });
}

export async function createTrainingRun(input: TrainingConfig): Promise<number> {
  const config = trainingConfigSchema.parse(input);
  const { status, body } = await createTrainerJob(toTrainerConfig(config));

  if (status === 422 || status === 409 || status === 400) {
    throw new TrainingRejectedError(
      body.error ?? 'El entrenador rechazó la configuración.',
      status === 409 ? 409 : 400,
      toFormFieldErrors(body.errors ?? []),
    );
  }
  if (status !== 202) {
    throw new Error(`El servicio trainer respondió ${status}: ${body.error ?? 'sin detalle'}`);
  }

  // Solo aquí, con el trabajo real ya lanzado por el trainer, se crea la fila. Estado,
  // época, progreso y logs salen de la vista que devolvió el trainer.
  const update = trainerViewToJobUpdate(body);
  return createTrainingJob({
    ...update,
    logs: update.logs ?? `Trabajo ${body.job_id} creado en el trainer.`,
    optimizer: config.optimizer.toLowerCase(),
    batchSize: config.batchSize,
    epochs: config.epochs,
    learningRate: config.learningRate,
    imageSize: config.imageSize,
    hiddenLayers: JSON.stringify(config.hiddenLayers),
    dropout: config.dropout,
    trainerJobId: body.job_id,
    datasetVersion: body.provenance?.dataset_version ?? null,
    qualityGateStatus: body.provenance?.quality_gate_status ?? null,
    manifestSha256: body.provenance?.manifest_sha256 ?? null,
  });
}

export async function getTrainingRun(id: number) {
  await syncTrainingJob(id);
  return getTrainingJob(id);
}

export async function getLatestTrainingRun() {
  const latest = await getLatestTrainingJob();
  if (!latest) {
    return null;
  }
  await syncTrainingJob(latest.id);
  return getTrainingJob(latest.id);
}

export async function getTrainingProvenance() {
  const { status, body } = await getTrainerProvenance();
  if (status !== 200) {
    throw new TrainingRejectedError(body.error ?? 'Procedencia no disponible.', 409);
  }
  return body;
}
