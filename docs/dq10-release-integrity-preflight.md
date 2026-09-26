# DQ-10 — Integridad final del release

**Estado:** PASS
**Fecha de cierre:** 2026-09-18
**Rama:** feat/phase-4-rol1-dq10

## Objetivo

Confirmar que las mutaciones adversariales usadas durante las pruebas no llegaron al
release y que el pipeline usa el dataset real, con sus filas de MariaDB y objetos de
MinIO correspondientes.

## Restauración verificable del dataset

Se ejecutó ./scripts/restore-env.sh desde Git Bash. El script descargó el asset
oficial v1.0.0-data, validó su SHA-256 antes de extraerlo y cargó el entorno:

| Control | Resultado |
| --- | --- |
| SHA-256 del bundle | 04b30b874bb8ef012dccf02aecaee31043bd40b63effbbcd105a3bb74810abc4 (válido) |
| Objetos de imagen en MinIO | 311 / 311 |
| Filas en images | 313 / 313 (311 reales + 2 seed) |
| Anotaciones en MariaDB | 1,038 / 1,038 |
| IDs COCO y storage_key | Disponibles para medir pHash real |

Esta restauración resuelve el bloqueo anterior:
DuplicateBytesUnavailableError ya no ocurre porque el analizador puede resolver
cada image_id del COCO a su storage_key y descargar sus bytes desde MinIO.

## Integridad de código, política y datos

| Criterio de DQ-10 | Evidencia | Resultado |
| --- | --- | --- |
| Cajas negativas o fuera de límites | Suite adversarial y análisis del dataset real | Restauradas / detectables |
| Imágenes duplicadas temporales | Dataset del release y detección pHash real | No hay inyección temporal; se observó 1 par real |
| quality.yaml | Umbrales: 300 mínimo, 5 duplicados máximo y 0 cajas inválidas máximo | Restaurado |
| Comparaciones del Quality Gate | Suite de política y DQ-08 | Restauradas |
| Cálculo de área de bounding boxes | Suite del pipeline | Restaurado |
| Fixtures de prueba en producción | git status --short sin salida; datos generados ignorados | No rastreados |

## Evidencia de ejecución final

Se reconstruyó la imagen del profile pipeline antes de la verificación, para evitar
reutilizar una imagen previa que todavía tenía dataset_version: v0.1.0-dev.

~~~sh
docker compose --profile pipeline run --rm --build pipeline sh -c "PYTHONPATH=src dvc pull -f -r dev && PYTHONPATH=src dvc repro"
~~~

El resultado generado corresponde a v1.0.0, usa objetos reales y deja los seis
checks del Quality Gate en pass. La suite completa del pipeline se ejecutó en un
contenedor temporal con la raíz del repositorio montada de solo lectura para incluir
los contratos versionados:

~~~text
94 passed in 4.07s
~~~

Finalmente, el Gate se ejecutó de forma directa contra las observaciones de v1.0.0
y terminó correctamente:

~~~text
QUALITY_GATE_EXIT_CODE=0
~~~

El árbol de trabajo quedó limpio. Los artefactos de pipeline/data/interim/ están
ignorados por diseño: son reproducibles y no deben publicarse como datos fuente.

## Conclusión

DQ-10 queda completado. El dataset, la política, la lógica del Gate y las
validaciones adversariales están restaurados y verificados. La evidencia de calidad
del release se registra en [dq09-final-quality-report.md](dq09-final-quality-report.md).
