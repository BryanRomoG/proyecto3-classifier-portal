"""Thin wrapper around the object-store client so callers never touch boto3 directly."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dataset_quality.config.clients import get_object_store_client
from dataset_quality.config.settings import Settings, get_settings


@dataclass
class ObjectStore:
    bucket: str
    client: Any

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> ObjectStore:
        settings = settings or get_settings()
        return cls(bucket=settings.object_store_bucket, client=get_object_store_client(settings))

    def get_bytes(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()

    def put_bytes(self, key: str, data: bytes, content_type: str | None = None) -> None:
        extra_args = {"ContentType": content_type} if content_type else {}
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, **extra_args)

    # --- file-oriented helpers (used by the model-release tool, T3-3.6) -------------------
    # Kept here, not in the caller, so the "only this module talks to boto3" rule holds.

    def put_file(self, key: str, path: Path, content_type: str | None = None) -> None:
        extra_args = {"ContentType": content_type} if content_type else {}
        self.client.upload_file(str(path), self.bucket, key, ExtraArgs=extra_args)

    def download_file(self, key: str, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(self.bucket, key, str(path))

    def head(self, key: str) -> dict:
        return self.client.head_object(Bucket=self.bucket, Key=key)

    def list_keys(self, prefix: str) -> list[str]:
        paginator = self.client.get_paginator("list_objects_v2")
        keys: list[str] = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            keys.extend(item["Key"] for item in page.get("Contents", []))
        return sorted(keys)
