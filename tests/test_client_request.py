"""Tests for _client()/_request() — the thin HTTP layer to the real
HyperVault backend. Network calls are mocked with respx; nothing here ever
touches a real host."""

from __future__ import annotations

import httpx
import pytest
import respx

from hypervault_mcp.server import (
    DEFAULT_API_URL,
    HyperVaultError,
    _client,
    _request,
)


@pytest.fixture
def stdio_key(monkeypatch):
    monkeypatch.setenv("HYPERVAULT_API_KEY", "hv_test_key")
    return "hv_test_key"


class TestClient:
    def test_default_base_url(self, stdio_key):
        with _client() as client:
            assert str(client.base_url) == DEFAULT_API_URL

    def test_custom_base_url_env(self, monkeypatch, stdio_key):
        monkeypatch.setenv("HYPERVAULT_API_URL", "https://staging.hypervault.store/")
        with _client() as client:
            assert str(client.base_url) == "https://staging.hypervault.store"

    def test_sends_api_key_header(self, stdio_key):
        with _client() as client:
            assert client.headers["x-hypervault-key"] == "hv_test_key"

    def test_raises_without_a_key(self):
        with pytest.raises(HyperVaultError, match="HYPERVAULT_API_KEY is not set"):
            _client()


class TestRequest:
    @respx.mock
    def test_success_returns_json_payload(self, stdio_key):
        route = respx.get(f"{DEFAULT_API_URL}/api/artifacts").mock(
            return_value=httpx.Response(200, json={"items": []})
        )
        result = _request("GET", "/api/artifacts")
        assert result == {"items": []}
        assert route.called

    @respx.mock
    def test_sends_method_path_json_and_params(self, stdio_key):
        route = respx.post(f"{DEFAULT_API_URL}/api/save").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        _request("POST", "/api/save", json={"title": "x"}, params={"dry_run": "1"})
        sent = route.calls.last.request
        assert sent.method == "POST"
        assert sent.url.path == "/api/save"
        assert sent.url.params["dry_run"] == "1"
        import json as _json

        assert _json.loads(sent.content) == {"title": "x"}

    @respx.mock
    def test_error_status_with_json_error_message(self, stdio_key):
        respx.get(f"{DEFAULT_API_URL}/api/artifacts").mock(
            return_value=httpx.Response(401, json={"error": "Invalid or revoked HyperVault API key."})
        )
        with pytest.raises(HyperVaultError, match="Invalid or revoked HyperVault API key."):
            _request("GET", "/api/artifacts")

    @respx.mock
    def test_error_status_without_json_body(self, stdio_key):
        respx.get(f"{DEFAULT_API_URL}/api/artifacts").mock(
            return_value=httpx.Response(500, text="internal error")
        )
        with pytest.raises(HyperVaultError, match="HyperVault returned HTTP 500"):
            _request("GET", "/api/artifacts")

    @respx.mock
    def test_error_status_with_non_dict_json_body(self, stdio_key):
        respx.get(f"{DEFAULT_API_URL}/api/artifacts").mock(
            return_value=httpx.Response(404, json=["not", "a", "dict"])
        )
        with pytest.raises(HyperVaultError):
            _request("GET", "/api/artifacts")

    @respx.mock
    def test_network_error_is_wrapped(self, stdio_key):
        respx.get(f"{DEFAULT_API_URL}/api/artifacts").mock(
            side_effect=httpx.ConnectError("connection refused")
        )
        with pytest.raises(HyperVaultError, match="Could not reach HyperVault"):
            _request("GET", "/api/artifacts")

    @respx.mock
    def test_timeout_is_wrapped(self, stdio_key):
        respx.get(f"{DEFAULT_API_URL}/api/artifacts").mock(
            side_effect=httpx.ConnectTimeout("timed out")
        )
        with pytest.raises(HyperVaultError, match="Could not reach HyperVault"):
            _request("GET", "/api/artifacts")

    def test_missing_key_raises_before_any_network_call(self):
        # No respx mock installed at all — if _request tried to make a real
        # network call here, this test would hang or hit the real network.
        with pytest.raises(HyperVaultError, match="HYPERVAULT_API_KEY is not set"):
            _request("GET", "/api/artifacts")
