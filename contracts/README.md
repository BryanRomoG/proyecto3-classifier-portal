# Data Contracts — Web App & Dataset Copilot

Este directorio define los **contratos de datos** que la Web App (Overview,
Analyzers, Splits, Versions, Copilot, Settings) y el Dataset Copilot (MCP)
van a consumir desde el pipeline de calidad y versionado.

Se crean como parte de `APP-01` para que el desarrollo de la aplicación
pueda arrancar (`APP-02` y siguientes) **sin esperar** a que Data Quality
(analizadores, `quality.yaml`) y MLOps (DVC, splits) terminen su parte.

## Estado

Estos son **archivos de ejemplo (mock)**, no salidas reales del pipeline.
Las cifras son ilustrativas y deliberadamente no coinciden con ninguna
métrica real de producción — su propósito es fijar la **forma** de los
datos (nombres de campos, tipos, anidamiento), no el contenido.

Cuando los tiers 2-5 del pipeline (analizadores, quality gate, splits, DVC)
existan de verdad, sus salidas deben producir JSON con esta misma forma.
Cualquier cambio a la forma aquí definida debe acordarse con los dueños de
Data Quality y MLOps antes de mergear, y quedar reflejado en este README.

## Archivos

- `quality.json` — salida de la Quality Gate (Tier 3): resultado por check
  (`pass` / `warn` / `fail`), valor observado vs. umbral, y muestras
  ofensoras. Lo consumen las pantallas **Overview**, **Analyzers** y
  **Settings**, y las herramientas de solo lectura del Copilot.
- `splits.json` — salida del split estratificado (Tier 4): conteos y
  distribución de clases por partición, semilla usada, proporciones
  configuradas y resultado del chequeo de fuga (leakage) entre
  train/val/test. Lo consume la pantalla **Splits**.
- `versions.json` — salida del versionado con DVC (Tier 5): línea de
  tiempo de versiones semánticas, hash de contenido, estado de
  sincronización DEV (MinIO) / PROD (S3), y diff entre versión actual y
  anterior. Lo consume la pantalla **Versions**.

## Reconciliación con DQ-02

`DQ-02` definió la política real de la Quality Gate (`pipeline/quality.yaml`)
y los modelos Pydantic que la validan (`pipeline/src/dataset_quality/quality_gate/`).
Al mergear `main` en esta rama se ajustó `quality.json` para que coincida
exactamente con esa política:

- Los 5 checks (`min_images_per_class`, `class_imbalance`, `small_objects`,
  `duplicates`, `invalid_boxes`) usan el mismo `threshold`, `severity` y
  `unit` que `quality.yaml`.
- Se quitó el check `spatial_bias`: no está definido en la política de
  DQ-02 y el motor de evaluación (`evaluate_policy`) solo puede producir
  un resultado por check declarado ahí, así que un check fuera de esa
  lista nunca aparecería en una salida real. Si se retoma más adelante,
  debe agregarse primero a `quality.yaml` con un `threshold` numérico
  (el modelo `QualityCheckResult` no permite `threshold`/`observed`
  nulos).
- Se quitaron los campos `_contract`/`_note` del nivel superior: el
  modelo `QualityReport` usa `extra = "forbid"`, así que cualquier campo
  fuera de `dataset_version`, `generated_at`, `overall_status` y `checks`
  rompe la validación real del pipeline.

Verificado cargando este archivo con el `QualityReport` real de DQ-02
(`QualityReport.model_validate(...)`): valida sin errores y los 5 checks
coinciden 1:1 con `quality.yaml`.

## Reconciliación con APP-04

`APP-04` implementó el generador de splits real
(`pipeline/src/dataset_quality/splits/`) y su modelo de salida
`SplitResult` (`pipeline/src/dataset_quality/splits/models.py`), que
también usa `extra = "forbid"`. Se ajustó `splits.json`:

- Se quitaron los campos `_contract`/`_note` del nivel superior, por la
  misma razón que en la reconciliación de `quality.json` con DQ-02: son
  metadata del mock, no parte de la forma real que produce el pipeline.
- El resto del archivo (proporciones, `tolerance`, totales, distribución
  de clases, `leakage_check`, `reproducibility_check`) ya tenía exactamente
  la forma que `SplitResult` produce — no fue necesario cambiar nada más.

