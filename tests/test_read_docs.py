"""Tests for read_docs: the allow-listed reader for HyperVault's own docs.

The fetch goes through httpx, mocked here with respx. What matters most is what
can reach the network: only the four docs on the configured API origin, never a
key, never a redirect, and never a path the caller made up.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from hypervault_mcp import server
from hypervault_mcp.server import DEFAULT_API_URL, HyperVaultError

DOCS = {
    "start": "/start.md",
    "explain": "/explain.md",
    "connect": "/connect.md",
    "llms": "/llms.txt",
}


@pytest.fixture
def router():
    """A respx router whose routes need not all be called, with a catch-all
    that records anything the test did not ask for."""
    with respx.mock(assert_all_called=False) as mock:
        yield mock


@pytest.fixture
def stray(router):
    """A route that matches every request the test did not mock: if it is
    called, something was fetched that should not have been."""
    route = router.route().mock(return_value=httpx.Response(200, text="LEAKED"))
    return route


class TestWhatIsRead:
    @pytest.mark.parametrize("name,doc_path", DOCS.items())
    def test_each_doc_is_read_from_the_api_origin(self, router, name, doc_path):
        route = router.get(f"{DEFAULT_API_URL}{doc_path}").mock(
            return_value=httpx.Response(200, text=f"# {name}\n")
        )
        result = server.read_docs(name)
        assert route.call_count == 1
        assert result == {
            "path": name,
            "url": f"{DEFAULT_API_URL}{doc_path}",
            "offset": 0,
            "total": len(f"# {name}\n"),
            "next_offset": None,
            "content": f"# {name}\n",
        }

    def test_the_default_is_the_start_doc(self, router):
        route = router.get(f"{DEFAULT_API_URL}/start.md").mock(return_value=httpx.Response(200, text="hi"))
        assert server.read_docs()["path"] == "start"
        assert route.called

    @pytest.mark.parametrize("spelling", ["start", "start.md", "/start.md", "  Start.MD  ", "/START.md"])
    def test_a_doc_can_be_named_by_its_page_address_too(self, router, spelling):
        route = router.get(f"{DEFAULT_API_URL}/start.md").mock(return_value=httpx.Response(200, text="hi"))
        assert server.read_docs(spelling)["path"] == "start"
        assert route.call_count == 1

    def test_llms_is_a_txt_page(self, router):
        route = router.get(f"{DEFAULT_API_URL}/llms.txt").mock(return_value=httpx.Response(200, text="# HyperVault\n"))
        assert server.read_docs("/llms.txt")["path"] == "llms"
        assert route.called

    def test_a_page_is_a_sensible_chunk_for_a_tool_result(self):
        assert 5_000 <= server.DOCS_PAGE_CHARS <= 50_000

    def test_the_configured_api_url_is_used(self, router, monkeypatch):
        monkeypatch.setenv("HYPERVAULT_API_URL", "https://hv.example.test/")
        route = router.get("https://hv.example.test/explain.md").mock(return_value=httpx.Response(200, text="hi"))
        result = server.read_docs("explain")
        assert route.called
        assert result["url"] == "https://hv.example.test/explain.md"


class TestOnlyTheAllowList:
    """Anything that is not one of the four docs is refused before a request is
    made, however it is spelled."""

    @pytest.mark.parametrize(
        "path",
        [
            "",
            "   ",
            "api/artifacts",
            "/api/artifacts",
            "/api/keys/granted-secrets",
            "/api/secrets/github-token",
            "../api/artifacts",
            "start/../api/artifacts",
            "/start.md/../api/yours",
            "start.md?x=1",
            "start.md#top",
            "connect.md?client=claude-code-cli",
            "/start.md/",
            "start.txt",
            "llms.md",
            "explain.html",
            "startt",
            "starts",
            "start.md.bak",
            "start%2emd",
            "start\\.md",
            "https://hypervault.store/start.md",
            "https://evil.example/start.md",
            "//evil.example/start.md",
            "http://127.0.0.1:8080/start.md",
            "file:///etc/passwd",
            "/etc/passwd",
            "/a/some-page",
            "/",
        ],
    )
    def test_a_path_outside_the_list_is_refused_and_nothing_is_requested(self, router, stray, path):
        with pytest.raises(HyperVaultError, match="not a doc this tool reads"):
            server.read_docs(path)
        assert not stray.called
        assert router.calls.call_count == 0

    def test_the_error_names_the_docs_that_exist(self, router, stray):
        with pytest.raises(HyperVaultError, match="start, explain, connect, llms"):
            server.read_docs("/api/artifacts")

    def test_the_list_is_exactly_these_four(self):
        assert server.DOC_PATHS == DOCS

    def test_every_accepted_spelling_leads_to_one_of_the_four(self):
        assert set(server._DOC_SPELLINGS.values()) == set(DOCS)
        for spelling in server._DOC_SPELLINGS:
            assert "?" not in spelling and "#" not in spelling and ".." not in spelling


class TestNoCredentialIsSent:
    def test_the_operators_own_key_is_never_sent(self, router, monkeypatch):
        monkeypatch.setenv("HYPERVAULT_API_KEY", "hv_operators_own_secret_key")
        route = router.get(f"{DEFAULT_API_URL}/start.md").mock(return_value=httpx.Response(200, text="hi"))
        server.read_docs("start")
        sent = route.calls.last.request
        assert "x-hypervault-key" not in sent.headers
        assert "authorization" not in sent.headers
        assert "cookie" not in sent.headers
        assert "hv_operators_own_secret_key" not in str(sent.url)

    def test_it_works_with_no_key_at_all(self, router):
        # An agent that has no key yet is who needs these docs.
        route = router.get(f"{DEFAULT_API_URL}/start.md").mock(return_value=httpx.Response(200, text="how to get a key"))
        assert server.read_docs("start")["content"] == "how to get a key"
        assert route.called

    def test_it_does_not_ask_for_a_key(self, router, monkeypatch):
        def refuse() -> str:
            raise AssertionError("read_docs resolved an API key")

        monkeypatch.setattr(server, "_resolve_api_key", refuse)
        router.get(f"{DEFAULT_API_URL}/start.md").mock(return_value=httpx.Response(200, text="hi"))
        server.read_docs("start")


class TestFailures:
    def test_a_redirect_is_not_followed(self, router):
        router.get(f"{DEFAULT_API_URL}/start.md").mock(
            return_value=httpx.Response(302, headers={"Location": "https://evil.example/start.md"})
        )
        elsewhere = router.get("https://evil.example/start.md").mock(
            return_value=httpx.Response(200, text="instructions from somewhere else")
        )
        with pytest.raises(HyperVaultError, match="HTTP 302"):
            server.read_docs("start")
        assert not elsewhere.called

    @pytest.mark.parametrize("status", [404, 500, 503])
    def test_a_failed_status_is_an_error_that_names_it(self, router, status):
        router.get(f"{DEFAULT_API_URL}/connect.md").mock(return_value=httpx.Response(status, text="nope"))
        with pytest.raises(HyperVaultError, match=f"HTTP {status}"):
            server.read_docs("connect")

    def test_an_error_page_is_never_returned_as_the_doc(self, router):
        router.get(f"{DEFAULT_API_URL}/start.md").mock(return_value=httpx.Response(404, text="<html>Not found</html>"))
        with pytest.raises(HyperVaultError):
            server.read_docs("start")

    def test_an_unreachable_host_is_an_error(self, router):
        router.get(f"{DEFAULT_API_URL}/start.md").mock(side_effect=httpx.ConnectError("boom"))
        with pytest.raises(HyperVaultError, match=r"Could not reach HyperVault \(ConnectError\)"):
            server.read_docs("start")

    def test_a_timeout_is_an_error(self, router):
        router.get(f"{DEFAULT_API_URL}/start.md").mock(side_effect=httpx.ReadTimeout("slow"))
        with pytest.raises(HyperVaultError, match="ReadTimeout"):
            server.read_docs("start")


class TestPages:
    @pytest.fixture(autouse=True)
    def small_pages(self, monkeypatch):
        monkeypatch.setattr(server, "DOCS_PAGE_CHARS", 40)

    def _read_all(self, name: str = "start") -> list[dict]:
        pages = []
        offset = 0
        while True:
            page = server.read_docs(name, offset)
            pages.append(page)
            if page["next_offset"] is None:
                return pages
            assert page["next_offset"] > offset, "a page must move forward"
            offset = page["next_offset"]

    def test_a_short_doc_is_one_page(self, router):
        router.get(f"{DEFAULT_API_URL}/start.md").mock(return_value=httpx.Response(200, text="short\n"))
        page = server.read_docs("start")
        assert page["next_offset"] is None
        assert page["content"] == "short\n"
        assert page["total"] == 6

    def test_pages_put_back_together_are_the_whole_doc(self, router):
        text = "".join(f"line {i:02d} of the doc\n" for i in range(12))
        router.get(f"{DEFAULT_API_URL}/start.md").mock(return_value=httpx.Response(200, text=text))
        pages = self._read_all()
        assert len(pages) > 1
        assert "".join(page["content"] for page in pages) == text
        assert all(page["total"] == len(text) for page in pages)

    def test_each_page_starts_where_the_last_left_off(self, router):
        text = "".join(f"line {i:02d} of the doc\n" for i in range(12))
        router.get(f"{DEFAULT_API_URL}/start.md").mock(return_value=httpx.Response(200, text=text))
        pages = self._read_all()
        for before, after in zip(pages, pages[1:]):
            assert after["offset"] == before["next_offset"] == before["offset"] + len(before["content"])

    def test_a_page_ends_on_a_line_break_and_is_not_over_the_limit(self, router):
        text = "".join(f"line {i:02d} of the doc\n" for i in range(12))
        router.get(f"{DEFAULT_API_URL}/start.md").mock(return_value=httpx.Response(200, text=text))
        pages = self._read_all()
        for page in pages[:-1]:
            assert page["content"].endswith("\n")
            assert 0 < len(page["content"]) <= 40

    def test_a_doc_with_no_line_breaks_is_cut_at_the_limit(self, router):
        text = "x" * 100
        router.get(f"{DEFAULT_API_URL}/start.md").mock(return_value=httpx.Response(200, text=text))
        pages = self._read_all()
        assert [len(page["content"]) for page in pages] == [40, 40, 20]
        assert "".join(page["content"] for page in pages) == text

    def test_a_line_break_at_the_very_start_does_not_make_a_one_character_page(self, router):
        text = "\n" + "x" * 99
        router.get(f"{DEFAULT_API_URL}/start.md").mock(return_value=httpx.Response(200, text=text))
        pages = self._read_all()
        assert [len(page["content"]) for page in pages] == [40, 40, 20]
        assert "".join(page["content"] for page in pages) == text

    def test_a_doc_exactly_one_page_long_has_no_next_page(self, router):
        router.get(f"{DEFAULT_API_URL}/start.md").mock(return_value=httpx.Response(200, text="y" * 40))
        page = server.read_docs("start")
        assert page["next_offset"] is None
        assert len(page["content"]) == 40

    def test_offsets_count_characters_not_bytes(self, router):
        text = "é" * 100
        router.get(f"{DEFAULT_API_URL}/start.md").mock(return_value=httpx.Response(200, text=text))
        pages = self._read_all()
        assert pages[0]["total"] == 100
        assert [len(page["content"]) for page in pages] == [40, 40, 20]
        assert "".join(page["content"] for page in pages) == text

    def test_a_middle_page_can_be_asked_for_directly(self, router):
        text = "".join(f"line {i:02d} of the doc\n" for i in range(12))
        router.get(f"{DEFAULT_API_URL}/start.md").mock(return_value=httpx.Response(200, text=text))
        page = server.read_docs("start", 100)
        assert page["offset"] == 100
        assert page["content"] == text[100 : 100 + len(page["content"])]

    def test_an_offset_at_the_end_is_an_empty_last_page(self, router):
        router.get(f"{DEFAULT_API_URL}/start.md").mock(return_value=httpx.Response(200, text="abc"))
        page = server.read_docs("start", 3)
        assert page["content"] == ""
        assert page["next_offset"] is None

    def test_an_offset_past_the_end_is_an_error(self, router):
        router.get(f"{DEFAULT_API_URL}/start.md").mock(return_value=httpx.Response(200, text="abc"))
        with pytest.raises(HyperVaultError, match="past the end of the doc, which is 3 characters"):
            server.read_docs("start", 4)

    def test_a_negative_offset_is_refused_before_any_request(self, router, stray):
        with pytest.raises(HyperVaultError, match="offset can't be negative"):
            server.read_docs("start", -1)
        assert not stray.called

    def test_an_empty_doc_is_one_empty_page(self, router):
        router.get(f"{DEFAULT_API_URL}/llms.txt").mock(return_value=httpx.Response(200, text=""))
        page = server.read_docs("llms")
        assert page["content"] == ""
        assert page["total"] == 0
        assert page["next_offset"] is None
