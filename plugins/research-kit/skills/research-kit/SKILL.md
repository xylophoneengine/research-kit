---
name: research-kit
description: Use when starting a research repo (paper, software, reverse-engineering, experiment, thesis), when adding a kind to one, when upgrading it from light to full mode, when a repo's AGENTS.md or kind files may be outdated against the research-kit templates, when the user says "close stage", or when the user invokes /rk-init, /rk-add-kind, /rk-upgrade, /rk-sync or /rk-close.
---

# research-kit

Canonical generic rules live in this plugin's `template/`
(`${CLAUDE_PLUGIN_ROOT}/skills/research-kit/template/`): `AGENTS.md` (core) and
`kinds/<kind>.md`. A repo's `AGENTS.md` = template generic part (above
`## Project appendix`) + the repo's own appendix. The kind files are copied to
`pm/kinds/<kind>.md` and announced by the managed `<!-- rk:kinds -->` block in
the appendix. Generic parts are replaced on every sync; repo-specific rules
live in the appendix.

Kinds: `paper`, `software`, `reverse-eng`, `experiment`, `thesis`.

Script (every mode below): `python3 -I "${CLAUDE_PLUGIN_ROOT}/skills/research-kit/scripts/rk.py" <mode> <repo_dir> ...`

The ledger commands use the same script (`rk.py add|start|close|list|import|...`); the
reference is core AGENTS.md 4.2.

The command argument says the mode: init, add-kind, upgrade, sync or close.

## init (repo has no `AGENTS.md`)

1. Ask the user with AskUserQuestion, all four in one call:
   - kinds (`multiSelect: true`; the five ids above);
   - mode: `full` (stage folders, close checklist) or `light` (no stage
     folders; critics, the ledger, logs, handoffs stay);
   - git policy: `user` (the user commits) or `orchestrator` (the lead commits
     and merges);
   - global note: "Add the research-kit team-roles note to your global
     `~/.claude/CLAUDE.md`?" yes (recommended) / no. Run `global-rules` (dry
     run) first; if it prints "up to date", drop this question and step 5.
2. Run `init <repo_dir> --kinds <k1,k2> --mode <full|light> --git <user|orchestrator>`.
   Exit 1 = repo already initialised or unknown kind: tell the user, stop.
3. Follow the kind files' own start-up steps with the user (each kind file
   says what to ask), then the appendix lines (project name, repo tag).
4. `init` also writes a marked `## Compact Instructions` block into the repo's
   `CLAUDE.md` (created if missing; existing text kept), creates an empty
   `pm/ledger.jsonl`, ignores `pm/STATUS.md` and writes a marked block into
   `.gitattributes` with `pm/ledger.jsonl merge=union` (branch merges of the
   append-only ledger then do not conflict).
5. Only on yes to the global note: run `global-rules --write` (marked block in
   `~/.claude/CLAUDE.md`; text outside kept). Never run without that yes.
6. Tell the user: new session needed to load the rules; commits follow the
   chosen git policy.

## add-kind

1. If the user named no kind, ask (AskUserQuestion, single choice from the
   five ids not yet in the kinds block).
2. Run `add-kind <repo_dir> <kind>`. Exit 1 = unknown kind (stdout lists the
   valid ids). Exit 0 with no change = kind already active; say so.

## upgrade (light -> full)

Run `upgrade <repo_dir>`. It sets `Mode: full` and creates `pm/stages/`.
Output "already full" = nothing to do.

## sync (repo has `AGENTS.md`)

1. Run `sync <repo_dir>` (dry run). It prints the stamps, one combined diff for
   `AGENTS.md` and every `pm/kinds/<kind>.md` listed in the kinds block, and
   a DROPPED list: repo lines the template lacks. `up to date` = done.
   A repo with the legacy (pre-research-kit) stamp is migrated: `AGENTS.md` is
   rewritten, `pm/` (folders, skeleton files, among them an empty
   `pm/ledger.jsonl`), `pm/kinds/paper.md` and the
   `.gitignore` block are added, old stage and waste paths are recorded in the
   appendix as `Legacy stages:` / `Legacy waste:`; no existing file is moved.
2. Sort each DROPPED line:
   - old template text (template changed since) -> drop;
   - repo-specific (names the project id, repo paths, dated user decisions) ->
     move it into the repo's appendix with Edit, keep its wording; for a kind
     file, into the appendix too, never into the copy;
   - generic improvement the repo found -> back-port to the template in a
     clone of this plugin's repo, then sync again;
   - unclear -> ask the user (AskUserQuestion, one option per line).
3. Rerun the dry run until DROPPED holds only text to drop. Show the user the
   diff summary, then run `sync <repo_dir> --write --accept-drop`. Without
   `--accept-drop`, `--write` exits 2 while drops exist.
