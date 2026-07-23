"""HyperVault MCP server (PRD 2).

Lets any MCP-capable agent save artifacts straight into a user's HyperVault
and claim vanity subdomains, by calling the same backend the web app uses.

Authentication differs by transport:

* STDIO (local agents) — a single trusted local user. The key comes from the
  HYPERVAULT_API_KEY environment variable, set once when the process starts.
* HTTP (the hosted deployment at https://mcp.vault.cool/mcp — a custom-domain
  alias for https://hypervault-mcp.vercel.app/mcp, shared by many callers) —
  every call must carry the *caller's own* key, sent per-request as either
  ``Authorization: Bearer hv_...`` or ``X-HyperVault-Key: hv_...``. There is
  no server-side fallback key for HTTP: an operator-configured
  HYPERVAULT_API_KEY environment variable, if set at all, is never used to
  answer someone else's request. The key is forwarded as-is to the real
  HyperVault backend (hypervault.store), which is the only place that ever
  looks it up (it stores just a salted SHA-256 hash) — this server never
  persists, logs, or validates keys itself.

Configuration (environment variables):
    HYPERVAULT_API_KEY   STDIO only — created in the web dashboard (/vault)
    HYPERVAULT_API_URL   optional — defaults to https://hypervault.store

Run over STDIO (local agents):
    hypervault-mcp

Run over HTTP (web agents):
    hypervault-mcp --transport http --host 0.0.0.0 --port 8787
"""

from __future__ import annotations

import argparse
import html as html_module
import os
import re
from typing import Any

import httpx
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers, get_http_request

DEFAULT_API_URL = "https://hypervault.store"
API_KEY_HEADER = "X-HyperVault-Key"
SOURCE_PROMPT_META_NAME = "hypervault-source-prompt"

# Artifact groups: multi-file containers (HTML/CSS/JS/JSX) that route through
# a root index.html, previewed/run in a JSFiddle-style container at
# https://hypervault.store/g/{slug}. Limits mirror the ~1 MB single-artifact
# guidance in save_to_hypervault's docs.
GROUP_INDEX_PATH = "index.html"
GROUP_ALLOWED_EXTENSIONS = (".html", ".css", ".js", ".jsx")
GROUP_MAX_FILES = 50
GROUP_MAX_FILE_BYTES = 256_000
GROUP_MAX_TOTAL_BYTES = 1_000_000
_GROUP_PATH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")

mcp = FastMCP(
    name="HyperVault",
    instructions=(
        "Save anything you create (HTML pages, React/JSX components, reports, "
        "games) permanently to the user's HyperVault, and claim memorable "
        "vanity subdomains like name.vault.cool. Every save returns a "
        "shareable, installable URL. Artifacts are immutable by default, but "
        "save one with mutable=true to get a living document you can rewrite: "
        "read_artifact reads it, write_artifact commits a new iteration, and "
        "artifact_history lists (and lets you revert) those git commits. "
        "For multi-file projects, use artifact groups instead: "
        "create_artifact_group bundles several .html/.css/.js/.jsx files "
        "behind a required root index.html and returns a JSFiddle-style "
        "run/preview URL; add_artifact_group_item, edit_artifact_group_item, "
        "and remove_artifact_group_item keep editing it after creation. "
        "HyperVault is also the user's long-term "
        "memory: memorize() stores chunks into their private LLM-wiki and "
        "recall() answers natural-language questions about what they've "
        "stored — use them whenever the user says 'remember this' or asks "
        "about something from a past session. The wiki is versioned like git "
        "(a 'git for a mind'): every write is a commit, and the mind_* tools "
        "branch, merge, diff, time-travel, and revert the user's memory."
    ),
)


class HyperVaultError(Exception):
    """Raised with a human-readable message when the backend rejects a call."""


