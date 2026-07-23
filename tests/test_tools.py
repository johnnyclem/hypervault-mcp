"""Tests for each @mcp.tool function's request-shaping logic.

_request() itself is mocked here (it's covered separately in
test_client_request.py) so these tests focus purely on: does each tool build
the right HTTP method/path/payload, apply the right defaults, and validate
its inputs before making a call.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from hypervault_mcp import server
from hypervault_mcp.server import HyperVaultError


@pytest.fixture
def fake_request(monkeypatch):
    mock = MagicMock(return_value={"ok": True})
    monkeypatch.setattr(server, "_request", mock)
    return mock


class TestSaveToHypervault:
    def test_minimal_call_defaults(self, fake_request):
        result = server.save_to_hypervault(content="<h1>hi</h1>")
        assert result == {"ok": True}
        fake_request.assert_called_once_with(
            "POST",
            "/api/save",
            json={
                "content": "<h1>hi</h1>",
                "title": "Untitled",
                "type": "html",
                "tags": [],
                "connect_to": [],
                "make_pwa": True,
                "source_prompt": None,
                "visibility": "private",
                "mutable": False,
            },
        )

    def test_full_call_passes_through_all_fields(self, fake_request):
        server.save_to_hypervault(
            content="<h1>hi</h1>",
            title="My Page",
            type="jsx",
            tags=["a", "b"],
            connect_to=["other-slug"],
            make_pwa=False,
            source_prompt="build a page",
            visibility="public",
            mutable=True,
        )
        _, _, kwargs = fake_request.mock_calls[0]
        assert kwargs["json"] == {
            "content": "<h1>hi</h1>",
            "title": "My Page",
            "type": "jsx",
            "tags": ["a", "b"],
            "connect_to": ["other-slug"],
            "make_pwa": False,
            "source_prompt": "build a page",
            "visibility": "public",
            "mutable": True,
        }


class TestReadArtifact:
    def test_without_version(self, fake_request):
        server.read_artifact("my-slug")
        fake_request.assert_called_once_with(
            "GET", "/api/artifacts/my-slug/content", params=None
        )

    def test_with_version(self, fake_request):
        server.read_artifact("my-slug", version="v123")
        fake_request.assert_called_once_with(
            "GET", "/api/artifacts/my-slug/content", params={"version": "v123"}
        )

    def test_resolves_ref_from_url(self, fake_request):
        server.read_artifact("https://hypervault.store/a/my-slug")
        fake_request.assert_called_once_with(
            "GET", "/api/artifacts/my-slug/content", params=None
        )

    def test_blank_version_treated_as_absent(self, fake_request):
        server.read_artifact("my-slug", version="   ")
        fake_request.assert_called_once_with(
            "GET", "/api/artifacts/my-slug/content", params=None
        )


class TestWriteArtifact:
    def test_writes_new_content(self, fake_request):
        server.write_artifact("my-slug", "<h1>v2</h1>", title="New", message="edit")
        fake_request.assert_called_once_with(
            "PUT",
            "/api/artifacts/my-slug/content",
            json={
                "content": "<h1>v2</h1>",
                "title": "New",
                "message": "edit",
                "force_html": False,
            },
        )

    def test_empty_content_raises_without_calling_request(self, fake_request):
        with pytest.raises(HyperVaultError, match="Pass the new content"):
            server.write_artifact("my-slug", "")
        fake_request.assert_not_called()

    def test_whitespace_only_content_raises(self, fake_request):
        with pytest.raises(HyperVaultError, match="Pass the new content"):
            server.write_artifact("my-slug", "   ")
        fake_request.assert_not_called()


class TestArtifactHistory:
    def test_default_params(self, fake_request):
        server.artifact_history("my-slug")
        fake_request.assert_called_once_with(
            "GET", "/api/artifacts/my-slug/versions", params={"limit": 50}
        )

    def test_full_true_adds_flag(self, fake_request):
        server.artifact_history("my-slug", full=True, limit=10)
        fake_request.assert_called_once_with(
            "GET", "/api/artifacts/my-slug/versions", params={"limit": 10, "full": "1"}
        )


class TestClaimVanitySubdomain:
    def test_defaults(self, fake_request):
        server.claim_vanity_subdomain("nova")
        fake_request.assert_called_once_with(
            "POST",
            "/api/claim-domain",
            json={"desired_name": "nova", "base_domain": "vault.cool"},
        )

    def test_custom_base_domain(self, fake_request):
        server.claim_vanity_subdomain("nova", base_domain="example.com")
        fake_request.assert_called_once_with(
            "POST",
            "/api/claim-domain",
            json={"desired_name": "nova", "base_domain": "example.com"},
        )


class TestConnectVaultItems:
    def test_connects_two_items(self, fake_request):
        server.connect_vault_items("slug-a", "slug-b")
        fake_request.assert_called_once_with(
            "POST", "/api/connections", json={"source": "slug-a", "target": "slug-b"}
        )


class TestListMyVaultItems:
    def test_no_params(self, fake_request):
        server.list_my_vault_items()
        fake_request.assert_called_once_with("GET", "/api/artifacts")


class TestDeleteVaultItem:
    def test_deletes_by_slug(self, fake_request):
        server.delete_vault_item("my-game-x7k2p9")
        fake_request.assert_called_once_with(
            "DELETE", "/api/artifacts", json={"slug": "my-game-x7k2p9"}
        )

    def test_deletes_by_uuid(self, fake_request):
        uuid = "550e8400-e29b-41d4-a716-446655440000"
        server.delete_vault_item(uuid)
        fake_request.assert_called_once_with("DELETE", "/api/artifacts", json={"id": uuid})

    def test_uuid_is_case_insensitive(self, fake_request):
        uuid = "550E8400-E29B-41D4-A716-446655440000"
        server.delete_vault_item(uuid)
        fake_request.assert_called_once_with("DELETE", "/api/artifacts", json={"id": uuid})

    def test_blank_ref_raises_without_calling_request(self, fake_request):
        with pytest.raises(HyperVaultError, match="Pass the artifact's slug or id"):
            server.delete_vault_item("   ")
        fake_request.assert_not_called()

    def test_strips_whitespace(self, fake_request):
        server.delete_vault_item("  my-game  ")
        fake_request.assert_called_once_with(
            "DELETE", "/api/artifacts", json={"slug": "my-game"}
        )


class TestCreateArtifactGroup:
    def test_minimal_call_defaults(self, fake_request):
        files = [{"path": "index.html", "content": "<h1>hi</h1>"}]
        result = server.create_artifact_group(files=files)
        assert result == {"ok": True}
        fake_request.assert_called_once_with(
            "POST",
            "/api/artifact-groups",
            json={
                "files": files,
                "title": "Untitled",
                "tags": [],
                "connect_to": [],
                "visibility": "private",
                "source_prompt": None,
            },
        )

    def test_full_call_passes_through_all_fields(self, fake_request):
        files = [
            {"path": "index.html", "content": "<html></html>"},
            {"path": "style.css", "content": "body{}"},
            {"path": "app.js", "content": "console.log(1)"},
        ]
        server.create_artifact_group(
            files=files,
            title="My Game",
            tags=["a", "b"],
            connect_to=["other-slug"],
            visibility="public",
            source_prompt="build a game",
        )
        _, _, kwargs = fake_request.mock_calls[0]
        assert kwargs["json"] == {
            "files": files,
            "title": "My Game",
            "tags": ["a", "b"],
            "connect_to": ["other-slug"],
            "visibility": "public",
            "source_prompt": "build a game",
        }

    def test_missing_index_html_raises_without_calling_request(self, fake_request):
        files = [{"path": "style.css", "content": "body{}"}]
        with pytest.raises(HyperVaultError, match="root 'index.html'"):
            server.create_artifact_group(files=files)
        fake_request.assert_not_called()

    def test_empty_files_raises_without_calling_request(self, fake_request):
        with pytest.raises(HyperVaultError, match="at least one file"):
            server.create_artifact_group(files=[])
        fake_request.assert_not_called()

    def test_path_traversal_raises_without_calling_request(self, fake_request):
        files = [
            {"path": "index.html", "content": "hi"},
            {"path": "../evil.js", "content": "bad"},
        ]
        with pytest.raises(HyperVaultError, match="'\\.\\.'"):
            server.create_artifact_group(files=files)
        fake_request.assert_not_called()

    def test_disallowed_extension_raises_without_calling_request(self, fake_request):
        files = [
            {"path": "index.html", "content": "hi"},
            {"path": "server.py", "content": "print(1)"},
        ]
        with pytest.raises(HyperVaultError, match="unsupported extension"):
            server.create_artifact_group(files=files)
        fake_request.assert_not_called()

    def test_duplicate_path_raises_without_calling_request(self, fake_request):
        files = [
            {"path": "index.html", "content": "a"},
            {"path": "index.html", "content": "b"},
        ]
        with pytest.raises(HyperVaultError, match="Duplicate item path"):
            server.create_artifact_group(files=files)
        fake_request.assert_not_called()


class TestReadArtifactGroup:
    def test_by_slug(self, fake_request):
        server.read_artifact_group("my-app-x7k2p9")
        fake_request.assert_called_once_with("GET", "/api/artifact-groups/my-app-x7k2p9")

    def test_resolves_ref_from_url(self, fake_request):
        server.read_artifact_group("https://hypervault.store/g/my-app-x7k2p9")
        fake_request.assert_called_once_with("GET", "/api/artifact-groups/my-app-x7k2p9")

    def test_blank_ref_raises_without_calling_request(self, fake_request):
        with pytest.raises(HyperVaultError, match="Pass the artifact group's slug or URL"):
            server.read_artifact_group("   ")
        fake_request.assert_not_called()


class TestListArtifactGroups:
    def test_no_params(self, fake_request):
        server.list_artifact_groups()
        fake_request.assert_called_once_with("GET", "/api/artifact-groups")


class TestAddArtifactGroupItem:
    def test_adds_item(self, fake_request):
        server.add_artifact_group_item("my-app-x7k2p9", "style.css", "body{}")
        fake_request.assert_called_once_with(
            "POST",
            "/api/artifact-groups/my-app-x7k2p9/items",
            json={"path": "style.css", "content": "body{}"},
        )

    def test_resolves_ref_from_url(self, fake_request):
        server.add_artifact_group_item(
            "https://hypervault.store/g/my-app-x7k2p9", "style.css", "body{}"
        )
        fake_request.assert_called_once_with(
            "POST",
            "/api/artifact-groups/my-app-x7k2p9/items",
            json={"path": "style.css", "content": "body{}"},
        )

    def test_bad_path_raises_without_calling_request(self, fake_request):
        with pytest.raises(HyperVaultError, match="'\\.\\.'"):
            server.add_artifact_group_item("my-app-x7k2p9", "../evil.js", "bad")
        fake_request.assert_not_called()

    def test_disallowed_extension_raises_without_calling_request(self, fake_request):
        with pytest.raises(HyperVaultError, match="unsupported extension"):
            server.add_artifact_group_item("my-app-x7k2p9", "data.json", "{}")
        fake_request.assert_not_called()

    def test_oversized_content_raises_without_calling_request(self, fake_request):
        from hypervault_mcp.server import GROUP_MAX_FILE_BYTES

        with pytest.raises(HyperVaultError, match="per-file limit"):
            server.add_artifact_group_item("my-app-x7k2p9", "app.js", "a" * (GROUP_MAX_FILE_BYTES + 1))
        fake_request.assert_not_called()


class TestEditArtifactGroupItem:
    def test_edits_item(self, fake_request):
        server.edit_artifact_group_item("my-app-x7k2p9", "index.html", "<h1>v2</h1>")
        fake_request.assert_called_once_with(
            "PUT",
            "/api/artifact-groups/my-app-x7k2p9/items",
            json={"path": "index.html", "content": "<h1>v2</h1>"},
        )

    def test_resolves_ref_from_url(self, fake_request):
        server.edit_artifact_group_item(
            "https://hypervault.store/g/my-app-x7k2p9", "index.html", "<h1>v2</h1>"
        )
        fake_request.assert_called_once_with(
            "PUT",
            "/api/artifact-groups/my-app-x7k2p9/items",
            json={"path": "index.html", "content": "<h1>v2</h1>"},
        )

    def test_bad_path_raises_without_calling_request(self, fake_request):
        with pytest.raises(HyperVaultError, match="must be relative"):
            server.edit_artifact_group_item("my-app-x7k2p9", "/index.html", "hi")
        fake_request.assert_not_called()


class TestRemoveArtifactGroupItem:
    def test_removes_item(self, fake_request):
        server.remove_artifact_group_item("my-app-x7k2p9", "style.css")
        fake_request.assert_called_once_with(
            "DELETE",
            "/api/artifact-groups/my-app-x7k2p9/items",
            json={"path": "style.css"},
        )

    def test_resolves_ref_from_url(self, fake_request):
        server.remove_artifact_group_item("https://hypervault.store/g/my-app-x7k2p9", "style.css")
        fake_request.assert_called_once_with(
            "DELETE",
            "/api/artifact-groups/my-app-x7k2p9/items",
            json={"path": "style.css"},
        )

    def test_removing_index_html_raises_without_calling_request(self, fake_request):
        with pytest.raises(HyperVaultError, match="Can't remove the root 'index.html'"):
            server.remove_artifact_group_item("my-app-x7k2p9", "index.html")
        fake_request.assert_not_called()

    def test_bad_path_raises_without_calling_request(self, fake_request):
        with pytest.raises(HyperVaultError, match="'\\.\\.'"):
            server.remove_artifact_group_item("my-app-x7k2p9", "../evil.js")
        fake_request.assert_not_called()


class TestDeleteArtifactGroup:
    def test_deletes_by_slug(self, fake_request):
        server.delete_artifact_group("my-app-x7k2p9")
        fake_request.assert_called_once_with(
            "DELETE", "/api/artifact-groups", json={"slug": "my-app-x7k2p9"}
        )

    def test_deletes_by_uuid(self, fake_request):
        uuid = "550e8400-e29b-41d4-a716-446655440000"
        server.delete_artifact_group(uuid)
        fake_request.assert_called_once_with("DELETE", "/api/artifact-groups", json={"id": uuid})

    def test_uuid_is_case_insensitive(self, fake_request):
        uuid = "550E8400-E29B-41D4-A716-446655440000"
        server.delete_artifact_group(uuid)
        fake_request.assert_called_once_with("DELETE", "/api/artifact-groups", json={"id": uuid})

    def test_blank_ref_raises_without_calling_request(self, fake_request):
        with pytest.raises(HyperVaultError, match="Pass the artifact group's slug or id"):
            server.delete_artifact_group("   ")
        fake_request.assert_not_called()

    def test_strips_whitespace(self, fake_request):
        server.delete_artifact_group("  my-app  ")
        fake_request.assert_called_once_with(
            "DELETE", "/api/artifact-groups", json={"slug": "my-app"}
        )


class TestMemorize:
    def test_defaults(self, fake_request):
        server.memorize("some content")
        fake_request.assert_called_once_with(
            "POST",
            "/api/memories",
            json={
                "content": "some content",
                "title": None,
                "tags": [],
                "source": "agent",
                "branch": None,
                "message": None,
            },
        )

    def test_full_fields(self, fake_request):
        server.memorize(
            "some content",
            title="My memory",
            tags=["x"],
            source="chat",
            branch="ideas",
            message="init",
        )
        fake_request.assert_called_once_with(
            "POST",
            "/api/memories",
            json={
                "content": "some content",
                "title": "My memory",
                "tags": ["x"],
                "source": "chat",
                "branch": "ideas",
                "message": "init",
            },
        )


class TestRecall:
    def test_query_only(self, fake_request):
        server.recall("rust borrow checker")
        fake_request.assert_called_once_with(
            "GET", "/api/memories", params={"q": "rust borrow checker"}
        )

    def test_with_branch(self, fake_request):
        server.recall("rust borrow checker", branch="ideas")
        fake_request.assert_called_once_with(
            "GET",
            "/api/memories",
            params={"q": "rust borrow checker", "branch": "ideas"},
        )

    def test_blank_query_raises_without_calling_request(self, fake_request):
        with pytest.raises(HyperVaultError, match="Pass a non-empty query"):
            server.recall("   ")
        fake_request.assert_not_called()


class TestListMemories:
    def test_no_branch(self, fake_request):
        server.list_memories()
        fake_request.assert_called_once_with("GET", "/api/memories", params=None)

    def test_with_branch(self, fake_request):
        server.list_memories(branch="ideas")
        fake_request.assert_called_once_with(
            "GET", "/api/memories", params={"branch": "ideas"}
        )


class TestForgetMemory:
    def test_default_branch(self, fake_request):
        server.forget_memory("mem-1")
        fake_request.assert_called_once_with(
            "DELETE", "/api/memories/mem-1", params=None
        )

    def test_with_branch(self, fake_request):
        server.forget_memory("mem-1", branch="ideas")
        fake_request.assert_called_once_with(
            "DELETE", "/api/memories/mem-1", params={"branch": "ideas"}
        )

    def test_blank_id_raises(self, fake_request):
        with pytest.raises(HyperVaultError, match="Pass the memory id to forget"):
            server.forget_memory("   ")
        fake_request.assert_not_called()


class TestEditMemory:
    def test_edits_fields(self, fake_request):
        server.edit_memory("mem-1", content="new", title="t", tags=["a"], message="m", branch="b")
        fake_request.assert_called_once_with(
            "PATCH",
            "/api/memories/mem-1",
            json={"content": "new", "title": "t", "tags": ["a"], "message": "m", "branch": "b"},
        )

    def test_blank_id_raises(self, fake_request):
        with pytest.raises(HyperVaultError, match="Pass the memory id to edit"):
            server.edit_memory("   ")
        fake_request.assert_not_called()


class TestMemoryHistory:
    def test_default_params(self, fake_request):
        server.memory_history("mem-1")
        fake_request.assert_called_once_with(
            "GET", "/api/memories/mem-1/history", params={"limit": 50}
        )

    def test_full_true(self, fake_request):
        server.memory_history("mem-1", full=True, limit=5)
        fake_request.assert_called_once_with(
            "GET", "/api/memories/mem-1/history", params={"limit": 5, "full": "1"}
        )

    def test_blank_id_raises(self, fake_request):
        with pytest.raises(HyperVaultError, match="Pass the memory id whose history"):
            server.memory_history("   ")
        fake_request.assert_not_called()


class TestMindLog:
    def test_default(self, fake_request):
        server.mind_log()
        fake_request.assert_called_once_with(
            "GET", "/api/mind/commits", params={"limit": 50}
        )

    def test_with_branch(self, fake_request):
        server.mind_log(branch="ideas", limit=10)
        fake_request.assert_called_once_with(
            "GET", "/api/mind/commits", params={"limit": 10, "branch": "ideas"}
        )


class TestMindBranches:
    def test_lists_branches(self, fake_request):
        server.mind_branches()
        fake_request.assert_called_once_with("GET", "/api/mind/branches")


class TestMindBranch:
    def test_creates_branch(self, fake_request):
        server.mind_branch("ideas", from_ref="main")
        fake_request.assert_called_once_with(
            "POST", "/api/mind/branches", json={"name": "ideas", "from": "main"}
        )

    def test_blank_name_raises(self, fake_request):
        with pytest.raises(HyperVaultError, match="Pass a branch name"):
            server.mind_branch("   ")
        fake_request.assert_not_called()


class TestMindDiff:
    def test_graph_diff(self, fake_request):
        server.mind_diff("main", "ideas")
        fake_request.assert_called_once_with(
            "GET", "/api/mind/diff", params={"from": "main", "to": "ideas"}
        )

    def test_single_memory_diff(self, fake_request):
        server.mind_diff("main", "ideas", memory_id="mem-1")
        fake_request.assert_called_once_with(
            "GET",
            "/api/mind/diff",
            params={"from": "main", "to": "ideas", "memory_id": "mem-1"},
        )


class TestMindMerge:
    def test_defaults(self, fake_request):
        server.mind_merge("ideas")
        fake_request.assert_called_once_with(
            "POST",
            "/api/mind/merge",
            json={"source": "ideas", "target": "main", "message": None, "resolutions": None},
        )

    def test_with_resolutions(self, fake_request):
        resolutions = [{"memory_id": "mem-1", "resolution": "theirs"}]
        server.mind_merge("ideas", target="main", message="merge it", resolutions=resolutions)
        fake_request.assert_called_once_with(
            "POST",
            "/api/mind/merge",
            json={
                "source": "ideas",
                "target": "main",
                "message": "merge it",
                "resolutions": resolutions,
            },
        )


class TestMindRevert:
    def test_reverts(self, fake_request):
        server.mind_revert("mem-1", "rev-1", branch="ideas")
        fake_request.assert_called_once_with(
            "POST",
            "/api/mind/revert",
            json={"memory_id": "mem-1", "revision_id": "rev-1", "branch": "ideas"},
        )


class TestMindState:
    def test_at_only(self, fake_request):
        server.mind_state("2026-06-01T00:00:00Z")
        fake_request.assert_called_once_with(
            "GET", "/api/mind/state", params={"at": "2026-06-01T00:00:00Z"}
        )

    def test_with_branch(self, fake_request):
        server.mind_state("2026-06-01T00:00:00Z", branch="ideas")
        fake_request.assert_called_once_with(
            "GET",
            "/api/mind/state",
            params={"at": "2026-06-01T00:00:00Z", "branch": "ideas"},
        )
