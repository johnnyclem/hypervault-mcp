from __future__ import annotations

import asyncio

import pytest
from fastmcp import Client

from hypervault_mcp import server


@pytest.fixture(autouse=True)
def clean_hypervault_env(monkeypatch):
    """Every test starts with no HyperVault env vars set, so tests are
    hermetic and never accidentally depend on (or leak into) the real
    environment."""
    monkeypatch.delenv("HYPERVAULT_API_KEY", raising=False)
    monkeypatch.delenv("HYPERVAULT_API_URL", raising=False)
    yield


@pytest.fixture
def tool_names() -> set[str]:
    """The names of every tool the server registers, as an MCP client lists
    them (the same call on every fastmcp this package supports)."""

    async def list_names() -> set[str]:
        async with Client(server.mcp) as client:
            return {tool.name for tool in await client.list_tools()}

    return asyncio.run(list_names())
