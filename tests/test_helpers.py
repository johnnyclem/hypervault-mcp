"""Unit tests for the small pure-logic helpers in hypervault_mcp.server."""

from __future__ import annotations

import pytest

from hypervault_mcp.server import (
    GROUP_MAX_FILE_BYTES,
    GROUP_MAX_FILES,
    GROUP_MAX_TOTAL_BYTES,
    HyperVaultError,
    _actor,
    _artifact_group_slug,
    _artifact_slug,
    _find_source_prompt_meta,
    _normalize_group_files,
    _task_id,
    _task_write_body,
    _tasklist_project,
    _validate_group_item_content,
    _validate_group_item_path,
    _validate_ref_segment,
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

    def test_bare_dot_dot_raises(self):
        # httpx normalizes '..' path segments client-side, so an unvalidated
        # ".." slug would silently redirect the request to a different
        # backend endpoint (e.g. /api/artifacts/../x -> /api/x).
        with pytest.raises(HyperVaultError):
            _artifact_slug("..")

    def test_dot_dot_extracted_from_url_raises(self):
        with pytest.raises(HyperVaultError):
            _artifact_slug("https://hypervault.store/a/..")


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

    def test_bare_dot_dot_raises(self):
        with pytest.raises(HyperVaultError):
            _artifact_group_slug("..")


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


class TestTasklistProject:
    def test_bare_project_id(self):
        assert _tasklist_project("eurorack-choir") == "eurorack-choir"

    def test_data_slug(self):
        assert _tasklist_project("tasks-eurorack-choir") == "tasks-eurorack-choir"

    def test_strips_whitespace(self):
        assert _tasklist_project("  eurorack-choir  ") == "eurorack-choir"

    def test_full_url(self):
        assert (
            _tasklist_project("https://hypervault.store/a/tasks-eurorack-choir")
            == "tasks-eurorack-choir"
        )

    def test_vanity_subdomain_url(self):
        assert (
            _tasklist_project("https://nova.vault.cool/a/tasks-eurorack-choir")
            == "tasks-eurorack-choir"
        )

    def test_url_with_query_and_fragment(self):
        assert (
            _tasklist_project("https://hypervault.store/a/tasks-choir?v=3#top")
            == "tasks-choir"
        )

    def test_empty_raises(self):
        with pytest.raises(HyperVaultError):
            _tasklist_project("")

    def test_whitespace_only_raises(self):
        with pytest.raises(HyperVaultError):
            _tasklist_project("   ")

    def test_none_like_raises(self):
        with pytest.raises(HyperVaultError):
            _tasklist_project(None)  # type: ignore[arg-type]

    def test_unusable_url_raises(self):
        with pytest.raises(HyperVaultError):
            _tasklist_project("https://hypervault.store/vault/tasks")

    def test_stray_slash_raises(self):
        # A path segment with a slash would silently break the request URL.
        with pytest.raises(HyperVaultError):
            _tasklist_project("tasklists/eurorack-choir")

    def test_bare_dot_dot_raises(self):
        with pytest.raises(HyperVaultError):
            _tasklist_project("..")


class TestTaskId:
    def test_trims(self):
        assert _task_id("  task-1  ") == "task-1"

    def test_empty_raises(self):
        with pytest.raises(HyperVaultError):
            _task_id("")

    def test_whitespace_only_raises(self):
        with pytest.raises(HyperVaultError):
            _task_id("   ")

    def test_none_like_raises(self):
        with pytest.raises(HyperVaultError):
            _task_id(None)  # type: ignore[arg-type]

    def test_embedded_slash_raises(self):
        with pytest.raises(HyperVaultError):
            _task_id("epic-1/../other-project")

    def test_bare_dot_dot_raises(self):
        with pytest.raises(HyperVaultError):
            _task_id("..")


class TestValidateRefSegment:
    def test_returns_plain_value(self):
        assert _validate_ref_segment("my-slug-x7k2p9", "slug") == "my-slug-x7k2p9"

    def test_rejects_embedded_slash(self):
        with pytest.raises(HyperVaultError, match="not a valid reference"):
            _validate_ref_segment("a/b", "slug")

    def test_rejects_embedded_backslash(self):
        with pytest.raises(HyperVaultError, match="not a valid reference"):
            _validate_ref_segment("a\\b", "slug")

    def test_rejects_bare_dot_dot(self):
        with pytest.raises(HyperVaultError, match="not a valid reference"):
            _validate_ref_segment("..", "slug")

    def test_rejects_bare_dot(self):
        with pytest.raises(HyperVaultError, match="not a valid reference"):
            _validate_ref_segment(".", "slug")


class TestActor:
    def test_none_when_nothing_given(self):
        assert _actor(None, None) is None

    def test_none_when_both_blank(self):
        assert _actor("  ", "") is None

    def test_name_only(self):
        assert _actor("claude-code:abc", None) == {"name": "claude-code:abc"}

    def test_name_and_type(self):
        assert _actor("claude-code:abc", "claude-code") == {
            "name": "claude-code:abc",
            "agentType": "claude-code",
        }

    def test_trims_both(self):
        assert _actor(" a ", " b ") == {"name": "a", "agentType": "b"}

    def test_type_only_still_produces_an_actor(self):
        assert _actor(None, "claude-code") == {"agentType": "claude-code"}


class TestTaskWriteBody:
    def test_omits_both_optionals(self):
        assert _task_write_body({"patch": {"progress": 1}}, None, None, None) == {
            "patch": {"progress": 1}
        }

    def test_adds_expected_version_and_actor(self):
        assert _task_write_body({"patch": {}}, 7, "a", "b") == {
            "patch": {},
            "expected_version": 7,
            "actor": {"name": "a", "agentType": "b"},
        }

    def test_expected_version_zero_is_kept(self):
        assert _task_write_body({}, 0, None, None) == {"expected_version": 0}

    def test_does_not_mutate_the_caller_payload(self):
        payload = {"patch": {"progress": 1}}
        _task_write_body(payload, 3, "a", None)
        assert payload == {"patch": {"progress": 1}}
