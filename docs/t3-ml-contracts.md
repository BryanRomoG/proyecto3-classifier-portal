# Contratos ML para el portal (Training, Experiments, Evaluation)

Qué datos **reales** expone el lado ML y dónde, para que las páginas del portal no usen
mocks. Cada fuente de esta lista se consultó contra el stack corriendo
(`docker compose up --build`) el 30 de septiembre de 2026. Responsable del contrato: Luisa
(ML). Responsable de las páginas: Ignacio (frontend).

Servicios involucrados (ver `docker-compose.yml`):

| Servicio | Desde el host | Desde otro contenedor | Qué sirve |
|---|---|---|---|
| `classifier-api` | `http://localhost:8200` · Web App: `/classifier-api/` | `http://classifier-api:8200` | validación de la configuración de entrenamiento |
| `mlflow` | `http://localhost:5000` | `http://mlflow:5000` | corridas, parámetros, métricas por época, artefactos |
| archivos versionados | `pipeline/reports/classifier/` | montar como volumen de solo lectura | selección, evaluación final, predicciones |

> nginx **no** reenvía hoy `/mlflow` al navegador. Para leer MLflow desde la Web App hace
> falta un `location` en `frontend/docker/nginx.conf` (como `/classifier-api/`) o que el
> backend lo consulte y lo reexponga. Esa decisión le toca al frontend.

## Training

**Validar antes de crear un trabajo** (rúbrica 2.2: rechazar un valor inválido antes de que
exista el trabajo):

- `GET /classifier-api/training/schema`: JSON Schema de `TrainingConfig` (tipos, rangos,
  valores por defecto, `additionalProperties: false`). El formulario debería construir sus
  campos y límites desde aquí.
- `POST /classifier-api/training/validate` con la configuración candidata:
  - `422 {"valid": false, "errors": [{"field": "batch_size", "message": "..."}]}`: mostrar
    cada mensaje junto a su campo y **no crear el trabajo**;
  - `200 {"valid": true, "config": {...}}`: la configuración **efectiva**, con valores por
    defecto incluidos. Es exactamente lo que recibirá el entrenador.

**Lanzar y seguir un trabajo** (T3-2.3, fuera del request HTTP): el entrenador es
`python -m dataset_quality.classifier train --json '<config>' --run-name <nombre>` desde
`pipeline/`, con `MLFLOW_TRACKING_URI` apuntando a `mlflow`. Mientras corre, reescribe tras
cada época `artifacts/classifier/runs/<run_id>/status.json`:

```json
{
  "run_id": "44725ac6b1704fed8b06bc4f846651d8",
  "state": "finished",
  "started_at": "2026-09-30T14:33:53.163105+00:00",
  "updated_at": "2026-09-30T14:35:34.842620+00:00",
  "max_epochs": 15,
  "epoch": 11,
  "best_epoch": 7,
  "stopped_early": true,
  "best_val_accuracy": 0.9802955665024631,
  "checkpoint_sha256": "fe1c2370…"
}
```

`state` puede ser `running` (con `epoch`, `last_metrics`, `improved`), `finished` o
`failed` (con `error`, y un `error.log` al lado). Como es un archivo, el progreso sobrevive a
recargar la página. Las métricas por época también están en MLflow en cuanto termina cada
época (ver Experiments).

## Experiments

Fuente principal: la API REST de MLflow, experimento `t3-classifier` (`experiment_id` `2`).

| Dato | Llamada |
|---|---|
| Corridas | `POST /api/2.0/mlflow/runs/search` con `{"experiment_ids": ["2"], "max_results": 50}` |
| Parámetros efectivos | `run.data.params`: `optimizer`, `batch_size`, `max_epochs`, `learning_rate`, `image_size`, `hidden_layers`, `dropout`, `seed.*` |
| Métricas finales | `run.data.metrics`: `best_val_accuracy`, `best_val_loss`, `best_epoch`, `stopped_epoch` |
| Curvas por época | `GET /api/2.0/mlflow/metrics/get-history?run_id=<id>&metric_key=<train_loss\|train_accuracy\|val_loss\|val_accuracy>` |
| Imagen de curvas | `GET /get-artifact?path=curves.png&run_uuid=<id>` |
| Trazabilidad | `run.data.tags`: `manifest_sha256`, `dataset_version`, `dvc_raw_md5`, `git_commit`, `classes`, `grid_run` |

**Qué corridas son válidas** (hay 12 en el experimento y 10 cuentan): no recalcularlo en el
frontend. `python -m dataset_quality.classifier list-runs` devuelve cada corrida con `valid`
e `invalid_reasons` (r06 tiene pesos idénticos a r01; el primer r01 quedó `KILLED`). Sin
servidor MLflow, la misma información está versionada en
`pipeline/reports/classifier/mlflow_runs.json` y `curves/` (PR #6).

## Evaluation

Todo en `pipeline/reports/classifier/`, versionado en git:

| Archivo | Contenido |
|---|---|
| `selection.json` | `run_id`, `run_name`, `checkpoint_sha256`, `selected_at`, `policy`, `ranking` (10 corridas, solo métricas de validación), `test_opened`, `test_evaluated_at` |
| `test_evaluation.json` | `total`, `correct`, `accuracy`, `macro_f1`, `per_class` (precision/recall/f1/support), `confusion_matrix` (`rows: "true"`, `columns: "predicted"`, `labels`, `matrix`), `majority_baseline`, `most_confused`, `examples[clase].correct / .errors`, `dataset_version`, `manifest_sha256`, `evaluated_at` |
| `test_predictions.csv` | una fila por recorte de test: `annotation_id`, `source_image_id`, `relative_path`, `true_label`, `predicted_label`, `correct`, `confidence`, `prob_car`, `prob_person` |
| `confusion_matrix.png` | la matriz como imagen |
| `interpretation.md` | interpretación de errores (rúbrica 4.4) |

- Los `relative_path` (en el CSV y en `examples`) apuntan a los recortes bajo `pipeline/`
  (p. ej. `data/processed/crops/person/56.png`), que DVC genera. Sirven para mostrar los
  ejemplos de aciertos y errores con su imagen.
- Regla de la rúbrica 6.3: la pantalla no debe mostrar resultados de test si
  `selection.json` no existe o tiene `test_opened: false`.
- Las mismas métricas están en el run seleccionado de MLflow como `test_accuracy`,
  `test_macro_f1`, `test_<clase>_{precision,recall,f1}`, `test_total`, `test_correct` y
  `test_majority_baseline_accuracy`. `python -m dataset_quality.classifier audit-test`
  comprueba que CSV, JSON y MLflow coincidan (T3-3.8).
