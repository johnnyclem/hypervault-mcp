from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def clean_hypervault_env(monkeypatch):
    """Every test starts with no HyperVault env vars set, so tests are
    hermetic and never accidentally depend on (or leak into) the real
    environment."""
    monkeypatch.delenv("HYPERVAULT_API_KEY", raising=False)
    monkeypatch.delenv("HYPERVAULT_API_URL", raising=False)
    yield
