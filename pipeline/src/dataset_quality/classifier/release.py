"""T3-3.6: package the selected classifier candidate and publish it to the releases bucket.

The selected candidate (``selection.json`` -> ``model.pt``) is wrapped into a self-contained,
versioned package that a clean machine can download, verify and run:

    <version>/
      model.pt         the exact checkpoint that was selected and test-evaluated
      MODEL_CARD.md    human-readable card (architecture, classes, metrics, lineage)
      config.json      the effective ``TrainingConfig`` used to train it
      class_map.json   index -> class name, exactly as training produced it
      metadata.json    machine-readable traceability (run id, dataset, metrics, hashes)
      SHA256SUMS       SHA-256 of every file above (the integrity manifest)

Design decisions:

* **Build is deterministic.** The same inputs produce a byte-identical package: no
  wall-clock time is ever written, JSON is serialised with ``sort_keys=True``, and the only
  timestamps are the ones already committed in ``selection.json`` / ``test_evaluation.json``.
* **Traceability is enforced, not decorated.** Before anything is written the checkpoint on
  disk must hash to the SHA-256 recorded *both* in the selection report and in the final test
  evaluation, belong to the same run and manifest, and carry the selected class list. A killed
  / swapped / re-selected checkpoint is refused, so the published weights are provably the
  ones whose test metrics are in the card.
* **Credentials are never hardcoded.** ``release_store`` builds the object-store client
  through the shared ``ObjectStore`` wrapper using boto3's *standard* credential chain (env
  vars, shared config, SSO, or the task/instance role), so the same code runs locally and
  under GitHub Actions OIDC.
* **Imports stay torch-free at module load.** Reading a real ``model.pt`` needs torch, so it
  happens lazily inside ``read_checkpoint``; the packaging, integrity and upload logic can be
  unit-tested with an injected checkpoint reader and an in-memory store, no GPU/network.

The module never calls AWS by itself: ``upload_package`` / ``fetch_package`` take any store
that exposes ``put_file`` / ``download_file`` / ``head`` / ``list_keys`` (``ObjectStore`` in
production, an in-memory double in the tests).
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dataset_quality.classifier.config import SEARCHED_HYPERPARAMETERS, TrainingConfig

# ``model.pt`` matches ``training.CHECKPOINT_NAME``; the name is repeated here (kept as a
# constant, not imported) so importing this module never pulls in torch.
MODEL_FILE = "model.pt"
MODEL_CARD_FILE = "MODEL_CARD.md"
CONFIG_FILE = "config.json"
CLASS_MAP_FILE = "class_map.json"
METADATA_FILE = "metadata.json"
CHECKSUMS_FILE = "SHA256SUMS"

RELEASE_FORMAT = "t3-classifier-release/v1"
DEFAULT_PREFIX = "t3-classifier"

# Every package ships these; SHA256SUMS covers all of them (itself excluded).
PACKAGE_FILES = (MODEL_FILE, MODEL_CARD_FILE, CONFIG_FILE, CLASS_MAP_FILE, METADATA_FILE)

CONTENT_TYPES = {
    ".pt": "application/octet-stream",
    ".md": "text/markdown; charset=utf-8",
    ".json": "application/json",
}


class ReleaseError(RuntimeError):
    """The model package cannot be built, uploaded or verified."""


def parse_semver(version: str) -> tuple[int, int, int]:
    """Validate ``v<MAJOR>.<MINOR>.<PATCH>`` and return its tuple form.

    Same MAJOR.MINOR.PATCH rule the dataset release ledger uses (``versioning``); kept local
    so the model-release tool has no dependency on the DVC release stage.
    """

    error = ReleaseError(f"model version {version!r} must be v<MAJOR>.<MINOR>.<PATCH>, e.g. v1.0.0")
    if not version.startswith("v"):
        raise error
    parts = version[1:].split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise error
    major, minor, patch = (int(part) for part in parts)
    return major, minor, patch


def sha256_file(path: Path) -> str:
    """SHA-256 of a file, streamed so a large checkpoint does not sit in memory."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


