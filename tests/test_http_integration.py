"""End-to-end tests against the real Streamable-HTTP ASGI app (the same app
object Vercel serves), with the outbound call to hypervault.store mocked via
respx. These are the tests that actually exercise the fix for the auth
bypass: a real MCP tools/call request, over a real ASGI transport, with no
caller-supplied key, must be rejected — even when an operator
HYPERVAULT_API_KEY is present in the process environment.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from asgi_lifespan import LifespanManager

from hypervault_mcp.server import DEFAULT_API_URL, mcp

MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


def _call_tool_body(name: str, arguments: dict | None = None, request_id: int = 1) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}},
    }


@pytest.fixture
def http_app():
    return mcp.http_app(path="/mcp", stateless_http=True, json_response=True)


async def _post(http_app, body, headers=None):
    async with LifespanManager(http_app):
        transport = httpx.ASGITransport(app=http_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            merged = {**MCP_HEADERS, **(headers or {})}
            return await client.post("/mcp", json=body, headers=merged)


def _tool_result_text(response: httpx.Response) -> str:
    payload = response.json()
    return payload["result"]["content"][0]["text"]


def _is_tool_error(response: httpx.Response) -> bool:
    return response.json()["result"]["isError"]


class TestUnauthenticatedCallsAreRejected:
    @pytest.mark.asyncio
    async def test_tool_call_without_any_header_is_rejected(self, http_app, monkeypatch):
        monkeypatch.delenv("HYPERVAULT_API_KEY", raising=False)
        response = await _post(http_app, _call_tool_body("list_my_vault_items"))
        assert response.status_code == 200  # JSON-RPC error, not a transport error
        assert _is_tool_error(response)
        assert "Authentication required" in _tool_result_text(response)

    @pytest.mark.asyncio
    async def test_operator_env_key_is_never_used_as_a_fallback(self, http_app, monkeypatch):
        """This is the regression test for the actual vulnerability: setting
        HYPERVAULT_API_KEY server-side must never let an anonymous caller
        through."""
        monkeypatch.setenv("HYPERVAULT_API_KEY", "hv_operators_own_secret_key")

        with respx.mock:
            route = respx.get(f"{DEFAULT_API_URL}/api/artifacts").mock(
                return_value=httpx.Response(200, json={"items": ["should never be reached"]})
            )
            response = await _post(http_app, _call_tool_body("list_my_vault_items"))

            assert _is_tool_error(response)
            assert "Authentication required" in _tool_result_text(response)
            assert not route.called, "backend must never be called for an unauthenticated request"

    @pytest.mark.asyncio
    async def test_blank_header_is_also_rejected(self, http_app, monkeypatch):
        monkeypatch.delenv("HYPERVAULT_API_KEY", raising=False)
        response = await _post(
            http_app, _call_tool_body("list_my_vault_items"), headers={"X-HyperVault-Key": "   "}
        )
        assert _is_tool_error(response)
        assert "Authentication required" in _tool_result_text(response)


class TestAuthenticatedCallsForwardTheCallersOwnKey:
    @pytest.mark.asyncio
    async def test_x_hypervault_key_header_is_forwarded(self, http_app, monkeypatch):
        monkeypatch.delenv("HYPERVAULT_API_KEY", raising=False)
        with respx.mock:
            route = respx.get(f"{DEFAULT_API_URL}/api/artifacts").mock(
                return_value=httpx.Response(200, json={"items": []})
            )
            response = await _post(
                http_app,
                _call_tool_body("list_my_vault_items"),
                headers={"X-HyperVault-Key": "hv_caller_key"},
            )
            assert not _is_tool_error(response)
            assert route.called
            forwarded = route.calls.last.request.headers["x-hypervault-key"]
            assert forwarded == "hv_caller_key"

    @pytest.mark.asyncio
    async def test_authorization_bearer_header_is_forwarded(self, http_app, monkeypatch):
        monkeypatch.delenv("HYPERVAULT_API_KEY", raising=False)
        with respx.mock:
            route = respx.get(f"{DEFAULT_API_URL}/api/artifacts").mock(
                return_value=httpx.Response(200, json={"items": []})
            )
            response = await _post(
                http_app,
                _call_tool_body("list_my_vault_items"),
                headers={"Authorization": "Bearer hv_caller_key"},
            )
            assert not _is_tool_error(response)
            forwarded = route.calls.last.request.headers["x-hypervault-key"]
            assert forwarded == "hv_caller_key"

    @pytest.mark.asyncio
    async def test_backend_rejection_surfaces_to_the_caller(self, http_app, monkeypatch):
        monkeypatch.delenv("HYPERVAULT_API_KEY", raising=False)
        with respx.mock:
            respx.get(f"{DEFAULT_API_URL}/api/artifacts").mock(
                return_value=httpx.Response(401, json={"error": "Invalid or revoked HyperVault API key."})
            )
            response = await _post(
                http_app,
                _call_tool_body("list_my_vault_items"),
                headers={"X-HyperVault-Key": "hv_bad_key"},
            )
            assert _is_tool_error(response)
            assert "Invalid or revoked HyperVault API key." in _tool_result_text(response)

    @pytest.mark.asyncio
    async def test_two_different_callers_never_cross_contaminate(self, http_app, monkeypatch):
        """Two sequential requests with two different keys must each reach
        the backend with their own key — never the other caller's."""
        monkeypatch.delenv("HYPERVAULT_API_KEY", raising=False)
        with respx.mock:
            route = respx.get(f"{DEFAULT_API_URL}/api/artifacts").mock(
                return_value=httpx.Response(200, json={"items": []})
            )

            await _post(
                http_app,
                _call_tool_body("list_my_vault_items", request_id=1),
                headers={"X-HyperVault-Key": "hv_alice"},
            )
            await _post(
                http_app,
                _call_tool_body("list_my_vault_items", request_id=2),
                headers={"X-HyperVault-Key": "hv_bob"},
            )

            sent_keys = [call.request.headers["x-hypervault-key"] for call in route.calls]
            assert sent_keys == ["hv_alice", "hv_bob"]


