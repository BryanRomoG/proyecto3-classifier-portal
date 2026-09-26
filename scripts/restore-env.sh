#!/usr/bin/env bash
# Deja el entorno de datos listo en una máquina limpia, con un solo comando.
#
# En un clon nuevo, MinIO arranca vacío y la base no tiene las imágenes del
# Proyecto 1, así que la etapa `analyze` falla cerrado (necesita los bytes
# reales para el pHash de duplicados — ver pipeline/README.md). Este script
# baja el bundle de datos del release v1.0.0 desde GitHub Releases y delega en
# el restore.sh que viene dentro, que es el que sube los objetos a MinIO, carga
# el dump y verifica los conteos.
#
# El bundle NO vive en git (son ~496 MiB): es un asset del release, y lo que se
# extrae queda bajo .dq-env-bundle/, ignorado por .gitignore.
#
# Requisitos: bash, curl, y unzip o python3. El stack debe estar levantado
# (`docker compose up -d --build`) antes de correr esto: el restore escribe en
# MinIO y en MariaDB.
#
# Uso:  ./scripts/restore-env.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUNDLE_DIR="$REPO_DIR/.dq-env-bundle"
BUNDLE_ZIP="$REPO_DIR/.dq-env-bundle.zip"
BUNDLE_URL="https://github.com/White-eclipse1/Proyecto-02-dataset-Quality/releases/download/v1.0.0-data/dq-env-bundle-v1.0.0.zip"

# Corrección de revisión (seguridad): el digest que GitHub publica para este
# asset, verificable sin confiar en este archivo:
#
#   gh api repos/White-eclipse1/Proyecto-02-dataset-Quality/releases/tags/v1.0.0-data \
#     --jq '.assets[] | "\(.name) \(.digest)"'
#
# Antes de esto el script extraía y ejecutaba restore.sh directo de lo que
# viniera por la red: cualquier cosa que pudiera responder a esa URL (un proxy
# corporativo que reescribe descargas, un DNS envenenado, o el asset
# reemplazado en el release) terminaba corriendo como script con los permisos
# de quien clona. Un ZIP de 496 MiB tampoco se revisa a ojo. Ahora se verifica
# el SHA-256 ANTES de extraer y antes de ejecutar nada; si no cuadra, se borra
# la descarga y se corta.
EXPECTED_SHA256="04b30b874bb8ef012dccf02aecaee31043bd40b63effbbcd105a3bb74810abc4"

die() {
  echo "ERROR: $*" >&2
  exit 1
}

# sha256 con lo que haya en la máquina: coreutils (Linux), macOS, openssl, o
# Python, que el pipeline ya exige de todos modos.
sha256_of() {
  local file="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$file" | cut -d' ' -f1
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$file" | cut -d' ' -f1
  elif command -v openssl >/dev/null 2>&1; then
    openssl dgst -sha256 "$file" | awk '{print $NF}'
  elif command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1; then
    local py
    py="$(command -v python3 || command -v python)"
    "$py" -c 'import hashlib,sys
h=hashlib.sha256()
with open(sys.argv[1],"rb") as f:
    for chunk in iter(lambda: f.read(1024*1024), b""):
        h.update(chunk)
print(h.hexdigest())' "$file"
  else
    return 1
  fi
}

command -v curl >/dev/null 2>&1 || die "hace falta curl para descargar el bundle."

# Marcador con el digest del ZIP que se verificó antes de extraer. Sin él no hay
# forma de saber si lo que hay en .dq-env-bundle/ salió de un ZIP verificado (una
# instalación hecha con la versión anterior de este script extraía sin verificar,
# y luego ejecutaba ese restore.sh sin más). Se exige que coincida con el digest
# fijado: si falta, sobra o es de otro release, se descarta todo y se baja de nuevo.
MARKER="$BUNDLE_DIR/.sha256-verificado"

if [[ -d "$BUNDLE_DIR" ]] \
  && [[ "$(cat "$MARKER" 2>/dev/null || true)" == "$EXPECTED_SHA256" ]]; then
  echo "==> El bundle ya está en .dq-env-bundle/ y coincide con el digest fijado, no se descarga de nuevo"
else
  if [[ -d "$BUNDLE_DIR" ]]; then
    echo "==> .dq-env-bundle/ no tiene una verificación SHA-256 vigente (¿instalación anterior?): se descarta y se descarga de nuevo"
  fi
  echo "==> Descargando el bundle de datos (~496 MiB) desde GitHub Releases"
  curl -fL --progress-bar "$BUNDLE_URL" -o "$BUNDLE_ZIP"

  echo "==> Verificando SHA-256 del bundle"
  actual="$(sha256_of "$BUNDLE_ZIP")" \
    || die "no encontré con qué calcular el SHA-256 (sha256sum, shasum, openssl o python)."
  if [[ "$actual" != "$EXPECTED_SHA256" ]]; then
    rm -f "$BUNDLE_ZIP"
    die "el SHA-256 del bundle no coincide -- descarga borrada, no se extrajo ni se ejecutó nada.
  esperado: $EXPECTED_SHA256
  obtenido: $actual
Si el release se republicó a propósito, actualiza EXPECTED_SHA256 en este
script con el digest que publica GitHub (ver el comentario de arriba)."
  fi
  echo "    OK: $actual"

  echo "==> Extrayendo"
  # El zip trae todo bajo dq-env-bundle/; se renombra a .dq-env-bundle/ para
  # que caiga bajo la regla de .gitignore y no se pueda colar al repo.
  rm -rf "$REPO_DIR/dq-env-bundle" "$BUNDLE_DIR"
  if command -v unzip >/dev/null 2>&1; then
    unzip -q "$BUNDLE_ZIP" -d "$REPO_DIR"
  elif command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1; then
    # Git Bash no siempre trae unzip, pero el pipeline ya exige Python.
    py="$(command -v python3 || command -v python)"
    "$py" -c 'import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])' \
      "$BUNDLE_ZIP" "$REPO_DIR"
  else
    die "hace falta unzip o python3 para extraer el bundle."
  fi
  mv "$REPO_DIR/dq-env-bundle" "$BUNDLE_DIR"
  echo "$actual" >"$MARKER"
  rm -f "$BUNDLE_ZIP"
fi

[[ -f "$BUNDLE_DIR/restore.sh" ]] || die "el bundle no trae restore.sh en $BUNDLE_DIR."

echo
exec bash "$BUNDLE_DIR/restore.sh" "$REPO_DIR"
