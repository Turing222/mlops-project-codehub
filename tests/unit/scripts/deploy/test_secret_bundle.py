"""Unit tests for the file-compatible AWS secret bundle bridge.

职责：验证 manifest、目录导入、materialize 和 AWS 合并契约。
边界：只使用临时文件与 fake clients，不访问真实 AWS。
副作用：仅写入 pytest 临时目录。
"""

from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path

import pytest
import yaml
from botocore.exceptions import ClientError

from backend.core.secret_env import SECRET_ENV_NAMES
from scripts.deploy import secret_bundle


class FakeSecretsManager:
    def __init__(self, secret_string: str | None = None) -> None:
        self.secret_string = secret_string
        self.created_kwargs: dict[str, object] | None = None
        self.updated_kwargs: dict[str, object] | None = None

    def create_secret(self, **kwargs: object) -> dict[str, object]:
        if self.secret_string is not None:
            raise ClientError(
                {"Error": {"Code": "ResourceExistsException", "Message": "exists"}},
                "CreateSecret",
            )
        self.created_kwargs = kwargs
        value = kwargs["SecretString"]
        assert isinstance(value, str)
        self.secret_string = value
        return {"VersionId": "created-version"}

    def get_secret_value(self, **kwargs: object) -> dict[str, object]:
        assert kwargs["SecretId"] == "dewflow-prod-runtime"
        assert self.secret_string is not None
        return {
            "SecretString": self.secret_string,
            "VersionId": "current-version",
        }

    def put_secret_value(self, **kwargs: object) -> dict[str, object]:
        self.updated_kwargs = kwargs
        value = kwargs["SecretString"]
        assert isinstance(value, str)
        self.secret_string = value
        return {"VersionId": "updated-version"}


class FakeSsm:
    def __init__(self, value: str) -> None:
        self.value = value

    def get_parameter(self, **kwargs: object) -> dict[str, object]:
        assert kwargs["WithDecryption"] is True
        return {"Parameter": {"Value": self.value}}


@pytest.fixture
def manifest() -> secret_bundle.SecretManifest:
    return secret_bundle.load_manifest()


def _write_required_files(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "secret_key.txt").write_text("app-secret\n", encoding="utf-8")
    (directory / "postgres_password.txt").write_text(
        "database-secret\n",
        encoding="utf-8",
    )
    (directory / "redis_password.txt").write_text(
        "cache-secret\n",
        encoding="utf-8",
    )


def test_manifest_matches_runtime_secret_env_names(
    manifest: secret_bundle.SecretManifest,
) -> None:
    assert {spec.env_name for spec in manifest.secrets} == SECRET_ENV_NAMES


def test_manifest_matches_production_compose_secret_names(
    manifest: secret_bundle.SecretManifest,
) -> None:
    compose_path = secret_bundle.PROJECT_ROOT / "deploy" / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    expected = {spec.env_name for spec in manifest.secrets}

    assert set(compose["x-app-secrets"]) == expected
    assert set(compose["secrets"]) == expected


def test_read_directory_bundle_omits_empty_optional_files(
    tmp_path: Path,
    manifest: secret_bundle.SecretManifest,
) -> None:
    _write_required_files(tmp_path)
    (tmp_path / "openai_api_key.txt").write_text("", encoding="utf-8")
    (tmp_path / "deepseek_api_key.txt").write_text(
        "provider-secret\n",
        encoding="utf-8",
    )

    bundle = secret_bundle.read_directory_bundle(tmp_path, manifest)

    assert bundle == {
        "secret_key": "app-secret",
        "postgres_password": "database-secret",
        "redis_password": "cache-secret",
        "deepseek_api_key": "provider-secret",
    }


def test_read_directory_bundle_rejects_unknown_secret_file(
    tmp_path: Path,
    manifest: secret_bundle.SecretManifest,
) -> None:
    _write_required_files(tmp_path)
    (tmp_path / "unexpected_token.txt").write_text("token", encoding="utf-8")

    with pytest.raises(secret_bundle.SecretBundleError, match="Unknown secret files"):
        secret_bundle.read_directory_bundle(tmp_path, manifest)


