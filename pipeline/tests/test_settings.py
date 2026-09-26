from dataset_quality.config.settings import Settings


def test_settings_load_from_env(monkeypatch):
    monkeypatch.setenv("DB_HOST", "test-db")
    monkeypatch.setenv("OBJECT_STORE_BUCKET", "test-bucket")

    settings = Settings(_env_file=None)

    assert settings.db_host == "test-db"
    assert settings.object_store_bucket == "test-bucket"
    assert settings.database_url.startswith("mysql+pymysql://")


def test_copilot_contracts_dir_defaults_to_pipeline_data_interim_not_contracts():
    """APP-10: mirrors the fix to copilot.agent.default_contracts_dir -- this
    is the setting the Copilot's HTTP service (__main__.py) actually reads at
    startup, so it must default to the same place, not the versioned
    contracts/ mock."""

    settings = Settings(_env_file=None)

    assert settings.copilot_contracts_dir == "data/interim"


def test_copilot_contracts_dir_overridable_from_env(monkeypatch):
    monkeypatch.setenv("COPILOT_CONTRACTS_DIR", "/data/pipeline-output")

    settings = Settings(_env_file=None)

    assert settings.copilot_contracts_dir == "/data/pipeline-output"
