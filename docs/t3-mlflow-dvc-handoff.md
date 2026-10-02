# MLflow DVC production handoff

Cómo pasar el store real de MLflow del clasificador (`pipeline/mlflow-data/`) al remoto DVC
de producción en S3, y cómo comprobar que un clon limpio lo recupera. Lo preparó Luisa (ML),
que no tiene credenciales de AWS; el `push` lo hace quien sí las tiene.

## Estado actual

> **Push hecho y recuperación verificada el 2 de octubre de 2026:** 94 objetos en
> `s3://dvc-cache-prod-685538571046`, y un clon limpio restauró los 205 archivos idénticos con
> el verificador en `"passes": true`. Evidencia en
> `pipeline/reports/classifier/mlflow_s3_persistence.md` y `mlflow_restore_check.json`. El resto
> de este documento queda como procedimiento por si el store cambia y hay que volver a subirlo.

| | |
|---|---|
| Qué se versiona | `pipeline/mlflow-data/` completo, como **una sola salida DVC**: `mlflow.db` (SQLite con experimentos, corridas, parámetros, métricas y etiquetas) + `artifacts/` (checkpoints `model.pt`, curvas, JSON y CSV de cada corrida) |
| Puntero en git | `pipeline/mlflow-data.dvc`: md5 `85f87cb65a175928215cb05c1bc736db.dir`, 205 archivos, 908 751 931 bytes |
| Contenido | experimento `t3-classifier` (12 corridas: 10 válidas, r06 duplicada, primer r01 `KILLED`) y `t3-smoke-repro` (9 corridas cortas de reproducibilidad) |
| Remoto destino | `prod` → `s3://dvc-cache-prod-685538571046` (`pipeline/.dvc/config`; cuenta `685538571046`, `us-east-1`, SSE-S3 `AES256`, versionado activo, según `infra/`) |
| Remoto por defecto | `dev` (MinIO local). Por eso **todos los comandos llevan `-r prod`** |

La base y los artefactos se referencian entre sí por run ID
(`mlflow-artifacts:/<experimento>/<run>/artifacts`), así que se restauran juntos desde el
mismo snapshot. El snapshot se tomó con el servicio `mlflow` detenido (SQLite en
`journal_mode=delete`, sin archivos `-wal` ni `-journal`, `integrity_check` ok), y los 205
archivos quedaron idénticos byte a byte antes y después de `dvc add`.

## Por qué hace falta un paquete además del commit

`dvc push` sube lo que está en la **caché DVC local** de quien lo ejecuta. Esos objetos
solo existen en la máquina de Luisa, así que se exportaron a un remoto DVC de carpeta,
comprimido en `mlflow-dvc-remote.zip` (ZIP estándar, 841 719 088 bytes, 94 objetos DVC):

```
SHA-256  e528ef671ef47c2a08dfa81bb4708ff5a6fe5dde2a68216cfcb0faed26f196a7  mlflow-dvc-remote.zip
```

Es exactamente el contenido direccionado por hash que irá a S3. No contiene credenciales.

## Push (persona con acceso a AWS)

Requisitos: git, Python 3.12, `pip install "dvc[s3]>=3,<4"` (la misma restricción que
`pipeline/Dockerfile`) y credenciales AWS **propias** en el entorno (perfil, SSO o variables
de entorno). Nunca en `.dvc/config`, en git ni en archivos del repo.

```bash
git fetch origin
git checkout chore/t3-mlflow-dvc-tracking     # o main, una vez fusionado el PR
cd pipeline

# 1. Verificar y descomprimir el paquete fuera del repo
sha256sum /ruta/mlflow-dvc-remote.zip         # debe ser e528ef67...96a7
unzip /ruta/mlflow-dvc-remote.zip -d /ruta/   # crea /ruta/dvc-remote/ (en Windows: Expand-Archive)

# 2. Llenar la caché local con los objetos (no escribe nada en mlflow-data/)
dvc remote add --local handoff /ruta/dvc-remote   # --local: queda en .dvc/config.local, ignorado por git
dvc fetch -r handoff mlflow-data.dvc              # esperado: "94 files fetched"

# 3. Subir a producción
dvc remote list                                   # prod  s3://dvc-cache-prod-685538571046
aws sts get-caller-identity --query Account --output text   # esperado: 685538571046
dvc push -r prod mlflow-data.dvc                  # esperado: "94 files pushed"
dvc status -c -r prod mlflow-data.dvc             # esperado: "Cache and remote 'prod' are in sync."
aws s3api head-object --bucket dvc-cache-prod-685538571046 \
  --key files/md5/85/f87cb65a175928215cb05c1bc736db.dir   # el índice del directorio existe

# 4. Quitar el remoto temporal
dvc remote remove --local handoff
```

