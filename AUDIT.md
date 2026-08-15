# HyperVault MCP — Code Review & Security Audit

**Date:** 2026-08-15
**Scope:** Full repository (`src/hypervault_mcp/server.py`, `api/index.py`, tests, packaging/deploy config). No access to the separate `hypervault` backend repo — findings are scoped to what this MCP server controls.

## Summary

This repo is a single-module (~1,850 line) FastMCP server that acts as a thin, stateless, authenticated proxy in front of the real HyperVault backend (`hypervault.store`). It holds no data itself: every tool call validates/shapes a request locally, forwards it with the caller's own API key, and relays the backend's response.

The codebase was in good shape overall — a deliberately-designed per-request auth model with real regression tests for its own documented history (an earlier deployment leaked the operator's env-var key to anonymous HTTP callers), thorough local validation for the artifact-group file-upload path, and 262 passing tests before this audit. Two concrete, previously-untested input-validation gaps were found and fixed, both now covered by regression tests (284 tests passing after the changes). No Critical/High findings, no dependency CVEs.

## Findings

### Medium — Path injection via unvalidated `memory_id` / slug parameters

**Where:** `forget_memory`, `edit_memory`, `memory_history` in `src/hypervault_mcp/server.py`.

`memory_id` was interpolated straight into the request path (`f"/api/memories/{memory_id}"`) after only a `.strip()` — no check for `/`, `\`, or `..`. Separately, `_artifact_slug`, `_artifact_group_slug`, `_tasklist_project`, and `_task_id` did reject embedded slashes, but not a bare `..` segment. I confirmed httpx normalizes dot-segments client-side before sending:

```
_client.build_request('GET', '/api/artifacts/../secret/content').url
-> https://hypervault.store/api/secret/content
```

So a caller-supplied `memory_id` of `../artifacts` (or a slug/task-id of exactly `..`) could redirect a tool call onto a different backend endpoint than the one the tool name implies, still carrying the caller's own forwarded credentials — most concerning on `forget_memory`, which issues a `DELETE`. This is agent-reachable, not just user-reachable: any content an LLM ingests (a fetched webpage, a task-board note, a prior tool result) could contain an id string that gets passed straight through to one of these tools.

**Fix:** added a shared `_validate_ref_segment()` helper (rejects `/`, `\`, and bare `.`/`..`) and applied it consistently everywhere a caller-supplied string is interpolated into a URL path segment — the existing slug/task-id helpers, and the three memory-id call sites that previously had no protection at all. Existing error messages for the already-covered cases (empty/whitespace input) were preserved; new tests cover the previously-blank spot in `tests/test_helpers.py` and `tests/test_tools.py`.

### Medium — Unrestricted outbound fetch in `extract_source_prompt`'s fallback path (SSRF-shaped)

**Where:** `extract_source_prompt` in `src/hypervault_mcp/server.py`.

The tool's primary path resolves artifact URLs through the backend's own `/api/extract` endpoint (safe — the fetch happens server-side, out of this process's control). But when that call fails or returns an unexpected shape, it fell back to fetching the caller-supplied URL directly with `httpx.get(cleaned, follow_redirects=True)` — no restriction on the resolved host. A URL pointed at `127.0.0.1`, an RFC1918 address, or the cloud metadata address (`169.254.169.254`) would be fetched exactly like any public artifact page. Because `follow_redirects=True` was in play, even validating just the initial host wouldn't have been sufficient — a public-looking host could 302 to an internal one.

**Fix:** added `_assert_public_host()`, wired in as an httpx **request event hook** (fires on the initial request *and* every redirect hop, not just the first one) so a request is refused the moment any hop in the chain resolves to a loopback/private/link-local/reserved/multicast address. Verified against a synthetic redirect chain (public-resolving host → 302 → private-resolving host) that the second hop is correctly blocked before any connection is made. This is intentionally scoped as defense-in-depth rather than a redesign: the tool's whole purpose is fetching arbitrary public artifact URLs (including vanity subdomains the backend doesn't control), so the fix blocks non-public *targets*, not the general shape of the feature.

### Low — Dependency floor didn't match what the code actually requires

`pyproject.toml`/`requirements.txt` declared `fastmcp>=2.0.0`, but this code uses `fastmcp.server.dependencies.get_http_headers`/`get_http_request` and `FastMCP.http_app(stateless_http=..., json_response=...)`, none of which exist before fastmcp 2.12. I confirmed by installing several versions in a clean venv: 2.0.0–2.2.0 don't have the `dependencies` module at all; 2.3.0 has the module but not `get_http_headers`; `http_app` doesn't exist until well into the 2.x line either. A fresh install resolving an old-but-still->=2.0.0 fastmcp (plausible without a lockfile, especially if another dependency in a larger project constrains it down) would fail to import. **Fixed** — floor raised to `fastmcp>=2.12.0`, verified working, with a comment explaining why.

No CVEs were found in current dependencies (`pip-audit` against a fresh install: zero findings for `fastmcp`/`httpx`; the only hits were in the audit venv's own `pip`/`setuptools`, which aren't runtime dependencies of this project). A fresh install today resolves to `fastmcp==3.4.7`, `httpx==0.28.1` — both current, and the test suite passes unmodified against them.

### Low — No CI

There was no `.github/workflows/` — 262 (now 284) passing tests only ran when someone remembered to run them locally, and nothing would catch a regression before merge. **Fixed** — added `.github/workflows/tests.yml`, running `pytest` on push/PR across Python 3.10–3.13 (matching the `requires-python = ">=3.10"` floor in `pyproject.toml`).

### Low — Two dead-looking doc links (not fixed)

`README.md` links to `[docs/greywall.md](../docs/greywall.md)` and `docs/polytician.md` — both resolve *outside* this repo's root (`..` from `README.md` at the repo root), so they 404 on GitHub. I didn't touch these: I don't have visibility into whether they're meant to live in a sibling repo checkout, and fabricating replacement content or a guessed URL felt worse than flagging it. Worth a follow-up once it's clear where those docs actually live.

## What's already solid (no action taken)

- **Auth model.** STDIO uses a single trusted-process env var; HTTP requires each caller to send their own key (`Authorization: Bearer` or `X-HyperVault-Key`), with no operator-key fallback — and this is enforced with real end-to-end ASGI-level tests, including the specific historical regression it was built to prevent.
- **Artifact-group file validation** (`_validate_group_item_path` et al.) already had the traversal/charset/extension/size checks that the id/slug helpers were missing — thorough and well-tested; used as the model for this audit's path-injection fix.
- No secrets committed; `greywall.json` correctly marks `HYPERVAULT_API_KEY` as sandboxed/secret.
- No database/SQL surface in this repo — all persistent state lives in the separate backend.
- Consistent error handling: every backend call funnels through `_request()`, wrapping failures in `HyperVaultError` with the backend's own message relayed to the caller.

## Testing performed

- Full test suite: 262 → 284 tests, all passing (`pytest -q`), including a fresh `pip install -e ".[test]"` in a clean venv against the tightened dependency floor.
- `pip-audit` against the installed dependency set: 0 findings in `fastmcp`/`httpx`.
- Manual verification (outside the test suite, using mocked DNS resolution) that the SSRF fix blocks a redirect chain from a public-resolving host to a private one — the scenario a single up-front host check would have missed.
- Manually confirmed httpx's client-side dot-segment normalization (`/a/../b` → `/b`) to validate the path-injection finding's exploitability before fixing it.

## Recommended next steps (not done in this pass — flagged, not fixed)

- Resolve the two dead-looking README doc links once the intended target location is confirmed.
- Consider a lockfile (`uv lock` / `pip-compile`) so dependency resolution is reproducible rather than "whatever `>=` resolves to today" — this audit's fastmcp-floor finding is exactly the kind of drift a lockfile would have caught earlier.
- No other TODO/FIXME/HACK markers or half-finished features were found in the codebase.
