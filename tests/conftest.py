"""Global pytest fixtures and test-safe environment setup.

Keep this file lightweight and avoid importing FastAPI app here.
Fixtures that require app startup should live in tests/integration/conftest.py.
"""

import os


def pytest_configure():
    """Normalize env before test collection imports backend settings."""
    os.environ.setdefault("SECRET_KEY", "test-secret")
    # backend.core.config uses Literal[768]; env vars are strings and can break import.
    os.environ.pop("RAG_EMBED_DIM", None)
