FROM python:3.12-slim

WORKDIR /app

# DVC lives in its own venv, isolated from the app's own pinned boto3 —
# dvc[s3]'s aiobotocore dependency needs an incompatible botocore range, so
# installing it into the same site-packages breaks the app's --require-hashes
# install. Symlinking the entrypoint onto PATH keeps `dvc ...` usable as-is.
RUN python -m venv /opt/dvc-venv \
    && /opt/dvc-venv/bin/pip install --no-cache-dir "dvc[s3]>=3,<4" \
    && ln -s /opt/dvc-venv/bin/dvc /usr/local/bin/dvc

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml ./
COPY src/ src/
COPY tests/ tests/

# The DVC pipeline definition itself — without these, `dvc dag`/`repro`/
# `status` have nothing to run against inside this image. .dvc/config only
# (never .dvc/cache or the dataset), matching .dockerignore.
COPY dvc.yaml dvc.lock params.yaml quality.yaml ./
COPY .dvc/config .dvc/config
COPY data/raw/coco-dataset.json.dvc data/raw/coco-dataset.json.dvc

# .git isn't copied into the image (deliberately — no reason to ship repo
# history in a runtime image), but DVC was init'd assuming a parent git repo
# is present and refuses to run at all without one ("ERROR: /app is not a
# git repository"). core.no_scm here is a *local*, uncommitted override
# (.dvc/config.local, gitignored) — it only affects this image; a normal
# checkout with .git present still gets DVC's git integration.
RUN dvc config --local core.no_scm true

RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

ENV PYTHONPATH=/app/src

CMD ["python", "-c", "print('dataset-quality pipeline image ready')"]
