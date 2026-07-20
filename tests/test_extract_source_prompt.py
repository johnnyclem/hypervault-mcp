"""Tests for extract_source_prompt's preferred-backend / legacy-fetch
fallback chain."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest
import respx

from hypervault_mcp import server
from hypervault_mcp.server import HyperVaultError


class TestInvalidUrl:
    def test_rejects_missing_protocol(self):
        with pytest.raises(HyperVaultError, match="Pass a full artifact URL"):
            server.extract_source_prompt("hypervault.store/a/x")

    def test_rejects_empty_string(self):
        with pytest.raises(HyperVaultError, match="Pass a full artifact URL"):
            server.extract_source_prompt("")


class TestPreferredBackendPath:
    def test_uses_backend_result_when_found_key_present(self, monkeypatch):
        fake_request = MagicMock(
            return_value={"found": True, "source_prompt": "a prompt", "url": "u", "message": "m"}
        )
        monkeypatch.setattr(server, "_request", fake_request)
        legacy_get = MagicMock()
        monkeypatch.setattr(server.httpx, "get", legacy_get)

        result = server.extract_source_prompt("https://hypervault.store/a/my-slug")

        fake_request.assert_called_once_with(
            "GET", "/api/extract", params={"url": "https://hypervault.store/a/my-slug"}
        )
        assert result["found"] is True
        legacy_get.assert_not_called()

    def test_falls_back_when_backend_response_lacks_found_key(self, monkeypatch):
        fake_request = MagicMock(return_value={"unexpected": "shape"})
        monkeypatch.setattr(server, "_request", fake_request)
        monkeypatch.setattr(
            server.httpx,
            "get",
            lambda *a, **k: httpx.Response(200, text="<html></html>", request=httpx.Request("GET", "https://x")),
        )

        result = server.extract_source_prompt("https://hypervault.store/a/my-slug")
        assert result["found"] is False

    def test_falls_back_when_backend_raises(self, monkeypatch):
        def _raise(*a, **k):
            raise HyperVaultError("backend down")

        monkeypatch.setattr(server, "_request", _raise)
        monkeypatch.setattr(
            server.httpx,
            "get",
            lambda *a, **k: httpx.Response(
                200,
                text='<meta name="hypervault-source-prompt" content="legacy prompt">',
                request=httpx.Request("GET", "https://x"),
            ),
        )

        result = server.extract_source_prompt("https://hypervault.store/a/my-slug")
        assert result["found"] is True
        assert result["source_prompt"] == "legacy prompt"


class TestLegacyFetchPath:
    def _no_backend(self, monkeypatch):
        def _raise(*a, **k):
            raise HyperVaultError("no backend in this test")

        monkeypatch.setattr(server, "_request", _raise)

    def test_extracts_prompt_from_page(self, monkeypatch):
        self._no_backend(monkeypatch)
        monkeypatch.setattr(
            server.httpx,
            "get",
            lambda *a, **k: httpx.Response(
                200,
                text='<meta name="hypervault-source-prompt" content="legacy prompt">',
                request=httpx.Request("GET", "https://x"),
            ),
        )
        result = server.extract_source_prompt("https://hypervault.store/a/my-slug")
        assert result == {
            "found": True,
            "source_prompt": "legacy prompt",
            "url": "https://hypervault.store/a/my-slug",
            "message": "Source prompt extracted — use it to understand the original intent and build on it.",
        }

    def test_no_meta_tag_returns_not_found(self, monkeypatch):
        self._no_backend(monkeypatch)
        monkeypatch.setattr(
            server.httpx,
            "get",
            lambda *a, **k: httpx.Response(
                200, text="<html><body>no meta here</body></html>", request=httpx.Request("GET", "https://x")
            ),
        )
        result = server.extract_source_prompt("https://hypervault.store/a/my-slug")
        assert result["found"] is False
        assert result["source_prompt"] is None

    def test_fetch_error_raises_hypervault_error(self, monkeypatch):
        self._no_backend(monkeypatch)

        def _raise(*a, **k):
            raise httpx.ConnectError("boom")

        monkeypatch.setattr(server.httpx, "get", _raise)
        with pytest.raises(HyperVaultError, match="Could not fetch the artifact page"):
            server.extract_source_prompt("https://hypervault.store/a/my-slug")

    @respx.mock
    def test_legacy_fetch_never_sends_api_key_header(self, monkeypatch):
        """The legacy path fetches the public artifact page directly (not
        through _client()), so no API key should ever be attached to it."""
        self._no_backend(monkeypatch)
        route = respx.get("https://hypervault.store/a/my-slug").mock(
            return_value=httpx.Response(200, text="<html></html>")
        )
        server.extract_source_prompt("https://hypervault.store/a/my-slug")
        sent = route.calls.last.request
        assert "x-hypervault-key" not in {h.lower() for h in sent.headers.keys()}