def test_read_directory_bundle_rejects_empty_required_file(
    tmp_path: Path,
    manifest: secret_bundle.SecretManifest,
) -> None:
    _write_required_files(tmp_path)
    (tmp_path / "redis_password.txt").write_text("", encoding="utf-8")

    with pytest.raises(secret_bundle.SecretBundleError, match="is empty"):
        secret_bundle.read_directory_bundle(tmp_path, manifest)


def test_decode_bundle_rejects_unknown_key(
    manifest: secret_bundle.SecretManifest,
) -> None:
    raw = json.dumps(
        {
            "secret_key": "app",
            "postgres_password": "db",
            "redis_password": "cache",
            "unknown": "value",
        }
    )

    with pytest.raises(secret_bundle.SecretBundleError, match="Unknown"):
        secret_bundle.decode_bundle(raw, manifest)


def test_materialize_bundle_writes_allowlisted_files_and_permissions(
    tmp_path: Path,
    manifest: secret_bundle.SecretManifest,
) -> None:
    target = tmp_path / "runtime"
    bundle = {
        "secret_key": "app-secret",
        "postgres_password": "database-secret",
        "redis_password": "cache-secret",
        "openai_api_key": "provider-secret",
    }

    secret_bundle.materialize_bundle(bundle, target, manifest)

    assert stat.S_IMODE(target.stat().st_mode) == 0o700
    assert (target / "secret_key.txt").read_text(encoding="utf-8") == "app-secret"
    assert (target / "openai_api_key.txt").read_text(
        encoding="utf-8"
    ) == "provider-secret"
    assert (target / "deepseek_api_key.txt").read_text(encoding="utf-8") == ""
    assert stat.S_IMODE((target / "secret_key.txt").stat().st_mode) == 0o644
    assert len(list(target.glob("*.txt"))) == len(manifest.secrets)


def test_materialize_bundle_replaces_previous_managed_directory(
    tmp_path: Path,
    manifest: secret_bundle.SecretManifest,
) -> None:
    target = tmp_path / "runtime"
    first = {
        "secret_key": "first-app",
        "postgres_password": "first-db",
        "redis_password": "first-cache",
        "openai_api_key": "first-provider",
    }
    second = {
        "secret_key": "second-app",
        "postgres_password": "second-db",
        "redis_password": "second-cache",
    }
    secret_bundle.materialize_bundle(first, target, manifest)

    secret_bundle.materialize_bundle(second, target, manifest)

    assert (target / "secret_key.txt").read_text(encoding="utf-8") == "second-app"
    assert (target / "openai_api_key.txt").read_text(encoding="utf-8") == ""


def test_materialize_bundle_rejects_unmanaged_nonempty_directory(
    tmp_path: Path,
    manifest: secret_bundle.SecretManifest,
) -> None:
    target = tmp_path / "runtime"
    target.mkdir()
    (target / "keep.txt").write_text("do-not-replace", encoding="utf-8")
    bundle = {
        "secret_key": "app",
        "postgres_password": "db",
        "redis_password": "cache",
    }

    with pytest.raises(secret_bundle.SecretBundleError, match="unmanaged"):
        secret_bundle.materialize_bundle(bundle, target, manifest)

    assert (target / "keep.txt").read_text(encoding="utf-8") == "do-not-replace"


def test_import_bundle_creates_secret_with_non_sensitive_tags(
    manifest: secret_bundle.SecretManifest,
) -> None:
    client = FakeSecretsManager()
    bundle = {
        "secret_key": "app",
        "postgres_password": "db",
        "redis_password": "cache",
    }

    action, version_id, imported_count = secret_bundle.import_bundle(
        client,
        secret_id="dewflow-prod-runtime",
        environment="prod",
        bundle=bundle,
        manifest=manifest,
        update_existing=False,
    )

    assert (action, version_id, imported_count) == (
        "created",
        "created-version",
        3,
    )
    assert client.created_kwargs is not None
    assert client.created_kwargs["Name"] == "dewflow-prod-runtime"


