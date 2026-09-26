# Proyecto-02-dataset-Quality
MLOps project for dataset quality, validation, reproducible splitting, versioning and release management using COCO, Pydantic, DVC, MinIO/S3, Docker, Terraform and GitHub Actions. Includes automated quality analyzers, quality gates, dataset versioning, a web dashboard and an MCP-based Dataset Copilot.
# Team 3 — Dataset Quality & Versioning Pipeline



Este proyecto implementa un pipeline reproducible para transformar un dataset en formato COCO en un dataset validado, analizado, particionado, versionado y liberable.

El objetivo principal es garantizar que una versión del dataset solo pueda ser liberada cuando cumpla las políticas de calidad definidas por el equipo.

---

## Team 3

- Hannah Chenoa
- Diego Lemus
- Mauricio Figueroa
- Santiago Ortiz

---

## Objetivo del proyecto

El sistema toma como entrada un dataset COCO y ejecuta un pipeline compuesto por cinco etapas principales:

1. Ingesta y validación del dataset
2. Análisis automático de calidad
3. Quality Gate
4. Generación reproducible de splits
5. Versionado y promoción del dataset

El pipeline puede terminar en dos estados:

- `PASS`: el dataset cumple las políticas y puede continuar hacia split y versionado.
- `FAIL`: el dataset no cumple una o más políticas críticas y el release queda bloqueado.

---

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

Esto levanta los cinco servicios por defecto (`mariadb`, `minio`, `backend`,
`copilot` y `frontend`, ver `docker-compose.yml`) -- **no** incluye el
pipeline de Python, que vive detrás de un profile aparte (ver
[Pipeline (Python)](#pipeline-python) más abajo). El Portal de Anotación
(Proyecto 1, rutas `/dashboard`, `/search`, `/upload`) funciona con solo este
comando. **Las 6 pantallas de Dataset Quality** (`/overview`, `/analyzers`,
`/splits`, `/versions`, `/copilot`, `/settings`) necesitan además que el
pipeline haya corrido al menos una vez -- son las que leen
`pipeline/data/interim/*.json` -- ver la sección de DVC más abajo para el
comando exacto; sin eso, cargan pero sin datos. De esos cinco, tres
exponen una URL a la que entrar desde el navegador (MariaDB no tiene UI
propia, solo la usa `backend` internamente, y `copilot` es el servicio HTTP
del Dataset Copilot que consume la pantalla `/copilot`, no una UI aparte):

- Web App: http://localhost:8080
- API (backend): http://localhost:3100
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

# Arquitectura

El flujo general del proyecto es:

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

**El remote DEV usa el hostname de Compose** (`http://minio:9000` en `.dvc/config`, ya versionado), así que `dvc repro`/`push`/`pull` necesitan correr donde ese hostname resuelva — dentro del profile `pipeline` de Compose, o en un contenedor conectado a la misma red (`docker network connect` / `--network proyecto-02-dataset-quality_default`).

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
docker compose --profile pipeline run --rm pipeline sh -c "PYTHONPATH=src dvc pull -r dev && PYTHONPATH=src dvc repro"
```

El restore levanta el stack por su cuenta, así que ese es literalmente el
primer comando de un clon limpio. Con el stack arriba, las 6 pantallas
recogen los datos en la siguiente petición, sin reiniciar nada — verificado
de punta a punta: tras el restore, `dvc pull -r dev` trae los 9 archivos del
remote DEV, `dvc repro` reporta las 7 etapas sin cambios, y
`GET /quality-report` responde con `v1.0.0` / `pass` reales.

Y ese restore es lo que hace reproducible todo lo demás: en un clon limpio el
bucket `dvc-cache` de MinIO lo crea `minio-init` **vacío** y el dataset crudo
no vive en git (solo su puntero `.dvc`), así que `dvc pull -r dev` no tiene de
dónde bajar nada todavía; el bundle del release `v1.0.0` es el que trae los
bytes reales (ver [Dataset real](#dataset-real-necesario-para-el-pipeline)
arriba). El `dvc repro` tarda la primera vez porque corre las 6 etapas de
verdad.

**Limitación conocida:** la verificación de `duplicates` (pHash) necesita descargar las imágenes reales desde el object store — el export COCO solo trae el nombre de archivo, no el `storage_key` de MinIO, así que la etapa `analyze` lo resuelve consultando la tabla `images` de MariaDB por `id` (los IDs de COCO son los mismos IDs de la BD). `duplicates` es un check `severity: fail` en `quality.yaml`, así que si esa BD/objeto no está disponible en el entorno donde corre `dvc repro` (por ejemplo, corriendo contra un dataset anotado en otra instancia), la etapa `analyze` **falla cerrado**: lanza `DuplicateBytesUnavailableError` y no se genera `quality.json` — nunca se reporta un `duplicates: 0` fabricado que dejaría pasar el gate sin haber medido nada de verdad.