def _extract_bearer_key(headers: dict[str, str]) -> str | None:
    """Pull an API key out of a lowercased header dict.

    Accepts ``X-HyperVault-Key`` directly, or a standard
    ``Authorization: Bearer <key>`` header (case-insensitive scheme).
    """
    direct = (headers.get(API_KEY_HEADER.lower()) or "").strip()
    if direct:
        return direct
    auth = (headers.get("authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        token = auth[len("bearer ") :].strip()
        if token:
            return token
    return None


def _in_http_request_context() -> bool:
    """True when running inside an active HTTP request (Streamable HTTP
    transport), as opposed to a local STDIO session."""
    try:
        get_http_request()
    except RuntimeError:
        return False
    return True


def _resolve_api_key() -> str:
    """Resolve the API key to use for the current call.

    Over HTTP, the key must come from the incoming request itself — every
    caller authenticates with their own key, and there is no shared
    server-side fallback. Over STDIO, the key comes from the
    HYPERVAULT_API_KEY environment variable, set once for the local process.
    """
    if _in_http_request_context():
        headers = get_http_headers(include_all=True)
        api_key = _extract_bearer_key(headers)
        if not api_key:
            raise HyperVaultError(
                "Authentication required. Pass your HyperVault API key "
                f"(create one in the web dashboard's Vault → Agent API keys) "
                f"as either '{API_KEY_HEADER}: hv_...' or "
                "'Authorization: Bearer hv_...' on every request."
            )
        return api_key

    api_key = os.environ.get("HYPERVAULT_API_KEY", "").strip()
    if not api_key:
        raise HyperVaultError(
            "HYPERVAULT_API_KEY is not set. Create a key in the HyperVault "
            "dashboard (Vault → Agent API keys) and export it before starting "
            "the server."
        )
    return api_key


def _client() -> httpx.Client:
    api_key = _resolve_api_key()
    base_url = os.environ.get("HYPERVAULT_API_URL", DEFAULT_API_URL).rstrip("/")
    return httpx.Client(
        base_url=base_url,
        headers={API_KEY_HEADER: api_key},
        timeout=30.0,
    )


def _request(
    method: str,
    path: str,
    json: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        with _client() as client:
            response = client.request(method, path, json=json, params=params)
    except httpx.HTTPError as exc:
        raise HyperVaultError(f"Could not reach HyperVault ({exc.__class__.__name__}): {exc}") from exc

    try:
        payload = response.json()
    except ValueError:
        payload = {}

    if response.status_code >= 400:
        error = payload.get("error") if isinstance(payload, dict) else None
        raise HyperVaultError(error or f"HyperVault returned HTTP {response.status_code}.")
    return payload


def _artifact_slug(ref: str) -> str:
    """Resolve an artifact reference to its slug.

    Accepts a bare slug ("my-game-x7k2p9") or a full HyperVault URL — including
    vanity-subdomain links — and returns the slug (the last path segment after
    /a/). Raises HyperVaultError on an empty or unusable reference.
    """
    cleaned = (ref or "").strip()
    if not cleaned:
        raise HyperVaultError("Pass the artifact's slug or URL.")
    match = re.search(r"/a/([^/?#]+)", cleaned)
    if match:
        return match.group(1)
    # Not a URL — treat it as a bare slug, but reject a stray protocol/host.
    if "://" in cleaned or "/" in cleaned:
        raise HyperVaultError(
            "Could not find an artifact slug in that reference — pass a slug like "
            "'my-game-x7k2p9' or a full URL like https://hypervault.store/a/my-game-x7k2p9."
        )
    return cleaned


def _artifact_group_slug(ref: str) -> str:
    """Resolve an artifact-group reference to its slug.

    Accepts a bare slug or a full HyperVault group URL (.../g/{slug},
    including vanity subdomains) and returns the slug. Raises
    HyperVaultError on an empty or unusable reference.
    """
    cleaned = (ref or "").strip()
    if not cleaned:
        raise HyperVaultError("Pass the artifact group's slug or URL.")
    match = re.search(r"/g/([^/?#]+)", cleaned)
    if match:
        return match.group(1)
    if "://" in cleaned or "/" in cleaned:
        raise HyperVaultError(
            "Could not find an artifact-group slug in that reference — pass a slug like "
            "'my-app-x7k2p9' or a full URL like https://hypervault.store/g/my-app-x7k2p9."
        )
    return cleaned


def _validate_group_item_path(path: Any) -> str:
    """Validate a single artifact-group item path, returning it cleaned.

    Enforces: non-empty, relative (no leading slash), no '..' traversal, no
    backslashes, a restricted safe charset, no empty/duplicate path
    segments, and one of the allowed file extensions
    (.html/.css/.js/.jsx). Raises HyperVaultError with a specific,
    actionable message on the first violation found.
    """
    if not isinstance(path, str):
        raise HyperVaultError(f"Item path {path!r} must be a string.")
    cleaned = path.strip()
    if not cleaned:
        raise HyperVaultError("Every artifact-group item needs a non-empty path.")
    if cleaned != path:
        raise HyperVaultError(f"Item path {path!r} has leading/trailing whitespace — pass it trimmed.")
    if cleaned.startswith("/") or cleaned.startswith("\\"):
        raise HyperVaultError(f"Item path {cleaned!r} must be relative (no leading slash).")
    if "\\" in cleaned:
        raise HyperVaultError(f"Item path {cleaned!r} may not contain backslashes — use '/' as the separator.")
    if ".." in cleaned.split("/"):
        raise HyperVaultError(f"Item path {cleaned!r} may not contain '..' path segments.")
    if "//" in cleaned or cleaned.endswith("/"):
        raise HyperVaultError(f"Item path {cleaned!r} is not a valid file path.")
    if not _GROUP_PATH_RE.match(cleaned):
        raise HyperVaultError(
            f"Item path {cleaned!r} may only contain letters, digits, '.', '_', '-', and '/' as a "
            "separator, and must start with a letter or digit."
        )
    last_segment = cleaned.rsplit("/", 1)[-1]
    if "." not in last_segment:
        raise HyperVaultError(f"Item path {cleaned!r} has no file extension.")
    ext = "." + last_segment.rsplit(".", 1)[-1].lower()
    if ext not in GROUP_ALLOWED_EXTENSIONS:
        raise HyperVaultError(
            f"Item path {cleaned!r} has an unsupported extension — artifact groups only accept "
            f"{', '.join(GROUP_ALLOWED_EXTENSIONS)} files."
        )
    return cleaned


def _validate_group_item_content(path: str, content: Any) -> str:
    """Validate a single item's content: must be a string within the
    per-file size cap. Returns the content unchanged."""
    if not isinstance(content, str):
        raise HyperVaultError(f"{path!r} content must be a string.")
    size = len(content.encode("utf-8"))
    if size > GROUP_MAX_FILE_BYTES:
        raise HyperVaultError(
            f"{path!r} is {size} bytes, over the {GROUP_MAX_FILE_BYTES}-byte per-file limit."
        )
    return content


def _normalize_group_files(files: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    """Validate and normalize a full artifact-group file set for creation.

    Requires at least one file, at most GROUP_MAX_FILES, unique paths
    (case-insensitive), a total size under GROUP_MAX_TOTAL_BYTES, and a
    root ``index.html`` — the entry point the run/preview container routes
    through. Each item must be an object with 'path' and 'content' keys;
    see _validate_group_item_path / _validate_group_item_content for the
    per-item rules.
    """
    if not files:
        raise HyperVaultError(
            "Pass at least one file: files=[{'path': 'index.html', 'content': '...'}, ...]."
        )
    if len(files) > GROUP_MAX_FILES:
        raise HyperVaultError(
            f"Too many files ({len(files)}) — artifact groups accept at most {GROUP_MAX_FILES}."
        )
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    total_bytes = 0
    for i, item in enumerate(files):
        if not isinstance(item, dict) or "path" not in item or "content" not in item:
            raise HyperVaultError(f"files[{i}] must be an object with 'path' and 'content' keys.")
        path = _validate_group_item_path(item["path"])
        content = _validate_group_item_content(path, item["content"])
        key = path.lower()
        if key in seen:
            raise HyperVaultError(f"Duplicate item path: {path!r}.")
        seen.add(key)
        total_bytes += len(content.encode("utf-8"))
        normalized.append({"path": path, "content": content})
    if total_bytes > GROUP_MAX_TOTAL_BYTES:
        raise HyperVaultError(
            f"Artifact group is {total_bytes} bytes total, over the {GROUP_MAX_TOTAL_BYTES}-byte limit."
        )
    if not any(f["path"] == GROUP_INDEX_PATH for f in normalized):
        raise HyperVaultError(
            f"Artifact groups must include a root {GROUP_INDEX_PATH!r} file — it's the entry point "
            "the run/preview container routes through. (A nested one like 'public/index.html' "
            "doesn't count.)"
        )
    return normalized


@mcp.tool
def save_to_hypervault(
    content: str,
    title: str = "Untitled",
    type: str = "html",
    tags: list[str] | None = None,
    connect_to: list[str] | None = None,
    make_pwa: bool = True,
    source_prompt: str | None = None,
    visibility: str = "private",
    mutable: bool = False,
) -> dict[str, Any]:
    """Save an artifact (HTML page, React/JSX component, report, game, etc.)
    permanently to the user's HyperVault and get back a shareable URL.

    React/JSX content is detected automatically and wrapped into a working
    standalone page — you can pass a bare component and it will just work.

    Args:
        content: The full HTML document or React/JSX source to save.
        title: Human-friendly title shown in the user's vault.
        type: Content hint: "html", "jsx", "report", "game", etc.
        tags: Optional tags for organizing the vault. Tags also power
            auto-connections: items sharing a tag get linked in graph view.
        connect_to: Titles or slugs of related artifacts. Creates
            bidirectional connections drawn as edges in the vault's graph view.
        make_pwa: When true (default), the page gets a manifest and
            Add-to-Home-Screen support so it installs like a native app.
        source_prompt: The prompt that produced this artifact (max 10,000
            chars). It is baked into the page as a
            <meta name="hypervault-source-prompt"> tag, so any agent that
            later opens the URL can read the original prompt and iterate on
            the artifact. Pass it whenever you have it.
        visibility: "private" (default) or "public". Private artifacts only
            open for the signed-in owner and accounts they invite from the
            vault dashboard; public ones open for anyone with the link.
        mutable: When true, save a *living document* you can rewrite later.
            A mutable artifact can be read with read_artifact and rewritten
            with write_artifact; every write is kept as a version (a git
            commit) you can list with artifact_history and revert to. Defaults
            to false — artifacts are immutable, and re-saving identical content
            just returns the existing link. Turn this on when you expect to
            iterate on the same artifact over time.

    Saving the exact same content twice is safe: HyperVault detects the
    duplicate and returns the existing artifact's URL (with `duplicate: true`)
    instead of creating a copy. (Mutable saves skip this — a living document is
    never a duplicate, so each mutable save creates its own artifact.)

    Returns:
        dict with `url` (the permanent artifact link), `slug`, `is_jsx`
        (whether JSX wrapping happened), `mutable` (whether it's a living
        document), `duplicate` (true when the content already existed and the
        existing link was returned), and a human-readable `message`.
    """
    payload = _request(
        "POST",
        "/api/save",
        json={
            "content": content,
            "title": title,
            "type": type,
            "tags": tags or [],
            "connect_to": connect_to or [],
            "make_pwa": make_pwa,
            "source_prompt": source_prompt or None,
            "visibility": visibility,
            "mutable": mutable,
        },
    )
    return payload


@mcp.tool
def read_artifact(ref: str, version: str | None = None) -> dict[str, Any]:
    """Read the current source of one of the user's artifacts, so you can
    iterate on it.

    Returns the *editable* source: the raw React/JSX for a JSX artifact (what
    the page re-wraps and renders), or the stored HTML otherwise — not the
    wrapped page chrome. Pair it with write_artifact to make an edit: read,
    modify the returned content, then write it back.

    Args:
        ref: The artifact's slug (e.g. "my-game-x7k2p9") or full URL
            (https://hypervault.store/a/my-game-x7k2p9, vanity domains work
            too).
        version: Optional version id (from artifact_history) to read a past
            iteration instead of the current head — useful to inspect or
            revert to an earlier commit.

    Returns:
        dict with `slug`, `title`, `content` (the editable source), `is_jsx`,
        `mutable` (whether it's a living document you can write to), the
        `content_hash`, and `version` (the commit this content came from, or
        null if the artifact has no recorded history).
    """
    slug = _artifact_slug(ref)
    params = {"version": version.strip()} if version and version.strip() else None
    return _request("GET", f"/api/artifacts/{slug}/content", params=params)


@mcp.tool
def write_artifact(
    ref: str,
    content: str,
    title: str | None = None,
    message: str | None = None,
    force_html: bool = False,
) -> dict[str, Any]:
    """Write a new iteration of a *mutable* artifact — a git commit on the
    living document.

    The artifact is updated to the new content in place (its URL never
    changes), and the write is kept as a version you can list with
    artifact_history and revert to. Only artifacts saved with mutable=true
    accept writes; an immutable artifact returns an error telling you to
    re-create it as mutable. React/JSX is auto-detected and re-wrapped, exactly
    like save_to_hypervault. Writing content identical to the current version
    is a no-op (returns `unchanged: true`, no new commit).

    Typical loop: read_artifact(ref) → modify the returned content →
    write_artifact(ref, new_content, message="what changed").

    Args:
        ref: The artifact's slug or full URL.
        content: The full new HTML or React/JSX source (replaces the current
            content; max 1 MB).
        title: Optional new title (omit to keep the current one).
        message: Optional commit message describing the change (default
            "edit"). It shows up in artifact_history.
        force_html: Pass true to store the content as plain HTML even if it
            looks like JSX (skips auto-wrapping).

    Returns:
        dict with `url`, `slug`, `is_jsx`, `unchanged` (true when the content
        matched the current version), the `version` this write recorded (id,
        message, created_at), and a human-readable `message`.
    """
    slug = _artifact_slug(ref)
    if not content or not content.strip():
        raise HyperVaultError("Pass the new content to write.")
    return _request(
        "PUT",
        f"/api/artifacts/{slug}/content",
        json={
            "content": content,
            "title": title,
            "message": message,
            "force_html": force_html,
        },
    )


@mcp.tool
def artifact_history(ref: str, full: bool = False, limit: int = 50) -> dict[str, Any]:
    """List the version history (git commits) of a mutable artifact, newest
    first.

    Each entry carries the commit message, its author (you'll appear as your
    API key prefix), the content fingerprint, and whether it's the current head.
    Use the returned version ids with read_artifact(ref, version=...) to inspect
    an old iteration, or write its content back to revert.

    Args:
        ref: The artifact's slug or full URL.
        full: When true, include each version's full stored content.
        limit: Max versions to return (default 50, max 200).

    Returns:
        dict with `slug`, `mutable`, and `versions`: [{id, parent_version_id,
        title, message, author_kind, author_key_prefix, content_hash, is_jsx,
        is_head, created_at, content (when full)}], newest first.
    """
    slug = _artifact_slug(ref)
    params: dict[str, Any] = {"limit": limit}
    if full:
        params["full"] = "1"
    return _request("GET", f"/api/artifacts/{slug}/versions", params=params)


@mcp.tool
def claim_vanity_subdomain(desired_name: str, base_domain: str = "vault.cool") -> dict[str, Any]:
    """Claim a vanity subdomain (e.g. nova.vault.cool) for the user's vault.

    The claim takes effect immediately — the address serves the user's public
    vault as soon as this returns. Names are lowercase letters, digits, and
    hyphens, 2–63 characters. Pro accounts can hold up to 10 subdomains, and
    every one of them serves the user's full vault.

    Args:
        desired_name: The subdomain to claim (just the name, e.g. "nova").
        base_domain: Base domain from the HyperVault portfolio.
            Defaults to "vault.cool".

    Returns:
        dict with `domain`, `url`, and a celebratory `message` on success.
    """
    return _request(
        "POST",
        "/api/claim-domain",
        json={"desired_name": desired_name, "base_domain": base_domain},
    )


@mcp.tool
def connect_vault_items(source: str, target: str) -> dict[str, Any]:
    """Connect two items already in the user's HyperVault.

    Items can be artifacts or memories, in any combination: artifact↔artifact,
    memory↔memory, or memory↔artifact (a semantic bridge between the wiki and
    the vault). Connections are bidirectional and appear as edges in the
    vault's graph view. Use list_my_vault_items or recall_from_memory first to
    find the right items.

    Args:
        source: Id, slug, or exact title of the first artifact — or the id or
            exact title of a memory.
        target: Id, slug, or exact title of the item to connect it to.

    Returns:
        dict with `connected` (the two item ids) and a `message`.
    """
    return _request("POST", "/api/connections", json={"source": source, "target": target})


@mcp.tool
def list_my_vault_items() -> dict[str, Any]:
    """List the artifacts already saved in the user's HyperVault.

    Useful before saving (to avoid duplicates), or to link new artifacts to
    existing ones via save_to_hypervault's connect_to parameter.

    Returns:
        dict with `items`: a list of {url, slug, title, type, tags, is_pwa,
        is_jsx, created_at}, newest first.
    """
    return _request("GET", "/api/artifacts")


@mcp.tool
def delete_vault_item(slug_or_id: str) -> dict[str, Any]:
    """Permanently delete an artifact from the user's HyperVault.

    Deletion is immediate and irreversible: the share URL stops working and
    the item's graph connections are removed. Use list_my_vault_items first
    to find the right item, and only delete when the user clearly asks.

    Args:
        slug_or_id: The artifact's slug (the last path segment of its URL,
            e.g. "my-game-x7k2p9") or its id.

    Returns:
        dict with `deleted` ({id, slug, title}) and a confirmation `message`.
    """
    ref = slug_or_id.strip()
    if not ref:
        raise HyperVaultError("Pass the artifact's slug or id to delete.")
    key = "id" if re.fullmatch(r"[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", ref) else "slug"
    return _request("DELETE", "/api/artifacts", json={key: ref})


@mcp.tool
def create_artifact_group(
    files: list[dict[str, str]],
    title: str = "Untitled",
    tags: list[str] | None = None,
    connect_to: list[str] | None = None,
    visibility: str = "private",
    source_prompt: str | None = None,
) -> dict[str, Any]:
    """Save a multi-file "artifact group" — several .html/.css/.js/.jsx
    files that run together as one project — to the user's HyperVault.

    Unlike save_to_hypervault (a single file), a group bundles a whole
    little project: markup, styles, and script(s) as separate files that
    reference each other normally (e.g. `<link href="style.css">`,
    `<script src="app.js">`). It is always run/previewed as a container,
    similar to a JSFiddle: the returned URL opens a minimal editor/preview
    UI where the files render together, routed through the required root
    `index.html`.

    Args:
        files: The group's files, e.g.
            [{"path": "index.html", "content": "<html>...</html>"},
             {"path": "style.css", "content": "body { ... }"},
             {"path": "app.js", "content": "console.log('hi')"}].
            Rules (validated locally before any network call):
            - Must include exactly one root file at path "index.html" —
              the entry point the container routes through. A nested one
              like "public/index.html" does not count.
            - Paths must be relative, use '/' separators, contain no '..'
              segments, and only [A-Za-z0-9._/-] characters.
            - Extensions are limited to .html, .css, .js, .jsx.
            - At most 50 files; 256 KB per file; 1 MB total.
            - Paths must be unique (case-insensitively).
        title: Human-friendly title shown in the user's vault.
        tags: Optional tags for organizing the vault (also power
            auto-connections between items sharing a tag).
        connect_to: Titles or slugs of related artifacts/groups to link.
        visibility: "private" (default) or "public".
        source_prompt: The prompt that produced this group, if any — baked
            in the same way save_to_hypervault embeds it, so a later agent
            can read it back and iterate.

    Returns:
        dict with `url` (the group's permanent, shareable run/preview
        link), `slug`, `preview_url`, the normalized `files`, and a
        human-readable `message`.
    """
    normalized_files = _normalize_group_files(files)
    payload = _request(
        "POST",
        "/api/artifact-groups",
        json={
            "files": normalized_files,
            "title": title,
            "tags": tags or [],
            "connect_to": connect_to or [],
            "visibility": visibility,
            "source_prompt": source_prompt or None,
        },
    )
    return payload


@mcp.tool
def read_artifact_group(ref: str) -> dict[str, Any]:
    """Read an artifact group's full file set and metadata, so you can
    iterate on it (e.g. before calling edit_artifact_group_item).

    Args:
        ref: The group's slug (e.g. "my-app-x7k2p9") or full URL
            (https://hypervault.store/g/my-app-x7k2p9, vanity domains work
            too).

    Returns:
        dict with `slug`, `title`, `files` ([{path, content}, ...]),
        `preview_url`, `visibility`, and timestamps.
    """
    slug = _artifact_group_slug(ref)
    return _request("GET", f"/api/artifact-groups/{slug}")


@mcp.tool
def list_artifact_groups() -> dict[str, Any]:
    """List the artifact groups already saved in the user's HyperVault.

    Useful before creating a new one (to avoid duplicates) or to find a
    slug to pass to read_artifact_group / add_artifact_group_item / etc.

    Returns:
        dict with `items`: a list of {url, slug, title, tags, file_count,
        visibility, created_at}, newest first.
    """
    return _request("GET", "/api/artifact-groups")


@mcp.tool
def add_artifact_group_item(ref: str, path: str, content: str) -> dict[str, Any]:
    """Add a new file to an existing artifact group.

    Fails if a file already exists at that path — use
    edit_artifact_group_item to change one, or read_artifact_group first if
    you're not sure what's already there.

    Args:
        ref: The group's slug or full URL.
        path: The new file's path (e.g. "styles/theme.css"). Same rules as
            create_artifact_group: relative, no '..', [A-Za-z0-9._/-] only,
            one of .html/.css/.js/.jsx, at most 256 KB.
        content: The file's full content.

    Returns:
        dict with the updated `files` list, the added item's `path`, and a
        `message`.
    """
    slug = _artifact_group_slug(ref)
    clean_path = _validate_group_item_path(path)
    clean_content = _validate_group_item_content(clean_path, content)
    return _request(
        "POST",
        f"/api/artifact-groups/{slug}/items",
        json={"path": clean_path, "content": clean_content},
    )


@mcp.tool
def edit_artifact_group_item(ref: str, path: str, content: str) -> dict[str, Any]:
    """Replace the content of an existing file in an artifact group.

    Fails if no file exists at that path yet — use add_artifact_group_item
    to create one. This is also how you update index.html itself.

    Args:
        ref: The group's slug or full URL.
        path: The existing file's path to overwrite.
        content: The new full content for that file (replaces the old
            content entirely; max 256 KB).

    Returns:
        dict with the updated `files` list, the edited item's `path`, and a
        `message`.
    """
    slug = _artifact_group_slug(ref)
    clean_path = _validate_group_item_path(path)
    clean_content = _validate_group_item_content(clean_path, content)
    return _request(
        "PUT",
        f"/api/artifact-groups/{slug}/items",
        json={"path": clean_path, "content": clean_content},
    )


@mcp.tool
def remove_artifact_group_item(ref: str, path: str) -> dict[str, Any]:
    """Remove a file from an artifact group.

    The root index.html can't be removed this way — a group must always
    keep its entry point. Replace its content with
    edit_artifact_group_item instead, or delete the whole group with
    delete_artifact_group if you no longer need it.

    Args:
        ref: The group's slug or full URL.
        path: The file's path to remove.

    Returns:
        dict with the updated `files` list, the removed `path`, and a
        `message`.
    """
    slug = _artifact_group_slug(ref)
    clean_path = _validate_group_item_path(path)
    if clean_path == GROUP_INDEX_PATH:
        raise HyperVaultError(
            f"Can't remove the root {GROUP_INDEX_PATH!r} — a group must always keep its entry "
            "point. Use edit_artifact_group_item to change its content, or delete_artifact_group "
            "to remove the whole group."
        )
    return _request(
        "DELETE",
        f"/api/artifact-groups/{slug}/items",
        json={"path": clean_path},
    )


@mcp.tool
def delete_artifact_group(slug_or_id: str) -> dict[str, Any]:
    """Permanently delete an artifact group from the user's HyperVault.

    Deletion is immediate and irreversible: the share/preview URL stops
    working and the group's graph connections are removed. Use
    list_artifact_groups first to find the right one, and only delete when
    the user clearly asks.

    Args:
        slug_or_id: The group's slug (the last path segment of its URL,
            e.g. "my-app-x7k2p9") or its id.

    Returns:
        dict with `deleted` ({id, slug, title}) and a confirmation
        `message`.
    """
    ref = slug_or_id.strip()
    if not ref:
        raise HyperVaultError("Pass the artifact group's slug or id to delete.")
    key = "id" if re.fullmatch(r"[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", ref) else "slug"
    return _request("DELETE", "/api/artifact-groups", json={key: ref})


@mcp.tool
def memorize(
    content: str,
    title: str | None = None,
    tags: list[str] | None = None,
    source: str = "agent",
    branch: str | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    """Store a chunk of context in the user's private memory wiki (Imaging V2).

    Call this whenever the user says "remember this", "memorize this", or
    shares a decision, preference, or insight worth keeping beyond this
    session. The backend auto-titles, auto-tags, and summarizes the chunk,
    then links it to related memories in the user's knowledge graph.
    Memories are private to the user — they never appear on public pages.

    Args:
        content: The text to memorize — a conclusion, a code insight, a
            decision, meeting notes, anything worth recalling later.
        title: Optional title; when omitted one is derived from the content.
        tags: Optional extra tags; auto-extracted tags are added regardless.
        source: Where this came from: "chat", "coding", "agent" (default),
            or "manual".
        branch: Optional mind branch to write on (default "main"). Create
            branches with mind_branch to explore ideas without touching main.
        message: Optional commit message (default "memorize: <title>").

    Returns:
        dict with `id`, the derived `title`, `summary`, `tags`, `links`
        (how many related memories it was connected to), the `branch` and
        `commit_id` the write landed as, and a `message`.
    """
    return _request(
        "POST",
        "/api/memories",
        json={
            "content": content,
            "title": title,
            "tags": tags or [],
            "source": source,
            "branch": branch,
            "message": message,
        },
    )


@mcp.tool
def recall(query: str, branch: str | None = None) -> dict[str, Any]:
    """Search the user's private memory wiki with a natural-language query.

    Use this to answer questions like "what did I say about the Rust borrow
    checker last month?" — it combines full-text search with relevance
    scoring over the user's stored memories. The top matches include the
    exact stored content; the rest return summaries. Each result also lists
    the titles of linked memories, so you can follow the knowledge graph
    with further recall calls.

    Args:
        query: What to look for, in plain language (e.g. "rust borrow
            checker", "deployment checklist we agreed on").
        branch: Optional mind branch to search (default "main").

    Returns:
        dict with `results`: a relevance-ranked list of {id, title, summary,
        tags, source, created_at, score, content (top matches only),
        related (titles of linked memories), provenance (the commit that
        last touched it: who wrote it and when)}, plus a `message`.
    """
    query = query.strip()
    if not query:
        raise HyperVaultError("Pass a non-empty query — what should I recall?")
    params: dict[str, Any] = {"q": query}
    if branch:
        params["branch"] = branch
    return _request("GET", "/api/memories", params=params)


@mcp.tool
def list_memories(branch: str | None = None) -> dict[str, Any]:
    """List everything in the user's private memory wiki, newest first.

    Useful for a broad look at what the user has memorized before deciding
    what to recall in detail — each entry carries the summary and tags, not
    the full content.

    Args:
        branch: Optional mind branch to list (default "main").

    Returns:
        dict with `memories`: a list of {id, title, summary, tags, source,
        created_at}, newest first.
    """
    return _request("GET", "/api/memories", params={"branch": branch} if branch else None)


@mcp.tool
def forget_memory(memory_id: str, branch: str | None = None) -> dict[str, Any]:
    """Delete one memory from the user's wiki (recorded as a delete commit).

    Only call this when the user explicitly asks to forget or delete a
    memory. The memory's knowledge-graph links are removed with it. The
    deletion is a commit, so the page stays in history and can be restored
    with mind_revert.

    Args:
        memory_id: The memory's id, as returned by memorize/recall/list_memories.
        branch: Optional mind branch to forget on (default "main").

    Returns:
        dict with `deleted` (the id) and a confirmation `message`.
    """
    memory_id = memory_id.strip()
    if not memory_id:
        raise HyperVaultError("Pass the memory id to forget (see list_memories or recall).")
    return _request(
        "DELETE",
        f"/api/memories/{memory_id}",
        params={"branch": branch} if branch else None,
    )


@mcp.tool
def edit_memory(
    memory_id: str,
    content: str | None = None,
    title: str | None = None,
    tags: list[str] | None = None,
    message: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Edit a wiki page — the change lands as an update commit, never
    overwriting history (see memory_history for the page's revisions).

    Content edits re-derive the summary and merge in fresh auto-tags; new
    knowledge-graph links ride in the same commit.

    Args:
        memory_id: The memory to edit.
        content: New content (omit to keep the current text).
        title: New title (omit to keep).
        tags: Replacement tag list (omit to keep/auto-derive).
        message: Optional commit message (default "edit: <title>").
        branch: Optional mind branch to edit on (default "main").

    Returns:
        dict with the updated `title`, `summary`, `tags`, the `commit_id`
        recorded, and a `message`.
    """
    memory_id = memory_id.strip()
    if not memory_id:
        raise HyperVaultError("Pass the memory id to edit.")
    return _request(
        "PATCH",
        f"/api/memories/{memory_id}",
        json={"content": content, "title": title, "tags": tags, "message": message, "branch": branch},
    )


@mcp.tool
def memory_history(memory_id: str, full: bool = False, limit: int = 50) -> dict[str, Any]:
    """Every revision of one wiki page, newest first — its edit history.

    Each revision carries the commit that produced it: message, author (the
    user, or the agent key prefix that wrote it), branch, and time. Pass a
    revision_id to mind_revert to restore an old version.

    Args:
        memory_id: The memory whose history to read.
        full: When true, include the full content snapshot of each revision.
        limit: Max revisions to return (default 50).

    Returns:
        dict with `revisions`: [{revision_id, op, title, summary, tags,
        content (when full), commit: {id, message, author_kind,
        author_key_prefix, branch, created_at}}].
    """
    memory_id = memory_id.strip()
    if not memory_id:
        raise HyperVaultError("Pass the memory id whose history you want.")
    params: dict[str, Any] = {"limit": limit}
    if full:
        params["full"] = "1"
    return _request("GET", f"/api/memories/{memory_id}/history", params=params)


@mcp.tool
def mind_log(branch: str | None = None, limit: int = 50) -> dict[str, Any]:
    """`git log` for the user's mind: the branch's commit history, newest
    first, with per-commit change counts and authorship.

    Args:
        branch: Branch to read (default "main").
        limit: Max commits (default 50).

    Returns:
        dict with `commits`: [{id, message, author_kind, author_key_prefix,
        parent_commit_id, merge_parent_commit_id, created_at,
        change_counts: {created, updated, deleted, links}}].
    """
    params: dict[str, Any] = {"limit": limit}
    if branch:
        params["branch"] = branch
    return _request("GET", "/api/mind/commits", params=params)


@mcp.tool
def mind_branches() -> dict[str, Any]:
    """List the branches of the user's mind, with live memory counts.

    Returns:
        dict with `branches`: [{id, name, is_default, head_commit_id,
        created_at, memory_count}].
    """
    return _request("GET", "/api/mind/branches")


@mcp.tool
def mind_branch(name: str, from_ref: str | None = None) -> dict[str, Any]:
    """Branch the user's ideas: fork the wiki so edits, new memories, and
    forgets there don't touch the source branch until merged.

    Branch names are lowercase letters, digits, and /_- (max 63 chars).

    Args:
        name: The new branch's name (e.g. "ideas", "research/quantum").
        from_ref: Branch to fork from (default "main").

    Returns:
        dict with the new branch's `id`, `name`, `from`, and a `message`.
    """
    name = name.strip()
    if not name:
        raise HyperVaultError("Pass a branch name.")
    return _request("POST", "/api/mind/branches", json={"name": name, "from": from_ref})


@mcp.tool
def mind_diff(from_ref: str, to_ref: str, memory_id: str | None = None) -> dict[str, Any]:
    """Diff the user's mind between two refs — branch names, commit ids, or
    timestamps ("what changed in my memory since last week?").

    Without memory_id: memories added/changed/removed (with content hunks)
    and links added/removed. With memory_id: just that page's diff.

    Args:
        from_ref: The older ref (branch, commit id, or ISO timestamp).
        to_ref: The newer ref.
        memory_id: Optional — diff a single memory instead of the whole graph.

    Returns:
        Graph mode: dict with `memories` {added, removed, changed} and
        `links` {added, removed}. Single-memory mode: dict with `diff`
        (hunks of add/del/ctx lines), `title_from/to`, `tags_added/removed`.
    """
    params: dict[str, Any] = {"from": from_ref, "to": to_ref}
    if memory_id:
        params["memory_id"] = memory_id
    return _request("GET", "/api/mind/diff", params=params)


@mcp.tool
def mind_merge(
    source: str,
    target: str = "main",
    message: str | None = None,
    resolutions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Merge understanding: fold a branch into a target (default main) with a
    three-way merge from their common ancestor.

    Memories only one side touched merge automatically; links merge
    set-wise. If both sides changed the same memory the call fails with the
    conflict list (each has base/ours/theirs snapshots and hunks) — resolve
    by calling again with resolutions like
    [{"memory_id": "...", "resolution": "theirs"}] or
    [{"memory_id": "...", "resolution": {"title": "...", "content": "..."}}]
    for a hand-merged version. Relay conflicts to the user when the choice
    isn't obvious.

    Args:
        source: Branch to merge from.
        target: Branch to merge into (default "main").
        message: Optional merge-commit message.
        resolutions: Conflict resolutions from a previous attempt.

    Returns:
        dict with `commit_id` (the merge commit), `merged` counts
        {created, updated, deleted}, `links_changed`, and a `message`.
    """
    return _request(
        "POST",
        "/api/mind/merge",
        json={"source": source, "target": target, "message": message, "resolutions": resolutions},
    )


@mcp.tool
def mind_revert(memory_id: str, revision_id: str, branch: str | None = None) -> dict[str, Any]:
    """Restore a memory to an earlier revision — including undeleting a
    forgotten one. History is never rewritten: the restore lands as a new
    commit.

    Find revision ids with memory_history.

    Args:
        memory_id: The memory to restore.
        revision_id: The revision to restore it to.
        branch: Branch to restore on (default "main").

    Returns:
        dict with `commit_id`, `restored` {memory_id, title, revision_id},
        and a `message`.
    """
    return _request(
        "POST",
        "/api/mind/revert",
        json={"memory_id": memory_id, "revision_id": revision_id, "branch": branch},
    )


@mcp.tool
def mind_state(at: str, branch: str | None = None) -> dict[str, Any]:
    """Time-travel: the whole wiki (memories + links) as it stood at a commit,
    branch head, or moment in time.

    Args:
        at: A commit id, branch name, or ISO timestamp (e.g.
            "2026-06-01T00:00:00Z" for "my mind as of June 1st").
        branch: Branch whose history timestamps resolve along (default "main").

    Returns:
        dict with `commit_id`, `memories` (summaries), `links`, and a
        `message`.
    """
    params: dict[str, Any] = {"at": at}
    if branch:
        params["branch"] = branch
    return _request("GET", "/api/mind/state", params=params)


def _find_source_prompt_meta(page_html: str) -> str | None:
    """Pull the hidden source-prompt meta tag out of artifact HTML.

    Tolerates either attribute order (name-first is what HyperVault emits) and
    single- or double-quoted attributes; HTML entities are unescaped.
    """
    meta_name = re.escape(SOURCE_PROMPT_META_NAME)
    patterns = [
        rf'<meta[^>]*name=["\']{meta_name}["\'][^>]*content=["\'](.*?)["\']',
        rf'<meta[^>]*content=["\'](.*?)["\'][^>]*name=["\']{meta_name}["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, page_html, re.IGNORECASE | re.DOTALL)
        if match:
            return html_module.unescape(match.group(1))
    return None


@mcp.tool
def extract_source_prompt(url: str) -> dict[str, Any]:
    """Extract the original source prompt from a HyperVault artifact URL.

    HyperVault artifacts can carry the prompt that generated them as a hidden
    <meta name="hypervault-source-prompt"> tag. Call this when the user shares
    a HyperVault link (including vanity-subdomain links) and you want to
    understand or iterate on the artifact — the returned prompt tells you the
    original intent, so you can reply like: "This was originally generated
    from: '…' — here's an improved version with X."

    Args:
        url: The artifact's full URL (e.g. https://hypervault.store/a/my-game).

    Returns:
        dict with `found` (bool), `source_prompt` (the extracted prompt, or
        None), the fetched `url`, and a human-readable `message`.
    """
    cleaned = url.strip()
    if not re.match(r"^https?://", cleaned, re.IGNORECASE):
        raise HyperVaultError("Pass a full artifact URL, starting with http:// or https://.")

    # Preferred path: the backend resolves the URL from its own database
    # (GET /api/extract). That keeps this server single-host — every tool
    # call goes to the API origin only, so it works inside deny-by-default
    # sandboxes like greywall — and it resolves private artifacts the key's
    # owner can open. Backends that predate the endpoint fall through to the
    # legacy page fetch below.
    try:
        payload = _request("GET", "/api/extract", params={"url": cleaned})
        if "found" in payload:
            return payload
    except HyperVaultError:
        pass

    # Legacy path: artifact pages are public — fetched without the API key so
    # the key is never sent to arbitrary hosts (vanity domains included).
    try:
        response = httpx.get(cleaned, follow_redirects=True, timeout=30.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HyperVaultError(
            f"Could not fetch the artifact page ({exc.__class__.__name__}): {exc}"
        ) from exc

    prompt = _find_source_prompt_meta(response.text)
    if prompt is None:
        return {
            "found": False,
            "source_prompt": None,
            "url": url,
            "message": (
                "No source prompt is embedded in this artifact — it was saved "
                "without one. You can still iterate on the page content itself."
            ),
        }
    return {
        "found": True,
        "source_prompt": prompt,
        "url": url,
        "message": "Source prompt extracted — use it to understand the original intent and build on it.",
    }


@mcp.resource("hypervault://help")
def get_vault_help() -> str:
    """How to use HyperVault from an agent."""
    return (
        "# HyperVault — agent quickstart\n\n"
        "HyperVault is the user's permanent home for AI-created artifacts.\n\n"
        "## Tools\n"
        "1. save_to_hypervault(content, title, type, tags, connect_to,\n"
        "   make_pwa, source_prompt, visibility)\n"
        "   Save HTML or React/JSX. JSX is auto-detected and wrapped into a\n"
        "   runnable page. Returns a permanent URL the user can share and\n"
        "   install to their home screen. Pass source_prompt (the prompt that\n"
        "   produced the artifact) whenever you have it — it is embedded as\n"
        "   <meta name=\"hypervault-source-prompt\"> in the page. Re-saving\n"
        "   identical content returns the existing URL (duplicate: true)\n"
        "   instead of creating a copy. New artifacts are private by default\n"
        "   (only the owner and invited accounts can open them); pass\n"
        "   visibility='public' for a link anyone can open. Pass mutable=true\n"
        "   for a living document you can rewrite later (see Mutable artifacts).\n"
        "2. claim_vanity_subdomain(desired_name, base_domain='vault.cool')\n"
        "   Give the user a memorable address like nova.vault.cool. Works\n"
        "   immediately.\n"
        "3. list_my_vault_items()\n"
        "   See what's already saved; use connect_to to link related items.\n"
        "4. connect_vault_items(source, target)\n"
        "   Link two existing artifacts. Connections are bidirectional and\n"
        "   show up as edges in the vault's graph view.\n"
        "5. extract_source_prompt(url)\n"
        "   Given any HyperVault artifact URL (vanity domains included),\n"
        "   returns the original prompt that generated it.\n"
        "6. delete_vault_item(slug_or_id)\n"
        "   Permanently remove an artifact (and its graph connections).\n"
        "   Irreversible — only when the user clearly asks.\n\n"
        "## Artifact groups (multi-file HTML/CSS/JS/JSX projects)\n"
        "Use these instead of save_to_hypervault when a project needs more\n"
        "than one file — separate markup, styles, and script(s) that\n"
        "reference each other normally. A group always runs/previews as a\n"
        "JSFiddle-style container at https://hypervault.store/g/{slug},\n"
        "routed through a required root index.html.\n"
        "7. create_artifact_group(files, title, tags, connect_to,\n"
        "   visibility, source_prompt)\n"
        "   files is [{\"path\": ..., \"content\": ...}, ...]. Must include a\n"
        "   root \"index.html\"; extensions limited to .html/.css/.js/.jsx;\n"
        "   paths must be relative with no '..'; at most 50 files, 256 KB\n"
        "   per file, 1 MB total. Validated locally before any network call.\n"
        "   Returns the run/preview `url` and `slug`.\n"
        "8. read_artifact_group(ref)\n"
        "   Read a group's full file set and metadata by slug or URL.\n"
        "9. list_artifact_groups()\n"
        "   List the user's saved groups.\n"
        "10. add_artifact_group_item(ref, path, content)\n"
        "    Add a new file to an existing group (fails if that path\n"
        "    already exists).\n"
        "11. edit_artifact_group_item(ref, path, content)\n"
        "    Replace an existing file's content, including index.html\n"
        "    itself (fails if that path doesn't exist yet).\n"
        "12. remove_artifact_group_item(ref, path)\n"
        "    Remove a file from a group. The root index.html can't be\n"
        "    removed this way — edit it instead, or delete the whole group.\n"
        "13. delete_artifact_group(slug_or_id)\n"
        "    Permanently delete a group. Irreversible — only when the user\n"
        "    clearly asks.\n\n"
        "## Memory (the user's private LLM-wiki)\n"
        "14. memorize(content, title, tags, source)\n"
        "   Store a chunk in the user's private memory wiki. It is\n"
        "   auto-titled, auto-tagged, summarized, and linked to related\n"
        "   memories in their knowledge graph. Use whenever the user says\n"
        "   'remember this' or something is clearly worth keeping.\n"
        "15. recall(query)\n"
        "   Natural-language search over the wiki ('what did I say about\n"
        "   the Rust borrow checker?'). Top matches include the exact\n"
        "   stored content plus titles of linked memories to follow.\n"
        "16. list_memories()\n"
        "   Browse everything memorized, newest first (summaries only).\n"
        "17. forget_memory(memory_id, branch=None)\n"
        "   Delete a memory — only on the user's explicit request. It is\n"
        "   recorded as a delete commit, so mind_revert can undelete it.\n"
        "Memories are private to the user and never appear on public\n"
        "pages; the wiki UI lives at /vault/memory.\n\n"
        "## Git for your mind (versioned memory)\n"
        "The wiki is version-controlled like git: every memorize/edit/forget\n"
        "is a commit with full provenance (who wrote it — you'll appear as\n"
        "your key prefix). Nothing is ever lost; history is append-only.\n"
        "18. edit_memory(memory_id, content, title, tags, message, branch)\n"
        "    Edit a wiki page as an update commit.\n"
        "19. memory_history(memory_id, full, limit)\n"
        "    A page's revisions with their commits — its edit history.\n"
        "20. mind_log(branch, limit) — commit history of a branch.\n"
        "21. mind_branches() / mind_branch(name, from_ref)\n"
        "    List branches / fork a new one. Writes take branch=... so you\n"
        "    can explore ideas without touching main.\n"
        "22. mind_diff(from_ref, to_ref, memory_id=None)\n"
        "    What changed between two branches/commits/timestamps —\n"
        "    memories added/changed/removed with hunks, links added/removed.\n"
        "23. mind_merge(source, target='main', resolutions=None)\n"
        "    Three-way merge a branch in; conflicts come back with\n"
        "    base/ours/theirs for you (or the user) to resolve.\n"
        "24. mind_revert(memory_id, revision_id, branch=None)\n"
        "    Restore an old revision (or undelete) as a new commit.\n"
        "25. mind_state(at, branch=None)\n"
        "    Time-travel: the whole wiki as of a commit or timestamp.\n\n"
        "## Mutable artifacts (a living document you can rewrite)\n"
        "Artifacts are immutable by default — a save is permanent and re-saving\n"
        "identical content just returns the existing link. Save with\n"
        "mutable=true instead to get a document you can iterate on in place; its\n"
        "URL never changes and every write is kept as a git commit.\n"
        "26. read_artifact(ref, version=None)\n"
        "    Read an artifact's current editable source (raw JSX for JSX\n"
        "    artifacts, HTML otherwise). ref is a slug or full URL. Pass a\n"
        "    version id to read a past iteration.\n"
        "27. write_artifact(ref, content, title=None, message=None,\n"
        "    force_html=False)\n"
        "    Commit a new iteration of a mutable artifact. The page updates in\n"
        "    place and the write is recorded as a version. Only mutable\n"
        "    artifacts accept writes. Loop: read_artifact → edit → write_artifact.\n"
        "28. artifact_history(ref, full=False, limit=50)\n"
        "    List the commits, newest first, with authorship. Revert by reading\n"
        "    an old version's content and writing it back.\n\n"
        "## Iterating on an existing artifact\n"
        "Call extract_source_prompt(url) — or fetch the page and read the\n"
        "<meta name=\"hypervault-source-prompt\"> tag in <head> — that is the\n"
        "prompt that created it. Combine it with the user's new request,\n"
        "regenerate, and save (optionally with connect_to linking back).\n\n"
        "## Polytician interop\n"
        "HyperVault also speaks Polytician's AgentVault REST contract, so a\n"
        "Polytician MCP server (github.com/johnnyclem/polytician) can sync its\n"
        "concepts straight into this versioned wiki with no code changes — set\n"
        "its apiBaseUrl to this deployment and apiToken to an hv_ API key. See\n"
        "docs/polytician.md. You don't call these endpoints yourself; Polytician\n"
        "does. Synced concepts land on the 'polytician-main' branch — merge it\n"
        "into main (mind_merge) to fold them into everyday recall.\n\n"
        "## Tips\n"
        "- Always pass a descriptive title — it becomes the page title and\n"
        "  home-screen app name.\n"
        "- Keep artifacts under 1 MB (inline assets count).\n"
        "- On errors, the message explains exactly what to fix; relay it to\n"
        "  the user when action is needed (e.g. creating an API key).\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="hypervault-mcp",
        description="HyperVault MCP server — save artifacts and claim vanity domains.",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="stdio for local agents (default), http for web agents",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host")
    parser.add_argument("--port", type=int, default=8787, help="HTTP bind port")
    args = parser.parse_args()

    if args.transport == "http":
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        mcp.run()  # stdio


if __name__ == "__main__":
    main()
