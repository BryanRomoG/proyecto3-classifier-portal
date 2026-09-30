# Regresión de reproducibilidad antes de las corridas oficiales (T3-2.5, rúbrica 2.3)

Fuente de todas las cifras: experimento MLflow `t3-smoke-repro` (tags `initial_state_sha256`,
`epoch1_order_sha256`, `final_state_sha256`, `checkpoint_sha256`, `git_commit`; métricas por
época; artefactos `sample_order.json` y `environment.json` de cada run). Todos los hashes son
SHA-256.

## Qué se repitió

La misma configuración dos veces por dispositivo:
`python -m dataset_quality.classifier train --json '{"max_epochs": 2}'`, es decir los valores
por defecto de `TrainingConfig` en ese momento (ResNet-18 preentrenada, Adam, lr 0.001,
batch 32, imagen 128, `[256]`, dropout 0.3, aumentación activa, `num_workers` 0). Semillas
`partition` / `shuffle` / `augmentation` / `init` = 42 / 42 / 42 / 42. Manifiesto `39474340…`
(740 recortes de train, 203 de val, 24 pasos de optimizador por época). El árbol de git estaba
limpio en las cuatro corridas (`git_dirty = false`).

| Run | Run ID | Inicio (UTC) | Dispositivo | Commit |
|---|---|---|---|---|
| repro-a | `dfd86d8d749d4bb68f8300e4b50bb426` | 14:11:24 | CPU | `65e55b2` |
| repro-b | `de2938629201469fa6a01d7d84b8cb9d` | 14:13:23 | CPU | `65e55b2` |
| repro-gpu-a | `50131ca083b046bf82baaca8e896aaad` | 14:29:05 | RTX 2060 Max-Q (CUDA 12.8, cuDNN 9.10.2) | `6783bf7` |
| repro-gpu-b | `0f76d4d9f9ec42c28468d7515c03c657` | 14:29:50 | RTX 2060 Max-Q (CUDA 12.8, cuDNN 9.10.2) | `6783bf7` |

Entorno común: Python 3.12.10, torch 2.8.0 y torchvision 0.23.0 (`+cpu` / `+cu128`), Windows 11,
`torch.use_deterministic_algorithms(True, warn_only=True)` activo.

## Resultado

| Comprobación | repro-a | repro-b | repro-gpu-a | repro-gpu-b |
|---|---|---|---|---|
| Pesos iniciales | `cb94fede…` | `cb94fede…` | `cb94fede…` | `cb94fede…` |
| Orden de muestras, época 1 | `78708dc1…` | `78708dc1…` | `78708dc1…` | `78708dc1…` |
| Orden de muestras, época 2 | `56039cc5…` | `56039cc5…` | `56039cc5…` | `56039cc5…` |
| Pesos finales | `b4062e5b…` | `b4062e5b…` | `5715dee4…` | `5715dee4…` |
| val_loss época 1 / 2 | 1.631888 / 1.009678 | 1.631888 / 1.009678 | 0.638167 / 0.329499 | 0.638167 / 0.329499 |
| val_accuracy época 1 / 2 | 0.778325 / 0.660099 | 0.778325 / 0.660099 | 0.886700 / 0.857143 | 0.886700 / 0.857143 |

- **Mismo dispositivo → resultado idéntico bit a bit.** En CPU y en GPU, las dos repeticiones
  tienen los mismos pesos finales y las mismas métricas de train/val en cada época, hasta el
  último decimal registrado.
- **Entre dispositivos → mismo orden de muestras e inicialización, distinto resultado
  numérico.** El orden de los minibatches depende solo de `seeds.shuffle` y de la época
  (`SeededEpochSampler`) y los pesos se inicializan en CPU, así que ambos coinciden en los
  cuatro runs. Los kernels de CPU y de CUDA redondean distinto, por eso los pesos finales
  difieren. Por eso las 10 corridas oficiales se hicieron todas en la misma GPU (tag
  `device_name` en cada run).
- **El `checkpoint_sha256` difiere entre repeticiones aunque los pesos sean idénticos.** Es
  esperado: el archivo `model.pt` guarda también el `run_id` de su corrida. La comparación de
  pesos se hace con `final_state_sha256` (hash de los tensores, sin metadatos).

## Operaciones no deterministas (documentadas, no observadas)

`enable_determinism()` pide algoritmos deterministas en modo `warn_only` y desactiva
`cudnn.benchmark`. Si una operación de CUDA no tiene versión determinista, torch emite un
aviso en vez de fallar. Que las dos repeticiones en GPU sean idénticas bit a bit muestra que,
con esta configuración, no hubo no determinismo que afectara el resultado. `num_workers=0`
evita el no determinismo del orden de carga entre procesos.

## Cronología frente a las corridas oficiales

| Momento (UTC) | Evento |
|---|---|
| 14:11 – 14:15 | repro-a / repro-b en CPU |
| 14:16 – 14:25 | primer intento de r01 en CPU, detenido tras 1 época (`KILLED`, no cuenta como válido) |
| 14:28:44 | commit `6783bf7`: entrenamiento en CUDA |
| 14:29 – 14:30 | repro-gpu-a / repro-gpu-b |
| 14:30:55 | primera de las 10 corridas oficiales válidas (r01-base, GPU) |

La regresión quedó cerrada en el dispositivo definitivo antes de cualquier corrida oficial
válida. Las 10 corridas válidas usan las mismas semillas (42 / 42 / 42 / 42) y la misma GPU.
Nueve corrieron en el commit `6783bf7` y r11 en `17b8f92`. Entre ambos commits solo cambiaron
el grid (se añadió r11), la regla de validez de `experiments.py` y un test, nada que ejecute el
entrenamiento.
