import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

import { beforeEach, describe, expect, it, vi } from 'vitest';

const stateDir = path.join(os.tmpdir(), `models-test-${process.pid}`);

vi.mock('../src/config/env.js', () => ({
  env: {
    SELECTED_MODEL_PATH: path.join(os.tmpdir(), `models-test-${process.pid}`, 'selected.json'),
    CLASSIFIER_REPORTS_DIR: path.join(os.tmpdir(), `models-test-${process.pid}`, 'reports'),
  },
}));
vi.mock('../src/data/mlflow.client.js', () => ({
  getArtifact: vi.fn(),
  getArtifactUrl: vi.fn(() => 'unused'),
  getClassifierRun: vi.fn(),
  getClassifierRuns: vi.fn(),
}));

import { getClassifierRun } from '../src/data/mlflow.client.js';
import { ValidationError } from '../src/logic/errors.js';
import { selectModel } from '../src/logic/models.service.js';

function run(status: string) {
  return {
    info: { run_id: 'run-1', run_name: 'r01', status, start_time: 0 },
    data: { params: {}, metrics: {}, tags: {} },
  };
}

/**
 * T3-3.7 / rúbrica 6.4: elegir un modelo para inferencia. Un run que no terminó (KILLED,
 * FAILED) no tiene un modelo utilizable: es un error del usuario (400), no del servidor.
 */
describe('Models: selección para inferencia', () => {
  beforeEach(async () => {
    await fs.rm(stateDir, { recursive: true, force: true });
    await fs.mkdir(stateDir, { recursive: true });
  });

  it('rechaza un run que no terminó con un ValidationError', async () => {
    vi.mocked(getClassifierRun).mockResolvedValue(run('KILLED'));

    await expect(selectModel('run-1')).rejects.toBeInstanceOf(ValidationError);
  });

  it('guarda la selección de un run terminado', async () => {
    vi.mocked(getClassifierRun).mockResolvedValue(run('FINISHED'));

    const selected = await selectModel('run-1');

    expect(selected.runId).toBe('run-1');
    const stored = JSON.parse(await fs.readFile(path.join(stateDir, 'selected.json'), 'utf8'));
    expect(stored.runId).toBe('run-1');
  });
});

describe('Models: versiones publicadas', () => {
  beforeEach(async () => {
    await fs.rm(stateDir, { recursive: true, force: true });
    await fs.mkdir(path.join(stateDir, 'reports', 'releases'), { recursive: true });
  });

  it('lista las versiones semánticas publicadas con su estado en S3, no los runs', async () => {
    const { listVersions } = await import('../src/logic/models.service.js');
    await fs.writeFile(
      path.join(stateDir, 'reports', 'releases', 'v1.0.0.json'),
      JSON.stringify({
        version: 'v1.0.0',
        bucket: 'dataset-releases-prod-1',
        s3_uri: 's3://dataset-releases-prod-1/t3-classifier/v1.0.0/',
        run_id: 'run-1',
        run_name: 'r03',
        checkpoint_sha256: 'fe1c',
        dataset: { dataset_version: 'v1.0.0', manifest_sha256: 'abc' },
        test_metrics: { accuracy: 0.98 },
        dependencies: null,
        split: null,
        objects: {
          'model.pt': {
            key: 't3-classifier/v1.0.0/model.pt',
            size: 10,
            version_id: 'V1',
            sha256: 'fe1c',
          },
        },
        card_markdown: '# Model card',
        recorded_at: '2026-10-03T00:00:00Z',
        verified_with: 'HeadObject',
      }),
    );
    vi.mocked(getClassifierRun).mockResolvedValue(run('FINISHED'));
    await selectModel('run-1');

    const versions = await listVersions();

    expect(versions).toHaveLength(1);
    expect(versions[0]).toMatchObject({
      version: 'v1.0.0',
      runId: 'run-1',
      datasetVersion: 'v1.0.0',
      published: true,
      s3Uri: 's3://dataset-releases-prod-1/t3-classifier/v1.0.0/',
      cardMarkdown: '# Model card',
      selected: true,
    });
    expect(versions[0]?.objects[0]).toMatchObject({ name: 'model.pt', versionId: 'V1' });
  });
});
