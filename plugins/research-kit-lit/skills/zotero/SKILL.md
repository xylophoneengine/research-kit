---
name: zotero
description: Use before any Zotero MCP write (zotero_add_item, zotero_attach_file, tags, collections, zotero_update_item, zotero_batch_update) and whenever the Zotero MCP misbehaves in a new repo. Holds the tested procedure, the preflight script, recipes and the stop conditions that keep PDFs off zotero.org storage.
---

# Zotero (MCP) -- tested procedure

Hard rule: file bodies never go to zotero.org storage (300 MB quota). They
sync only through Zotero desktop's own file sync to your WebDAV server
(see Setup). Any doubt, any stop
condition below = notify the user (via the lead if you are a teammate) and ask
for guidance. Never silently skip, never engineer around it.

Metadata writes (add item, tag, collections) do not move files and are safe
once step 1 passes. Attachments additionally need step R7.

## Setup (once per machine; the preflight checks it)

- Zotero desktop 7+ (local MCP writes need 10+): Settings > Sync > File
  Syncing = WebDAV (your own server); Settings > Advanced > allow other
  applications to communicate with Zotero (local API on 127.0.0.1:23119).
- Zotero MCP server env block: `ZOTERO_LOCAL=true`,
  `ZOTERO_SEARCH_BACKEND=sqlite`, and `ZOTERO_API_KEY=""`. The empty key
  masks any key your shell exports, so the MCP has no path to zotero.org.
- Optional, for `--file-check` only: export a read-only `ZOTERO_API_KEY` and
  `ZOTERO_LIBRARY_ID` in your shell (never in the MCP env).

## 0. Load the tools

Zotero tools are deferred: calling one before loading it fails with
InputValidationError. Load once, in ONE call:

    ToolSearch select:mcp__zotero__zotero_write_capabilities,mcp__zotero__zotero_add_item,mcp__zotero__zotero_batch_update,mcp__zotero__zotero_search_items,mcp__zotero__zotero_search_collections,mcp__zotero__zotero_create_collection,mcp__zotero__zotero_set_item_collections,mcp__zotero__zotero_get_collection_items,mcp__zotero__zotero_get_item_children,mcp__zotero__zotero_get_item_metadata,mcp__zotero__zotero_attach_file,mcp__zotero__zotero_authorize_local_writes

## 1. Preflight (every session, before the first write)

Shell side (read-only, never prints a key):

    python3 -I ${CLAUDE_PLUGIN_ROOT}/skills/zotero/scripts/preflight.py

It checks: desktop running, local API 127.0.0.1:23119 answers, desktop file
sync protocol = webdav (prefs.js), MCP env masks ZOTERO_API_KEY to "" and has
ZOTERO_LOCAL + sqlite backend, local write key held, web key present for the
/file check, group libraries. Verdict OK or ASK_USER (exit 0 / 1).
ASK_USER = stop, relay the listed reasons to the user.

MCP side (the shell cannot see the live MCP env): call
`zotero_write_capabilities()` and require BOTH lines:

    **Mode:** local       (line continues "Local API, writes go directly to the running Zotero")
    - Web API credentials: not set

Mode local + credentials not set = the MCP has no path to zotero.org at all;
a missing web key is then expected, not a blocker.

## Recipes

Use the local API (`http://127.0.0.1:23119/api/users/0/...`, read-only;
Zotero 7+ for reads, local MCP writes need Zotero 10+) for bulk reads; use MCP tools for writes. One plain command per
Bash call; dumps go to the scratchpad.

**R1 add by DOI, metadata only**

    zotero_add_item(source="10.1364/oe.489449", source_type="doi",
                    attach_mode="none", if_exists="file", tags=["<tag>"])

- `attach_mode="none"` always: the default "auto" uploads an OA PDF.
- `if_exists="file"`: idempotent; an existing DOI match only gets the tag.
  The default "duplicate" creates duplicates.
- Metadata comes from Crossref, not from your list: titles may differ.
- No verified DOI: do not guess (a guessed arXiv ID once created a stray
  item). arXiv: `source="10.48550/arXiv.<id>"` only with a verified ID.
  Books: ISBN works but is noisy, read the item back. Else list it for the user.
- Log one row per DOI: key, DOI, Zotero key, created / existing / failed.

**R2 dedupe (DOI + title)** -- `if_exists="file"` matches DOI/ISBN/URL only,
so a title-only duplicate (item without DOI) slips through. Before adding,
check the title:

    curl -s 'http://127.0.0.1:23119/api/users/0/items?q=<url-encoded short title>&qmode=titleCreatorYear&itemType=-attachment&limit=5'

Hit -> tag the existing item (R3) instead of adding. Preprint items often
carry the DOI only in `extra` as a `DOI: ...` line; check there too.

**R3 tag** -- incremental, keeps other tags:

    zotero_batch_update(item_keys=["KEY1", "KEY2"], add_tags=["<tag>"])

Never `zotero_update_item(tags=...)`: it REPLACES the whole tag list.

**R4 create collections** -- first check the name is free
(`zotero_search_collections`), then
`zotero_create_collection(name="01 Topic", parent_collection="<parentKey>")`.
Record every new key. A 2-digit prefix fixes display order.

**R5 add items to collections** -- add-only:

    zotero_set_item_collections(item_keys=["KEY1", "KEY2"], add_to=["<collKey>"])

`item_keys` must be an array. Never pass `remove_from` unless asked; never
`zotero_update_item(collections=...)` (REPLACES membership). Read back a few
collections afterwards (`zotero_get_collection_items`).

