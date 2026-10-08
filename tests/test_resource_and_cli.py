"""Tests for the hypervault://help resource and the CLI entrypoint."""

from __future__ import annotations

import re
from unittest.mock import MagicMock

from hypervault_mcp import server

# The words a first-run surface must not use (lib/copy.ts FIRST_RUN_BANNED in
# the web app). The agent-facing text below names them once, to forbid them.
BANNED = re.compile(r"\b(?:MCP|tombstone|GraphRAG|grant|artifact\s+node|subdomain|AgentVault|wiki|vault\s+item)", re.I)
NEW_TOOLS = ["yours", "my_keys", "read_memory", "read_docs"]


def flat(text: str) -> str:
    """The text on one line, so a check does not depend on where it wraps."""
    return " ".join(text.split())


class TestVaultHelpResource:
    def test_mentions_every_tool(self):
        text = server.get_vault_help()
        for tool_name in [
            "save_to_hypervault",
            "claim_vanity_subdomain",
            "list_my_vault_items",
            "setup_challenge",
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
            "create_task_board",
            "list_task_boards",
            "tasklist_get",
            "tasklist_summary",
            "task_create",
            "task_update",
            "task_claim",
            "task_complete",
            "yours",
            "my_keys",
            "read_memory",
            "read_docs",
        ]:
            assert tool_name in text, f"{tool_name} missing from help text"

    def test_returns_a_string(self):
        assert isinstance(server.get_vault_help(), str)
        assert len(server.get_vault_help()) > 100

    def test_points_at_the_start_and_explain_docs(self):
        text = server.get_vault_help()
        assert "https://hypervault.store/start.md" in text
        assert "https://hypervault.store/explain.md" in text

    def test_the_doc_addresses_follow_the_configured_api_url(self, monkeypatch):
        monkeypatch.setenv("HYPERVAULT_API_URL", "https://hv.example.test/")
        text = server.get_vault_help()
        assert "https://hv.example.test/start.md" in text
        assert "https://hv.example.test/explain.md" in text
        assert "https://hypervault.store/start.md" not in text

    def test_says_how_to_read_the_docs_without_web_access(self):
        text = server.get_vault_help()
        assert "read_docs(path, offset)" in text
        for name in ("'start'", "'explain'", "'connect'", "'llms'"):
            assert name in text
        assert "next_offset" in text

    def test_asks_for_the_prd_vocabulary_and_names_the_words_to_leave_out(self):
        text = flat(server.get_vault_help())
        assert "say keep, memory, file, group, key and page" in text
        assert "called Yours" in text
        [forbidden] = re.findall(r"Never say ([^.]*)\.", text)
        for word in ("MCP", "grant", "wiki", "subdomain", "vault item"):
            assert f'"{word}"' in forbidden

    def test_the_new_opening_does_not_use_the_banned_words(self):
        # Everything above the numbered tool list is written for the person's
        # vocabulary, except the one paragraph that names the words to avoid.
        opening = server.get_vault_help().split("\n## Tools\n")[0]
        sections = re.split(r"\n(?=## )", opening)
        offenders = [
            section.splitlines()[0]
            for section in sections
            if not section.startswith("## Talk in plain words") and BANNED.search(section)
        ]
        assert offenders == []

    def test_the_keys_tools_are_names_only_and_no_tool_returns_a_value(self):
        text = flat(server.get_vault_help())
        assert "Names only. No tool returns a key's value" in text
        assert "It never lists keys." in text

    def test_new_tools_are_described_before_the_numbered_list(self):
        text = server.get_vault_help()
        numbered = text.index("## Tools")
        for name in ("yours(query, kind, limit)", "read_memory(memory_id, branch=None)", "my_keys()"):
            assert 0 <= text.index(name) < numbered


class TestInstructions:
    def test_points_at_the_start_and_explain_docs_and_the_tool_that_reads_them(self):
        text = server.mcp.instructions
        assert "/start.md" in text
        assert "/explain.md" in text
        assert "read_docs('start')" in text
        assert "read_docs('explain')" in text

    def test_names_the_new_tools(self):
        text = server.mcp.instructions
        for tool_name in NEW_TOOLS:
            assert tool_name in text, f"{tool_name} missing from the instructions"

    def test_leads_with_keeping_in_the_prd_words(self):
        text = server.mcp.instructions
        assert text.startswith("HyperVault keeps what the person's AI makes")
        assert "Kept. Here's the link." in text
        assert "keep, memory, file, group, key, page" in text

    def test_names_the_banned_words_only_to_forbid_them(self):
        text = server.mcp.instructions
        [forbidding] = re.findall(r'Never say [^.]*\.', text)
        assert BANNED.search(forbidding)
        assert not BANNED.search(text.replace(forbidding, ""))

    def test_says_no_tool_returns_a_keys_value(self):
        assert "no tool returns a key's value" in server.mcp.instructions

    def test_what_was_there_before_is_still_said(self):
        text = server.mcp.instructions
        for kept in ("mutable=true", "create_artifact_group", "memorize()", "recall()", "mind_*", "tasklist_get"):
            assert kept in text

    def test_every_tool_it_names_exists(self, tool_names):
        named = [
            "save_to_hypervault",
            "yours",
            "read_memory",
            "recall",
            "my_keys",
            "read_docs",
            "read_artifact",
            "write_artifact",
            "artifact_history",
            "create_artifact_group",
            "add_artifact_group_item",
            "edit_artifact_group_item",
            "remove_artifact_group_item",
            "memorize",
            "tasklist_get",
            "task_claim",
            "task_update",
            "task_complete",
            "claim_vanity_subdomain",
        ]
        for tool_name in named:
            assert tool_name in server.mcp.instructions, f"{tool_name} missing from the instructions"
            assert tool_name in tool_names, f"the instructions name {tool_name}, which is not a tool"


class TestMainCli:
    def test_defaults_to_stdio(self, monkeypatch):
        run_mock = MagicMock()
        monkeypatch.setattr(server.mcp, "run", run_mock)
        monkeypatch.setattr("sys.argv", ["hypervault-mcp"])
        server.main()
        run_mock.assert_called_once_with()

    def test_http_transport_wires_host_and_port(self, monkeypatch):
        """HTTP goes through uvicorn with the keyed app, not mcp.run, so a
        local HTTP server accepts /k/<key>/mcp like the hosted one."""
        run_mock = MagicMock()
        built = object()
        monkeypatch.setattr(server.mcp, "run", MagicMock())
        monkeypatch.setattr(server, "build_http_app", MagicMock(return_value=built))
        monkeypatch.setattr("uvicorn.run", run_mock)
        monkeypatch.setattr(
            "sys.argv",
            ["hypervault-mcp", "--transport", "http", "--host", "0.0.0.0", "--port", "9999"],
        )
        server.main()
        run_mock.assert_called_once_with(built, host="0.0.0.0", port=9999)
        server.mcp.run.assert_not_called()

    def test_http_transport_default_host_and_port(self, monkeypatch):
        run_mock = MagicMock()
        monkeypatch.setattr(server, "build_http_app", MagicMock(return_value="app"))
        monkeypatch.setattr("uvicorn.run", run_mock)
        monkeypatch.setattr("sys.argv", ["hypervault-mcp", "--transport", "http"])
        server.main()
        run_mock.assert_called_once_with("app", host="127.0.0.1", port=8787)

