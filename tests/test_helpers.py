"""Unit tests for the small pure-logic helpers in hypervault_mcp.server."""

from __future__ import annotations

import pytest

from hypervault_mcp.server import (
    HyperVaultError,
    _artifact_slug,
    _find_source_prompt_meta,
)


class TestArtifactSlug:
    def test_bare_slug(self):
        assert _artifact_slug("my-game-x7k2p9") == "my-game-x7k2p9"

    def test_strips_whitespace(self):
        assert _artifact_slug("  my-game-x7k2p9  ") == "my-game-x7k2p9"

    def test_full_url(self):
        assert _artifact_slug("https://hypervault.store/a/my-game-x7k2p9") == "my-game-x7k2p9"

    def test_vanity_subdomain_url(self):
        assert _artifact_slug("https://nova.vault.cool/a/my-game-x7k2p9") == "my-game-x7k2p9"

    def test_url_with_query_and_fragment(self):
        assert (
            _artifact_slug("https://hypervault.store/a/my-game-x7k2p9?ref=share#top")
            == "my-game-x7k2p9"
        )

    def test_empty_raises(self):
        with pytest.raises(HyperVaultError):
            _artifact_slug("")

    def test_whitespace_only_raises(self):
        with pytest.raises(HyperVaultError):
            _artifact_slug("   ")

    def test_none_like_raises(self):
        with pytest.raises(HyperVaultError):
            _artifact_slug(None)  # type: ignore[arg-type]

    def test_bare_url_without_a_segment_raises(self):
        with pytest.raises(HyperVaultError):
            _artifact_slug("https://hypervault.store/vault/settings")

    def test_stray_slash_without_protocol_raises(self):
        with pytest.raises(HyperVaultError):
            _artifact_slug("vault/my-game-x7k2p9")


class TestFindSourcePromptMeta:
    def test_name_first_double_quotes(self):
        html = '<meta name="hypervault-source-prompt" content="a fun prompt">'
        assert _find_source_prompt_meta(html) == "a fun prompt"

    def test_content_first_double_quotes(self):
        html = '<meta content="a fun prompt" name="hypervault-source-prompt">'
        assert _find_source_prompt_meta(html) == "a fun prompt"

    def test_single_quotes(self):
        html = "<meta name='hypervault-source-prompt' content='a fun prompt'>"
        assert _find_source_prompt_meta(html) == "a fun prompt"

    def test_case_insensitive_tag(self):
        html = '<META NAME="hypervault-source-prompt" CONTENT="shout">'
        assert _find_source_prompt_meta(html) == "shout"

    def test_unescapes_html_entities(self):
        html = '<meta name="hypervault-source-prompt" content="Tom &amp; Jerry &lt;3">'
        assert _find_source_prompt_meta(html) == "Tom & Jerry <3"

    def test_embedded_in_full_page(self):
        html = (
            "<!doctype html><html><head><title>x</title>"
            '<meta name="hypervault-source-prompt" content="build a game">'
            "</head><body>hi</body></html>"
        )
        assert _find_source_prompt_meta(html) == "build a game"

    def test_missing_returns_none(self):
        html = "<!doctype html><html><head><title>x</title></head><body>hi</body></html>"
        assert _find_source_prompt_meta(html) is None

    def test_other_meta_tags_ignored(self):
        html = '<meta name="description" content="not the one">'
        assert _find_source_prompt_meta(html) is None
