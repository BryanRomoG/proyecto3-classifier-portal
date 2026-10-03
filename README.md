# Proyecto 3 · Clasificador de imágenes integrado al portal

Clasificación multiclase de **un objeto por imagen**, entrenada sobre recortes de las cajas
COCO del dataset aprobado del Proyecto 2. Incluye experimentos registrados en MLflow,
selección del candidato por validación, una evaluación única sobre un test congelado, un
modelo versionado con su tarjeta en AWS S3, y cinco páginas nuevas dentro del mismo portal:
**Training, Experiments, Evaluation, Models e Inference**.

Este repositorio parte del release `v1.0.0` del Proyecto 2 (Quality Gate en `PASS`), trabajo
previo de Santiago Ortiz, reutilizado con autorización del profesor. El portal de anotación
(Proyecto 1) y el pipeline de calidad y versionado (Proyecto 2) siguen funcionando dentro de
la misma aplicación; sus secciones están más abajo.

---

## Equipo

| Integrante | Rol | Responsabilidad en el Proyecto 3 |
|---|---|---|
| Bryan Romo | Project Manager | repositorio y reglas, congelamiento de clases, CI y disciplina de repo, auditoría final |
| Luisa Zaldivar | ML Engineer | CNN, entrenamiento por minibatches, reproducibilidad, 10 corridas MLflow, selección y evaluación final |
| Ignacio Villaseñor | Frontend / Full-stack | las 5 páginas nuevas del portal |
| Santiago Ortiz | Backend / MLOps | recortes COCO, manifiesto 70/20/10, paquete del modelo y publicación en S3 |

Plan de trabajo: `Plan de Trabajo - Proyecto 3 V1.docx` (raíz del repo).

---

## Flujo del Proyecto 3

```text
release aprobado del Proyecto 2 (DVC v1.0.0, Quality Gate PASS)
  -> recortes desde cajas COCO válidas, con exclusiones registradas      (T3-1.1)
  -> manifiesto derivado 70/20/10 sin fuga, agrupado por imagen original
     y por duplicados cercanos                                          (T3-1.2)
  -> entrenamiento por minibatches: ResNet-18, semillas controladas,
     aumentación solo en train, early stopping con la mejor época      (T3-1.3 a T3-2.5)
  -> 10 corridas en MLflow                                              (T3-3.1)
  -> selección del candidato por validación, antes de abrir el test     (T3-3.2)
  -> evaluación única sobre el test congelado                           (T3-3.3)
  -> paquete versionado del modelo + tarjeta -> AWS S3                  (T3-3.6)
  -> páginas del portal                                (T3-1.5, 2.3, 3.4, 3.5, 3.7, 4.1)
```

Clases: `car` y `person`. `dog` se excluyó **antes** de ver el test por no tener muestras
(acta en `docs/t3-0-6-class-freeze.md`). El manifiesto tiene 1038 recortes (740 / 203 / 95)
de 309 imágenes originales de `car` y 311 de `person`.

## Resultados y trazabilidad

| Eslabón | Valor | Dónde se verifica |
|---|---|---|
| Release de origen | `v1.0.0`, COCO md5 `0ac4ecdbbd5a9b3144624ec86009b9e7`, Quality Gate `pass` | `pipeline/data/raw/coco-dataset.json.dvc`; etiquetas `dvc_raw_md5` y `quality_gate_status` de cada corrida |
| Manifiesto 70/20/10 | SHA-256 `394743403f8a263b462687b733272e9993d7dddaea6a1229f8ee2896b82f3f7d` | `pipeline/data/processed/classifier_split_manifest.json` (salida DVC) |
| Corridas | 12 en el experimento `t3-classifier`, **10 válidas** | `list-runs`; `pipeline/reports/classifier/audit_runs.json` |
| Candidato | `r03-adamw-lr1e-4`, run `44725ac6b1704fed8b06bc4f846651d8` | `pipeline/reports/classifier/selection.json` |
| Checkpoint | SHA-256 `fe1c2370cb9d811d32cccc27edf0beeb3c440fe758c467a9e3fb91a73e6047cb` | `selection.json`; `verify_mlflow_restore.py` |
| Test | **94/95 = 0.98947**, F1 macro 0.98924, baseline de clase mayoritaria 0.5684 | `test_predictions.csv`, `test_evaluation.json`, `interpretation.md`; `audit-test` |
| Store de MLflow | DVC `pipeline/mlflow-data.dvc` en `s3://dvc-cache-prod-685538571046` | `pipeline/reports/classifier/mlflow_s3_persistence.md` |
| Versión del modelo | `v1.0.0`: pesos, tarjeta, configuración, mapa de clases y preprocesamiento | `docs/t3-3-6-model-release.md` |

