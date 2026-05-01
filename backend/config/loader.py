"""YAML configuration loader.

职责：解析配置目录并加载项目 YAML 配置文件。
边界：本模块只返回原始 mapping；schema 校验由具体 config 模块负责。
失败处理：缺失、非文件、非法 YAML 或非 mapping 都转换为 ConfigurationError。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


class ConfigurationError(RuntimeError):
    """配置文件缺失或非法。"""


def get_config_dir(config_dir: str | Path | None = None) -> Path:
    """返回配置根目录，显式参数优先于 CONFIG_DIR。"""
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
    """加载相对于配置根目录的 YAML mapping。"""
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