Verificado cargando este archivo con `SplitResult.model_validate(...)`:
valida sin errores (`pipeline/tests/test_splits.py`).

Las cifras siguen siendo ilustrativas (mock de APP-01) — `APP-04` fija la
forma real de la salida, pero todavía no corre contra un dataset real;
eso es alcance de `APP-07` (conectar la Web App a las salidas reales del
pipeline).

## Reconciliación con APP-06

`APP-06` agrega el servidor MCP de solo lectura y el Dataset Copilot
(`pipeline/src/dataset_quality/copilot/`), que leen los tres contratos de
este directorio (`quality.json`, `splits.json`, `versions.json`) tal cual
están en disco — es el único I/O del Copilot (ver `copilot/store.py`).

`versions.json` (Tier 5) no tenía todavía un modelo Pydantic estricto —
`quality.json` ya lo tiene desde `DQ-02`, y `splits.json` lo obtiene en
`APP-04`. `APP-06` define `VersionsReport` (`copilot/contracts.py`,
`extra = "forbid"`) como el modelo real de `versions.json`, y al
reconciliar se ajustó el archivo:

- Se quitaron los campos `_contract`/`_note` del nivel superior, igual que
  se hizo con `quality.json` en `DQ-02`: `VersionsReport` no permite campos
  fuera de `current_version` y `versions`, así que cualquier metadato de
  mock rompe la validación real.
- No se tocó la forma de `environments` (`dev`/`prod`) ni `diff_from_previous`:
  ya coincidían campo por campo con `VersionEnvironments`/`VersionDiff`.

Verificado cargando este archivo con el `VersionsReport` real de APP-06
(`VersionsReport.model_validate(...)`): valida sin errores
(`tests/test_copilot.py::test_real_versions_contract_validates_with_the_new_model`).

Para `splits.json`, el Copilot todavía usa a propósito un modelo propio y
más permisivo (`SplitsSummary`, `extra = "ignore"`) en lugar del
`SplitResult` estricto de `APP-04` — quedó así de cuando `APP-04` todavía
no estaba en `main`. Ahora que ya se mergeó, sigue pendiente un cambio de
seguimiento (fuera de este PR) para reemplazar `SplitsSummary` por el
`SplitResult` real; ver el `TODO(APP-04 merge)` en `copilot/contracts.py`.
Mientras tanto, ninguna herramienta del Copilot deja de funcionar contra
`main`.

## Reconciliación con APP-05

`APP-05` implementó las pantallas del dashboard (Overview, Analyzers,
Splits, Versions, Settings) contra estos contratos. Dos ajustes:

- Se agregó `dataset_summary` (`total_images`, `total_bounding_boxes`,
  `total_categories`) a `quality.json`, y el modelo real `QualityReport`
  (`pipeline/src/dataset_quality/quality_gate/models.py`) gana el campo
  opcional correspondiente (`QualityDatasetSummary`, `extra = "forbid"`,
  por defecto `None`). Es opcional a propósito: ningún check por sí solo
  trae estos totales (son del dataset completo, no de un check), y así
  cualquier llamada existente a `evaluate_policy()` sin un `CocoDataset` a
  la mano sigue validando igual que antes. Cuando sí se le pasa un
  `CocoDataset` (parámetro nuevo `dataset`, opcional), `evaluate_policy()`
  calcula el bloque a partir de `len(dataset.images)`,
  `len(dataset.annotations)` y `len(dataset.categories)`. La pantalla
  Overview lo consume para las cuatro cifras que pide su Acceptance
  Criteria (imágenes, cajas, categorías, checks fallidos — este último se
  deriva en el frontend contando `checks` con `status: "fail"`, no
  requiere campo nuevo).
- La pestaña "Spatial Bias" de Analyzers sigue en la UI (la pide el AC de
  `APP-05`), pero ya no tiene datos reales que mostrar desde la
  reconciliación con `DQ-02` (ver arriba: el check se quitó de
  `quality.yaml`). Se muestra con un estado explícito de "no disponible"
  en vez de datos inventados — ver `frontend/src/pages/dataset/Analyzers.tsx`.
  Si `DQ-02` retoma `spatial_bias` más adelante, la pestaña empieza a
  mostrar datos reales sin cambios adicionales en la Web App.