Si `dvc push` falla por región, exportar `AWS_DEFAULT_REGION=us-east-1` en la terminal (no
en el repo). Repetir el push es seguro: responde `Everything is up to date.`

No hacer: `dvc gc` sobre el remoto, borrar objetos del bucket, hacer push a otro bucket,
`dvc add` o `dvc commit` (cambiarían el puntero), ni correr `train`, `run-grid`, `select` o
`evaluate` (crean corridas o reabren el test).

## Validación desde un clon limpio

Sin el paquete ni la caché anterior. Solo git + DVC + Docker + Python 3 (el verificador usa
la biblioteca estándar, sin torch ni MLflow):

```bash
git clone https://github.com/BryanRomoG/proyecto3-classifier-portal.git t3-restore-check
cd t3-restore-check
git checkout <mismo commit que se usó para el push>
cd pipeline
pip install "dvc[s3]>=3,<4"

dvc pull -r prod mlflow-data.dvc        # esperado: "94 files fetched and 205 files added"
dvc status mlflow-data.dvc              # esperado: "Data and pipelines are up to date."
sha256sum mlflow-data/mlflow.db         # esperado: 62ee077b8d93e7a7715cd797895209567eb32f82eb76b9b3f48ca71ed99a9c5b

cd .. && docker compose up -d mlflow && cd pipeline
python scripts/verify_mlflow_restore.py --tracking-uri http://localhost:5000 \
  --report reports/classifier/mlflow_restore_check.json      # esperado: "passes": true, exit 0
```

`verify_mlflow_restore.py` toma los valores esperados de los reportes ya commiteados
(`selection.json`, `test_evaluation.json`) y comprueba, en solo lectura:

- que las 10 corridas del ranking existan, estén FINISHED y conserven su `best_val_accuracy`;
- que el run seleccionado (`r03-adamw-lr1e-4`) conserve sus etiquetas de selección;
- que su `model.pt` se descargue con el SHA-256 registrado (`fe1c2370…`);
- que sus métricas `test_*` sean iguales a `test_evaluation.json`.

Contra un MLflow vacío falla los cuatro checks y sale con código 1.

Este procedimiento completo ya se probó localmente, con una carpeta en lugar de S3: el
worktree limpio recuperó los 205 archivos idénticos, MLflow los sirvió y el verificador pasó.
Después se repitió con `-r prod` contra S3 (ver el aviso al inicio).

## Permisos mínimos en S3

Derivados de `pipeline/.dvc/config` y de `infra/`. No hacen falta permisos
administrativos, IAM ni KMS (el bucket cifra con SSE-S3).

| Operación | Acción | Recurso |
|---|---|---|
| `dvc push` y `dvc pull` (listar qué objetos ya existen) | `s3:ListBucket` | `arn:aws:s3:::dvc-cache-prod-685538571046` |
| `dvc push` (subir objetos, incluidas las partes de un multipart upload) | `s3:PutObject` | `arn:aws:s3:::dvc-cache-prod-685538571046/*` |
| `dvc pull`, `dvc status -c`, `head-object` | `s3:GetObject` | `arn:aws:s3:::dvc-cache-prod-685538571046/*` |

Son las mismas acciones que ya concede la política `dataset-quality-release-publish`
(`infra/environments/dev/main.tf`). Para validar el pull basta con `ListBucket` + `GetObject`.
Opcional: `s3:AbortMultipartUpload` sobre `/*`, para que un push interrumpido limpie sus partes.

## Evidencia a devolver

1. El SHA del commit usado (`git rev-parse HEAD`).
2. La salida de `dvc push -r prod mlflow-data.dvc` y de `dvc status -c -r prod mlflow-data.dvc`.
3. La salida de `aws s3api head-object` sobre la clave `.dir` (sin credenciales).
4. Desde el clon limpio: salidas de `dvc pull -r prod`, `dvc status` y `sha256sum mlflow-data/mlflow.db`.
5. `pipeline/reports/classifier/mlflow_restore_check.json`, generado por el verificador. Lo
   ideal es que quien hizo la validación lo agregue en un PR propio, para que la evidencia
   tenga su autoría.

## Si el store cambia después

Cualquier corrida nueva modifica `mlflow.db`. Para versionarla: detener `mlflow`
(`docker compose stop mlflow`), `dvc add mlflow-data`, commitear el nuevo
`mlflow-data.dvc` y repetir el push. Arrancar el servidor y consultarlo no modifica el
archivo (comprobado por hash).
