# T3-4.4 — Regresión desde clon limpio

Fecha de ejecución: 2026-10-03.

## Alcance

Se clonó `main` en un directorio temporal sin reutilizar `.env`, dependencias,
artefactos DVC ni volúmenes del repositorio de desarrollo. El stack anterior se
detuvo sin borrar sus datos.

## Flujo ejecutado

1. Se instaló `dvc[s3]` en un entorno virtual aislado.
2. `dvc pull -r prod mlflow-data.dvc` restauró 94 archivos de cache y 205
   archivos del store de MLflow desde S3.
3. `scripts/verify_mlflow_restore.py` devolvió `passes: true`: diez runs,
   checkpoint seleccionado y métricas finales coincidieron.
4. `./scripts/restore-env.sh` verificó el SHA-256 del bundle y restauró 311
   objetos en MinIO, 313 filas de imágenes y 1,038 anotaciones en MariaDB.
5. El `dvc pull` global documentado inicialmente falló porque el cache histórico
   del bundle no contiene cinco salidas derivadas agregadas por el clasificador.
   La corrección comprobada fue traer solo `data/raw/coco-dataset.json.dvc` y
   ejecutar después `dvc repro`.
6. Las ocho etapas reprodujeron 1,038 recortes, un split sin fuga, el quality
   gate y el release idempotente `v1.0.0`.

Durante la repetición se comprobó que un contenedor `run --rm` descartaba tanto
el cambio de `dvc.lock` como su cache local. El servicio `pipeline` ahora monta
ambos desde el host; así conserva la información necesaria para reconocer
salidas ya calculadas en ejecuciones posteriores.

## Prueba del portal y la inferencia

Respondieron HTTP 200:

- `/`, `/overview`, `/experiments`, `/evaluation`, `/models` e `/inference`;
- `/health`, `/quality-report`, `/split-report`, `/version-history`,
  `/experiments` y `/evaluation` del backend.

Se seleccionó el run `44725ac6b1704fed8b06bc4f846651d8`. Una imagen del
dataset limpio produjo:

- clase `car`;
- confianza `0.9998664855957031`;
- checkpoint SHA-256
  `fe1c2370cb9d811d32cccc27edf0beeb3c440fe758c467a9e3fb91a73e6047cb`.

La acción de enviar a la cola respondió HTTP 201 y creó la imagen 316 en
estado `pending`, persistida en MariaDB y MinIO.

## Incidencia ambiental

En el primer intento, un contenedor del stack de desarrollo conservó el puerto
5000. Se detuvo sin borrar sus volúmenes y se recreó únicamente MLflow en el
stack temporal. La restauración y todas las comprobaciones posteriores se
ejecutaron contra los volúmenes nuevos del clon.

## Resultado

El flujo completo funciona desde cero con la corrección documentada para DVC.
No se copiaron datos ni artefactos desde el repositorio de desarrollo.