- `Settings` habilita la edición de `threshold`/`severity` que pedía el
  AC, pero solo en estado local de React — no hay persistencia contra
  `quality.yaml` todavía (sigue siendo alcance de un ticket posterior, una
  vez exista la política real editable de Data Quality). No se agregó un
  botón "Guardar" que fingiera persistir el cambio.

Verificado cargando `quality.json` con el `QualityReport` real de APP-05
(`QualityReport.model_validate(...)`): valida sin errores, incluyendo el
nuevo bloque `dataset_summary`
(`pipeline/tests/test_quality_policy.py`).

## Reconciliación con APP-07

`APP-07` conecta la Web App a las salidas REALES de la pipeline en vez de
los mocks estáticos de `frontend/public/contracts/*.json` (copias de este
directorio, ver "Estado" arriba). El AC pedía dos cosas: que las pantallas
de solo lectura muestren datos reales, y que `Settings` persista de verdad
contra `pipeline/quality.yaml` (Agent Test: un cambio en Settings afecta la
siguiente corrida del Quality Gate, `dvc repro`).

Antes de este ticket no existía ningún mecanismo para que el backend
(Node/Express, Fase 2) o el frontend leyeran/escribieran los archivos de
este directorio ni `pipeline/quality.yaml` — solo el Copilot (Python,
`copilot/store.py`) los tocaba. Se agregó una capa nueva en el backend
(`backend/src/logic/pipeline-contracts.service.ts`,
`backend/src/logic/quality-policy.service.ts` +
`quality-policy.builder.ts`, spec completo en
`backend/specs/pipeline-contracts.spec.md`, SPEC-PIPE-001):

- `GET /quality-report`, `GET /split-report`, `GET /version-history` leen
  `pipeline/data/interim/quality.json` / `splits.json` / `versions.json`
  (la salida real de los stages `quality_gate`/`split`/`release` de
  `pipeline/dvc.yaml` — **no** `contracts/quality.json` etc. en la raíz del
  repo, que sigue siendo el mock versionado de APP-01/APP-05; ver
  "Corrección de revisión" abajo) y los devuelven **tal cual** — el backend
  NO revalida su forma contra un
  esquema propio. La forma ya está garantizada por los modelos Pydantic
  `extra = "forbid"` de la pipeline (documentados en las reconciliaciones
  de arriba) y el frontend la valida con Zod al recibirla
  (`frontend/src/lib/contracts/schemas.ts`); una tercera copia del esquema
  en TypeScript del lado del backend solo arriesgaría que las tres
  copias se desincronicen sin que nada lo note. Si el archivo todavía no
  existe (la pipeline no ha corrido), el backend responde 404 con un
  mensaje explícito en vez de un 500 genérico o un objeto vacío que la UI
  pudiera confundir con "dataset real sin datos".
- `GET`/`PUT /quality-policy` leen y escriben `pipeline/quality.yaml`
  directamente — el mismo archivo que `dataset_quality.quality_gate.runner`
  lee en cada corrida (`pipeline/dvc.yaml`, stage `quality_gate`), sin
  ninguna copia intermedia. `PUT` edita ÚNICAMENTE `threshold` y
  `severity` por check: `label`, `comparison` y `unit` nunca los expone
  `Settings` para editar, y se conservan tal cual estaban. El body debe
  traer el conjunto EXACTO de `check_id` que ya existe en el archivo — ni
  uno de menos ni uno nuevo — porque agregar/quitar checks sigue siendo
  decisión de Data Quality, no de la Web App.
- El invariante de negocio `min_images_per_class.severity == "fail"` y
  `threshold >= 300` (`QualityPolicy.require_minimum_images_policy`,
  `pipeline/src/dataset_quality/quality_gate/models.py`) se reimplementó
  en TypeScript puro (`quality-policy.builder.ts`) para que `PUT
  /quality-policy` lo rechace con 400 ANTES de tocar el disco — no basta
  con que la pipeline lo vuelva a validar en la siguiente corrida, porque
  para entonces `Settings` ya habría mostrado "guardado" con éxito.

En `docker-compose.yml`, el servicio `backend` monta `./pipeline/data/interim`
como volumen de solo lectura y `./pipeline/quality.yaml` de lectura-escritura
(mismas rutas que usa la pipeline), configurables vía `PIPELINE_OUTPUT_DIR` /
`QUALITY_POLICY_PATH` (ver `.env.example` / `.env.production.example`).