**R6 list items by tag / dateAdded** -- one local API dump instead of one MCP
call per item. Pages of 100; `Total-Results` header gives the count:

    curl -s 'http://127.0.0.1:23119/api/users/0/items/top?tag=<tag>&limit=100&start=0' -o <scratchpad>/p1.json

Add `&sort=dateAdded&direction=desc` for newest first. Filter
`data.dateAdded` (ISO, UTC) in a small `python3 -I` script. Spot-check two
items via `zotero_get_item_metadata`.

**R7 attach ONE file, then prove the sync target** (new batch, new repo,
new session):

1. Preflight OK + MCP step OK. Item is in My Library (users/0), not a group.
2. `zotero_get_item_children(item_key=[...all keys...])` in one call; skip
   items that already have a PDF.
3. Page-1 check of the file: `pdftotext -l 3 <file> -` contains the DOI or
   >= 80 pct of the item's title words. Else do not attach.
4. `zotero_attach_file(item_key="KEY", file_path="/abs/path.pdf")`. Read the
   reply for quota / zotero.org text (stop condition).
5. Evidence, in order:
   (a) web key in shell (preflight INFO says so): wait for Zotero to sync,
       then `python3 -I ${CLAUDE_PLUGIN_ROOT}/skills/zotero/scripts/preflight.py --file-check <attKey>`.
       Required: `OK: file synced (md5 set) and not on zotero.org`.
       `NO EVIDENCE` / `WEAK` = sync pending: retry in a minute or ask the
       user to press sync. Redirect = STOP.
   (b) no web key: the file shows up on your WebDAV server, or preflight
       `sync-target` = webdav (Zotero File Syncing preference). The pref is
       static evidence from before the attach: say so in the report, do not
       call it "proven by the one-file test".
   No evidence obtainable -> attach nothing further, ask the user.

**R8 batch attach** (only after R7 passed):

- Match file -> item by DOI first, title second; page-1 check every file;
  pick one file per duplicate set (the one that fits the item: VoR /
  journal layout over preprint) and say which.
- Keep the default `link_mode="import"` (stores the file, syncs via
  WebDAV). Not `"linked"` unless asked: it stores a local path only.
- Batches of ~10, sequential. Read every reply for quota / zotero.org text.
- `--file-check` on the largest file and every ~30 attachments.
- Post-check: local API re-dump, each attached item has exactly one child
  (`meta.numChildren` = 1 when it had none before; no double attach). Report table: item key, DOI, file, status.
- Optional: `zotero_update_search_database` for semantic search.

## Stop conditions -> notify the user, ask for guidance

- Any reply or error mentioning quota, storage, or zotero.org (e.g.
  `HTTP 413 File would exceed quota`): stop at once, quote the text verbatim.
- `zotero_write_capabilities` says hybrid or web, or
  `Web API credentials: set`. The MCP env's `ZOTERO_API_KEY=""` (Setup)
  masks any shell key, so a dead key makes writes fail instead of going to
  the cloud. "set" = that mask got lost.
- Mode none / local key not held: tell the user to switch to Zotero, call
  `zotero_authorize_local_writes()` once (blocks <= 55 s, user clicks
  "Always Allow", ~5 prompts/min limit, never loop; key is saved in
  `~/.config/zotero-mcp/config.json`). Refused or timed out:
  ask the user; or leave PDFs on disk and hand over a list (item key,
  title, local path).
- Preflight ASK_USER (any FAIL line).
- Sync target unproven after R7, or `--file-check` shows a redirect.
- Target item is in a group library: group files always go to zotero.org,
  WebDAV covers My Library only. Never `zotero_switch_library` to a group
  before a write.
- A permission prompt or classifier block: say what was blocked; the user
  can approve or run it with `!`.

## Pitfalls (each one happened)

- The reply "uploaded to WebDAV as <key>.zip" is NOT evidence: in hybrid
  mode the MCP's own WebDAV creds got 403 and it uploaded to zotero.org.
- `links.enclosure` in Web API JSON is NOT evidence.
- `/file` 404 means nothing until the item exists on the server (item 200)
  and its file sync finished (`md5` set); `--file-check` tests all three.
- The tool docstrings say writes "fail in local-only mode": that is
  read-only local. Mode local with a held key (Zotero 10+) writes fine.
- `zotero_attach_file` is idempotent by filename / MD5 only: the same paper
  under another filename becomes a second attachment. Check children first.
- `zotero_search_items` is substring match: short queries ("Author Year").
  `search_all_libraries=true` needs the sqlite backend; the error "global
  search requires the SQLite backend" = env var lost: report it, then
  search one library at a time. Quote errors before blaming Zotero.
- Per-item MCP metadata calls for 100+ items are slow; use R6.
- Process name is lowercase `zotero` on macOS (`pgrep -x Zotero` misses it).
- prefs.js is a snapshot (written on pref change / exit).
- Never echo or log `$ZOTERO_API_KEY`; use `--file-check`, which never
  prints it. Never send email addresses to APIs.
- Do not touch items outside the task's tag/scope; no deletions unasked.

## Model guidance

- Haiku: R1-R6 from a given list (add, tag, collect, dumps).
- Sonnet: dedupe judgment, matching files to items, R7-R8 batch attach.
- Opus: taxonomy design, anything where a wrong match is silent.

Teammates that touch Zotero run as agent type `research-kit-lit:zotero-worker`, keep an
append-only journal, and route stop conditions to the lead.
