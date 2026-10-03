# T3-3.6 — Empaquetado y publicación del modelo (release)

Empaqueta el **candidato seleccionado** (`selection.json` → `model.pt`) en un paquete
autodescriptivo con versión semántica, y lo publica/recupera del bucket S3 de releases.
La herramienta vive en `pipeline/src/dataset_quality/classifier/release.py` y se maneja por
el CLI del clasificador (`python -m dataset_quality.classifier`).

## Qué contiene el paquete (`<output-dir>/<version>/`)

| Archivo | Contenido |
|---|---|
| `model.pt` | copia byte a byte del checkpoint seleccionado y evaluado en test |
| `MODEL_CARD.md` | tarjeta legible: arquitectura, clases, métricas de test, trazabilidad, uso |
| `config.json` | `TrainingConfig` efectiva (7 hiperparámetros buscados + fijos) |
| `class_map.json` | índice → clase (`{"0": "car", "1": "person"}`) |
| `metadata.json` | trazabilidad máquina: run ID, dataset/release, métricas, hashes de archivos |
| `SHA256SUMS` | manifiesto SHA-256 de **todos** los archivos anteriores |

El build es **determinista**: los mismos insumos producen un paquete byte a byte idéntico
(no se escribe ninguna marca de tiempo; los únicos timestamps son los ya commiteados en
`selection.json` / `test_evaluation.json`). Antes de escribir nada se comprueba que el
`model.pt` en disco tiene el SHA-256 registrado **tanto** en la selección **como** en la
evaluación final de test, que ambas pertenecen al mismo run y manifiesto, y que las clases
coinciden — de lo contrario el build se rechaza.

## Comandos

Todos desde `pipeline/` con `PYTHONPATH=src`.

### 1. Construir el paquete

```bash
PYTHONPATH=src python -m dataset_quality.classifier release-build \
  --version v1.0.0 \
  --checkpoint artifacts/classifier/selected/<run_id>/model.pt
```

`--selection` y `--evaluation` toman por defecto
`reports/classifier/selection.json` y `reports/classifier/test_evaluation.json`;
`--output-dir` toma por defecto `artifacts/classifier/release` (ignorado por git).

### 2. Verificar la integridad local

```bash
PYTHONPATH=src python -m dataset_quality.classifier release-verify \
  --package-dir artifacts/classifier/release/v1.0.0
```

Devuelve `"ok": true` solo si el manifiesto lista exactamente los archivos requeridos, cada
uno está presente con su SHA-256 correcto y no hay archivos extra. Sale con código 2 en caso
contrario.

### 3. Publicar en S3 (credenciales por cadena estándar de AWS)

```bash
# Credenciales SOLO por el entorno / perfil / rol — nunca en el repo:
export AWS_ACCESS_KEY_ID=...  AWS_SECRET_ACCESS_KEY=...  AWS_DEFAULT_REGION=us-east-1
# (o un perfil ~/.aws, o el rol de instancia/tarea, o GitHub Actions OIDC)

PYTHONPATH=src python -m dataset_quality.classifier release-upload \
  --version v1.0.0 \
  --package-dir artifacts/classifier/release/v1.0.0 \
  --bucket dataset-releases-prod-<account_id>
```

`release` **no** hardcodea secretos: `get_release_store_client()`
(`config/clients.py`) construye el cliente boto3 sin pasar credenciales, así que boto3 las
resuelve por su cadena estándar. El bucket se pasa por `--bucket` (el nombre local lleva el
account id: `dataset-releases-dev-<account_id>` / `dataset-releases-prod-<account_id>`).

Las llaves son `s3://<bucket>/t3-classifier/<version>/<archivo>` (el prefijo se cambia con
`--prefix`). El comando hace `PutObject` de cada archivo y a continuación `HeadObject` para
confirmar que aterrizó; rechaza el paquete si no verifica localmente.

### 4. `head-object` / `get-object` directo (AWS CLI)

```bash
ACCOUNT=<account_id>
aws s3api head-object --bucket dataset-releases-prod-$ACCOUNT \
  --key t3-classifier/v1.0.0/model.pt
aws s3api get-object --bucket dataset-releases-prod-$ACCOUNT \
  --key t3-classifier/v1.0.0/SHA256SUMS SHA256SUMS
aws s3 cp --recursive s3://dataset-releases-prod-$ACCOUNT/t3-classifier/v1.0.0/ ./downloaded/
```

### 5. Recuperar y verificar en un entorno limpio

```bash
PYTHONPATH=src python -m dataset_quality.classifier release-fetch \
  --version v1.0.0 \
  --bucket dataset-releases-prod-<account_id> \
  --destination /tmp/t3-release-v1.0.0
```

Descarga los seis archivos y verifica el manifiesto SHA-256: devuelve `"ok": true` solo si
todo coincide. Verificación manual equivalente con coreutils:

```bash
cd /tmp/t3-release-v1.0.0 && sha256sum -c SHA256SUMS
```

### 6. Inferencia limpia (modelo descargado)

```bash
PYTHONPATH=src python -m dataset_quality.classifier predict \
  --checkpoint /tmp/t3-release-v1.0.0/model.pt imagen.png
```

No necesita MLflow ni el store de DVC: `model.pt` lleva dentro la configuración, el mapa de
clases y el preprocesamiento de evaluación, así que la inferencia no puede desviarse de cómo
se validó y probó el modelo.

## Pruebas

- `pipeline/tests/test_t3_3_6_release.py` — unitarias/contrato sin torch (reader de
  checkpoint inyectado + object store en memoria): build determinista, manifiesto,
  verificación, rechazo de paquetes alterados y round-trip upload/fetch.
- `pipeline/tests/classifier/test_t3_classifier_release.py` — contrato con un checkpoint real
  de torch: empaqueta, recarga con el cargador de inferencia y predice desde el paquete.

## Evidencia del release `v1.0.0`

Validación ejecutada el 2 de octubre de 2026 con Python 3.12, PyTorch 2.8.0 y
torchvision 0.23.0, sin reentrenar ni volver a evaluar el split de test:

- checkpoint seleccionado: run `44725ac6b1704fed8b06bc4f846651d8`;
- SHA-256 del checkpoint: `fe1c2370cb9d811d32cccc27edf0beeb3c440fe758c467a9e3fb91a73e6047cb`;
- pruebas de contrato puras: 26 aprobadas;
- pruebas con checkpoint real e inferencia: 3 aprobadas;
- destino: `s3://dataset-releases-prod-685538571046/t3-classifier/v1.0.0/`;
- `HeadObject`: seis objetos presentes; `model.pt` tiene 45,304,323 bytes;
- descarga limpia con `release-fetch`: `ok: true`, sin faltantes, extras ni diferencias;
- inferencia desde el `model.pt` descargado: el recorte `car/1.png` produjo clase `car`
  con confianza `0.9998664856`.

El ETag de `model.pt` es multipart y no se usa como digest. La integridad se demuestra
descargando el objeto y comparando el SHA-256 contra `SHA256SUMS`.
