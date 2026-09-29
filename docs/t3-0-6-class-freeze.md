# T3-0.6 — Congelamiento de clases elegibles antes de abrir el test

| Campo | Valor |
| --- | --- |
| Ticket | T3-0.6 |
| Fecha | 2026-09-29 |
| Dataset | `pipeline/data/raw/coco-dataset.json` |
| Release | v1.0.0 |
| Estado | Propuesta de acta — pendiente de aprobación del equipo |

## Objetivo

Dejar registradas, antes de abrir el conjunto de test, las clases con las que se
entrenará y evaluará el clasificador del Proyecto 3, junto con la evidencia de
conteos que justifica la selección. Este documento es la propuesta que el equipo
debe aprobar; no sustituye la aprobación.

## Fuente de los conteos

Los conteos provienen de la verificación del archivo COCO crudo del release
v1.0.0 (`person` = `category_id` 1, `car` = `category_id` 2, `dog` =
`category_id` 3). El puntero DVC versionado para ese archivo es
`pipeline/data/raw/coco-dataset.json.dvc` (`md5`
`0ac4ecdbbd5a9b3144624ec86009b9e7`, `size` 345858), correspondiente a
`dataset_version: v1.0.0` en `pipeline/params.yaml`.

| Categoría | `category_id` | Anotaciones | Cajas válidas | Imágenes distintas con al menos una caja válida |
| --- | ---: | ---: | ---: | ---: |
| `person` | 1 | 472 | 472 | 311 |
| `car` | 2 | 566 | 566 | 309 |
| `dog` | 3 | 0 | 0 | 0 |

Lectura de la tabla: `dog` aparece declarada en la sección `categories` del
archivo COCO, pero no tiene ni una sola anotación, ninguna caja válida y
ninguna imagen distinta asociada en el release v1.0.0.

## Decisión propuesta

1. **Incluir `person` (`category_id` 1).** 472 anotaciones válidas repartidas en
   311 imágenes distintas.
2. **Incluir `car` (`category_id` 2).** 566 anotaciones válidas repartidas en
   309 imágenes distintas.
3. **Excluir `dog` (`category_id` 3).** Cero anotaciones, cero cajas válidas y
   cero imágenes distintas: no existe muestra alguna con la que entrenar ni
   evaluar esa clase, por lo que no puede formar parte del conjunto de clases
   congeladas.

Es decir, el conjunto de clases congeladas propuesto es de dos clases:
`person` y `car`. Esta selección coincide con los `target_categories`
declarados hoy en `pipeline/params.yaml` (`person`, `car`), de modo que la
decisión no requiere cambios de clases en el pipeline, solo su formalización.

La exclusión de `dog` es por **ausencia total de muestras observadas**, no por
un juicio sobre la calidad o el interés de la clase. Si en el futuro apareciera
un dataset con muestras reales de `dog`, eso implicaría reabrir este ticket y
volver a congelar las clases antes de tocar el test.

## La categoría declarada en COCO no implica muestras

Estar listado en la sección `categories` de un archivo COCO es solo una
declaración de vocabulario: el archivo puede enumerar un `category_id` que
ninguna anotación usa. Por eso el criterio de elegibilidad usado aquí **no** es
la presencia en `categories`, sino el conteo efectivo de anotaciones, de cajas
válidas y de imágenes distintas con al menos una caja válida.

Por la misma razón, el hecho de que `dog` esté declarado con `category_id` 3 no
debe interpretarse como evidencia de que hay perros anotados en el dataset.
Declaración y evidencia son cosas distintas: en este release, la primera existe
y la segunda es cero.

## Alcance y límites de esta verificación

- Los conteos anteriores provienen únicamente del archivo COCO crudo del release
  v1.0.0 (anotaciones, cajas e imágenes).
- **No se consultaron predicciones, métricas de modelo ni resultados del test**
  para tomar esta decisión. La congelación de clases se decide con evidencia del
  dataset, antes de abrir el test, precisamente para que ningún resultado
  observado pueda sesgar la selección.
- La verificación de conteos se limita a lo declarado en la sección anterior; no
  incluye análisis de calidad, balance entre clases ni desempeño de ningún
  modelo.

## Compromiso de congelamiento

Se propone formalizar el siguiente compromiso para el equipo:

- Una vez abierto el conjunto de test, **no se cambiarán las clases** del
  entrenamiento ni de la evaluación. El conjunto de clases congeladas es
  `person` y `car`.
- Ninguna clase se agregará, quitará o redefinirá en función de métricas
  obtenidas después de abrir el test.
- Cualquier cambio de clases posterior a la apertura del test invalida los
  resultados reportados y exige repetir la evaluación con las clases
  congeladas.

## Impacto en T3-1.1 y T3-1.2

- **T3-1.1 (entrenamiento):** el modelo debe definir su espacio de salida sobre
  las dos clases congeladas (`person`, `car`). No debe reservar una salida para
  `dog`: una clase sin muestras en el release v1.0.0 no es entrenable y solo
  aportaría una salida degenerada sin señal de supervisión.
- **T3-1.2 (evaluación):** las métricas deben calcularse únicamente sobre
  `person` y `car`. `dog` no debe aparecer en el conjunto de test ni en ninguna
  tabla, gráfica o métrica agregada, porque no tiene imágenes distintas en el
  release.
- Ambos tickets quedan condicionados a la aprobación de este acta: si el equipo
  rechaza o modifica el conjunto de clases, el trabajo de T3-1.1 y T3-1.2 debe
  rehacerse sobre el conjunto aprobado antes de abrir el test.

## Aprobaciones

| Persona | Estado | Fecha |
| --- | --- | --- |
| Santiago | Aprobado | 2026-09-29 |
| Bryan | Pendiente | — |
| Luisa | Pendiente | — |
| Ignacio | Pendiente | — |

Las filas marcadas como pendientes solo se completarán cuando cada persona
confirme el acta. Este documento no registra aprobaciones que no hayan ocurrido.

## Referencias

- `pipeline/data/raw/coco-dataset.json.dvc` — puntero DVC del dataset crudo del
  release v1.0.0.
- `pipeline/params.yaml` — `dataset_version: v1.0.0` y
  `m3.target_categories: [person, car]`.
- [m3-baseline.md](m3-baseline.md) — línea base de conteos por clase sobre el
  mismo release.
