"""Bridge AWS Secrets Manager JSON bundles and Dewflow file-backed secrets.

The command never prints secret values. It keeps the existing ``*.txt`` file
contract as the runtime boundary while AWS becomes the upstream source.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

import boto3
from botocore.exceptions import ClientError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST_PATH = PROJECT_ROOT / "deploy" / "runtime-secret-manifest.json"
DEFAULT_SECRET_ID = "dewflow-prod-runtime"
DEFAULT_SOURCE_DIR = PROJECT_ROOT / "secrets" / "ec2"
DEFAULT_RUNTIME_DIR = Path("/run/dewflow-secrets")
MAX_SECRET_BYTES = 65_536
ENV_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
MANAGED_MARKER = ".dewflow-secret-bundle"


class SecretBundleError(RuntimeError):
    """Raised when a bundle or materialized secret directory is invalid."""


class SecretsManagerClient(Protocol):
    def create_secret(self, **kwargs: object) -> dict[str, object]: ...

    def get_secret_value(self, **kwargs: object) -> dict[str, object]: ...

    def put_secret_value(self, **kwargs: object) -> dict[str, object]: ...


class SsmClient(Protocol):
    def get_parameter(self, **kwargs: object) -> dict[str, object]: ...


@dataclass(frozen=True)
class SecretSpec:
    env_name: str
    file_name: str
    required: bool

    @property
    def bundle_key(self) -> str:
        return self.file_name.removesuffix(".txt")


@dataclass(frozen=True)
class SecretManifest:
    schema_version: int
    secrets: tuple[SecretSpec, ...]

    @property
    def bundle_keys(self) -> frozenset[str]:
        return frozenset(spec.bundle_key for spec in self.secrets)

    @property
    def file_names(self) -> frozenset[str]:
        return frozenset(spec.file_name for spec in self.secrets)


def load_manifest(path: Path = DEFAULT_MANIFEST_PATH) -> SecretManifest:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SecretBundleError(f"Cannot load secret manifest: {path}") from exc

    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise SecretBundleError("Secret manifest must use schema_version 1")
    items = raw.get("secrets")
    if not isinstance(items, list) or not items:
        raise SecretBundleError("Secret manifest must contain a non-empty secrets list")

    specs: list[SecretSpec] = []
    for item in items:
        if not isinstance(item, dict):
            raise SecretBundleError("Each secret manifest entry must be an object")
        env_name = item.get("env")
        file_name = item.get("file")
        required = item.get("required")
        if (
            not isinstance(env_name, str)
            or not ENV_NAME_PATTERN.fullmatch(env_name)
            or not isinstance(file_name, str)
            or file_name != f"{env_name.lower()}.txt"
            or not isinstance(required, bool)
        ):
            raise SecretBundleError(f"Invalid secret manifest entry: {env_name!r}")
        specs.append(SecretSpec(env_name, file_name, required))

    manifest = SecretManifest(schema_version=1, secrets=tuple(specs))
    if len(manifest.bundle_keys) != len(specs):
        raise SecretBundleError("Secret manifest contains duplicate bundle keys")
    if len(manifest.file_names) != len(specs):
        raise SecretBundleError("Secret manifest contains duplicate file names")
    return manifest


def _read_secret_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise SecretBundleError(f"Secret source must be a regular file: {path}")
    try:
        return path.read_text(encoding="utf-8").rstrip("\r\n")
    except (OSError, UnicodeError) as exc:
        raise SecretBundleError(f"Cannot read secret source: {path}") from exc


def read_directory_bundle(
    directory: Path,
    manifest: SecretManifest,
) -> dict[str, str]:
    if directory.is_symlink() or not directory.is_dir():
        raise SecretBundleError(f"Secret source must be a directory: {directory}")

    unknown_files = sorted(
        path.name
        for path in directory.glob("*.txt")
        if path.name not in manifest.file_names
    )
    if unknown_files:
        raise SecretBundleError(f"Unknown secret files: {', '.join(unknown_files)}")

    bundle: dict[str, str] = {}
    for spec in manifest.secrets:
        path = directory / spec.file_name
        if not path.exists():
            if spec.required:
                raise SecretBundleError(
                    f"Missing required secret file: {spec.file_name}"
                )
            continue
        value = _read_secret_file(path)
        if spec.required and not value:
            raise SecretBundleError(f"Required secret file is empty: {spec.file_name}")
        if value:
            bundle[spec.bundle_key] = value
    return bundle


def validate_bundle(
    raw_bundle: object,
    manifest: SecretManifest,
) -> dict[str, str]:
    if not isinstance(raw_bundle, dict):
        raise SecretBundleError("SecretString must contain a JSON object")

    bundle_object = cast(dict[object, object], raw_bundle)
    unknown_keys = [
        key
        for key in bundle_object
        if not isinstance(key, str) or key not in manifest.bundle_keys
    ]
    if unknown_keys:
        rendered = ", ".join(sorted(repr(key) for key in unknown_keys))
        raise SecretBundleError(f"Unknown secret bundle keys: {rendered}")

    bundle: dict[str, str] = {}
    for spec in manifest.secrets:
        value = bundle_object.get(spec.bundle_key)
        if value is None:
            if spec.required:
                raise SecretBundleError(
                    f"Missing required secret key: {spec.bundle_key}"
                )
            continue
        if not isinstance(value, str):
            raise SecretBundleError(
                f"Secret bundle value must be a string: {spec.bundle_key}"
            )
        if "\x00" in value:
            raise SecretBundleError(
                f"Secret bundle value contains a null byte: {spec.bundle_key}"
            )
        if spec.required and not value:
            raise SecretBundleError(
                f"Required secret bundle value is empty: {spec.bundle_key}"
            )
        if value:
            bundle[spec.bundle_key] = value
    return bundle


def decode_bundle(
    secret_string: str,
    manifest: SecretManifest,
) -> dict[str, str]:
    try:
        raw_bundle = json.loads(secret_string)
    except json.JSONDecodeError as exc:
        raise SecretBundleError("SecretString is not valid JSON") from exc
    return validate_bundle(raw_bundle, manifest)


def encode_bundle(bundle: dict[str, str], manifest: SecretManifest) -> str:
    normalized = validate_bundle(bundle, manifest)
    secret_string = json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if len(secret_string.encode("utf-8")) > MAX_SECRET_BYTES:
        raise SecretBundleError("Encoded secret bundle exceeds 65,536 bytes")
    return secret_string


def inspect_directory(
    directory: Path,
    manifest: SecretManifest,
) -> list[tuple[SecretSpec, str]]:
    status: list[tuple[SecretSpec, str]] = []
    for spec in manifest.secrets:
        path = directory / spec.file_name
        if not path.exists():
            state = "missing"
        elif path.is_symlink() or not path.is_file():
            state = "invalid"
        else:
            state = "present" if _read_secret_file(path) else "empty"
        status.append((spec, state))
    return status


def _prepare_materialized_directory(
    stage: Path,
    bundle: dict[str, str],
    manifest: SecretManifest,
) -> None:
    stage.chmod(0o700)
    (stage / MANAGED_MARKER).write_text("schema_version=1\n", encoding="utf-8")
    (stage / MANAGED_MARKER).chmod(0o600)
    for spec in manifest.secrets:
        destination = stage / spec.file_name
        destination.write_text(bundle.get(spec.bundle_key, ""), encoding="utf-8")
        destination.chmod(0o644)


def materialize_bundle(
    bundle: dict[str, str],
    target: Path,
    manifest: SecretManifest,
) -> None:
    normalized = validate_bundle(bundle, manifest)
    target_parent = target.parent
    target_parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise SecretBundleError(f"Refusing to replace symlink target: {target}")
    if target.exists() and not target.is_dir():
        raise SecretBundleError(f"Materialize target is not a directory: {target}")
    if (
        target.exists()
        and any(target.iterdir())
        and not (target / MANAGED_MARKER).is_file()
    ):
        raise SecretBundleError(
            f"Refusing to replace unmanaged non-empty directory: {target}"
        )

    stage = Path(tempfile.mkdtemp(prefix=f".{target.name}.stage-", dir=target_parent))
    backup: Path | None = None
    try:
        _prepare_materialized_directory(stage, normalized, manifest)
        if target.exists():
            backup = Path(
                tempfile.mkdtemp(prefix=f".{target.name}.backup-", dir=target_parent)
            )
            backup.rmdir()
            target.rename(backup)
        stage.rename(target)
    except Exception:
        if backup is not None and backup.exists() and not target.exists():
            backup.rename(target)
        raise
    finally:
        if stage.exists():
            shutil.rmtree(stage)
        if backup is not None and backup.exists():
            shutil.rmtree(backup)


def _client_error_code(exc: ClientError) -> str:
    error = exc.response.get("Error", {})
    code = error.get("Code") if isinstance(error, dict) else None
    return code if isinstance(code, str) else "Unknown"


def fetch_bundle(
    client: SecretsManagerClient,
    secret_id: str,
    manifest: SecretManifest,
) -> tuple[dict[str, str], str]:
    try:
        response = client.get_secret_value(SecretId=secret_id)
    except ClientError as exc:
        raise SecretBundleError(
            f"Cannot retrieve Secrets Manager secret ({_client_error_code(exc)})"
        ) from exc

    secret_string = response.get("SecretString")
    if not isinstance(secret_string, str):
        raise SecretBundleError("Secrets Manager response has no SecretString")
    version_id = response.get("VersionId")
    return (
        decode_bundle(secret_string, manifest),
        version_id if isinstance(version_id, str) else "unknown",
    )


def import_bundle(
    client: SecretsManagerClient,
    *,
    secret_id: str,
    environment: str,
    bundle: dict[str, str],
    manifest: SecretManifest,
    update_existing: bool,
) -> tuple[str, str, int]:
    secret_string = encode_bundle(bundle, manifest)
    try:
        response = client.create_secret(
            Name=secret_id,
            Description=(
                "Dewflow runtime secret bundle materialized into file-backed secrets."
            ),
            SecretString=secret_string,
            Tags=[
                {"Key": "Project", "Value": "dewflow"},
                {"Key": "Environment", "Value": environment},
                {"Key": "Purpose", "Value": "runtime"},
                {"Key": "ManagedBy", "Value": "dewflow-secret-bundle"},
            ],
        )
        action = "created"
        imported_count = len(bundle)
    except ClientError as exc:
        if _client_error_code(exc) != "ResourceExistsException":
            raise SecretBundleError(
                f"Cannot create Secrets Manager secret ({_client_error_code(exc)})"
            ) from exc
        if not update_existing:
            raise SecretBundleError(
                "Secret already exists; pass --update-existing to merge new values"
            ) from exc

        existing, _ = fetch_bundle(client, secret_id, manifest)
        merged = existing | bundle
        try:
            response = client.put_secret_value(
                SecretId=secret_id,
                SecretString=encode_bundle(merged, manifest),
            )
        except ClientError as put_exc:
            raise SecretBundleError(
                f"Cannot update Secrets Manager secret ({_client_error_code(put_exc)})"
            ) from put_exc
        action = "updated"
        imported_count = len(bundle)

    version_id = response.get("VersionId")
    return (
        action,
        version_id if isinstance(version_id, str) else "unknown",
        imported_count,
    )


def compare_file_to_parameter(
    client: SsmClient,
    *,
    secret_file: Path,
    parameter_name: str,
) -> bool:
    local_value = _read_secret_file(secret_file)
    try:
        response = client.get_parameter(Name=parameter_name, WithDecryption=True)
    except ClientError as exc:
        raise SecretBundleError(
            f"Cannot retrieve SSM parameter ({_client_error_code(exc)})"
        ) from exc

    parameter = response.get("Parameter")
    if not isinstance(parameter, dict):
        raise SecretBundleError("SSM response has no Parameter object")
    remote_value = cast(dict[str, object], parameter).get("Value")
    if not isinstance(remote_value, str):
        raise SecretBundleError("SSM response has no string parameter value")
    return hmac.compare_digest(local_value, remote_value)


def read_ssm_overrides(
    client: SsmClient,
    *,
    overrides: list[str],
    manifest: SecretManifest,
) -> dict[str, str]:
    values: dict[str, str] = {}
    for override in overrides:
        bundle_key, separator, parameter_name = override.partition("=")
        if (
            not separator
            or bundle_key not in manifest.bundle_keys
            or not parameter_name.startswith("/")
        ):
            raise SecretBundleError(
                "SSM override must use an allowlisted key and absolute parameter "
                f"name: {override!r}"
            )
        if bundle_key in values:
            raise SecretBundleError(f"Duplicate SSM override: {bundle_key}")
        try:
            response = client.get_parameter(
                Name=parameter_name,
                WithDecryption=True,
            )
        except ClientError as exc:
            raise SecretBundleError(
                f"Cannot retrieve SSM override ({_client_error_code(exc)})"
            ) from exc
        parameter = response.get("Parameter")
        value = (
            cast(dict[str, object], parameter).get("Value")
            if isinstance(parameter, dict)
            else None
        )
        if not isinstance(value, str) or not value:
            raise SecretBundleError(f"SSM override is empty: {bundle_key}")
        values[bundle_key] = value
    return values


def _secrets_manager_client(region: str | None) -> SecretsManagerClient:
    return boto3.client("secretsmanager", region_name=region)


def _ssm_client(region: str | None) -> SsmClient:
    return boto3.client("ssm", region_name=region)


def _default_region() -> str | None:
    return (
        os.getenv("DEPLOY_AWS_REGION")
        or os.getenv("AWS_REGION")
        or os.getenv("AWS_DEFAULT_REGION")
    )


def _run_status(args: argparse.Namespace, manifest: SecretManifest) -> int:
    directory = args.directory
    if directory.is_symlink() or not directory.is_dir():
        raise SecretBundleError(f"Secret source must be a directory: {directory}")
    unknown = sorted(
        path.name
        for path in directory.glob("*.txt")
        if path.name not in manifest.file_names
    )
    invalid_required = False
    active_count = 0
    for spec, state in inspect_directory(directory, manifest):
        print(
            f"secret_file={spec.file_name} state={state} "
            f"required={'true' if spec.required else 'false'}"
        )
        active_count += state == "present"
        invalid_required |= spec.required and state != "present"
    if unknown:
        print(f"unknown_secret_files={','.join(unknown)}")
    print(f"secret_file_total={len(manifest.secrets)}")
    print(f"secret_file_active={active_count}")
    return 1 if invalid_required or unknown else 0


def _run_aws_status(args: argparse.Namespace, manifest: SecretManifest) -> int:
    bundle, version_id = fetch_bundle(
        _secrets_manager_client(args.region),
        args.secret_id,
        manifest,
    )
    for spec in manifest.secrets:
        state = "present" if spec.bundle_key in bundle else "disabled"
        print(
            f"secret_key={spec.bundle_key} state={state} "
            f"required={'true' if spec.required else 'false'}"
        )
    print(f"secret_aws_name={args.secret_id}")
    print(f"secret_aws_version={version_id}")
    print(f"secret_aws_active={len(bundle)}")
    return 0


def _run_import(args: argparse.Namespace, manifest: SecretManifest) -> int:
    bundle = read_directory_bundle(args.directory, manifest)
    overrides = (
        read_ssm_overrides(
            _ssm_client(args.region),
            overrides=args.ssm_override,
            manifest=manifest,
        )
        if args.ssm_override
        else {}
    )
    bundle.update(overrides)
    bundle = validate_bundle(bundle, manifest)
    print(f"secret_import_source={args.directory}")
    print(f"secret_import_target={args.secret_id}")
    print(f"secret_import_key_count={len(bundle)}")
    print(f"secret_import_keys={','.join(sorted(bundle))}")
    print(f"secret_import_override_keys={','.join(sorted(overrides))}")
    if not args.apply:
        print("secret_import_status=dry_run")
        return 0

    action, version_id, imported_count = import_bundle(
        _secrets_manager_client(args.region),
        secret_id=args.secret_id,
        environment=args.environment,
        bundle=bundle,
        manifest=manifest,
        update_existing=args.update_existing,
    )
    print(f"secret_import_status={action}")
    print(f"secret_import_version={version_id}")
    print(f"secret_import_applied_keys={imported_count}")
    return 0


def _run_materialize(args: argparse.Namespace, manifest: SecretManifest) -> int:
    bundle, version_id = fetch_bundle(
        _secrets_manager_client(args.region),
        args.secret_id,
        manifest,
    )
    materialize_bundle(bundle, args.directory, manifest)
    print("secret_materialize_status=written")
    print(f"secret_materialize_source={args.secret_id}")
    print(f"secret_materialize_version={version_id}")
    print(f"secret_materialize_target={args.directory}")
    print(f"secret_materialize_active_keys={len(bundle)}")
    return 0


def _run_compare_ssm(args: argparse.Namespace) -> int:
    matches = compare_file_to_parameter(
        _ssm_client(args.region),
        secret_file=args.secret_file,
        parameter_name=args.parameter_name,
    )
    print(f"secret_comparison={'match' if matches else 'mismatch'}")
    return 0 if matches else 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage Dewflow JSON secret bundles without printing values."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST_PATH,
        help="Non-secret runtime file manifest.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status", help="Inspect file presence only.")
    status.add_argument("--directory", type=Path, default=DEFAULT_SOURCE_DIR)

    aws_status = subparsers.add_parser(
        "status-aws",
        help="Inspect bundle key presence without printing values.",
    )
    aws_status.add_argument("--secret-id", default=DEFAULT_SECRET_ID)
    aws_status.add_argument("--region", default=_default_region())

    import_directory = subparsers.add_parser(
        "import-directory",
        help="Create or merge a Secrets Manager JSON bundle from a file directory.",
    )
    import_directory.add_argument("--directory", type=Path, default=DEFAULT_SOURCE_DIR)
    import_directory.add_argument("--secret-id", default=DEFAULT_SECRET_ID)
    import_directory.add_argument("--environment", default="prod")
    import_directory.add_argument("--region", default=_default_region())
    import_directory.add_argument("--apply", action="store_true")
    import_directory.add_argument("--update-existing", action="store_true")
    import_directory.add_argument(
        "--ssm-override",
        action="append",
        default=[],
        metavar="KEY=/parameter/name",
        help="Replace one allowlisted directory value from a SecureString.",
    )

    materialize = subparsers.add_parser(
        "materialize",
        help="Fetch a JSON bundle and write the allowlisted runtime files.",
    )
    materialize.add_argument("--secret-id", default=DEFAULT_SECRET_ID)
    materialize.add_argument("--directory", type=Path, default=DEFAULT_RUNTIME_DIR)
    materialize.add_argument("--region", default=_default_region())

    compare_ssm = subparsers.add_parser(
        "compare-ssm",
        help="Compare one file and one SecureString without printing either value.",
    )
    compare_ssm.add_argument("--secret-file", type=Path, required=True)
    compare_ssm.add_argument("--parameter-name", required=True)
    compare_ssm.add_argument("--region", default=_default_region())
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        manifest = load_manifest(args.manifest)
        if args.command == "status":
            return _run_status(args, manifest)
        if args.command == "status-aws":
            return _run_aws_status(args, manifest)
        if args.command == "import-directory":
            if args.update_existing and not args.apply:
                raise SecretBundleError("--update-existing requires --apply")
            return _run_import(args, manifest)
        if args.command == "materialize":
            return _run_materialize(args, manifest)
        if args.command == "compare-ssm":
            return _run_compare_ssm(args)
    except SecretBundleError as exc:
        print(f"secret_bundle_error={exc}", file=sys.stderr)
        return 1
    raise SecretBundleError(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
