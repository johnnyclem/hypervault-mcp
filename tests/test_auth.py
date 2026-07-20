"""Tests for per-request authentication.

These guard the specific vulnerability that shipped in the first Vercel
deployment: an HTTP caller who sent no key of their own was silently served
using the operator's HYPERVAULT_API_KEY environment variable, so any
anonymous request against the hosted server read/wrote *the operator's own*
vault. Every test in the "HTTP mode" section below asserts the opposite: no
caller-supplied key means no access, full stop, regardless of what is set in
the process environment.
"""

from __future__ import annotations

import pytest

from hypervault_mcp import server
from hypervault_mcp.server import (
    API_KEY_HEADER,
    HyperVaultError,
    _extract_bearer_key,
    _in_http_request_context,
    _resolve_api_key,
)


class TestExtractBearerKey:
    def test_x_hypervault_key_header(self):
        assert _extract_bearer_key({"x-hypervault-key": "hv_abc123"}) == "hv_abc123"

    def test_authorization_bearer_header(self):
        assert _extract_bearer_key({"authorization": "Bearer hv_abc123"}) == "hv_abc123"

    def test_authorization_bearer_case_insensitive_scheme(self):
        assert _extract_bearer_key({"authorization": "bearer hv_abc123"}) == "hv_abc123"

    def test_x_hypervault_key_takes_precedence(self):
        headers = {"x-hypervault-key": "hv_direct", "authorization": "Bearer hv_bearer"}
        assert _extract_bearer_key(headers) == "hv_direct"

    def test_no_headers_returns_none(self):
        assert _extract_bearer_key({}) is None

    def test_blank_x_hypervault_key_falls_through_to_bearer(self):
        headers = {"x-hypervault-key": "   ", "authorization": "Bearer hv_bearer"}
        assert _extract_bearer_key(headers) == "hv_bearer"

    def test_authorization_without_bearer_scheme_ignored(self):
        assert _extract_bearer_key({"authorization": "Basic dXNlcjpwYXNz"}) is None

    def test_bearer_with_empty_token_returns_none(self):
        assert _extract_bearer_key({"authorization": "Bearer "}) is None

    def test_header_name_matches_module_constant(self):
        # Sanity check that the header we parse is the same one _client() sends.
        assert API_KEY_HEADER.lower() == "x-hypervault-key"


class TestInHttpRequestContext:
    def test_false_outside_a_request(self):
        assert _in_http_request_context() is False

    def test_true_when_request_available(self, monkeypatch):
        monkeypatch.setattr(server, "get_http_request", lambda: object())
        assert _in_http_request_context() is True

    def test_false_when_get_http_request_raises(self, monkeypatch):
        def _raise():
            raise RuntimeError("No active HTTP request found.")

        monkeypatch.setattr(server, "get_http_request", _raise)
        assert _in_http_request_context() is False


class TestResolveApiKeyStdio:
    """STDIO mode: single local trusted user via HYPERVAULT_API_KEY."""

    def test_uses_env_var(self, monkeypatch):
        monkeypatch.setattr(server, "_in_http_request_context", lambda: False)
        monkeypatch.setenv("HYPERVAULT_API_KEY", "hv_local_dev_key")
        assert _resolve_api_key() == "hv_local_dev_key"

    def test_missing_env_var_raises(self, monkeypatch):
        monkeypatch.setattr(server, "_in_http_request_context", lambda: False)
        with pytest.raises(HyperVaultError, match="HYPERVAULT_API_KEY is not set"):
            _resolve_api_key()

    def test_blank_env_var_raises(self, monkeypatch):
        monkeypatch.setattr(server, "_in_http_request_context", lambda: False)
        monkeypatch.setenv("HYPERVAULT_API_KEY", "   ")
        with pytest.raises(HyperVaultError, match="HYPERVAULT_API_KEY is not set"):
            _resolve_api_key()

    def test_env_var_is_stripped(self, monkeypatch):
        monkeypatch.setattr(server, "_in_http_request_context", lambda: False)
        monkeypatch.setenv("HYPERVAULT_API_KEY", "  hv_local_dev_key  ")
        assert _resolve_api_key() == "hv_local_dev_key"


class TestResolveApiKeyHttp:
    """HTTP mode: every caller must supply their own key. No fallback."""

    def test_uses_callers_header_key(self, monkeypatch):
        monkeypatch.setattr(server, "_in_http_request_context", lambda: True)
        monkeypatch.setattr(server, "get_http_headers", lambda include_all=False: {
            "x-hypervault-key": "hv_caller_key"
        })
        assert _resolve_api_key() == "hv_caller_key"

    def test_uses_callers_bearer_key(self, monkeypatch):
        monkeypatch.setattr(server, "_in_http_request_context", lambda: True)
        monkeypatch.setattr(server, "get_http_headers", lambda include_all=False: {
            "authorization": "Bearer hv_caller_key"
        })
        assert _resolve_api_key() == "hv_caller_key"

    def test_missing_header_raises_even_with_env_var_set(self, monkeypatch):
        """Regression test for the exact bug: an operator env var must never
        answer for a caller who sent no key of their own."""
        monkeypatch.setattr(server, "_in_http_request_context", lambda: True)
        monkeypatch.setattr(server, "get_http_headers", lambda include_all=False: {})
        monkeypatch.setenv("HYPERVAULT_API_KEY", "hv_operators_own_secret_key")

        with pytest.raises(HyperVaultError, match="Authentication required"):
            _resolve_api_key()

    def test_never_returns_the_operator_env_key_over_http(self, monkeypatch):
        monkeypatch.setattr(server, "_in_http_request_context", lambda: True)
        monkeypatch.setattr(server, "get_http_headers", lambda include_all=False: {
            "x-hypervault-key": "hv_caller_key"
        })
        monkeypatch.setenv("HYPERVAULT_API_KEY", "hv_operators_own_secret_key")

        resolved = _resolve_api_key()

        assert resolved == "hv_caller_key"
        assert resolved != "hv_operators_own_secret_key"

    def test_blank_header_value_raises(self, monkeypatch):
        monkeypatch.setattr(server, "_in_http_request_context", lambda: True)
        monkeypatch.setattr(server, "get_http_headers", lambda include_all=False: {
            "x-hypervault-key": "   "
        })
        with pytest.raises(HyperVaultError, match="Authentication required"):
            _resolve_api_key()

    def test_two_callers_get_isolated_keys(self, monkeypatch):
        """Sequential calls in HTTP mode must never leak one caller's key
        into another caller's request."""
        monkeypatch.setattr(server, "_in_http_request_context", lambda: True)

        monkeypatch.setattr(server, "get_http_headers", lambda include_all=False: {
            "x-hypervault-key": "hv_caller_one"
        })
        assert _resolve_api_key() == "hv_caller_one"

        monkeypatch.setattr(server, "get_http_headers", lambda include_all=False: {
            "x-hypervault-key": "hv_caller_two"
        })
        assert _resolve_api_key() == "hv_caller_two"