class TestUnauthenticatedProtocolLevelCallsStillWork:
    """Listing tool schemas is not sensitive (no user data), so the MCP
    handshake itself should not require a key — only tool execution does."""

    @pytest.mark.asyncio
    async def test_initialize_does_not_require_auth(self, http_app, monkeypatch):
        monkeypatch.delenv("HYPERVAULT_API_KEY", raising=False)
        response = await _post(
            http_app,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0.0.1"},
                },
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["result"]["serverInfo"]["name"] == "HyperVault"

    @pytest.mark.asyncio
    async def test_tools_list_does_not_require_auth(self, http_app, monkeypatch):
        monkeypatch.delenv("HYPERVAULT_API_KEY", raising=False)
        response = await _post(
            http_app, {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        )
        assert response.status_code == 200
        tool_names = {t["name"] for t in response.json()["result"]["tools"]}
        assert "save_to_hypervault" in tool_names
        assert "list_my_vault_items" in tool_names
        assert "create_artifact_group" in tool_names


class TestArtifactGroupToolsOverHttp:
    """End-to-end coverage for the artifact-group tools: local validation
    still runs (and rejects) before any auth/network call, and a valid call
    is forwarded with the caller's own key like every other tool."""

    @pytest.mark.asyncio
    async def test_create_requires_auth_like_every_other_tool(self, http_app, monkeypatch):
        monkeypatch.delenv("HYPERVAULT_API_KEY", raising=False)
        response = await _post(
            http_app,
            _call_tool_body(
                "create_artifact_group",
                {"files": [{"path": "index.html", "content": "<h1>hi</h1>"}]},
            ),
        )
        assert _is_tool_error(response)
        assert "Authentication required" in _tool_result_text(response)

    @pytest.mark.asyncio
    async def test_create_validation_error_never_reaches_the_backend(self, http_app, monkeypatch):
        """Missing the required root index.html must fail locally — before
        auth is even checked — never hitting the network."""
        monkeypatch.delenv("HYPERVAULT_API_KEY", raising=False)
        with respx.mock:
            route = respx.post(f"{DEFAULT_API_URL}/api/artifact-groups").mock(
                return_value=httpx.Response(200, json={"url": "should never be reached"})
            )
            response = await _post(
                http_app,
                _call_tool_body(
                    "create_artifact_group",
                    {"files": [{"path": "style.css", "content": "body{}"}]},
                ),
                headers={"X-HyperVault-Key": "hv_caller_key"},
            )
            assert _is_tool_error(response)
            assert "root 'index.html'" in _tool_result_text(response)
            assert not route.called

    @pytest.mark.asyncio
    async def test_create_success_forwards_callers_key_and_normalized_files(self, http_app, monkeypatch):
        monkeypatch.delenv("HYPERVAULT_API_KEY", raising=False)
        with respx.mock:
            route = respx.post(f"{DEFAULT_API_URL}/api/artifact-groups").mock(
                return_value=httpx.Response(
                    200, json={"url": "https://hypervault.store/g/my-app-x7k2p9", "slug": "my-app-x7k2p9"}
                )
            )
            response = await _post(
                http_app,
                _call_tool_body(
                    "create_artifact_group",
                    {
                        "files": [
                            {"path": "index.html", "content": "<h1>hi</h1>"},
                            {"path": "style.css", "content": "body{}"},
                        ],
                        "title": "My App",
                    },
                ),
                headers={"X-HyperVault-Key": "hv_caller_key"},
            )
            assert not _is_tool_error(response)
            assert route.called
            assert route.calls.last.request.headers["x-hypervault-key"] == "hv_caller_key"
            sent = json.loads(route.calls.last.request.content)
            assert sent["files"] == [
                {"path": "index.html", "content": "<h1>hi</h1>"},
                {"path": "style.css", "content": "body{}"},
            ]
            assert sent["title"] == "My App"
            assert "my-app-x7k2p9" in _tool_result_text(response)

    @pytest.mark.asyncio
    async def test_remove_index_html_rejected_before_any_network_call(self, http_app, monkeypatch):
        monkeypatch.delenv("HYPERVAULT_API_KEY", raising=False)
        with respx.mock:
            route = respx.delete(f"{DEFAULT_API_URL}/api/artifact-groups/my-app/items").mock(
                return_value=httpx.Response(200, json={"ok": True})
            )
            response = await _post(
                http_app,
                _call_tool_body(
                    "remove_artifact_group_item", {"ref": "my-app", "path": "index.html"}
                ),
                headers={"X-HyperVault-Key": "hv_caller_key"},
            )
            assert _is_tool_error(response)
            assert "Can't remove the root 'index.html'" in _tool_result_text(response)
            assert not route.called


class TestVercelEntrypoint:
    """Sanity check for api/index.py — the module Vercel actually imports."""

    def test_app_is_the_mcp_http_app(self):
        import importlib
        import sys
        from pathlib import Path

        api_dir = Path(__file__).resolve().parent.parent / "api"
        sys.path.insert(0, str(api_dir))
        try:
            index = importlib.import_module("index")
            importlib.reload(index)
        finally:
            sys.path.remove(str(api_dir))

        assert index.app is not None
        assert callable(index.app)

    @pytest.mark.asyncio
    async def test_vercel_entrypoint_rejects_unauthenticated_calls(self, monkeypatch):
        import importlib
        import sys
        from pathlib import Path

        monkeypatch.delenv("HYPERVAULT_API_KEY", raising=False)

        api_dir = Path(__file__).resolve().parent.parent / "api"
        sys.path.insert(0, str(api_dir))
        try:
            index = importlib.import_module("index")
            importlib.reload(index)
        finally:
            sys.path.remove(str(api_dir))

        response = await _post(index.app, _call_tool_body("list_my_vault_items"))
        assert _is_tool_error(response)
        assert "Authentication required" in _tool_result_text(response)
