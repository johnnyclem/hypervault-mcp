"""Tests for extract_source_prompt's preferred-backend / legacy-fetch
fallback chain."""

from __future__ import annotations

import socket
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
        legacy_fetch = MagicMock()
        monkeypatch.setattr(server, "_fetch_legacy_artifact_page", legacy_fetch)

        result = server.extract_source_prompt("https://hypervault.store/a/my-slug")

        fake_request.assert_called_once_with(
            "GET", "/api/extract", params={"url": "https://hypervault.store/a/my-slug"}
        )
        assert result["found"] is True
        legacy_fetch.assert_not_called()

    def test_falls_back_when_backend_response_lacks_found_key(self, monkeypatch):
        fake_request = MagicMock(return_value={"unexpected": "shape"})
        monkeypatch.setattr(server, "_request", fake_request)
        monkeypatch.setattr(
            server,
            "_fetch_legacy_artifact_page",
            lambda url: httpx.Response(200, text="<html></html>", request=httpx.Request("GET", url)),
        )

        result = server.extract_source_prompt("https://hypervault.store/a/my-slug")
        assert result["found"] is False

    def test_falls_back_when_backend_raises(self, monkeypatch):
        def _raise(*a, **k):
            raise HyperVaultError("backend down")

        monkeypatch.setattr(server, "_request", _raise)
        monkeypatch.setattr(
            server,
            "_fetch_legacy_artifact_page",
            lambda url: httpx.Response(
                200,
                text='<meta name="hypervault-source-prompt" content="legacy prompt">',
                request=httpx.Request("GET", url),
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
            server,
            "_fetch_legacy_artifact_page",
            lambda url: httpx.Response(
                200,
                text='<meta name="hypervault-source-prompt" content="legacy prompt">',
                request=httpx.Request("GET", url),
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
            server,
            "_fetch_legacy_artifact_page",
            lambda url: httpx.Response(
                200, text="<html><body>no meta here</body></html>", request=httpx.Request("GET", url)
            ),
        )
        result = server.extract_source_prompt("https://hypervault.store/a/my-slug")
        assert result["found"] is False
        assert result["source_prompt"] is None

    def test_fetch_error_raises_hypervault_error(self, monkeypatch):
        self._no_backend(monkeypatch)

        def _raise(url):
            raise httpx.ConnectError("boom")

        monkeypatch.setattr(server, "_fetch_legacy_artifact_page", _raise)
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


class TestAssertPublicHost:
    """The legacy fetch path takes an arbitrary caller-supplied URL, so
    _assert_public_host guards it (and every redirect hop) against
    loopback/private/link-local targets — including the cloud metadata
    address, a classic SSRF target."""

    def _request_for(self, url: str) -> httpx.Request:
        return httpx.Request("GET", url)

    def test_rejects_loopback(self):
        with pytest.raises(HyperVaultError, match="non-public address"):
            server._assert_public_host(self._request_for("http://127.0.0.1/secret"))

    def test_rejects_localhost_hostname(self):
        with pytest.raises(HyperVaultError, match="non-public address"):
            server._assert_public_host(self._request_for("http://localhost/secret"))

    def test_rejects_private_range(self):
        with pytest.raises(HyperVaultError, match="non-public address"):
            server._assert_public_host(self._request_for("http://10.0.0.5/secret"))

    def test_rejects_link_local_cloud_metadata_address(self):
        with pytest.raises(HyperVaultError, match="non-public address"):
            server._assert_public_host(self._request_for("http://169.254.169.254/latest/meta-data/"))

    def test_allows_public_ip(self):
        server._assert_public_host(self._request_for("http://93.184.216.34/page"))  # no raise

    def test_unresolvable_host_raises(self, monkeypatch):
        def _raise(*a, **k):
            raise socket.gaierror("Name or service not known")

        monkeypatch.setattr(server.socket, "getaddrinfo", _raise)
        with pytest.raises(HyperVaultError, match="Could not resolve host"):
            server._assert_public_host(self._request_for("http://does-not-exist.invalid/x"))


class TestExtractSourcePromptRefusesPrivateHosts:
    """End-to-end: a private-host URL must never reach the network, even
    when the backend /api/extract call fails and the legacy path runs."""

    def test_legacy_path_refuses_loopback_target(self, monkeypatch):
        def _raise(*a, **k):
            raise HyperVaultError("backend down")

        monkeypatch.setattr(server, "_request", _raise)
        with pytest.raises(HyperVaultError, match="non-public address"):
            server.extract_source_prompt("http://127.0.0.1:8080/a/my-slug")


class TestAssertPublicHostBlocksRedirects:
    """A URL can resolve publicly on the first request and still 302 to an
    internal address — this is the actual SSRF shape the fetch needs to
    resist, not just a bad initial host. _fetch_legacy_artifact_page uses
    _assert_public_host as an httpx request event hook specifically so it
    re-runs on every redirect hop, not just the first request."""

    @respx.mock
    def test_redirect_to_private_host_is_blocked(self, monkeypatch):
        def fake_getaddrinfo(host, *args, **kwargs):
            addr = {"evil.example.com": "93.184.216.34", "internal.example.com": "127.0.0.1"}[host]
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, 0))]

        monkeypatch.setattr(server.socket, "getaddrinfo", fake_getaddrinfo)

        respx.get("https://evil.example.com/redirect").mock(
            return_value=httpx.Response(
                302, headers={"Location": "http://internal.example.com:8080/internal"}
            )
        )
        internal_route = respx.get("http://internal.example.com:8080/internal").mock(
            return_value=httpx.Response(200, text="should never be reached")
        )

        with pytest.raises(HyperVaultError, match="non-public address"):
            server._fetch_legacy_artifact_page("https://evil.example.com/redirect")
        assert not internal_route.called
