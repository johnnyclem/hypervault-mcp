# hypervault-mcp

MCP server for [HyperVault](https://github.com/johnnyclem/hypervault) — lets any
MCP-capable agent save artifacts to a user's vault and claim vanity subdomains.

Built with [FastMCP](https://gofastmcp.com).

## Install & run

```bash
pip install -e .          # from this directory (or: uv pip install -e .)

export HYPERVAULT_API_KEY=hv_...            # create one in the web dashboard (/vault)
export HYPERVAULT_API_URL=https://hypervault.store   # optional; defaults to hypervault.store

hypervault-mcp                                # STDIO (local agents)
hypervault-mcp --transport http --port 8787   # HTTP (web agents)
```

## Tools

| Tool | What it does |
| --- | --- |
| `save_to_hypervault(content, title, type, tags, connect_to, make_pwa, source_prompt, visibility, mutable)` | Saves HTML or React/JSX and returns a permanent, installable URL. JSX is auto-detected and wrapped server-side. `connect_to` links the new artifact to existing ones (graph view edges); similar items are auto-connected too. Pass `source_prompt` to bake the originating prompt into the page as `<meta name="hypervault-source-prompt">` so agents can iterate later. Re-saving identical content returns the existing URL (`duplicate: true`) instead of creating a copy. Pass `mutable=True` for a **living document** you can rewrite in place (see below). |
| `claim_vanity_subdomain(desired_name, base_domain="vault.cool")` | Claims `name.vault.cool` for the user, effective immediately. Pro accounts can hold up to 10 subdomains; the full vault lives on every one. |
| `connect_vault_items(source, target)` | Connects two existing artifacts (bidirectional, drawn in graph view). |
| `list_my_vault_items()` | Lists everything already in the vault. |
| `read_artifact(ref, version=None)` | Reads an artifact's current editable source (raw JSX for JSX artifacts, HTML otherwise) by slug or URL. Pass a `version` id to read a past iteration. Pair with `write_artifact` to iterate. |
| `write_artifact(ref, content, title, message, force_html)` | Writes a new iteration of a **mutable** artifact — a git commit on the living document. The page updates in place (URL unchanged) and the write is kept as a version. Immutable artifacts are refused. |
| `artifact_history(ref, full, limit)` | Lists a mutable artifact's version history (git commits), newest first, with authorship. Revert by reading an old version and writing it back. |
| `extract_source_prompt(url)` | Fetches any artifact URL (vanity domains included) and returns the source prompt from its hidden `<meta name="hypervault-source-prompt">` tag, so you can iterate on the original idea. |
| `delete_vault_item(slug_or_id)` | Permanently deletes an artifact (and its graph connections). Irreversible — the share URL stops working immediately. |
| `memorize(content, title, tags, source)` | Stores a chunk in the user's **private memory wiki** (Imaging V2). Auto-titled, auto-tagged, summarized, and linked to related memories in their knowledge graph. |
| `recall(query)` | Natural-language search over the wiki ("what did I say about the Rust borrow checker?"). Top matches return the exact stored content; every match lists its linked memories. |
| `list_memories()` | Browses everything memorized, newest first (summaries + tags). |
| `forget_memory(memory_id)` | Permanently deletes one memory — only on the user's explicit request. |

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
an old version's content (`read_artifact(ref, version=...)`) and write it back.
The write tools are owner-scoped (the API key resolves to its owner), so a
mutable artifact is read and written privately even when the page is public.

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

Every request carries your key in the `X-HyperVault-Key` header. Keys are
minted (and revoked) in the web dashboard; the backend stores only a SHA-256
hash and enforces 60 requests/minute per key.

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
