"""Tests for the hypervault://help resource and the CLI entrypoint."""

from __future__ import annotations

from unittest.mock import MagicMock

from hypervault_mcp import server


class TestVaultHelpResource:
    def test_mentions_every_tool(self):
        text = server.get_vault_help()
        for tool_name in [
            "save_to_hypervault",
            "claim_vanity_subdomain",
            "list_my_vault_items",
            "connect_vault_items",
            "extract_source_prompt",
            "delete_vault_item",
            "memorize",
            "recall",
            "list_memories",
            "forget_memory",
            "edit_memory",
            "memory_history",
            "mind_log",
            "mind_branches",
            "mind_branch",
            "mind_diff",
            "mind_merge",
            "mind_revert",
            "mind_state",
            "read_artifact",
            "write_artifact",
            "artifact_history",
            "create_artifact_group",
            "read_artifact_group",
            "list_artifact_groups",
            "add_artifact_group_item",
            "edit_artifact_group_item",
            "remove_artifact_group_item",
            "delete_artifact_group",
        ]:
            assert tool_name in text, f"{tool_name} missing from help text"

    def test_returns_a_string(self):
        assert isinstance(server.get_vault_help(), str)
        assert len(server.get_vault_help()) > 100


class TestMainCli:
    def test_defaults_to_stdio(self, monkeypatch):
        run_mock = MagicMock()
        monkeypatch.setattr(server.mcp, "run", run_mock)
        monkeypatch.setattr("sys.argv", ["hypervault-mcp"])
        server.main()
        run_mock.assert_called_once_with()

    def test_http_transport_wires_host_and_port(self, monkeypatch):
        run_mock = MagicMock()
        monkeypatch.setattr(server.mcp, "run", run_mock)
        monkeypatch.setattr(
            "sys.argv",
            ["hypervault-mcp", "--transport", "http", "--host", "0.0.0.0", "--port", "9999"],
        )
        server.main()
        run_mock.assert_called_once_with(transport="http", host="0.0.0.0", port=9999)

    def test_http_transport_default_host_and_port(self, monkeypatch):
        run_mock = MagicMock()
        monkeypatch.setattr(server.mcp, "run", run_mock)
        monkeypatch.setattr("sys.argv", ["hypervault-mcp", "--transport", "http"])
        server.main()
        run_mock.assert_called_once_with(transport="http", host="127.0.0.1", port=8787)
