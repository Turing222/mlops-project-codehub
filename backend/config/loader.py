from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


class ConfigurationError(RuntimeError):
    """Raised when a required application config file is missing or invalid."""


def get_config_dir(config_dir: str | Path | None = None) -> Path:
    if config_dir is None:
        config_dir = os.getenv("CONFIG_DIR")
    if config_dir:
        path = Path(config_dir)
        if not path.is_absolute():
            path = _repo_root() / path
        return path
    return _repo_root() / "configs"


def load_yaml_config(
    relative_path: str | Path,
    *,
    config_dir: str | Path | None = None,
) -> dict[str, Any]:
    path = get_config_dir(config_dir) / relative_path
    if not path.exists():
        raise ConfigurationError(f"Config file not found: {path}")
    if not path.is_file():
        raise ConfigurationError(f"Config path is not a file: {path}")

    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Invalid YAML in config file: {path}") from exc

    if not isinstance(data, dict):
        raise ConfigurationError(f"Config file must contain a mapping: {path}")
    return data


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]
