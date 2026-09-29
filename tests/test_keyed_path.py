"""The URL-keyed connector path: /k/<key>/mcp.

The Claude app's custom connectors (claude.ai web, iOS, Android) can point
at a remote MCP URL but can't attach headers, so the key rides in the URL.
These tests go through the real ASGI app that Vercel serves (build_http_app)
with the backend call mocked, proving the URL key reaches hypervault.store
as the X-HyperVault-Key header — and that nothing else about auth changed.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from asgi_lifespan import LifespanManager

from hypervault_mcp.server import DEFAULT_API_URL, KeyedPathMiddleware, build_http_app

MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}
LIST_ITEMS = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {"name": "list_my_vault_items", "arguments": {}},
}
TOOLS_LIST = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}


@pytest.fixture
def app():
    return build_http_app(path="/mcp")


async def _post(app, path, body, headers=None):
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(path, json=body, headers={**MCP_HEADERS, **(headers or {})})


def _text(response):
    return response.json()["result"]["content"][0]["text"]


def _is_error(response):
    return response.json()["result"]["isError"]


class TestKeyInTheUrl:
    @pytest.mark.asyncio
    async def test_url_key_is_forwarded_as_the_header(self, app):
        with respx.mock:
            route = respx.get(f"{DEFAULT_API_URL}/api/artifacts").mock(
                return_value=httpx.Response(200, json={"items": []})
            )
            response = await _post(app, "/k/hv_url_key-1/mcp", LIST_ITEMS)
            assert response.status_code == 200
            assert not _is_error(response), _text(response)
            assert route.calls.last.request.headers["x-hypervault-key"] == "hv_url_key-1"

    @pytest.mark.asyncio
    async def test_url_key_wins_over_a_conflicting_header(self, app):
        """The URL is the connector's identity: a stray header can't redirect
        the call to a different vault."""
        with respx.mock:
            route = respx.get(f"{DEFAULT_API_URL}/api/artifacts").mock(
                return_value=httpx.Response(200, json={"items": []})
            )
            await _post(
                app,
                "/k/hv_from_url/mcp",
                LIST_ITEMS,
                headers={"Authorization": "Bearer hv_from_header", "X-HyperVault-Key": "hv_other"},
            )
            sent = route.calls.last.request.headers
            assert sent["x-hypervault-key"] == "hv_from_url"
            assert "authorization" not in sent

    @pytest.mark.asyncio
    async def test_tools_list_works_on_the_keyed_path(self, app):
        response = await _post(app, "/k/hv_abc/mcp", TOOLS_LIST)
        assert response.status_code == 200
        names = {t["name"] for t in response.json()["result"]["tools"]}
        assert {"setup_challenge", "read_artifact", "write_artifact"} <= names

    @pytest.mark.asyncio
    async def test_operator_env_key_still_never_leaks_on_the_plain_path(self, app, monkeypatch):
        monkeypatch.setenv("HYPERVAULT_API_KEY", "hv_operators_secret")
        with respx.mock:
            route = respx.get(f"{DEFAULT_API_URL}/api/artifacts").mock(
                return_value=httpx.Response(200, json={"items": []})
            )
            response = await _post(app, "/mcp", LIST_ITEMS)
            assert _is_error(response)
            assert "Authentication required" in _text(response)
            assert "/k/<key>/mcp" in _text(response)
            assert not route.called


class TestMalformedKeyedPaths:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "path",
        [
            "/k//mcp",  # empty key
            "/k/notakey/mcp",  # not an hv_ key
            "/k/hv_abc/other",  # right prefix, wrong MCP path
            "/k/hv_abc/mcp/extra",  # trailing segment
            "/k/hv_abc",  # no MCP path at all
            "/k/hv_a%20b/mcp",  # key with a char outside the minted charset
        ],
    )
    async def test_is_not_rewritten(self, app, path):
        """Anything that isn't exactly /k/<hv_key>/mcp reaches FastMCP as-is
        and 404s there — no header is ever synthesised from it."""
        with respx.mock:
            route = respx.get(f"{DEFAULT_API_URL}/api/artifacts").mock(
                return_value=httpx.Response(200, json={"items": []})
            )
            response = await _post(app, path, LIST_ITEMS)
            assert response.status_code == 404
            assert not route.called


class TestMiddlewareUnit:
    @pytest.mark.asyncio
    async def test_rewrites_scope_for_the_inner_app(self):
        seen = {}

        async def inner(scope, receive, send):
            seen.update(scope)

        mw = KeyedPathMiddleware(inner, mcp_path="/mcp")
        scope = {
            "type": "http",
            "path": "/k/hv_k1/mcp",
            "raw_path": b"/k/hv_k1/mcp",
            "headers": [(b"host", b"x"), (b"authorization", b"Bearer hv_other")],
        }
        await mw(scope, None, None)
        assert seen["path"] == "/mcp"
        assert seen["raw_path"] == b"/mcp"
        assert seen["headers"] == [(b"host", b"x"), (b"x-hypervault-key", b"hv_k1")]
        # The caller's scope object is left alone (a copy was rewritten).
        assert scope["path"] == "/k/hv_k1/mcp"

    @pytest.mark.asyncio
    async def test_lifespan_and_other_paths_pass_through_untouched(self):
        seen = []

        async def inner(scope, receive, send):
            seen.append(scope)

        mw = KeyedPathMiddleware(inner)
        lifespan = {"type": "lifespan"}
        plain = {"type": "http", "path": "/mcp", "headers": [(b"x-hypervault-key", b"hv_h")]}
        await mw(lifespan, None, None)
        await mw(plain, None, None)
        assert seen[0] is lifespan
        assert seen[1] is plain