Toda la evidencia de ML está en `pipeline/reports/classifier/`. Cómo se generó cada archivo
está en la sección del clasificador de `pipeline/README.md`.

---

## Clon limpio: orden de arranque

1. **Restaurar el store de MLflow, antes del primer `docker compose up`.** Requiere DVC con
   soporte S3 y credenciales AWS de lectura sobre `dvc-cache-prod-685538571046`:

   ```bash
   pip install "dvc[s3]>=3,<4"
   cd pipeline
   dvc pull -r prod mlflow-data.dvc     # "94 files fetched and 205 files added"
   cd ..
   ```

   Si el servicio `mlflow` ya arrancó en este clon, habrá creado un store vacío y el `pull`
   se negará a sobrescribirlo. En ese caso: `docker compose stop mlflow`, luego
   `dvc pull -r prod --force mlflow-data.dvc` (desde `pipeline/`) y `docker compose start mlflow`.

   Sin credenciales, las 12 corridas con sus parámetros, métricas por época, etiquetas y
   curvas están versionadas en `pipeline/reports/classifier/mlflow_runs.json` y `curves/`.

2. **Restaurar el dataset real y levantar el stack:** `./scripts/restore-env.sh` (ver
   [Dataset real](#dataset-real-necesario-para-el-pipeline)). El script arranca
   `docker compose up -d` por su cuenta.

3. **Comprobar MLflow** (desde `pipeline/`, con el stack arriba):
   `python scripts/verify_mlflow_restore.py` debe terminar con `"passes": true`.

4. **Abrir el portal** en http://localhost:8080. Las páginas del clasificador se describen abajo.

## Páginas del clasificador

Viven en la misma Web App que las de los Proyectos 1 y 2, con su propio menú.

| Ruta | Qué muestra | Fuente de datos |
|---|---|---|
| `/training` | formulario de parámetros y trabajo en segundo plano, con estado, progreso y logs que persisten al recargar | backend `POST /training/jobs`, `GET /training/jobs/:jobId` (tabla `training_jobs` en MariaDB) |
| `/experiments` | corridas de MLflow, sus parámetros y métricas | backend `GET /experiments`, `GET /experiments/:runId` → API de MLflow |
| `/evaluation` | candidato seleccionado, métricas finales y matriz de confusión | backend `GET /evaluation`, `GET /evaluation/selection` → `pipeline/reports/classifier/` |
| `/models` | modelos, selección para inferencia y descarga | backend `GET /models`, `POST /models/:runId/select`, `GET /models/:runId/download` |
| `/inference` | carga de una imagen para clasificar | — |

La validación de la configuración de entrenamiento con las mismas reglas que el entrenador
está en el servicio `classifier-api` (`GET /classifier-api/training/schema`,
`POST /classifier-api/training/validate`). Los contratos de datos para el portal están en
`docs/t3-ml-contracts.md`.

### Pendientes conocidos

Estado del código en `main` a la fecha de esta revisión del README. Hay que quitar cada punto
cuando se resuelva:

- **Entrenamiento desde el portal:** `backend/src/logic/training.worker.ts` simula las épocas
  (`sleep`) en lugar de ejecutar el entrenador (`python -m dataset_quality.classifier train`).
  El formulario valida con su propio esquema, que no incluye `hidden_layers`, en lugar de usar
  `classifier-api`.
- **Experiments, Evaluation y Models dentro de Docker:** el servicio `backend` de
  `docker-compose.yml` no define `MLFLOW_TRACKING_URI` (el cliente usa `localhost:5000` por
  defecto) ni monta `pipeline/reports/classifier`, que el backend lee desde
  `../pipeline/reports/classifier`.
- **Inference:** la página todavía no llama a ningún endpoint de predicción.

---

## Clasificador: comandos y verificación

El código está en `pipeline/src/dataset_quality/classifier/`. La guía completa (entrenamiento,
las 10 corridas, selección, evaluación y verificación) está en la sección del clasificador de
`pipeline/README.md`. Desde `pipeline/`, con `PYTHONPATH=src` y
`MLFLOW_TRACKING_URI=http://localhost:5000`:

| Qué se comprueba | Comando |
|---|---|
| Pruebas del clasificador | `python -m pytest tests/classifier -q` |
| Configuración inválida rechazada (sale con código 2) | `python -m dataset_quality.classifier validate-config --json '{"batch_size": 0}'` |
| Las 10 corridas válidas y los 7 hiperparámetros con ≥ 2 valores | `python -m dataset_quality.classifier list-runs` |
| Selección por validación y antes del test | `python -m dataset_quality.classifier audit-selection` |
| Métricas desde las predicciones guardadas, contra el JSON y MLflow | `python -m dataset_quality.classifier recompute` y `audit-test` |
| Evaluación repetida con el checkpoint, sin sobrescribir | `python -m dataset_quality.classifier evaluate --audit` |
| Reproducibilidad de dos corridas | `python -m dataset_quality.classifier repro-check <RUN_A> <RUN_B>` |
| Prueba de mutación en una copia aislada | `python scripts/classifier_mutation_check.py` |

`list-runs`, `audit-selection`, `audit-test`, `evaluate --audit`, `repro-check` y la prueba
de mutación salen con código distinto de 0 si su comprobación falla; `recompute` solo imprime
las métricas recalculadas. Las salidas de referencia están commiteadas en
`pipeline/reports/classifier/`.

## Pruebas y CI

- GitHub Actions (`.github/workflows/pipeline-ci.yml`): `ruff check`, `ruff format --check` y
  `pytest` del pipeline, sin `continue-on-error`.
- Backend y frontend: `npm run lint` (Biome), `npm run typecheck` y `npm test` dentro de
  `backend/` o `frontend/`. Hoy no corren en CI.

---

# Base heredada de los Proyectos 1 y 2

Lo que sigue documenta el portal de anotación y el pipeline de calidad y versionado sobre los
que se construye el Proyecto 3.

## Levantar el stack (Web App)

<!-- APP-09: la validación de "clonar limpio y arrancar todo con solo el
README" encontró que este proyecto no tenía ningún paso a paso explícito
para levantar la Web App -- solo una mención de pasada dentro de la sección
del pipeline de Python. Esta sección lo cubre. -->

Requisitos: Docker y Docker Compose (`docker compose version`). No hace falta
Node, Python ni ninguna base de datos instalada localmente -- todo corre en
contenedores.

Eso cubre levantar la app. **Restaurar el dataset real** (siguiente sección)
pide además un shell POSIX: `bash`, `curl`, y `unzip` o Python. En Windows
eso significa **Git Bash o WSL** -- `./scripts/restore-env.sh` no corre desde
PowerShell ni desde `cmd`.

Desde la raíz del repo, sin ningún paso manual previo (no hay que copiar
ningún `.env`; las variables ya están fijadas en `docker-compose.yml` para
desarrollo local):

```bash
docker compose up --build
```

Esto levanta los siete servicios por defecto (`mariadb`, `minio`, `backend`,
`copilot`, `classifier-api`, `mlflow` y `frontend`, ver `docker-compose.yml`) -- **no** incluye el
pipeline de Python, que vive detrás de un profile aparte (ver
[Pipeline (Python)](#pipeline-python) más abajo). El Portal de Anotación
(Proyecto 1, rutas `/dashboard`, `/search`, `/upload`) funciona con solo este
comando. Las 5 páginas del clasificador (`/training`, `/experiments`, `/evaluation`,
`/models`, `/inference`) se describen en [Páginas del clasificador](#páginas-del-clasificador);
las que leen MLflow necesitan su store restaurado **antes** de este comando (ver
[Clon limpio: orden de arranque](#clon-limpio-orden-de-arranque)). **Las 6 pantallas de Dataset Quality** (`/overview`, `/analyzers`,
`/splits`, `/versions`, `/copilot`, `/settings`) necesitan además que el
pipeline haya corrido al menos una vez -- son las que leen
`pipeline/data/interim/*.json` -- ver la sección de DVC más abajo para el
comando exacto; sin eso, cargan pero sin datos. MariaDB no tiene UI
propia (solo la usa `backend` internamente); `copilot` es el servicio HTTP
del Dataset Copilot que consume la pantalla `/copilot`, y `classifier-api`
valida la configuración de entrenamiento con las mismas reglas que el
entrenador (la Web App lo llama como `/classifier-api/`, ver
`pipeline/README.md`). Las URLs para entrar desde el navegador:

- Web App: http://localhost:8080
- API (backend): http://localhost:3100
- API de configuración de entrenamiento: http://localhost:8200/training/schema
- MLflow (corridas del clasificador): http://localhost:5000
- Consola de MinIO: http://localhost:9001 (usuario/clave: `minioadmin` / `minioadmin`)

El backend aplica migraciones y siembra datos de ejemplo automáticamente al
arrancar (`backend/docker/entrypoint.sh`) -- no hace falta ningún paso manual
de base de datos. La primera vez tarda un poco más porque construye las
imágenes de `backend` y `frontend`.

Para bajar el stack: `docker compose down` (agrega `-v` si además quieres
borrar los volúmenes de datos de MariaDB/MinIO y arrancar desde cero).

## Dataset real (necesario para el pipeline)

Un clon limpio arranca con MinIO vacío y sin las imágenes del Proyecto 1 en la
base. Eso basta para el Portal de Anotación, pero **no** para el pipeline: la
etapa `analyze` mide duplicados con pHash sobre los bytes reales de cada
imagen, que resuelve consultando el `storage_key` en la tabla `images` y
bajando el objeto de MinIO. Sin esos datos falla cerrado a propósito
(`DuplicateBytesUnavailableError`) en vez de reportar un `duplicates: 0`
fabricado -- ver la "Limitación conocida" al final de la sección de DVC.

Para dejar el entorno con el dataset real del release `v1.0.0`, desde un shell
POSIX (`bash`; en Windows, Git Bash o WSL -- no PowerShell):

```bash
./scripts/restore-env.sh
```

No hace falta levantar nada antes: el restore arranca el stack por su cuenta
(`docker compose up -d`) y espera a que MariaDB y el esquema del backend
existan, porque escribe en MinIO y en MariaDB. Si ya lo tenías arriba,
tampoco estorba.

Necesita `curl` y, para descomprimir, `unzip` o Python (usa el que encuentre).

Baja el bundle de datos (~496 MiB) desde [GitHub Releases][bundle], **verifica
su SHA-256 contra el digest que publica GitHub antes de extraer o ejecutar
nada** (si no coincide, borra la descarga y corta), sube las 311 imágenes a
MinIO, carga el dump de MariaDB (313 filas en `images`, 1038 en `annotations`)
y verifica los conteos -- si algo no cuadra corta con error en vez de dejarte
seguir con datos a medias. Si el bundle ya está en disco, solo lo reutiliza
si quedó registrado el digest verificado (`.dq-env-bundle/.sha256-verificado`);
si falta (instalación de una versión anterior del script) o no coincide, lo
descarta y lo descarga y verifica de nuevo.

El digest esperado está fijado en el script y se puede contrastar con la
fuente sin confiar en el repo:

```bash
gh api repos/White-eclipse1/Proyecto-02-dataset-Quality/releases/tags/v1.0.0-data --jq '.assets[].digest'
```

El bundle es un asset del release, no contenido del repo: el dataset se
versiona con DVC, no con git.

[bundle]: https://github.com/White-eclipse1/Proyecto-02-dataset-Quality/releases/tag/v1.0.0-data

---

## Arquitectura del pipeline de calidad (Proyecto 2)

El flujo del pipeline de calidad es:

```text
COCO Dataset
     │
     ▼
┌─────────────────┐
│ 1. Ingesta      │
│ + Pydantic      │
└────────┬────────┘
         │
         ▼
┌─────────────────────┐
│ 2. Quality Analyzers│
└─────────┬───────────┘
          │
          ▼
┌─────────────────┐
│ 3. Quality Gate │
│   quality.yaml  │
└───────┬─────────┘
        │
    ┌───┴────┐
    │        │
  PASS      FAIL
    │        │
    ▼        └──► Re-anotación / corrección
┌─────────────────┐
│ 4. Data Splits  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 5. DVC Version  │
└────────┬────────┘
         │
         ├──► DEV  / MinIO
         └──► PROD / AWS S3
```

---

## Pipeline (Python)

El pipeline de calidad vive en [`pipeline/`](pipeline/), como paquete Python separado del portal de anotación (`backend/`, `frontend/`). Fijado a Python 3.12 (`pipeline/pyproject.toml`, `pipeline/Dockerfile`).

Setup local:

```bash
cd pipeline
cp .env.example .env
python -m venv .venv && source .venv/bin/activate   # Windows: ver nota abajo
pip install -r requirements.txt -r requirements-dev.txt
ruff check .
pytest
```

Las dependencias se editan en `requirements.in` / `requirements-dev.in` y se recompilan con `pip-compile --generate-hashes` hacia `requirements.txt` / `requirements-dev.txt`. Nunca se editan a mano los `.txt` compilados — si se hace, se pierde el hash-locking.

### Notas para Windows

Los archivos `requirements*.txt` se compilan con `pip-compile --generate-hashes` en Linux/Mac. Eso deja fuera del lockfile cualquier dependencia transitiva marcada como solo-Windows (`sys_platform == "win32"` en su metadata) — `pip install -r requirements-dev.txt --require-hashes` falla en Windows con `"all requirements must have their versions pinned"` para esos paquetes, aunque el resto instale bien. Hasta ahora se han visto:

- `colorama` (dependencia de `pytest` en Windows).
- `pywin32` (dependencia de `mcp`, usado por el Dataset Copilot / APP-06, en Windows).

Si `pip install -r requirements-dev.txt --require-hashes` se queja de alguno de estos (o de otro paquete nuevo con el mismo patrón), instálalo suelto primero y repite el comando — pip lo va a tratar como ya satisfecho y va a saltarse el requisito de hash solo para ese paquete:

```powershell
pip install colorama pywin32
pip install -r requirements-dev.txt --require-hashes
```

Además, en Windows conviene usar el lanzador `py` en vez de `python` a secas (puede no apuntar a la versión correcta si hay varios Pythons instalados). El proyecto está fijado a Python 3.12 (`pyproject.toml`):

```powershell
py -0                       # lista los Pythons instalados
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-dev.txt
```

También corre contenedorizado junto al resto del stack. Está detrás de un profile de Docker Compose (`pipeline`) porque hoy es solo tooling de CLI/batch — sin servidor HTTP — así que `docker compose up` sigue levantando únicamente app + MariaDB + MinIO:

```bash
docker compose --profile pipeline run --rm pipeline <comando>
```

### DVC (OPS-04)

El pipeline reproducible vive en `pipeline/dvc.yaml`: `ingest → validate → analyze → quality_gate → split → release`. Parámetros (categorías objetivo, umbrales de analizadores, proporciones de split) en `pipeline/params.yaml`; el dataset crudo (`pipeline/data/raw/coco-dataset.json`) nunca se versiona en git — solo su puntero `.dvc` — y se sincroniza contra MinIO (DEV) como remote de DVC.

**Instalar DVC por separado**, no como parte de `requirements-dev.txt`: `dvc[s3]` trae `aiobotocore`, que exige un rango de `botocore` incompatible con el `boto3` ya fijado del pipeline — mezclarlos en el mismo lockfile rompe la resolución. Instálalo aislado (`pipx install "dvc[s3]"` es lo más simple) o en un entorno Python separado.

**El remote DEV usa el hostname de Compose** (`http://minio:9000` en `.dvc/config`, ya versionado), así que `dvc repro`/`push`/`pull` necesitan correr donde ese hostname resuelva — dentro del profile `pipeline` de Compose (ver abajo), o en un contenedor conectado a la red que Compose crea para este repositorio. Esa red se llama `<nombre-del-proyecto>_default` y **no** es un nombre fijo que se pueda escribir a mano: por defecto es el nombre de la carpeta del clon, o el de `COMPOSE_PROJECT_NAME` si lo fijas, así que conviene sacarlo del propio contenedor de `minio` en vez de hardcodearlo:

```bash
NET="$(docker inspect "$(docker compose ps -q minio)" --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}')"
docker run --rm --network "$NET" <imagen> <comando>
```

**Dentro del profile `pipeline` de Compose, esto ya funciona sin pasos manuales**: el bucket `dvc-cache` lo crea el servicio `minio-init` (igual de profile-gated que `pipeline`, corre `mc mb --ignore-existing` una vez contra MinIO) y las credenciales llegan al binario `dvc` — que vive en su propio venv aislado dentro de la imagen, con su propio boto3, separado del `Settings`/`OBJECT_STORE_*` de la app — vía las variables estándar `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` ya seteadas en el `environment:` del servicio `pipeline`:

```bash
docker compose --profile pipeline run --rm pipeline sh -c "PYTHONPATH=src dvc repro"
docker compose --profile pipeline run --rm pipeline dvc push -r dev
docker compose --profile pipeline run --rm pipeline dvc pull -r dev
```

**Corriendo `dvc` fuera de Compose** (por ejemplo directo en el host) sí hace falta lo anterior a mano — ni el bucket ni las variables `AWS_*` existen fuera del servicio `pipeline`:

```bash
cd pipeline
dvc remote modify --local dev access_key_id minioadmin
dvc remote modify --local dev secret_access_key minioadmin
PYTHONPATH=src dvc repro
dvc push -r dev
dvc pull -r dev
```

`dvc repro` corrido dos veces no debe rehacer ninguna etapa; tocar `params.yaml` o `quality.yaml` solo debe rehacer las etapas realmente afectadas (`dvc dag` muestra el grafo completo).

**Su salida tiene que llegar al host** (hallazgo de la auditoría externa, OPS-09): sin un `volumes:` para `data/` en el servicio `pipeline`, `quality.json`/`splits.json`/`versions.json` se escriben solo dentro de la capa del contenedor `--rm` y desaparecen al salir — `backend` bind-montea ese mismo directorio del host en solo lectura y nunca ve nada, así que en un clon limpio las 6 pantallas de Dataset Quality (`/overview`, `/analyzers`, `/splits`, `/versions`, `/copilot`, `/settings`) cargan sin error pero sin datos. El montaje que lo resuelve (`./pipeline/data:/app/data`) lo aporta APP-10 (PR #55), que necesita esa misma persistencia para el Copilot; por eso no se duplica aquí. Con él en su lugar, el orden real para tener las 6 pantallas con datos reales desde un clon limpio es:

```bash
./scripts/restore-env.sh          # solo la primera vez, en un clon limpio
docker compose --profile pipeline run --rm pipeline sh -c "PYTHONPATH=src dvc pull -r dev data/raw/coco-dataset.json.dvc && PYTHONPATH=src dvc repro"
```

El restore levanta el stack por su cuenta, así que ese es literalmente el
primer comando de un clon limpio. Con el stack arriba, las 6 pantallas
recogen los datos en la siguiente petición, sin reiniciar nada — verificado
de punta a punta: tras el restore, el `dvc pull` dirigido trae el dataset fuente
desde el remote DEV y `dvc repro` genera las salidas derivadas de las 8 etapas; no
se usa un `dvc pull -r dev` global porque el cache del bundle no contiene todas las
salidas nuevas del clasificador. Finalmente,
`GET /quality-report` responde con `v1.0.0` / `pass` reales.

Y ese restore es lo que hace reproducible todo lo demás: en un clon limpio el
bucket `dvc-cache` de MinIO lo crea `minio-init` **vacío** y el dataset crudo
no vive en git (solo su puntero `.dvc`), así que `dvc pull -r dev` no tiene de
dónde bajar nada todavía; el bundle del release `v1.0.0` es el que trae los
bytes reales (ver [Dataset real](#dataset-real-necesario-para-el-pipeline)
arriba). El `dvc repro` tarda la primera vez porque corre las 8 etapas de
verdad.

**Limitación conocida:** la verificación de `duplicates` (pHash) necesita descargar las imágenes reales desde el object store — el export COCO solo trae el nombre de archivo, no el `storage_key` de MinIO, así que la etapa `analyze` lo resuelve consultando la tabla `images` de MariaDB por `id` (los IDs de COCO son los mismos IDs de la BD). `duplicates` es un check `severity: fail` en `quality.yaml`, así que si esa BD/objeto no está disponible en el entorno donde corre `dvc repro` (por ejemplo, corriendo contra un dataset anotado en otra instancia), la etapa `analyze` **falla cerrado**: lanza `DuplicateBytesUnavailableError` y no se genera `quality.json` — nunca se reporta un `duplicates: 0` fabricado que dejaría pasar el gate sin haber medido nada de verdad.
