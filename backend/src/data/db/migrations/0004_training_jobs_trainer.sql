-- Proyecto 3: los trabajos de Training los ejecuta el servicio `trainer` (entrenamiento real).
-- Se guardan la cabeza de la red (hidden_layers), el trabajo y el run de MLflow que produjo,
-- y la procedencia que el trainer verificó antes de empezar.
ALTER TABLE `training_jobs`
  ADD `hidden_layers` varchar(100) NOT NULL DEFAULT '[256]',
  ADD `trainer_job_id` varchar(64),
  ADD `mlflow_run_id` varchar(64),
  ADD `dataset_version` varchar(50),
  ADD `quality_gate_status` varchar(20),
  ADD `manifest_sha256` varchar(64);