Del lado del frontend, `Overview`, `Analyzers`, `Splits`, `Versions` y
`Copilot` cambiaron de `useContractFetch` (lee los JSON estáticos de
`public/contracts/`) a `useValidatedFetch` (pasa por el proxy `/api` hacia
el backend real). `Settings` se reescribió por completo: ya no lee
`quality.json` (un reporte de una corrida) sino `GET /quality-policy`
(`qualityPolicySchema`, la política editable), y el botón "Guardar" hace
`PUT /quality-policy` con el conjunto completo de checks (editados y sin
tocar) — ver `frontend/src/lib/api/qualityPolicy.ts`. Antes de `APP-07`,
`Settings` advertía explícitamente que los cambios eran locales a la
sesión y se perdían al recargar (ver "Reconciliación con APP-05" arriba);
ese banner ahora describe la persistencia real.

`useContractFetch.ts` y `frontend/public/contracts/*.json` se dejaron tal
cual — ya no los usa ninguna pantalla, pero se conservan como referencia
histórica de la forma mock original y para no invalidar `contracts-sync.test.ts`
(que sigue verificando que la copia servida coincida con este directorio).
Retirarlos por completo, si se decide, es un cambio de limpieza aparte.

Verificado con `npm test` en `backend/` (87/87, incluyendo las pruebas de
esta capa y la de la corrección de revisión de abajo) y en `frontend/`
(25/25, incluyendo el reemplazo de mocks por rutas reales y la
persistencia de `Settings`), `tsc --noEmit` y `biome check` limpios en
ambos paquetes, y verificaciones de mutación en el invariante de
`min_images_per_class` (backend) y en el armado del body completo de
`PUT` (frontend): sabotear cada regla hace fallar exactamente la prueba
que la cubre, nada más.

### Corrección de revisión (Mau)