@dataclass(frozen=True)
class CheckpointFacts:
    """What the packaged model card and metadata need, extracted from ``model.pt``."""

    config: dict
    class_names: list[str]
    run_id: str | None
    lineage: dict
    weights: dict
    best_epoch: int | None
    monitor: str | None
    best_value: float | None
    preprocessing: dict


def read_checkpoint(path: Path) -> CheckpointFacts:
    """Read the checkpoint through the inference loader so packaging proves it is loadable.

    Reuses ``predict.load_checkpoint`` (``weights_only=True``, ``strict=True``): if this
    succeeds the exact same call a clean machine would make succeeds too, so the package can
    never ship weights that do not reload. ``import`` happens here on purpose, to keep torch
    out of the module's import graph.
    """

    from dataset_quality.classifier.predict import load_checkpoint

    loaded = load_checkpoint(path)
    checkpoint = loaded.checkpoint
    return CheckpointFacts(
        config=loaded.config.model_dump(mode="json"),
        class_names=list(loaded.class_names),
        run_id=checkpoint.get("run_id"),
        lineage=dict(checkpoint.get("lineage") or {}),
        weights=dict(checkpoint.get("weights") or {}),
        best_epoch=checkpoint.get("best_epoch"),
        monitor=checkpoint.get("monitor"),
        best_value=checkpoint.get("best_value"),
        preprocessing=dict(checkpoint.get("preprocessing") or {}),
    )


