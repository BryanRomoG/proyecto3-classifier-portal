# Evaluación final en test — interpretación (T3-3.3, rúbrica 4.4)

Fuente única de las cifras: `test_evaluation.json` y `test_predictions.csv` de esta misma
carpeta (recalculables con `python -m dataset_quality.classifier recompute`), idénticas a las
métricas `test_*` del run MLflow `44725ac6b1704fed8b06bc4f846651d8`.

## Protocolo y cronología

| Paso | Momento (UTC) | Evidencia |
|---|---|---|
| Clases congeladas (`car`, `person`; `dog` excluida por 0 muestras) | 2026-09-29 | `docs/t3-0-6-class-freeze.md` |
| 10 corridas válidas sobre el manifiesto `39474340…` | 2026-09-30 | experimento MLflow `t3-classifier`, `list-runs` |
| Selección por validación: `r03-adamw-lr1e-4` | 14:48:58 | `selection.json` (commit `cff4fa2`, antes de abrir el test) |
| Test abierto una vez con el checkpoint `fe1c2370…` | 14:49:23 | `test_evaluation.json` |

La política (`experiments/selection_policy.yaml`: `best_val_accuracy`, desempate por
`best_val_loss`) estaba commiteada antes de las corridas. r01, r03 y r11 empataron en 0.9803
de accuracy de validación; r03 ganó por menor val_loss (0.0409).

## Resultado

- Accuracy top-1: **94 / 95 = 0.98947** (≥ 0.85, comparado sin redondear).
- F1 macro: **0.98924**.
- Baseline de clase mayoritaria (`car`, la más frecuente en train) sobre el mismo test:
  54 / 95 = **0.5684**. El modelo lo supera en 42 puntos.

| Real \ Predicha | car | person | Recall |
|---|---:|---:|---:|
| **car** (54) | 54 | 0 | 1.000 |
| **person** (41) | 1 | 40 | 0.976 |
| Precisión | 0.982 | 1.000 | |

## Errores

Único error: recorte `annotation_id` 56 (`data/processed/crops/person/56.png`, imagen original
39), etiqueta real `person`, predicho `car` con probabilidad 0.893. Es una persona de espaldas
con mochila y bastones; buena parte del recorte la ocupan una camioneta y autos estacionados
al fondo. Es la confusión más frecuente (y la única): `person → car`.

## ¿El 85% oculta bajo recall de alguna clase?

No. Ninguna clase queda por debajo de 0.85 de recall (`classes_below_target_recall` vacío):
`car` 1.000 y `person` 0.976. El test está moderadamente desbalanceado (57% `car`), por eso
se reportan también el F1 macro y el baseline de clase mayoritaria.

## Limitaciones

- Test pequeño: 95 recortes de 31 imágenes originales, así que cada error mueve el accuracy
  ~1.05 puntos.
- Dos clases fácilmente separables. El resultado no dice nada sobre clases que no estaban en
  el release (p. ej. `dog`, excluida antes del test por no tener muestras).
- Recortes de personas con vehículos al fondo son el modo de falla observado.
