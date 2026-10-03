import { describe, expect, it, vi } from 'vitest';

vi.mock('../src/data/mlflow.client.js', () => ({
  getArtifact: vi.fn(),
  getClassifierRun: vi.fn(),
  getClassifierRuns: vi.fn(),
}));
vi.mock('../src/data/trainer.client.js', () => ({ getTrainerRuns: vi.fn() }));

import { getClassifierRuns } from '../src/data/mlflow.client.js';
import { getTrainerRuns } from '../src/data/trainer.client.js';
import { listExperiments, toRow } from '../src/logic/experiments.service.js';

function run(id: string, name: string, status = 'FINISHED') {
  return {
    info: { run_id: id, run_name: name, status, start_time: 1 },
    data: {
      params: {
        optimizer: 'adam',
        batch_size: '32',
        max_epochs: '15',
        learning_rate: '0.0003',
        image_size: '128',
        hidden_layers: '[512, 128]',
        dropout: '0.5',
      },
      metrics: { best_val_accuracy: 0.98, best_epoch: 7, stopped_epoch: 11 },
      tags: { dataset_version: 'v1.0.0', manifest_sha256: 'abc' },
    },
  };
}

/**
 * T3-3.4 / rúbrica 3.3, 6.2: Experiments distingue las corridas válidas (reglas de
 * `list-runs`, servicio trainer), muestra los 7 hiperparámetros y sirve las curvas por el
 * backend en vez de la URL interna de MLflow.
 */
describe('Experiments', () => {
  it('muestra los 7 hiperparámetros y una ruta de curvas del backend', () => {
    const row = toRow(run('run-1', 'r10'));

    expect(row.hiddenLayers).toBe('[512, 128]');
    expect(row.batchSize).toBe('32');
    expect(row.stoppedEpoch).toBe(11);
    expect(row.curvesUrl).toBe('/experiments/run-1/curves');
    expect(row.curvesUrl).not.toContain('mlflow');
    expect(row.valid).toBeNull();
  });

  it('marca válidas e inválidas con la validez del trainer', async () => {
    vi.mocked(getClassifierRuns).mockResolvedValue([
      run('run-ok', 'r01-base'),
      run('run-dup', 'r06-epochs25'),
      run('run-killed', 'r01-base', 'KILLED'),
    ]);
    vi.mocked(getTrainerRuns).mockResolvedValue({
      status: 200,
      body: {
        experiment: 't3-classifier',
        manifest_sha256: 'abc',
        valid_runs: 1,
        runs: [
          {
            run_id: 'run-ok',
            run_name: 'r01-base',
            status: 'FINISHED',
            valid: true,
            invalid_reasons: [],
          },
          {
            run_id: 'run-dup',
            run_name: 'r06-epochs25',
            status: 'FINISHED',
            valid: false,
            invalid_reasons: ['identical final weights to run r01-base'],
          },
          {
            run_id: 'run-killed',
            run_name: 'r01-base',
            status: 'KILLED',
            valid: false,
            invalid_reasons: ['status KILLED'],
          },
        ],
      },
    });

    const rows = await listExperiments();

    expect(rows.map((row) => [row.runId, row.valid])).toEqual([
      ['run-ok', true],
      ['run-dup', false],
      ['run-killed', false],
    ]);
    expect(rows[1]?.invalidReasons).toEqual(['identical final weights to run r01-base']);
    expect(getClassifierRuns).toHaveBeenCalledWith({ finishedOnly: false });
  });

  it('deja la validez desconocida si el trainer no responde', async () => {
    vi.mocked(getClassifierRuns).mockResolvedValue([run('run-ok', 'r01-base')]);
    vi.mocked(getTrainerRuns).mockRejectedValue(new Error('down'));

    const rows = await listExperiments();

    expect(rows[0]?.valid).toBeNull();
  });
});