def test_import_bundle_merges_existing_keys_without_dropping_them(
    manifest: secret_bundle.SecretManifest,
) -> None:
    existing = secret_bundle.encode_bundle(
        {
            "secret_key": "old-app",
            "postgres_password": "old-db",
            "redis_password": "old-cache",
            "openai_api_key": "keep-provider",
        },
        manifest,
    )
    client = FakeSecretsManager(existing)

    action, version_id, imported_count = secret_bundle.import_bundle(
        client,
        secret_id="dewflow-prod-runtime",
        environment="prod",
        bundle={
            "secret_key": "new-app",
            "postgres_password": "new-db",
            "redis_password": "new-cache",
        },
        manifest=manifest,
        update_existing=True,
    )

    assert (action, version_id, imported_count) == (
        "updated",
        "updated-version",
        3,
    )
    assert client.secret_string is not None
    merged = secret_bundle.decode_bundle(client.secret_string, manifest)
    assert merged["secret_key"] == "new-app"
    assert merged["openai_api_key"] == "keep-provider"


def test_import_bundle_refuses_existing_secret_without_explicit_update(
    manifest: secret_bundle.SecretManifest,
) -> None:
    existing = secret_bundle.encode_bundle(
        {
            "secret_key": "app",
            "postgres_password": "db",
            "redis_password": "cache",
        },
        manifest,
    )
    client = FakeSecretsManager(existing)

    with pytest.raises(secret_bundle.SecretBundleError, match="already exists"):
        secret_bundle.import_bundle(
            client,
            secret_id="dewflow-prod-runtime",
            environment="prod",
            bundle={
                "secret_key": "new-app",
                "postgres_password": "new-db",
                "redis_password": "new-cache",
            },
            manifest=manifest,
            update_existing=False,
        )


def test_aws_status_prints_key_names_but_not_values(
    manifest: secret_bundle.SecretManifest,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = FakeSecretsManager(
        secret_bundle.encode_bundle(
            {
                "secret_key": "sensitive-app-value",
                "postgres_password": "sensitive-db-value",
                "redis_password": "sensitive-cache-value",
            },
            manifest,
        )
    )
    monkeypatch.setattr(secret_bundle, "_secrets_manager_client", lambda region: client)
    args = argparse.Namespace(
        region="us-west-2",
        secret_id="dewflow-prod-runtime",
    )

    assert secret_bundle._run_aws_status(args, manifest) == 0

    output = capsys.readouterr().out
    assert "secret_key=postgres_password state=present" in output
    assert "sensitive-" not in output


@pytest.mark.parametrize(
    ("parameter_value", "expected"),
    [("same-secret", True), ("different-secret", False)],
)
def test_compare_file_to_parameter_returns_only_equality(
    tmp_path: Path,
    parameter_value: str,
    expected: bool,
) -> None:
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("same-secret\n", encoding="utf-8")

    matches = secret_bundle.compare_file_to_parameter(
        FakeSsm(parameter_value),
        secret_file=secret_file,
        parameter_name="/dewflow/prod/postgres_password",
    )

    assert matches is expected


def test_read_ssm_overrides_replaces_allowlisted_bundle_key(
    manifest: secret_bundle.SecretManifest,
) -> None:
    overrides = secret_bundle.read_ssm_overrides(
        FakeSsm("authoritative-database-secret"),
        overrides=[
            "postgres_password=/dewflow/prod/postgres_password",
        ],
        manifest=manifest,
    )

    assert overrides == {
        "postgres_password": "authoritative-database-secret",
    }


def test_read_ssm_overrides_rejects_unknown_bundle_key(
    manifest: secret_bundle.SecretManifest,
) -> None:
    with pytest.raises(secret_bundle.SecretBundleError, match="allowlisted"):
        secret_bundle.read_ssm_overrides(
            FakeSsm("value"),
            overrides=["unknown=/dewflow/prod/unknown"],
            manifest=manifest,
        )


def test_encode_bundle_rejects_value_over_service_limit(
    manifest: secret_bundle.SecretManifest,
) -> None:
    bundle = {
        "secret_key": "x" * secret_bundle.MAX_SECRET_BYTES,
        "postgres_password": "db",
        "redis_password": "cache",
    }

    with pytest.raises(secret_bundle.SecretBundleError, match="65,536"):
        secret_bundle.encode_bundle(bundle, manifest)
