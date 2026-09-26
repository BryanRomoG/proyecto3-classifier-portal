"""Thin wrapper around the object-store client so callers never touch boto3 directly."""

from __future__ import annotations

from dataclasses import dataclass
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
