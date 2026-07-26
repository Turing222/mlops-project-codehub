"""Production bootstrap user script unit tests.

职责：验证生产 bootstrap 用户脚本参数校验；边界：直接调用脚本函数，不连数据库；副作用：无。
"""

import pytest

from scripts.seed import prod_bootstrap_user as bootstrap


def test_validate_args_rejects_short_password() -> None:
    args = bootstrap.argparse.Namespace(password="short")
    with pytest.raises(SystemExit):
        bootstrap._validate_args(args)


def test_validate_args_accepts_strong_password() -> None:
    args = bootstrap.argparse.Namespace(password="StrongPass123!")
    bootstrap._validate_args(args)
