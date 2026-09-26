"""Environment-driven settings. The only place in this codebase allowed to read env vars."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    db_host: str = "localhost"
    db_port: int = 3306
    db_user: str = "root"
    db_password: str = "password"
    db_name: str = "image_repo"

    # Same field set drives both MinIO (dev) and AWS S3 (prod) via one boto3 client —
    # leave object_store_endpoint_url unset to talk to real S3.
    object_store_endpoint_url: str | None = "http://localhost:9000"
    object_store_access_key: str = "minioadmin"
    object_store_secret_key: str = "minioadmin"
    # Source bucket: where Tier 1 ingestion reads the raw Proyecto 1 dataset from
    # (same bucket the backend uploads images into). NOT the dvc-cache /
    # dataset-releases buckets from the DVC/Terraform ticket — those version
    # pipeline outputs, a different role.
    object_store_bucket: str = "image-annotations"
    object_store_region: str = "us-east-1"
    object_store_use_ssl: bool = False

    quality_gate_config_path: str = "quality.yaml"

    # Dataset Copilot (APP-06). No default: AnthropicProvider.from_settings
    # raises a clear error rather than silently running unauthenticated.
    anthropic_api_key: str | None = None
    copilot_model: str = "claude-sonnet-4-5"

    # Dataset Copilot HTTP layer (APP-10): where the Copilot's ContractStore
    # reads quality.json/splits.json/versions.json from. Mirrors the Node
    # backend's PIPELINE_OUTPUT_DIR (SPEC-PIPE-001, backend/src/config/env.ts)
    # -- this is the Python-side equivalent, so the Web App's chat also sees
    # whatever `dvc repro` actually produced, never the versioned contracts/
    # mock (see the fix to `copilot.agent.default_contracts_dir`). Relative
    # to this package's own cwd (`pipeline/`), same convention as
    # quality_gate_config_path above; Docker Compose overrides it to the
    # mounted path (see docker-compose.yml).
    copilot_contracts_dir: str = "data/interim"
    copilot_port: int = 8100

    @property
    def database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
