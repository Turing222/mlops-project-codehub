from __future__ import annotations

from pathlib import Path

from backend.config.settings import Settings


def test_app_env_loads_layered_yaml_config(monkeypatch, tmp_path: Path):
    config_dir = tmp_path / "configs"
    app_dir = config_dir / "app"
    app_dir.mkdir(parents=True)
    (app_dir / "base.yaml").write_text(
        "STORAGE_BACKEND: local\nLOCAL_STORAGE_ROOT: base-files\n",
        encoding="utf-8",
    )
    (app_dir / "test.yaml").write_text(
        "APP_ENV: test\nLOCAL_STORAGE_ROOT: test-files\nLLM_PROVIDER: mock\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("SECRET_KEY", "test-secret")

    settings = Settings()

    assert settings.APP_ENV == "test"
    assert settings.STORAGE_BACKEND == "local"
    assert settings.local_storage_root == Path("test-files")
    assert settings.LLM_PROVIDER == "mock"


def test_environment_overrides_app_yaml(monkeypatch, tmp_path: Path):
    config_dir = tmp_path / "configs"
    app_dir = config_dir / "app"
    app_dir.mkdir(parents=True)
    (app_dir / "base.yaml").write_text("STORAGE_BACKEND: local\n", encoding="utf-8")
    (app_dir / "test.yaml").write_text(
        "LOCAL_STORAGE_ROOT: yaml-files\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("LOCAL_STORAGE_ROOT", "env-files")
    monkeypatch.setenv("SECRET_KEY", "test-secret")

    settings = Settings()

    assert settings.local_storage_root == Path("env-files")


def test_database_url_overrides_postgres_parts(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")

    settings = Settings(
        DATABASE_URL="postgresql+asyncpg://db-user:db-pass@rdc.example.com:5432/prod",
        POSTGRES_SERVER="localhost",
    )

    assert "rdc.example.com" in settings.database_url
    assert "localhost" not in settings.database_url
    assert "db-pass" not in settings.database_url_safe