def _fmt(value: object, digits: int = 4) -> str:
    """Deterministic, human-readable rendering of a metric value."""

    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "sí" if value else "no"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _model_card(
    *,
    version: str,
    selection: dict,
    evaluation: dict,
    facts: CheckpointFacts,
    checkpoint_sha256: str,
    class_names: list[str],
) -> str:
    """Render ``MODEL_CARD.md`` purely from the reports and the checkpoint."""

    matrix = evaluation.get("confusion_matrix") or {}
    labels = list(matrix.get("labels") or class_names)
    values = matrix.get("matrix") or []
    per_class = evaluation.get("per_class") or {}
    majority = evaluation.get("majority_baseline") or {}
    weights = facts.weights or {}
    policy = selection.get("policy") or {}
    classes = ", ".join(f"`{name}`" for name in class_names)

    lines = [
        f"# Model card — clasificador T3 (`{version}`)",
        "",
        "Paquete auto-descriptivo: pesos, configuración, mapa de clases y preprocesamiento de",
        "evaluación viajan juntos, así que la inferencia no se desvía de cómo se validó y probó.",
        "",
        "## Resumen",
        "",
        f"- Tarea: clasificación de recortes COCO en {classes}.",
        f"- Arquitectura: `{weights.get('architecture', 'n/a')}`.",
        f"- Origen de los pesos iniciales: {weights.get('initial_weights', 'n/a')}.",
        f"- Capas entrenables: {weights.get('trainable_layers', 'n/a')}.",
        f"- Parámetros: {_fmt(weights.get('trainable_parameters'))} entrenables de "
        f"{_fmt(weights.get('total_parameters'))}.",
        "",
        "## Trazabilidad",
        "",
        "| Campo | Valor |",
        "| --- | --- |",
        f"| MLflow run | `{selection.get('run_id')}` (`{selection.get('run_name')}`) |",
        f"| Experimento | `{selection.get('experiment_name')}` |",
        f"| dataset_version | `{evaluation.get('dataset_version')}` |",
        f"| manifest_sha256 | `{selection.get('manifest_sha256')}` |",
        f"| dvc_raw_md5 | `{facts.lineage.get('dvc_raw_md5')}` |",
        f"| quality_gate_status | `{facts.lineage.get('quality_gate_status')}` |",
        f"| Selección (validación) | `{policy.get('metric')}` = "
        f"{_fmt(selection.get('selected_metric_value'))} @ `{selection.get('selected_at')}` |",
        f"| Evaluación final en test (una vez) | `{evaluation.get('evaluated_at')}` |",
        f"| checkpoint_sha256 | `{checkpoint_sha256}` |",
        f"| Mejor época | {_fmt(facts.best_epoch, 0)} (monitor `{facts.monitor}`) |",
        "",
        "## Métricas en test (split congelado, abierto una sola vez)",
        "",
        "| Métrica | Valor |",
        "| --- | --- |",
        f"| Accuracy top-1 | {_fmt(evaluation.get('accuracy'))} |",
        f"| F1 macro | {_fmt(evaluation.get('macro_f1'))} |",
        f"| Correctas / total | {_fmt(evaluation.get('correct'), 0)} / "
        f"{_fmt(evaluation.get('total'), 0)} |",
        f"| Baseline clase mayoritaria (`{majority.get('class')}`) | "
        f"{_fmt(majority.get('accuracy'))} |",
        f"| Meta {_fmt(evaluation.get('target_accuracy', 0.85), 2)} alcanzada | "
        f"{_fmt(evaluation.get('meets_target'))} |",
        "",
        "### Por clase",
        "",
        "| Clase | Precisión | Recall | F1 | Soporte |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name in class_names:
        metrics = per_class.get(name) or {}
        lines.append(
            f"| {name} | {_fmt(metrics.get('precision'))} | {_fmt(metrics.get('recall'))} | "
            f"{_fmt(metrics.get('f1'))} | {_fmt(metrics.get('support'), 0)} |"
        )

    lines += [
        "",
        "### Matriz de confusión (filas = real, columnas = predicho)",
        "",
        "| real \\ predicho | " + " | ".join(labels) + " |",
        "| --- | " + " | ".join("---" for _ in labels) + " |",
    ]
    for label, row in zip(labels, values, strict=False):
        lines.append("| " + label + " | " + " | ".join(str(int(cell)) for cell in row) + " |")

    lines += [
        "",
        "## Hiperparámetros buscados (config efectiva)",
        "",
        "| Hiperparámetro | Valor |",
        "| --- | --- |",
    ]
    for name in SEARCHED_HYPERPARAMETERS:
        lines.append(f"| {name} | {json.dumps(facts.config.get(name))} |")
    lines += [
        "",
        "Configuración completa (incluidos los fijos): `config.json`.",
        "",
        "## Preprocesamiento de evaluación",
        "",
        "```json",
        json.dumps(facts.preprocessing, indent=2, sort_keys=True),
        "```",
        "",
        "## Uso (inferencia limpia)",
        "",
        "```bash",
        "python -m dataset_quality.classifier predict \\",
        f"  --checkpoint <paquete>/{MODEL_FILE} imagen.png",
        "```",
        "",
        "## Limitaciones",
        "",
        f"- Entrenado solo para las clases congeladas {classes}; no dice nada sobre clases",
        "  fuera de ese conjunto.",
        "- Las métricas provienen de un único split de test congelado, abierto una sola vez.",
        "- El preprocesamiento de entrada es fijo (bloque anterior); otra normalización cambia",
        "  las predicciones.",
        "",
    ]
    return "\n".join(lines)


def _cross_check(
    checkpoint_sha256: str, selection: dict, evaluation: dict, facts: CheckpointFacts
) -> None:
    """Refuse anything but the selected, test-evaluated checkpoint with the selected classes."""

    for label, report in (("selection", selection), ("test evaluation", evaluation)):
        recorded = report.get("checkpoint_sha256")
        if recorded != checkpoint_sha256:
            raise ReleaseError(
                f"checkpoint sha256 {checkpoint_sha256} does not match the one recorded in the "
                f"{label} report ({recorded}); refusing to package a model that is not the "
                "selected, test-evaluated candidate"
            )
    if selection.get("run_id") != evaluation.get("run_id"):
        raise ReleaseError("selection and test evaluation refer to different MLflow runs")
    if selection.get("manifest_sha256") != evaluation.get("manifest_sha256"):
        raise ReleaseError("selection and test evaluation were made on different manifests")

    classes = list(selection.get("classes") or [])
    if not classes:
        raise ReleaseError("the selection report has no class list")
    if list(facts.class_names) != classes:
        raise ReleaseError(
            f"checkpoint classes {list(facts.class_names)} != selected classes {classes}"
        )
    if list(evaluation.get("classes") or classes) != classes:
        raise ReleaseError("the test evaluation classes differ from the selected classes")

    run_id = selection.get("run_id")
    if not run_id or facts.run_id != run_id:
        raise ReleaseError(f"checkpoint run id {facts.run_id} != selected run id {run_id}")
    lineage_manifest = facts.lineage.get("manifest_sha256")
    if not lineage_manifest or lineage_manifest != selection.get("manifest_sha256"):
        raise ReleaseError("the checkpoint lineage manifest differs from the selected manifest")


def build_package(
    *,
    checkpoint: Path,
    version: str,
    selection_path: Path,
    evaluation_path: Path,
    output_dir: Path,
    checkpoint_reader: Callable[[Path], CheckpointFacts] = read_checkpoint,
) -> dict:
    """Assemble the versioned package under ``output_dir/<version>`` and return its summary.

    ``checkpoint_reader`` is injectable so the pure packaging logic can be tested without
    torch; production always uses the real, torch-backed ``read_checkpoint``.
    """

    parse_semver(version)
    checkpoint = Path(checkpoint)
    if not checkpoint.is_file() or checkpoint.stat().st_size == 0:
        raise ReleaseError(f"checkpoint {checkpoint} is missing or empty")
    selection_path, evaluation_path = Path(selection_path), Path(evaluation_path)
    if not selection_path.is_file():
        raise ReleaseError(f"selection report {selection_path} does not exist")
    if not evaluation_path.is_file():
        raise ReleaseError(f"test evaluation report {evaluation_path} does not exist")

    checkpoint_sha256 = sha256_file(checkpoint)
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    facts = checkpoint_reader(checkpoint)
    _cross_check(checkpoint_sha256, selection, evaluation, facts)

    config = TrainingConfig.model_validate(facts.config).model_dump(mode="json")
    class_names = list(facts.class_names)
    class_map = {str(index): name for index, name in enumerate(class_names)}

    package_dir = Path(output_dir) / version
    if package_dir.exists():
        shutil.rmtree(package_dir)
    package_dir.mkdir(parents=True)

    shutil.copyfile(checkpoint, package_dir / MODEL_FILE)
    _write_json(package_dir / CONFIG_FILE, config)
    _write_json(package_dir / CLASS_MAP_FILE, class_map)
    (package_dir / MODEL_CARD_FILE).write_text(
        _model_card(
            version=version,
            selection=selection,
            evaluation=evaluation,
            facts=facts,
            checkpoint_sha256=checkpoint_sha256,
            class_names=class_names,
        ),
        encoding="utf-8",
    )

    files = {
        name: sha256_file(package_dir / name)
        for name in (MODEL_FILE, CONFIG_FILE, CLASS_MAP_FILE, MODEL_CARD_FILE)
    }
    metadata = {
        "format": RELEASE_FORMAT,
        "version": version,
        "run_id": selection.get("run_id"),
        "run_name": selection.get("run_name"),
        "experiment_name": selection.get("experiment_name"),
        "classes": class_names,
        "checkpoint_sha256": checkpoint_sha256,
        "dataset": {
            "dataset_version": evaluation.get("dataset_version"),
            "manifest_sha256": selection.get("manifest_sha256"),
            "dvc_raw_md5": facts.lineage.get("dvc_raw_md5"),
            "quality_gate_status": facts.lineage.get("quality_gate_status"),
            "coco_sha256": facts.lineage.get("coco_sha256"),
        },
        "selection": {
            "selected_at": selection.get("selected_at"),
            "metric": (selection.get("policy") or {}).get("metric"),
            "metric_value": selection.get("selected_metric_value"),
            "policy": selection.get("policy"),
        },
        "test_metrics": {
            key: evaluation.get(key)
            for key in (
                "total",
                "correct",
                "accuracy",
                "macro_f1",
                "per_class",
                "confusion_matrix",
                "majority_baseline",
                "most_confused",
                "meets_target",
                "target_accuracy",
                "evaluated_at",
            )
        },
        "checkpoint": {
            "best_epoch": facts.best_epoch,
            "monitor": facts.monitor,
            "best_value": facts.best_value,
            "preprocessing": facts.preprocessing,
            "weights": facts.weights,
        },
        "files": files,
    }
    _write_json(package_dir / METADATA_FILE, metadata)

    checksums = {name: sha256_file(package_dir / name) for name in PACKAGE_FILES}
    (package_dir / CHECKSUMS_FILE).write_text(_checksums_text(checksums), encoding="utf-8")

    return {
        "format": RELEASE_FORMAT,
        "version": version,
        "package_dir": str(package_dir),
        "checkpoint_sha256": checkpoint_sha256,
        "run_id": selection.get("run_id"),
        "files": files,
        "checksums": checksums,
        "metadata": metadata,
    }


def _checksums_text(checksums: dict[str, str]) -> str:
    """GNU-coreutils-style manifest: ``<sha256>  <name>`` per line, sorted by name."""

    return "".join(f"{checksums[name]}  {name}\n" for name in sorted(checksums))


def _parse_checksums(text: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split(None, 1)
        if len(parts) != 2:
            raise ReleaseError(f"malformed checksum line: {line!r}")
        digest, name = parts
        name = name.lstrip("*")
        if name not in PACKAGE_FILES:
            raise ReleaseError(f"checksum manifest contains an invalid file name: {name!r}")
        if name in entries:
            raise ReleaseError(f"checksum manifest contains a duplicate file: {name!r}")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ReleaseError(f"checksum manifest contains an invalid SHA-256 for {name!r}")
        entries[name] = digest
    return entries


def verify_package(package_dir: Path, *, expected_version: str | None = None) -> dict:
    """Recompute every hash in ``SHA256SUMS`` and report any tampering.

    ``ok`` is true only when the manifest lists exactly the required files, each one is
    present with a matching SHA-256, and no extra file was slipped into the directory.
    """

    package_dir = Path(package_dir)
    result: dict = {
        "ok": False,
        "package_dir": str(package_dir),
        "files": {},
        "missing": [],
        "mismatches": [],
        "unexpected": [],
        "not_listed": [],
        "metadata_errors": [],
    }
    sums_path = package_dir / CHECKSUMS_FILE
    if not sums_path.is_file():
        result["error"] = f"missing {CHECKSUMS_FILE}"
        return result
    try:
        listed = _parse_checksums(sums_path.read_text(encoding="utf-8"))
    except ReleaseError as error:
        result["error"] = str(error)
        return result

    result["files"] = dict(listed)
    for name in sorted(listed):
        path = package_dir / name
        if not path.is_file():
            result["missing"].append(name)
            continue
        actual = sha256_file(path)
        if actual != listed[name]:
            result["mismatches"].append({"name": name, "expected": listed[name], "actual": actual})
    result["unexpected"] = sorted(
        path.name
        for path in package_dir.iterdir()
        if path.is_file() and path.name != CHECKSUMS_FILE and path.name not in listed
    )
    result["not_listed"] = sorted(set(PACKAGE_FILES) - set(listed))
    metadata_path = package_dir / METADATA_FILE
    if metadata_path.is_file() and not any(
        mismatch["name"] == METADATA_FILE for mismatch in result["mismatches"]
    ):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            result["metadata_errors"].append(f"invalid metadata.json: {error}")
        else:
            if metadata.get("format") != RELEASE_FORMAT:
                result["metadata_errors"].append(
                    f"metadata format {metadata.get('format')!r} != {RELEASE_FORMAT!r}"
                )
            metadata_version = metadata.get("version")
            try:
                parse_semver(metadata_version)
            except (ReleaseError, AttributeError):
                result["metadata_errors"].append(
                    f"metadata version {metadata_version!r} is not semantic"
                )
            if expected_version is not None and metadata_version != expected_version:
                result["metadata_errors"].append(
                    f"metadata version {metadata_version!r} != requested version "
                    f"{expected_version!r}"
                )
    result["ok"] = not (
        result["missing"]
        or result["mismatches"]
        or result["unexpected"]
        or result["not_listed"]
        or result["metadata_errors"]
    )
    return result


def package_key(prefix: str, version: str, name: str) -> str:
    """Object key for one package file: ``<prefix>/<version>/<name>``."""

    return f"{prefix.strip('/')}/{version}/{name}"


def release_store(bucket: str, region: str | None = None) -> Any:
    """Object-store client bound to ``bucket``, using boto3's standard credential chain.

    No keys are passed: boto3 resolves them from ``AWS_ACCESS_KEY_ID`` /
    ``AWS_SECRET_ACCESS_KEY`` / ``~/.aws`` / SSO / the instance or task role, so the same call
    works against MinIO (with ``AWS_ENDPOINT_URL`` / a profile) and against real S3 under
    GitHub Actions OIDC. Construction lives here so callers never import boto3.
    """

    from dataset_quality.config.clients import get_release_store_client
    from dataset_quality.storage.object_store import ObjectStore

    return ObjectStore(bucket=bucket, client=get_release_store_client(region))


def _content_type(name: str) -> str:
    if name == CHECKSUMS_FILE:
        return "text/plain; charset=utf-8"
    return CONTENT_TYPES.get(Path(name).suffix, "application/octet-stream")


def upload_package(
    *,
    store: Any,
    package_dir: Path,
    version: str,
    prefix: str = DEFAULT_PREFIX,
    verify: bool = True,
) -> dict:
    """Publish every package file to ``store`` and head each one back to confirm it landed.

    Refuses to upload a package that does not verify locally, so a corrupted/hand-edited
    directory can never reach the releases bucket.
    """

    parse_semver(version)
    package_dir = Path(package_dir)
    if verify:
        verification = verify_package(package_dir, expected_version=version)
        if not verification["ok"]:
            raise ReleaseError(
                f"refusing to upload an invalid package at {package_dir}: "
                f"missing={verification['missing']} mismatches="
                f"{[m['name'] for m in verification['mismatches']]} "
                f"unexpected={verification['unexpected']} not_listed={verification['not_listed']}"
            )

    objects: dict[str, dict] = {}
    for name in (*PACKAGE_FILES, CHECKSUMS_FILE):
        key = package_key(prefix, version, name)
        store.put_file(key, package_dir / name, content_type=_content_type(name))
        head = store.head(key)
        local_size = (package_dir / name).stat().st_size
        remote_size = int(head["ContentLength"])
        if remote_size != local_size:
            raise ReleaseError(
                f"uploaded object {key} has {remote_size} bytes, expected {local_size}"
            )
        objects[name] = {
            "key": key,
            "size": remote_size,
            "etag": str(head.get("ETag", "")).strip('"'),
        }
    return {
        "bucket": getattr(store, "bucket", None),
        "prefix": prefix,
        "version": version,
        "objects": objects,
    }


def fetch_package(
    *,
    store: Any,
    version: str,
    destination: Path,
    prefix: str = DEFAULT_PREFIX,
) -> dict:
    """Download a published package into ``destination`` and verify its SHA-256 manifest."""

    parse_semver(version)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for name in (*PACKAGE_FILES, CHECKSUMS_FILE):
        store.download_file(package_key(prefix, version, name), destination / name)
    verification = verify_package(destination, expected_version=version)
    verification["version"] = version
    verification["prefix"] = prefix
    verification["destination"] = str(destination)
    return verification