4. `sync` also refreshes the marked `## Compact Instructions` block in
   `CLAUDE.md` (diff shown in the dry run, written only with `--write`; text
   outside the markers is never touched, never counts as DROPPED). When it
   migrates a legacy repo, it also rewrites a `paper/README.md` pointer in
   `CLAUDE.md` to `pm/README.md` (named in the dry run; nothing else in the
   file changes).
5. If `~/.claude/CLAUDE.md` already holds the `research-kit:global` block, show
   the `global-rules` dry-run diff; run it with `--write` only with consent.
6. Tell the user: AGENTS.md loads at session start, so running teammates and
   this session keep the old rules; start a new session.

## import (legacy history into the ledger)

`rk.py import FILE.jsonl [FILE.jsonl ...] [--dry-run] [--repo DIR] [--who NAME]`
turns the old system's tasks, decisions and stages into ledger entries marked
`imported` (unverified). All or nothing: every row of every file is checked
first; one bad row and nothing is written (errors print as `FILE:LINE: message`).
Several files are one batch, read in the order given.

Each file is JSON Lines: one object per line, blank lines skipped, every value
a string except `link` and `ref` (lists of strings).

- Required: `type`, `title` (one line, at most 160 characters), `source` (where
  the row came from, e.g. `pm/living/TASKS.md:44`).
- Optional: `status` (default open; a decision: done), `owner` (a decision needs
  it), `stage` (a stage id or the exact title of one stage), `note`,
  `legacy_id`, `date` (YYYY-MM-DD, the original date), `link` (entry ids),
  `ref` (paths), `key`.
- `key` names a row (letters, digits, `_ . -` only, unique in the batch, not
  stored). Another row links to it with `"link": ["@KEY"]`, even if that row
  comes later in the batch (an unknown `@KEY` or a duplicate key is an error;
  plain entry ids in `link` still work). `stage` takes a stage id or a stage
  title, never `@KEY`; the stage row must come before the row that names it in
  the batch (earlier in the same file, or in a file given earlier), a stage row
  further down fails with `no stage`.

Run with `--dry-run` first: it checks everything and prints the per-type counts
and id ranges it would create, writing nothing. Then run without it. A re-run
refuses rows already in the ledger (same `source` and `legacy_id`, or same
`source` and `title` when there is no `legacy_id`), so the whole batch is
refused (exit 1, one `already imported as ID` line per row): put only the new
rows in their own file rather than importing twice (a duplicate earlier in the
same batch is refused too). Look an imported row up afterwards
with `rk.py search --source S` or `--legacy-id L` (exact match on the stored
value). Later notes on an entry append (`set|close|drop|reopen --note`);
`set --note-replace TEXT` replaces.
`rk.py import --help` has the full key list and example rows.

## close (user says "close stage", or `/rk-close`)

Full mode only (light has no stage entries: say so and stop).

1. Name the stage being closed: the open stages are
   `rk.py list --type stage`; its folder is `pm/stages/NN-<kind>-<topic>/`.
   Several open stages (at most one per kind): ask which. A legacy stage path from the
   appendix is read-only: do not close it.
2. First check the stage's **Done when** condition mechanically; if it does
   not hold, stop and tell the user what is missing.
3. Read the repo's `AGENTS.md` section 3.4 "Stage close" (8 steps: step 1 is
   the Done when check, step 6 is `rk.py stage-close S-<n> --sign-off D-<m>`,
   step 7 the kind's freeze steps from `pm/kinds/<kind>.md`, step 8 the chat
   archive) and run it exactly in the order given there. A `stage-close`
   refusal prints what is missing: fix it and rerun. Do not work from memory or a copy: 3.4 is the single
   source.
4. One todo per step, with the owner the checklist names. Lead steps: the lead
   does them. Teammate steps: brief a named teammate.
5. Confirm each step's output exists before the next step. The chat archive
   comes last. After closing, the stage folder is frozen.
6. End by telling the user what is left for them: optional `/export` into
   the stage's chat folder, and committing.

## Changing a generic rule

Edit `template/AGENTS.md` or `template/kinds/<kind>.md` in a clone of this
plugin's repo (never the installed copy under `~/.claude/plugins/`: an update
overwrites it). Bump the version stamp on line 1 of the changed template and the
`version` in `.claude-plugin/plugin.json` (installed users stay on the old
version until it changes), push, let users update the plugin (`/plugin` ->
update), then `/rk-sync` each repo. Never fix a generic rule only in one repo
copy: the next sync removes it.

## Common mistakes

| Mistake | Fix |
|---|---|
| `--accept-drop` before sorting DROPPED | repo decisions vanish; sort first |
| Editing the generic part or a `pm/kinds/` file in a repo | edit the template, then sync |
| Repo without `## Project appendix` heading | script exits; add the heading above the repo's project section, rerun |
| Running `init` in an initialised repo | exit 1; use `add-kind`, `upgrade` or `sync` |
