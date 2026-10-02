# MLflow store en S3: push y recuperación desde un clon limpio

Evidencia de que el store real de MLflow (`pipeline/mlflow-data/`, puntero
`pipeline/mlflow-data.dvc`) está en el remoto DVC de producción y que un clon limpio lo
recupera intacto. Ejecutado el 2 de octubre de 2026 (UTC) sobre el commit
`03c3b97c302a10a865f34084cca405fed46ea59b` de `main`, con un perfil AWS local de la cuenta
`685538571046`. Las credenciales nunca estuvieron en el repo.

## Push

| Paso | Salida |
|---|---|
| `aws sts get-caller-identity --query Account` | `685538571046` |
| `dvc status -c -r prod mlflow-data.dvc` (antes) | los objetos del store aparecen como `new` |
| `dvc push -r prod mlflow-data.dvc` (05:01:53 – 05:03:28 UTC) | `94 files pushed` |
| `dvc status -c -r prod mlflow-data.dvc` (después) | `Cache and remote 'prod' are in sync.` |
| `dvc push -r prod mlflow-data.dvc` (repetido) | `Everything is up to date.` |
| `aws s3api head-object --key files/md5/85/f87cb65a175928215cb05c1bc736db.dir` | 26 127 bytes, `ServerSideEncryption: AES256`, `VersionId: 43KKt.4zYQIEBQ.Zj1W1FBLRdgwVGrhd` |
| `aws s3 ls s3://dvc-cache-prod-685538571046/files/md5/ --recursive --summarize` | `Total Objects: 94`, `Total Size: 908416859` |

## Recuperación desde un clon limpio

Clon nuevo de `https://github.com/BryanRomoG/proyecto3-classifier-portal.git` en el mismo
commit, sin `mlflow-data/` ni caché DVC:

| Paso | Salida |
|---|---|
| `dvc pull -r prod mlflow-data.dvc` | `94 files fetched and 205 files added` |
| `dvc status mlflow-data.dvc` | `Data and pipelines are up to date.` |
| `sha256sum mlflow-data/mlflow.db` | `62ee077b8d93e7a7715cd797895209567eb32f82eb76b9b3f48ca71ed99a9c5b` |
| SHA-256 de los 205 archivos frente al store original | idénticos |
| MLflow servido sobre la copia restaurada: `runs/search` | 21 corridas: `t3-classifier` 11 FINISHED + 1 KILLED; `t3-smoke-repro` 8 FINISHED + 1 RUNNING |
| `python scripts/verify_mlflow_restore.py` | `"passes": true` → `mlflow_restore_check.json` |

`mlflow_restore_check.json` (esta carpeta) es la salida del verificador sobre esa copia
restaurada. El MLflow temporal se sirvió en el puerto 5001 para no chocar con el `mlflow`
de compose que ya corría en el 5000. Confirma, contra los reportes commiteados:

- las 10 corridas del ranking de `selection.json` existen, están FINISHED y conservan su
  `best_val_accuracy`;
- el run seleccionado `44725ac6…` (`r03-adamw-lr1e-4`) conserva sus etiquetas de selección;
- su `model.pt` se descarga con el SHA-256 de la selección (`fe1c2370…`, 45 304 323 bytes);
- sus métricas `test_*` son iguales a `test_evaluation.json` (94/95 = 0.9894736842105263,
  F1 macro 0.9892400045305243).

La corrida `RUNNING` de `t3-smoke-repro` (`a2840dc8`) es el intento de `repro-check`
que murió al cerrar por el error de codificación de la consola (ver commit `4c5c855`). Se
conserva tal cual, está fuera del experimento oficial y no afecta ningún check.
