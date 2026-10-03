const MLFLOW_BASE_URL =
  process.env.MLFLOW_TRACKING_URI ?? "http://localhost:5000";

const EXPERIMENT_NAME = "t3-classifier";

interface MlflowExperiment {
  experiment_id: string;
  name: string;
  lifecycle_stage: string;
}

interface MlflowRun {
  info: {
    run_id: string;
    run_name?: string;
    status: string;
    start_time: number;
    end_time?: number;
  };

  data: {
    params: Record<string, string>;
    metrics: Record<string, number>;
    tags: Record<string, string>;
  };
}

interface SearchRunsResponse {
  runs: MlflowRun[];
  next_page_token?: string;
}

async function mlflowRequest<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(`${MLFLOW_BASE_URL}${path}`, {
    ...init,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    const text = await response.text();

    throw new Error(
      `MLflow respondió ${response.status}: ${text}`,
    );
  }

  return (await response.json()) as T;
}

export async function getClassifierExperiment(): Promise<MlflowExperiment> {
  const query = new URLSearchParams({
    name: EXPERIMENT_NAME,
  });

  const response = await mlflowRequest<{
    experiments: MlflowExperiment[];
  }>(
    `/api/2.0/mlflow/experiments/get-by-name?${query}`,
  );

  const experiment = response.experiments?.[0];

  if (!experiment) {
    throw new Error(
      `No existe el experimento de MLflow "${EXPERIMENT_NAME}".`,
    );
  }

  return experiment;
}

export async function getClassifierRuns(): Promise<MlflowRun[]> {
  const experiment = await getClassifierExperiment();

  const response = await mlflowRequest<SearchRunsResponse>(
    "/api/2.0/mlflow/runs/search",
    {
      method: "POST",
      body: JSON.stringify({
        experiment_ids: [experiment.experiment_id],
        filter: "attributes.status = 'FINISHED'",
        order_by: ["attributes.start_time DESC"],
        max_results: 100,
      }),
    },
  );

  return response.runs;
}

export async function getClassifierRun(
  runId: string,
): Promise<MlflowRun> {
  const query = new URLSearchParams({
    run_id: runId,
  });

  const response = await mlflowRequest<{
    run: MlflowRun;
  }>(
    `/api/2.0/mlflow/runs/get?${query}`,
  );

  return response.run;
}

export function getArtifactUrl(
  runId: string,
  artifactPath: string,
): string {
  const query = new URLSearchParams({
    run_id: runId,
    path: artifactPath,
  });

  return `${MLFLOW_BASE_URL}/get-artifact?${query}`;
}

export async function getArtifact(
  runId: string,
  artifactPath: string,
): Promise<Response> {
  const response = await fetch(
    getArtifactUrl(runId, artifactPath),
  );

  if (!response.ok) {
    throw new Error(
      `No se pudo obtener el artefacto ${artifactPath}.`,
    );
  }

  return response;
}
