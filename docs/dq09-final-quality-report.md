# DQ-09 — Reporte final del Quality Gate

**Estado:** PASS
**Versión evaluada:** v1.0.0
**Fecha de ejecución:** 2026-09-18
**Fuente:** pipeline/data/interim/quality.json generado desde el pipeline DVC.

## Ejecución

La evaluación se realizó después de restaurar el release oficial en MinIO y MariaDB.
El pipeline se ejecutó desde la imagen reconstruida del profile pipeline, por lo que
usa los parámetros versionados actuales y no una imagen de desarrollo anterior.

~~~sh
docker compose --profile pipeline run --rm --build pipeline sh -c "PYTHONPATH=src dvc pull -f -r dev && PYTHONPATH=src dvc repro"
~~~

La etapa analyze ejecutó las áreas configuradas de cobertura M3, objetos pequeños,
desbalance, duplicados pHash, geometría de cajas y sesgo espacial. El Gate consume
las seis observaciones resultantes; por tanto no existe una métrica omitida ni un
valor de duplicados fabricado.

## Resultado del Gate

~~~text
QUALITY_GATE_EXIT_CODE=0
overall_status=pass
~~~

| Check | Área de análisis | Severidad | Umbral | Observado | Estado | Muestras ofensivas |
| --- | --- | --- | ---: | ---: | --- | --- |
| min_images_per_class | M3 / cobertura mínima | fail | ≥ 300 imágenes | 309 | pass | Ninguna |
| class_imbalance | DQ-04 / desbalance | warn | ≤ 3.0 | 1.0064724919 | pass | Ninguna |
| small_objects | DQ-04 / objetos pequeños | warn | ≤ 40 % | 1.3487475915 % | pass | Ninguna |
| duplicates | DQ-05 / pHash real | fail | ≤ 5 | 1 | pass | Ninguna |
| invalid_boxes | DQ-05 / geometría | fail | ≤ 0 | 0 | pass | Ninguna |
| spatial_bias | DQ-06 / distribución espacial | warn | ≤ 50 % | 45.4720616570 % | pass | Ninguna |

Los tres checks de severidad fail están en verde. Los checks configurados como warn
también pasan y sus valores quedan registrados arriba. offending_samples es una
lista vacía en los seis resultados, por lo que no hay muestras ofensivas que adjuntar.

## M3 y reproducibilidad

- M3 confirma una cobertura mínima de 309 imágenes distintas con cajas válidas en
  las categorías objetivo.
- El split reproducible usa seed: 42 y produjo 218 imágenes de entrenamiento, 47
  de validación y 46 de prueba.
- El control de fuga revisó el par de duplicado cercano y reportó leaked_pairs: 0.
- versions.json identifica la liberación como v1.0.0, con quality_status: pass y el
  entorno DEV disponible.

## Verificaciones complementarias

| Verificación | Resultado |
| --- | --- |
| Restauración de MinIO | 311 objetos reales disponibles |
| Restauración de MariaDB | 313 imágenes y 1,038 anotaciones |
| Suite completa del pipeline | 94 passed in 4.07s |
| Estado Git posterior | Limpio; los artefactos reproducibles están ignorados |

## Decisión de release

El Quality Gate no bloquea la liberación de v1.0.0: no hay checks fail en rojo,
el proceso terminó en código 0 y se generó el quality.json final. Esta evidencia
desbloquea DQ-09 para revisión/cierre por el responsable de release y elimina el
bloqueo técnico de DQ-10 sobre OPS-10.
