"""Unit tests for the small pure-logic helpers in hypervault_mcp.server."""

from __future__ import annotations

import pytest

from hypervault_mcp.server import (
    GROUP_MAX_FILE_BYTES,
    GROUP_MAX_FILES,
    GROUP_MAX_TOTAL_BYTES,
    HyperVaultError,
    _artifact_group_slug,
    _artifact_slug,
    _find_source_prompt_meta,
    _normalize_group_files,
    _validate_group_item_content,
    _validate_group_item_path,
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


class TestArtifactGroupSlug:
    def test_bare_slug(self):
        assert _artifact_group_slug("my-app-x7k2p9") == "my-app-x7k2p9"

    def test_strips_whitespace(self):
        assert _artifact_group_slug("  my-app-x7k2p9  ") == "my-app-x7k2p9"

    def test_full_url(self):
        assert _artifact_group_slug("https://hypervault.store/g/my-app-x7k2p9") == "my-app-x7k2p9"

    def test_vanity_subdomain_url(self):
        assert _artifact_group_slug("https://nova.vault.cool/g/my-app-x7k2p9") == "my-app-x7k2p9"

    def test_url_with_query_and_fragment(self):
        assert (
            _artifact_group_slug("https://hypervault.store/g/my-app-x7k2p9?ref=share#top")
            == "my-app-x7k2p9"
        )

    def test_empty_raises(self):
        with pytest.raises(HyperVaultError):
            _artifact_group_slug("")

    def test_whitespace_only_raises(self):
        with pytest.raises(HyperVaultError):
            _artifact_group_slug("   ")

    def test_none_like_raises(self):
        with pytest.raises(HyperVaultError):
            _artifact_group_slug(None)  # type: ignore[arg-type]

    def test_bare_url_without_g_segment_raises(self):
        with pytest.raises(HyperVaultError):
            _artifact_group_slug("https://hypervault.store/vault/settings")

    def test_single_artifact_url_does_not_match(self):
        # /a/ is single artifacts, not groups — must not be silently accepted.
        with pytest.raises(HyperVaultError):
            _artifact_group_slug("https://hypervault.store/a/my-game-x7k2p9")

    def test_stray_slash_without_protocol_raises(self):
        with pytest.raises(HyperVaultError):
            _artifact_group_slug("vault/my-app-x7k2p9")


class TestValidateGroupItemPath:
    def test_index_html_at_root_is_valid(self):
        assert _validate_group_item_path("index.html") == "index.html"

    def test_nested_path_is_valid(self):
        assert _validate_group_item_path("css/style.css") == "css/style.css"

    def test_deeply_nested_path_is_valid(self):
        assert _validate_group_item_path("js/components/widget.jsx") == "js/components/widget.jsx"

    def test_all_allowed_extensions(self):
        for ext in ("html", "css", "js", "jsx"):
            assert _validate_group_item_path(f"file.{ext}") == f"file.{ext}"

    def test_non_string_raises(self):
        with pytest.raises(HyperVaultError, match="must be a string"):
            _validate_group_item_path(123)  # type: ignore[arg-type]

    def test_empty_path_raises(self):
        with pytest.raises(HyperVaultError, match="non-empty path"):
            _validate_group_item_path("")

    def test_whitespace_only_path_raises(self):
        with pytest.raises(HyperVaultError, match="non-empty path"):
            _validate_group_item_path("   ")

    def test_untrimmed_path_raises(self):
        with pytest.raises(HyperVaultError, match="leading/trailing whitespace"):
            _validate_group_item_path("  index.html")

    def test_leading_slash_raises(self):
        with pytest.raises(HyperVaultError, match="must be relative"):
            _validate_group_item_path("/index.html")

    def test_leading_backslash_raises(self):
        with pytest.raises(HyperVaultError, match="must be relative"):
            _validate_group_item_path("\\index.html")

    def test_embedded_backslash_raises(self):
        with pytest.raises(HyperVaultError, match="backslashes"):
            _validate_group_item_path("css\\style.css")

    def test_parent_traversal_raises(self):
        with pytest.raises(HyperVaultError, match="'\\.\\.'"):
            _validate_group_item_path("../index.html")

    def test_nested_parent_traversal_raises(self):
        with pytest.raises(HyperVaultError, match="'\\.\\.'"):
            _validate_group_item_path("css/../../etc/passwd.js")

    def test_double_slash_raises(self):
        with pytest.raises(HyperVaultError, match="not a valid file path"):
            _validate_group_item_path("css//style.css")

    def test_trailing_slash_raises(self):
        with pytest.raises(HyperVaultError, match="not a valid file path"):
            _validate_group_item_path("css/")

    def test_disallowed_character_raises(self):
        with pytest.raises(HyperVaultError, match="may only contain"):
            _validate_group_item_path("styles/theme file.css")

    def test_leading_dot_raises(self):
        with pytest.raises(HyperVaultError, match="may only contain"):
            _validate_group_item_path(".hidden.html")

    def test_no_extension_raises(self):
        with pytest.raises(HyperVaultError, match="no file extension"):
            _validate_group_item_path("README")

    def test_disallowed_extension_raises(self):
        with pytest.raises(HyperVaultError, match="unsupported extension"):
            _validate_group_item_path("data.json")

    def test_python_extension_raises(self):
        with pytest.raises(HyperVaultError, match="unsupported extension"):
            _validate_group_item_path("server.py")

    def test_extension_check_is_case_sensitive_match_but_evaluated_lowercase(self):
        # ".HTML" lowercases to ".html", which is allowed.
        assert _validate_group_item_path("index.HTML") == "index.HTML"


class TestValidateGroupItemContent:
    def test_returns_content(self):
        assert _validate_group_item_content("index.html", "<h1>hi</h1>") == "<h1>hi</h1>"

    def test_non_string_raises(self):
        with pytest.raises(HyperVaultError, match="must be a string"):
            _validate_group_item_content("index.html", 123)  # type: ignore[arg-type]

    def test_oversized_content_raises(self):
        big = "a" * (GROUP_MAX_FILE_BYTES + 1)
        with pytest.raises(HyperVaultError, match="per-file limit"):
            _validate_group_item_content("app.js", big)

    def test_exactly_at_limit_is_allowed(self):
        exact = "a" * GROUP_MAX_FILE_BYTES
        assert _validate_group_item_content("app.js", exact) == exact


class TestNormalizeGroupFiles:
    def test_valid_minimal_group(self):
        files = [{"path": "index.html", "content": "<h1>hi</h1>"}]
        assert _normalize_group_files(files) == files

    def test_valid_multi_file_group(self):
        files = [
            {"path": "index.html", "content": "<html></html>"},
            {"path": "style.css", "content": "body{}"},
            {"path": "app.js", "content": "console.log(1)"},
        ]
        assert _normalize_group_files(files) == files

    def test_none_raises(self):
        with pytest.raises(HyperVaultError, match="at least one file"):
            _normalize_group_files(None)

    def test_empty_list_raises(self):
        with pytest.raises(HyperVaultError, match="at least one file"):
            _normalize_group_files([])

    def test_missing_index_html_raises(self):
        files = [{"path": "style.css", "content": "body{}"}]
        with pytest.raises(HyperVaultError, match="root 'index.html'"):
            _normalize_group_files(files)

    def test_nested_index_html_does_not_satisfy_root_requirement(self):
        files = [{"path": "public/index.html", "content": "<html></html>"}]
        with pytest.raises(HyperVaultError, match="root 'index.html'"):
            _normalize_group_files(files)

    def test_item_missing_path_key_raises(self):
        files = [{"content": "<html></html>"}]
        with pytest.raises(HyperVaultError, match="'path' and 'content' keys"):
            _normalize_group_files(files)

    def test_item_missing_content_key_raises(self):
        files = [{"path": "index.html"}]
        with pytest.raises(HyperVaultError, match="'path' and 'content' keys"):
            _normalize_group_files(files)

    def test_item_not_a_dict_raises(self):
        files = ["index.html"]
        with pytest.raises(HyperVaultError, match="'path' and 'content' keys"):
            _normalize_group_files(files)

    def test_duplicate_paths_raise(self):
        files = [
            {"path": "index.html", "content": "a"},
            {"path": "index.html", "content": "b"},
        ]
        with pytest.raises(HyperVaultError, match="Duplicate item path"):
            _normalize_group_files(files)

    def test_duplicate_paths_case_insensitive_raise(self):
        files = [
            {"path": "index.html", "content": "a"},
            {"path": "Index.html", "content": "b"},
        ]
        with pytest.raises(HyperVaultError, match="Duplicate item path"):
            _normalize_group_files(files)

    def test_bad_item_path_propagates(self):
        files = [
            {"path": "index.html", "content": "a"},
            {"path": "../evil.js", "content": "b"},
        ]
        with pytest.raises(HyperVaultError, match="'\\.\\.'"):
            _normalize_group_files(files)

    def test_too_many_files_raises(self):
        files = [{"path": "index.html", "content": "a"}]
        files += [{"path": f"f{i}.js", "content": "a"} for i in range(GROUP_MAX_FILES)]
        with pytest.raises(HyperVaultError, match="Too many files"):
            _normalize_group_files(files)

    def test_max_files_exactly_is_allowed(self):
        files = [{"path": "index.html", "content": "a"}]
        files += [{"path": f"f{i}.js", "content": "a"} for i in range(GROUP_MAX_FILES - 1)]
        assert len(_normalize_group_files(files)) == GROUP_MAX_FILES

    def test_total_size_over_limit_raises(self):
        chunk = "a" * (GROUP_MAX_FILE_BYTES)
        # 5 files at the per-file cap comfortably exceeds the 1MB total cap.
        files = [
            {"path": "index.html", "content": chunk},
            {"path": "a.js", "content": chunk},
            {"path": "b.js", "content": chunk},
            {"path": "c.js", "content": chunk},
            {"path": "d.js", "content": chunk},
        ]
        assert sum(len(f["content"]) for f in files) > GROUP_MAX_TOTAL_BYTES
        with pytest.raises(HyperVaultError, match="byte limit"):
            _normalize_group_files(files)
