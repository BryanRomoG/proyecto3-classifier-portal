"""Factories for external clients. Only this module may construct a DB engine or S3 client."""

from __future__ import annotations

import boto3
from sqlalchemy import Engine, create_engine

from dataset_quality.config.settings import Settings, get_settings


def get_db_engine(settings: Settings | None = None) -> Engine:
    settings = settings or get_settings()
    return create_engine(settings.database_url, pool_pre_ping=True)


def get_object_store_client(settings: Settings | None = None):
    settings = settings or get_settings()
    return boto3.client(
        "s3",
        endpoint_url=settings.object_store_endpoint_url,
        aws_access_key_id=settings.object_store_access_key,
        aws_secret_access_key=settings.object_store_secret_key,
        region_name=settings.object_store_region,
        use_ssl=settings.object_store_use_ssl,
    )


def get_release_store_client(region_name: str | None = None):
    """S3 client for publishing/reading model releases (T3-3.6).

    Unlike ``get_object_store_client``, no credentials or endpoint are passed here: boto3
    resolves them from its **standard credential chain** (``AWS_ACCESS_KEY_ID`` /
    ``AWS_SECRET_ACCESS_KEY``, ``~/.aws/credentials``, SSO, or the instance/task role), so no
    secret is ever hardcoded and the same code runs under GitHub Actions OIDC. The bucket and
    region live in the caller (``classifier.release``), not here.
    """

    return boto3.client("s3", region_name=region_name)
