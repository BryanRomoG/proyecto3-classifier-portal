# T3-1.6 — Regresión del split y entrenamiento corto

Fecha de ejecución: 2026-09-30  
Ejecutor: Santiago Ortiz (Rol 1)  
Base verificada: `4591a99` (`main`)  
Rama de evidencia: `test/t3-1-6-regression`

## Objetivo

Confirmar que el manifiesto 70/20/10 integrado no mezcla imágenes entre
particiones y que el pipeline de entrenamiento todavía puede completar una corrida
corta. Esta validación no repite la cuadrícula oficial, la selección del candidato ni
la evaluación final sobre test.

## Cero fuga entre particiones

Fuente: `pipeline/data/processed/classifier_split_manifest.json`.

| Control | Resultado |
| --- | ---: |
| Versión del dataset | `v1.0.0` |
| Semilla del split | `42` |
| Proporciones | `0.7 / 0.2 / 0.1` |
| Imágenes únicas | 311 |
| Anotaciones/crops únicos | 1,038 |
| Intersección train / val | 0 |
| Intersección train / test | 0 |
| Intersección val / test | 0 |
| Pares duplicados revisados | 1 |
| Pares duplicados conservados en el mismo split | 1 |
| Pares filtrados entre splits | 0 |
| Estado del control de fuga | `pass` |

Distribución resultante:

| Split | Imágenes | Crops |
| --- | ---: | ---: |
| train | 218 | 740 |
| val | 62 | 203 |
| test | 31 | 95 |

Hashes de procedencia:

- COCO: `da5b08e319f43aa5568e3530f48e2934a4a79f0cf6762bea93c0dfd74e467c1d`
- manifiesto de crops: `ce801267390938497570bd62498e11db45acc4cace681e59190a1aa56bb9f67a`
- pares duplicados: `b45b6d3b3f0a6898b0588ec1babc4294efa287a83030fd7efe783931c881294a`
- manifiesto del split: `394743403f8a263b462687b733272e9993d7dddaea6a1229f8ee2896b82f3f7d`

## Entrenamiento corto aislado

La corrida se ejecutó en CPU dentro de un contenedor desechable con el código y los
datos montados en modo de solo lectura. El tracking de MLflow, el checkpoint y los
artefactos se escribieron fuera del repositorio para no modificar las corridas
oficiales.

Configuración deliberadamente mínima:

```json
{
  "architecture": "simple_cnn",
  "pretrained": false,
  "max_epochs": 1,
  "image_size": 64,
  "batch_size": 32,
  "hidden_layers": [64],
  "dropout": 0.1,
  "augment": false
}
```

Resultado:

| Evidencia | Valor |
| --- | --- |
| Run ID temporal | `c2eebb502baf489bab30659240ec3b1f` |
| Epochs completados | 1 |
| Pasos del optimizador | 24 |
| Train loss / accuracy | `0.653246 / 0.628378` |
| Validation loss / accuracy | `0.709454 / 0.507389` |
| Mejor epoch | 1 |
| SHA-256 del checkpoint | `14aea374986836d3bc88bc65b912237786646a982b4cfe45274fb4fbcdbeca22` |
| Python | `3.12.14` |
| PyTorch | `2.8.0+cpu` |
| Torchvision | `0.23.0+cpu` |
| MLflow | `3.16.1` |

La exactitud de esta corrida no se usa para escoger modelo: su única finalidad es
demostrar que carga el split, entrena, valida, guarda el checkpoint y registra la
trazabilidad sin abrir el conjunto de test.

## Conclusión

T3-1.6 queda validada: el split no presenta fuga entre train, validation y test, y
el pipeline completa un entrenamiento corto sobre los crops integrados. La corrida
oficial seleccionada y su evaluación final permanecen sin cambios.