La primera versión de este PR conectó el backend a `contracts/quality.json`
/ `splits.json` / `versions.json` (raíz del repo) — el mismo directorio que
este README documenta arriba como "archivos de ejemplo (mock)". Mau lo
marcó como bloqueante en la revisión: **`pipeline/dvc.yaml` nunca escribe
ahí**. Los stages reales (`quality_gate`, `split`, `release`) escriben en
`pipeline/data/interim/quality.json` / `splits.json` / `versions.json` (ver
sus bloques `outs:`), así que correr `dvc repro` no cambiaba nada de lo que
mostraba la Web App — el Agent Test de APP-07 ("Settings afecta la
siguiente corrida del Quality Gate... y la Web App refleja el resultado")
fallaba en la práctica para los tres `GET` de solo lectura.

De las dos opciones que Mau propuso (conectar el backend directo a esa
salida, o agregar un paso que publique los resultados reales en
`contracts/`), se eligió la primera: apuntar `env.CONTRACTS_DIR` — renombrado
a `env.PIPELINE_OUTPUT_DIR` para que el nombre ya no sugiera `contracts/` —
directamente a `pipeline/data/interim/`. Se descartó la segunda porque
hubiera significado agregar un stage nuevo a `pipeline/dvc.yaml` (fuera del
código que este PR toca, y terreno de Data Quality/MLOps) solo para
mantener viva una copia intermedia que ya no cumple ningún propósito una
vez que el backend puede leer la salida real directamente.

Cambios: `backend/src/config/env.ts` (`PIPELINE_OUTPUT_DIR`, default
`../pipeline/data/interim`), `pipeline-contracts.service.ts` (mismo
renombre), `docker-compose.yml` (el volumen del servicio `backend` ahora
monta `./pipeline/data/interim` en vez de `./contracts`), `.env.example` /
`.env.production.example`, y `backend/specs/pipeline-contracts.spec.md` /
`backend/features/pipeline-contracts.feature`. `GET`/`PUT /quality-policy`
no cambiaron — ya apuntaban correctamente a `pipeline/quality.yaml`, que sí
es un archivo fuente real (no una salida de `dvc repro`); Mau no señaló
ningún problema ahí.

Reproducido primero como prueba en rojo (`tests/pipeline-contracts.test.ts`,
"el default resuelve a pipeline/data/interim, no a contracts/"): con el
default viejo, la prueba fallaba porque `env.CONTRACTS_DIR` ya no existía
tras el renombre; con el fix, pasa confirmando que el default resuelve
dentro de `pipeline/data/interim/` y no termina en `contracts`.

El Copilot (Python, `copilot/store.py`) tiene el mismo default apuntando a
`contracts/` (`copilot/agent.py::default_contracts_dir`) y por lo tanto el
mismo problema de fondo — pero es código de APP-06, ya mergeado a `main`
antes de este PR, y fuera del Acceptance Criteria de APP-07 (que es sobre
la Web App). Queda anotado en "Pendiente" abajo en vez de tocarse aquí.
Tampoco se tocó el servicio `pipeline` de `docker-compose.yml`: no tiene
ningún volumen para `data/`, así que un `dvc repro` corrido vía
`docker compose --profile pipeline run` todavía no persiste su salida al
host (sí funciona corriendo la pipeline localmente, como hace el equipo
hoy) — ese es el `pipeline` service completo, terreno de OPS-04, y también
queda anotado en "Pendiente" en vez de modificarse sin acuerdo con ese
ticket.

## Reconciliación con APP-10

`APP-10` era, en el AC tal cual está escrito, un smoke test final: recorrer
las seis pantallas y correr el Agent Test de cada ticket anterior. En la
práctica, el Agent Test del Copilot ("hacerle una pregunta real y que
responda con datos reales, citando versión y herramientas usadas") no se
podía cumplir — `frontend/src/pages/dataset/Copilot.tsx` seguía siendo el
placeholder estático que dejó `APP-07` (ver "Pendiente" de esa
reconciliación arriba: "conecta esa pantalla a datos reales de lectura,
pero no construye la UI de chat en sí"). El rubro de evaluación del
profesor (Sección 8, Dataset Copilot, 10 de 100 puntos) confirma que esto
es un requisito explícito y evaluado, no una mejora opcional: exige un chat
que fundamente cada respuesta en llamadas reales a las herramientas MCP,
que cambie de respuesta cuando cambia la fuente de datos, y que cite la
versión del dataset y las herramientas usadas por respuesta. Con eso, este
ticket dejó de ser solo un smoke test y pasó a incluir construir el chat
real, siguiendo el mismo patrón ya usado en `APP-07`/`APP-09`: encontrar el
gap entre lo que el AC da por hecho y lo que el código realmente hace, y
cerrarlo en vez de marcar la casilla.

Dos cambios:

- **Chat real del Copilot.** Se agregó un servicio HTTP nuevo
  (`pipeline/src/dataset_quality/copilot/http_app.py`, servido por
  `__main__.py` con uvicorn vía `python -m dataset_quality.copilot`) que
  envuelve el mismo agente y servidor MCP de solo lectura de `APP-06`
  (`agent.py::answer_question`) detrás de `POST /query` — no es un segundo
  camino de código, es una capa delgada de validación/HTTP sobre el mismo
  loop que ya usa `server.py` (ver el docstring de `agent.py`: "no separate
  code path"). En `docker-compose.yml` es un servicio nuevo, `copilot`,
  deliberadamente NO detrás del profile `pipeline` (que es solo tooling de
  CLI/batch): el Agent Test necesita que responda con un `docker compose
  up` normal. `frontend/src/pages/dataset/Copilot.tsx` se reescribió por
  completo — de un placeholder estático a un chat real
  (`frontend/src/lib/api/copilot.ts::askCopilot`, proxiado por nginx en
  `/copilot-api/` → `copilot:8100`, o por Vite en dev) que manda cada pregunta,
  muestra la respuesta, y renderiza `dataset_version` y `tools_used` como
  insignias junto a cada respuesta — cumpliendo directamente los incisos
  (b)/(c) de la Sección 8 del rubro. Un fallo del provider (sin
  `ANTHROPIC_API_KEY`, o el provider caído) llega al chat como un mensaje
  corto y fijo, nunca un traceback (`http_app.py` mapea
  `InvalidQuestionError`→400, provider no configurado→503,
  `CopilotProviderError`→502 — inciso (d) del rubro).
- **Mismo bug que encontró Mau en APP-07, del lado de Python.** Ya estaba
  anotado en "Pendiente" (ver abajo, y la "Corrección de revisión (Mau)" de
  `APP-07` arriba): `copilot/agent.py::default_contracts_dir` seguía
  apuntando por defecto a `contracts/` (raíz del repo, el mock versionado
  de APP-01/APP-05) en vez de `pipeline/data/interim/` (la salida real que
  escribe `pipeline/dvc.yaml`). Se corrigió el default y se agregaron los
  campos `copilot_contracts_dir`/`copilot_port` a `Settings`
  (`pipeline/src/dataset_quality/config/settings.py`) para que el nuevo
  servicio HTTP lea del mismo lugar, con `docker-compose.yml` montando
  `./pipeline/data/interim` como volumen de solo lectura para el servicio
  `copilot` — igual que ya hace `backend`. Sin este fix, el inciso (b) del
  rubro ("si cambia un valor en la fuente, la respuesta debe cambiar") no
  se podía cumplir para el Copilot aunque el chat ya funcionara: el agente
  seguiría leyendo el mock estático, nunca `dvc repro`.

### Corrección de revisión (validación en vivo del Agent Test, APP-10)

Validando el smoke test completo en una máquina con Docker (mismo patrón
que `APP-09`), entrar directo a `http://localhost:8080/copilot` en el
navegador tronaba con "Unable to connect", perdiendo el puerto (terminaba
en `http://localhost/copilot/`) — parecía un problema del navegador o de
una extensión/VPN, pero se reprodujo igual desde PowerShell
(`Invoke-WebRequest`, sin navegador de por medio) y en una ventana privada
sin historial, descartando ambas causas. Los logs de `docker compose logs
frontend` mostraron la causa real: `nginx.conf` tenía el proxy del Copilot
en `location /copilot/` — el mismo prefijo que ya usa esta pantalla como
ruta de React Router. Visitar `/copilot` (sin `/query`) activaba el
redirect automático de nginx para agregar la barra final
(`/copilot` → `/copilot/`), y ese redirect usa la variable `$host` de
nginx, que por diseño **siempre** quita el puerto — el navegador terminaba
en `http://localhost/copilot/` (puerto 80, nada escuchando ahí) en vez de
`:8080`. En uso normal de la app nunca se nota (`askCopilot` siempre pide
`/copilot/query`, nunca la ruta pelona), pero cualquiera que entrara
directo a la URL de la pantalla — exactamente lo que pide el Agent Test —
se topaba con esto.

Fix: renombrar el proxy a `location /copilot-api/` (`nginx.conf`) y
`/copilot-api` en el proxy de Vite (`vite.config.ts`) y en
`COPILOT_BASE_URL` (`lib/api/copilot.ts`), eliminando la colisión de raíz
en vez de intentar evitar el redirect de nginx. Confirmado con un rebuild
(`docker compose up --build`) real: `http://localhost:8080/copilot` carga
la SPA completa (no el proxy) y una pregunta real de punta a punta
respondió con `dataset_version`/`tools_used` citados y acentos correctos.

`ANTHROPIC_API_KEY` / `COPILOT_MODEL` se agregaron a `.env.example` /
`.env.production.example` (raíz del repo, los que lee `docker compose up`
vía sustitución automática de variables — no confundir con
`pipeline/.env.example`, que ya los tenía desde `APP-06` para correr el
Copilot fuera de Docker). Sin una key real de Anthropic, el chat sigue
respondiendo (503 limpio, ver arriba), pero el Agent Test del rubro
("hacerle una pregunta real") necesita una.

Verificado con `pytest` en `pipeline/` (99/99, incluyendo el fix de
`default_contracts_dir` y las 14 pruebas nuevas de `http_app.py`, todas
con el ciclo rojo→verde→mutación ya usado en el resto del proyecto),
`ruff check`/`ruff format --check` limpios, y en `frontend/` con
`tsc --noEmit`, `biome check` y `npm test` (27/27, incluyendo pruebas
nuevas del chat: pregunta real con insignias de versión/herramientas,
respuesta sin `dataset_version` cuando el agente no invoca ninguna tool, y
mensaje de error corto ante un 502 del provider) — todos limpios.
`docker compose config` valida la sintaxis del `docker-compose.yml`
resultante; la validación end-to-end contenedorizada se corrió en una
máquina con Docker, igual que se hizo para `APP-09` (ver arriba).

### Corrección de revisión (PM: persistir la salida real de `dvc repro`, APP-10)

La validación en vivo de arriba solo pudo probar el chat con datos reales
porque, ante `pipeline/data/interim/` completamente vacío en un clon
limpio, se copió a mano el mock de `contracts/*.json` para desatorar la
prueba de la UI — un parche temporal, no la solución. El PM lo señaló
correctamente en la revisión del PR: el servicio `pipeline` de
`docker-compose.yml` nunca tuvo volumen para `data/` (a diferencia de
`backend`/`copilot`, que sí montan `pipeline/data/interim` desde
`APP-07`/arriba), así que `docker compose --profile pipeline run --rm
pipeline dvc repro` escribe `quality.json`/`splits.json`/`versions.json`
solo dentro del contenedor efímero, que se destruye al salir del comando.
En un clon limpio, ni `backend` ni `copilot` llegan a ver nunca datos
reales — el Agent Test de la Sección 8 del rubro (`copilot` respondiendo
con datos reales, y "si cambia un valor en la fuente, la respuesta debe
cambiar") queda bloqueado sin importar que `ANTHROPIC_API_KEY` esté bien
configurada. Esto ya estaba anotado como fuera de alcance en "Pendiente"
(ver la versión anterior de esta sección) — el PM tenía razón en que no lo
es: sin este fix, el criterio mecánicamente verificable del rubro no se
puede cumplir nunca en un clon limpio.

Fix: `docker-compose.yml` monta ahora `./pipeline/data:/app/data`
(lectura + escritura, no `:ro`) en el servicio `pipeline` — todo `data/`,
no solo `interim/`, por dos razones más allá del pedido original: (1) la
etapa `release` de `dvc.yaml` también lee y reescribe
`data/version_history.json` (el ledger de releases, versionado en git,
fuera de `interim/`) vía `--history`, que se perdería igual sin este
volumen; (2) `dvc pull` escribe el dataset crudo en
`data/raw/coco-dataset.json`, y persistirlo evita reformarlo en cada
`dvc repro`. Verificado con `docker compose --profile pipeline config`:
el volumen resuelve a `<repo>/pipeline/data:/app/data` sin afectar a
ningún otro servicio.

También se actualizó la rama con `main` (`git merge`, sin conflictos):
trae la corrección de finales de línea de `APP-09` (`.gitattributes`,
mergeada a `main` como PR #54 después de que esta rama se creara desde un
`main` más viejo) más el trabajo de `OPS-07`/`DQ-07`/`DQ-08` que llegó
mientras tanto. Ninguno de esos cambios toca `docker-compose.yml`,
`contracts/` ni nada del código del Copilot, así que el merge fue
mecánico.

Pendiente de repetir en la máquina de validación: correr la pipeline real
(`docker compose --profile pipeline run --rm pipeline sh -c "PYTHONPATH=src
dvc repro"`, documentado en `README.md`, sección "DVC (OPS-04)" — el
bucket `dvc-cache` y las credenciales ya están resueltos dentro del
profile `pipeline`, sin pasos manuales) y repetir el smoke test del
Copilot con una pregunta real contra ese `pipeline/data/interim/`
genuino, en vez del mock de `contracts/` usado para la validación
anterior.

## Pendiente (fuera de alcance de APP-01 / APP-04 / APP-05 / APP-06 / APP-07 / APP-10)

- Reemplazar `SplitsSummary` (APP-06) por el `SplitResult` real de
  `APP-04` en `copilot/contracts.py`, ahora que esa rama ya está en `main`.
- Reincorporar `spatial_bias` a `quality.yaml` si Data Quality decide
  retomarlo — la pestaña de Analyzers ya está lista para mostrarlo sin
  cambios adicionales (ver "Reconciliación con APP-05").
- Decidir si `useContractFetch.ts` y `frontend/public/contracts/*.json`
  se retiran del todo ahora que ninguna pantalla los usa (ver
  "Reconciliación con APP-07").
- ~~El servicio `pipeline` de `docker-compose.yml` no tiene volumen para
  `data/`~~ — resuelto, ver "Corrección de revisión (PM: persistir la
  salida real de `dvc repro`, APP-10)" arriba.