import { describe, expect, it } from 'vitest';

import type { TrainerJobView } from '../src/data/trainer.client.js';
import { toFormFieldErrors, toTrainerConfig } from '../src/logic/training.service.js';
import { trainerViewToJobUpdate } from '../src/logic/training.worker.js';

/**
 * T3-2.3 / T3-2.4 (rúbrica 2.2, 6.1): el formulario de Training habla el idioma del
 * entrenador real (servicio `trainer`), y el estado del trabajo se refleja tal cual.
 */

const VIEW: TrainerJobView = {
  job_id: 'abc123',
  state: 'running',
  created_at: '2026-10-02T10:00:00+00:00',
  started_at: '2026-10-02T10:00:05+00:00',
  finished_at: null,
  run_id: 'run-1',
  epoch: 3,
  max_epochs: 10,
  progress: 30,
  last_metrics: { val_accuracy: 0.9 },
  best_epoch: 3,
  best_val_accuracy: 0.9,
  error: null,
  log_tail: '[train] epoch 3: ...',
  provenance: null,
};

describe('Training: formulario → trainer', () => {
  it('envía los 7 hiperparámetros con los nombres y el optimizador del entrenador', () => {
    expect(
      toTrainerConfig({
        optimizer: 'AdamW',
        batchSize: 16,
        epochs: 4,
        learningRate: 0.0001,
        imageSize: 160,
        hiddenLayers: [512, 128],
        dropout: 0.5,
      }),
    ).toEqual({
      optimizer: 'adamw',
      batch_size: 16,
      max_epochs: 4,
      learning_rate: 0.0001,
      image_size: 160,
      hidden_layers: [512, 128],
      dropout: 0.5,
    });
  });

  it('traduce los errores por campo del trainer a los campos del formulario', () => {
    expect(
      toFormFieldErrors([
        { field: 'batch_size', message: 'Input should be greater than or equal to 1' },
        { field: 'hidden_layers', message: 'each hidden layer width must be in [8, 4096]' },
        { field: 'max_epochs', message: 'too big' },
        { field: 'dropout', message: 'Input should be less than 1' },
      ]),
    ).toEqual([
      { field: 'batchSize', message: 'Input should be greater than or equal to 1' },
      { field: 'hiddenLayers', message: 'each hidden layer width must be in [8, 4096]' },
      { field: 'epochs', message: 'too big' },
      { field: 'dropout', message: 'Input should be less than 1' },
    ]);
  });
});

describe('Training: estado del trainer → training_jobs', () => {
  it('refleja época, progreso, run de MLflow y logs de un trabajo en curso', () => {
    const update = trainerViewToJobUpdate(VIEW);

    expect(update.status).toBe('running');
    expect(update.currentEpoch).toBe(3);
    expect(update.progress).toBe(30);
    expect(update.mlflowRunId).toBe('run-1');
    expect(update.logs).toBe('[train] epoch 3: ...');
    expect(update.errorMessage).toBeNull();
    expect(update.startedAt).toEqual(new Date('2026-10-02T10:00:05+00:00'));
  });

  it('marca como completado o fallido con el error del trainer', () => {
    expect(trainerViewToJobUpdate({ ...VIEW, state: 'finished', progress: 100 }).status).toBe(
      'completed',
    );
    const failed = trainerViewToJobUpdate({
      ...VIEW,
      state: 'failed',
      error: 'RuntimeError: boom',
      finished_at: '2026-10-02T10:01:00+00:00',
    });
    expect(failed.status).toBe('failed');
    expect(failed.errorMessage).toBe('RuntimeError: boom');
    expect(failed.finishedAt).toEqual(new Date('2026-10-02T10:01:00+00:00'));
  });

  it('no borra los logs guardados cuando el trainer aún no escribió ninguno', () => {
    expect('logs' in trainerViewToJobUpdate({ ...VIEW, log_tail: '' })).toBe(false);
  });
});
