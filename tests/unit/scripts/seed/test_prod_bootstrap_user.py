"""Unit tests for production bootstrap user script."""

import pytest

from scripts.seed import prod_bootstrap_user as bootstrap


def test_validate_args_rejects_short_password() -> None:
    args = bootstrap.argparse.Namespace(password="short")
    with pytest.raises(SystemExit):
        bootstrap._validate_args(args)


def test_validate_args_accepts_strong_password() -> None:
    args = bootstrap.argparse.Namespace(password="StrongPass123!")
    bootstrap._validate_args(args)
