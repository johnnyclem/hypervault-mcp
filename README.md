# hypervault-mcp

MCP server for [HyperVault](https://github.com/johnnyclem/hypervault) — lets any
MCP-capable agent save artifacts to a user's vault and claim vanity subdomains.

Built with [FastMCP](https://gofastmcp.com).

**Hosted endpoint:** `https://mcp.vault.cool/mcp` (Streamable HTTP) — no
install needed, just point your MCP client at it with your own API key. See
[Auth & rate limits](#auth--rate-limits) for the header format, or
[Connect from the Claude app](#connect-from-the-claude-app-web-iphone-android)
for clients that can't send headers.

## Connect from the Claude app (web, iPhone, Android)

The Claude app's custom connectors take a URL but no headers, so the key
rides in the URL instead:

```
https://mcp.vault.cool/k/hv_your_key_here/mcp
```

1. claude.ai → **Settings → Connectors → Add custom connector** (custom
   connectors need a paid plan; if the mobile app doesn't show the option,
   add it once in a browser — connectors sync to every device).
2. Name it **HyperVault**, paste the URL above, save, then turn it on in a
   chat's tools menu.
3. Say *"Complete the HyperVault setup challenge"* — the agent calls
   `setup_challenge()` to find the key's challenge page and finishes it with
   `read_artifact` → `write_artifact`. No key ever needs to be pasted into
   the chat.

The URL **is** the credential: anything that logs request paths (Vercel's
function logs included) can see it. Mint a key just for the connector, and
revoke it from the dashboard's Agent API keys panel if it leaks. When a
request carries both a URL key and a key header, the URL wins — the URL is
the connector's identity. The vault dashboard generates this URL for you
when you mint a key.

## Install & run

```bash
pip install -e .          # from this directory (or: uv pip install -e .)

export HYPERVAULT_API_KEY=hv_...            # create one in the web dashboard (/vault)
export HYPERVAULT_API_URL=https://hypervault.store   # optional; defaults to hypervault.store

hypervault-mcp                                # STDIO (local agents)
hypervault-mcp --transport http --port 8787   # HTTP (web agents)
```

Authentication differs by transport — see [Auth & rate limits](#auth--rate-limits) below.

## Tools

| Tool | What it does |
| --- | --- |
| `save_to_hypervault(content, title, type, tags, connect_to, make_pwa, source_prompt, visibility, mutable)` | Saves HTML or React/JSX and returns a permanent, installable URL. JSX is auto-detected and wrapped server-side. `connect_to` links the new artifact to existing ones (graph view edges); similar items are auto-connected too. Pass `source_prompt` to bake the originating prompt into the page as `<meta name="hypervault-source-prompt">` so agents can iterate later. Re-saving identical content returns the existing URL (`duplicate: true`) instead of creating a copy. Pass `mutable=True` for a **living document** you can rewrite in place (see below). |
| `claim_vanity_subdomain(desired_name, base_domain="vault.cool")` | Claims `name.vault.cool` for the user, effective immediately. Pro accounts can hold up to 10 subdomains; the full vault lives on every one. |
| `connect_vault_items(source, target)` | Connects two existing artifacts (bidirectional, drawn in graph view). |
| `list_my_vault_items()` | Lists everything already in the vault. |
| `setup_challenge()` | Finds this key's one-time setup challenge (slug, whether it's done, the exact edit steps). Completing it with `read_artifact` → edit → `write_artifact` flips the key's dashboard badge to **Agent connected ✓**. The first call to make on a fresh key. |
| `read_artifact(ref, version=None)` | Reads an artifact's current editable source (raw JSX for JSX artifacts, HTML otherwise) by slug or URL, plus its `head_version_id`. Pass a `version` id to read a past iteration. Pair with `write_artifact` to iterate. |
| `write_artifact(ref, content, title, message, force_html, base_version_id, requested_at, author)` | Writes a new iteration of a **mutable** artifact — a git commit on the living document. The page updates in place (URL unchanged) and the write is kept as a version. Pass the `head_version_id` you read as `base_version_id` and the write is applied like a commit: fast-forward when nothing changed underneath, rebased onto the new head when another agent committed first, and refused with `conflict: true` ("Cannot apply update … pull the latest version of the artifact and rebase locally first") when the edits overlap. `requested_at` orders colliding writes (earliest first); `author` names the agent in history. Immutable artifacts are refused. |
| `artifact_history(ref, full, limit)` | Lists a mutable artifact's version history (git commits), newest first, with authorship. Revert by reading an old version and writing it back. |
| `extract_source_prompt(url)` | Fetches any artifact URL (vanity domains included) and returns the source prompt from its hidden `<meta name="hypervault-source-prompt">` tag, so you can iterate on the original idea. |
| `delete_vault_item(slug_or_id)` | Permanently deletes an artifact (and its graph connections). Irreversible — the share URL stops working immediately. |
| `truth_events(since, author, kind, unseen, mark_seen, limit)` | What changed in the ledger that concerns you: your TBs/UVs **challenged, overturned, upheld or verified**, newest first. `unseen=True` (default) uses a per-key cursor so you only see news since you last looked; `author` narrows to entries you authored or signed. Chat and room turns get these as a system notice automatically; this is the explicit pull. |
| `register_webhook(url, name, events, authors, secret)` | Register a webhook: HyperVault POSTs signed JSON (`X-HyperVault-Signature: t=…,v1=HMAC-SHA256("t.body")`) to your URL on every matching truth event. `authors=[your name]` limits it to your entries. The secret is returned once. Retries with backoff; `test_webhook` sends a signed ping. |
| `list_webhooks()` / `webhook_status(webhook_id)` / `test_webhook(webhook_id)` / `delete_webhook(webhook_id)` | Manage webhooks: list them (never the secrets), see a hook's last 25 deliveries, send a `truth.test` ping, remove one. |
| `create_artifact_group(files, title, tags, connect_to, visibility, source_prompt)` | Saves a multi-file **artifact group** — several `.html`/`.css`/`.js`/`.jsx` files that run together — behind a required root `index.html`. Returns a JSFiddle-style run/preview URL (see [Artifact groups](#artifact-groups-multi-file-projects) below). |
| `read_artifact_group(ref)` | Reads a group's full file set and metadata by slug or URL. |
| `list_artifact_groups()` | Lists everything already saved as a group. |
| `add_artifact_group_item(ref, path, content)` | Adds a new file to an existing group (fails if that path already exists). |
| `edit_artifact_group_item(ref, path, content)` | Replaces an existing file's content, including `index.html` itself (fails if that path doesn't exist yet). |
| `remove_artifact_group_item(ref, path)` | Removes a file from a group. The root `index.html` can't be removed this way. |
| `delete_artifact_group(slug_or_id)` | Permanently deletes a whole group. Irreversible. |
| `memorize(content, title, tags, source)` | Stores a chunk in the user's **private memory wiki** (Imaging V2). Auto-titled, auto-tagged, summarized, and linked to related memories in their knowledge graph. |
| `recall(query)` | Natural-language search over the wiki ("what did I say about the Rust borrow checker?"). Top matches return the exact stored content; every match lists its linked memories. |
| `list_memories()` | Browses everything memorized, newest first (summaries + tags). |
| `forget_memory(memory_id)` | Permanently deletes one memory — only on the user's explicit request. |
| `create_task_board(title, project, tasks, stages, visibility)` | Creates a **universal task board** — a shared, versioned task list — plus the interactive board page the user watches it on. Returns `project` (what every other task tool takes) and `board.url` (the human deliverable). See [Universal task boards](#universal-task-boards-shared-work-lists) below. |
| `list_task_boards()` | Lists the user's existing boards, so you can join one instead of creating a duplicate. |
| `tasklist_get(project, since_version=None)` | Reads the full list. With `since_version` you get `{unchanged: true, version}` when nothing moved — the cheap poll. |
| `tasklist_summary(project)` | Rollup only: counts, progress, epics, who holds what. Prefer it over the full list for status reporting on a large board. |
| `task_create(project, title, type, parent, description, priority, active_form, depends_on, metadata, expected_version, agent_name, agent_type)` | Adds a task to an existing board. |
| `task_update(project, task_id, status, progress, note, title, description, priority, active_form, parent, metadata, expected_version, agent_name, agent_type)` | Patches one task; only the arguments you pass change. `note` **appends** to the task's thread, `metadata` **merges** key-wise. |
| `task_claim(project, task_id, agent_name, agent_type, force, release, lock_minutes, expected_version)` | Claims a task — lock + assign + `in_progress` — so several agents can share a board without colliding. `release=True` hands it back. |
| `task_complete(project, task_id, note, expected_version, agent_name, agent_type)` | Done, progress 100, lock released, in one call. The response includes the list `summary`. |

Plus the `hypervault://help` resource with agent-facing usage notes.

Memories are owner-only: they power the Memory Control Panel at
`/vault/memory` and are never rendered on public pages.

### Mutable artifacts (a living document)

Artifacts are immutable by default: a save is permanent, and re-saving the same
content just returns the existing link. Save with `mutable=True` to get a
document you can iterate on in place — its URL never changes, and every write is
kept as a git commit you can list and revert to:

```python
saved = save_to_hypervault(content="<h1>v1</h1>", title="Notes", mutable=True)
read_artifact(saved["slug"])                       # -> current source + head version
write_artifact(saved["slug"], "<h1>v2</h1>", message="expand intro")
artifact_history(saved["slug"])                    # -> the commit chain, newest first
```

`read_artifact` → edit → `write_artifact` is the iteration loop; to revert, read
an old version's content (`read_artifact(ref, version=...)`) and write it back
with `base_version_id` set to the current head (writing it "based on" the old
version itself is a no-op rebase, and the API says so).
The write tools are owner-scoped (the API key resolves to its owner), so a
mutable artifact is read and written privately even when the page is public.

### Artifact groups (multi-file projects)

Use an artifact group instead of `save_to_hypervault` when a project needs more
than one file — separate markup, styles, and script(s) that reference each
other normally, like a tiny JSFiddle. A group always runs/previews as a
container at `https://hypervault.store/g/{slug}` — a minimal editor/preview UI
similar to JSFiddle — routed through a required root `index.html`.

```python
group = create_artifact_group(
    files=[
        {"path": "index.html", "content": "<link rel='stylesheet' href='style.css'><script src='app.js'></script>"},
        {"path": "style.css", "content": "body { font-family: sans-serif; }"},
        {"path": "app.js", "content": "console.log('hello from the group')"},
    ],
    title="My Widget",
)
read_artifact_group(group["slug"])                                   # -> current files + metadata
add_artifact_group_item(group["slug"], "extra.js", "// more code")   # add a new file
edit_artifact_group_item(group["slug"], "style.css", "body { color: red; }")  # replace a file's content
remove_artifact_group_item(group["slug"], "extra.js")                # remove a file (not index.html)
list_artifact_groups()                                               # browse everything saved
delete_artifact_group(group["slug"])                                 # permanently delete the group
```

Validation runs locally before any network call, so bad input never reaches
the backend:

- Exactly one root file at path `index.html` — the entry point the
  run/preview container routes through. A nested one like
  `public/index.html` does not count.
- Paths must be relative, use `/` as the separator, contain no `..`
  segments, and only `[A-Za-z0-9._/-]` characters.
- Extensions are limited to `.html`, `.css`, `.js`, `.jsx`.
- At most 50 files; 256 KB per file; 1 MB total.
- Paths must be unique (case-insensitively).
- The root `index.html` can't be removed with `remove_artifact_group_item` —
  edit its content instead, or delete the whole group.

### Universal task boards (shared work lists)

A task board is a shared, versioned task list that an agent and the user work
from together. One call creates both halves: a JSON data artifact
(`tasks-{project}`) the agent syncs through, and an interactive board page
(`taskboard-{project}`) the user opens to watch and steer the work live. Every
write is an artifact version (audit trail + rollback), writes are
optimistic-concurrency-safe, and claims are locks, so several agents can share
one board without collisions.

```python
board = create_task_board(
    title="Eurorack choir firmware",
    tasks=[
        {"id": "epic-1", "title": "Firmware", "type": "epic"},
        {"title": "Bring up I2S clocking", "parent": "epic-1", "priority": "high"},
    ],
)
project = board["project"]
board["board"]["url"]        # <- hand this to the user; it's the living UI

tasks = tasklist_get(project)["tasklist"]["tasks"]
task_claim(project, tasks[1]["id"], agent_name="claude-code:session-abc")
task_update(project, tasks[1]["id"], progress=50, note="I2S clock locked at 48 kHz")
task_complete(project, tasks[1]["id"], note="landed in PR #12")

tasklist_get(project, since_version=12)   # -> {"unchanged": true, ...} when nothing moved
tasklist_summary(project)                 # -> counts, progress, epics, claims
```

The protocol agents should follow (it's also spelled out in
`hypervault://help`, so a connected agent reads it without being told):

- **Read at session start**, and re-poll with `since_version` at tool
  boundaries — that's how the user's steering from the board page reaches you
  mid-task.
- **Claim deliberately.** Prefer tasks assigned to you or unassigned. A live
  foreign lock fails with a 409 naming the holder; `force` is only for a holder
  who is clearly gone (expired locks need no force). Locks last 60 minutes by
  default, 24 h max, and re-claiming your own task renews it.
- **Push every meaningful change immediately** — the user's board polls the
  same list, and a stale board means they're steering blind.
- **Send `expected_version` on writes.** A version conflict comes back as
  `{conflict: true, latest, error}` — and `latest` is the *whole fresh list*, so
  the tools return that payload rather than collapsing it into an error
  message. Re-apply your change on top of `latest`; don't overwrite.
- **Map both ways via `metadata.externalId`** to keep a native todo list and
  the board in sync.

Statuses are `todo | in_progress | blocked | review | done | cancelled`;
priorities are `low | medium | high | critical`. Marking a task done (either
tool) releases the lock, and a done task can't be re-claimed. Task writes
return the whole list for convenience — on a large board that's token-heavy, so
reach for `tasklist_summary` and `since_version` polling instead.

## Claude Desktop / Claude Code config

```json
{
  "mcpServers": {
    "hypervault": {
      "command": "hypervault-mcp",
      "env": {
        "HYPERVAULT_API_KEY": "hv_your_key_here"
      }
    }
  }
}
```

## Running under greywall (sandboxed agents)

The server is single-host on purpose: every tool call — including
`extract_source_prompt`, which resolves artifact URLs through the backend's
`/api/extract` — goes to the API origin only. That means it works inside
deny-by-default sandboxes like [greywall](https://github.com/johnnyclem/greywall)
with exactly one domain allowed:

```bash
export HYPERVAULT_API_KEY=hv_...
greywall --profile claude,python --settings ./greywall.json -- claude
```

Then allow the API host (`hypervault.store`, or your `HYPERVAULT_API_URL`) in
the greyproxy dashboard. The [`greywall.json`](greywall.json) template also
marks `HYPERVAULT_API_KEY` as a secret, so the sandboxed agent only ever sees
a placeholder — greyproxy substitutes the real key into the
`X-HyperVault-Key` header outside the sandbox. Full guide:
[docs/greywall.md](../docs/greywall.md).

## Auth & rate limits

Keys are minted (and revoked) in the web dashboard's Vault → Agent API keys
panel. This MCP server never stores or looks up keys itself — it forwards
whatever key you give it straight to the real HyperVault backend
(hypervault.store), which is the only place that ever validates one (it
stores just a salted SHA-256 hash and enforces 60 requests/minute per key).

How the key gets there depends on the transport:

* **STDIO** (`hypervault-mcp`, no `--transport http`) — a single trusted
  local process. The key comes from the `HYPERVAULT_API_KEY` environment
  variable, set once when you start the server (as in Install & run above).
* **HTTP** (`hypervault-mcp --transport http`, and the hosted Vercel
  deployment) — a single server can be shared by many callers, so every
  request must carry *its own* key, sent per-call as either:
  * `Authorization: Bearer hv_...` (standard, recommended for MCP clients), or
  * `X-HyperVault-Key: hv_...`

  There is no shared fallback key for HTTP: a request with neither header is
  rejected with an "Authentication required" tool error before any call
  reaches the backend, even if the server process happens to have
  `HYPERVAULT_API_KEY` set in its own environment. Listing the available
  tools (`tools/list`) doesn't require a key — no user data is involved —
  but every tool call does. Configure your MCP client to send your key as a
  header on the hosted endpoint, e.g. for a `mcp.json`-style config:

  ```json
  {
    "mcpServers": {
      "hypervault": {
        "url": "https://mcp.vault.cool/mcp",
        "headers": { "Authorization": "Bearer hv_your_key_here" }
      }
    }
  }
  ```

  `https://mcp.vault.cool/mcp` is a custom-domain alias for the same
  deployment as `https://hypervault-mcp.vercel.app/mcp` — the two are
  interchangeable and always serve identical code.

  Clients that can't set headers use the URL form
  `https://mcp.vault.cool/k/hv_.../mcp` instead — see
  [Connect from the Claude app](#connect-from-the-claude-app-web-iphone-android).
  `hypervault-mcp --transport http` serves the same `/k/<key>/mcp` route
  locally.

## Tests

```bash
pip install -e ".[test]"
pytest
```

The suite (`tests/`) covers the request-shaping logic of every tool, the
`_client`/`_request` HTTP layer (mocked with `respx` — no real network
calls), the `extract_source_prompt` preferred/legacy fallback chain, the task-board
tools (body shaping, the empty-patch and blank-`agent_name` guards, and the
409 conflict payload coming back intact instead of as an exception), and —
most importantly — the per-request auth model: header parsing, the
STDIO-vs-HTTP key resolution split, and full end-to-end requests against the
real ASGI app proving an unauthenticated `tools/call` is rejected even when
an operator `HYPERVAULT_API_KEY` is set in the environment.

## Smoke test

With the web app running locally (`npm run dev` in the repo root) and a key
exported:

```bash
python - <<'PY'
from fastmcp import Client
from hypervault_mcp.server import mcp
import asyncio

async def go():
    async with Client(mcp) as client:
        tools = await client.list_tools()
        print("tools:", [t.name for t in tools])
        result = await client.call_tool("save_to_hypervault", {
            "content": "<h1>Hello from an agent</h1>",
            "title": "MCP smoke test",
        })
        print(result)

asyncio.run(go())
PY
```

Task boards need a backend running hypervault ≥ [PR #128](https://github.com/johnnyclem/hypervault/pull/128):

```bash
python - <<'PY'
from fastmcp import Client
from hypervault_mcp.server import mcp
import asyncio

async def go():
    async with Client(mcp) as c:
        board = (await c.call_tool("create_task_board", {
            "title": "MCP smoke", "tasks": [
                {"id": "epic-1", "title": "Epic", "type": "epic"},
                {"title": "Child task", "parent": "epic-1"},
            ]})).data
        p = board["project"]                          # board["board"]["url"] is the human page
        lst = (await c.call_tool("tasklist_get", {"project": p})).data["tasklist"]
        tid = next(t["id"] for t in lst["tasks"] if t["parent"] == "epic-1")
        await c.call_tool("task_claim", {"project": p, "task_id": tid, "agent_name": "smoke-test"})
        await c.call_tool("task_update", {"project": p, "task_id": tid, "progress": 50, "note": "halfway"})
        done = (await c.call_tool("task_complete", {"project": p, "task_id": tid, "note": "done"})).data
        assert done["summary"]["byStatus"]["done"] == 1
        assert (await c.call_tool("tasklist_get", {"project": p,
            "since_version": done["summary"]["version"]})).data["unchanged"] is True
        print("task board:", board["board"]["url"])

asyncio.run(go())
PY
```
