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

The command argument says the mode: init, add-kind, upgrade, sync or close.

## init (repo has no `AGENTS.md`)

1. Ask the user with AskUserQuestion, all four in one call:
   - kinds (`multiSelect: true`; the five ids above);
   - mode: `full` (stage folders, close checklist) or `light` (no stage
     folders; critics, DECISIONS/DEFERRED, logs, handoffs stay);
   - git policy: `user` (the user commits) or `orchestrator` (the lead commits
     and merges);
   - global note: "Add the research-kit team-roles note to your global
     `~/.claude/CLAUDE.md`?" yes (recommended) / no.
2. Run `init <repo_dir> --kinds <k1,k2> --mode <full|light> --git <user|orchestrator>`.
   Exit 1 = repo already initialised or unknown kind: tell the user, stop.
3. Follow the kind files' own start-up steps with the user (each kind file
   says what to ask), then the appendix lines (project name, repo tag).
4. `init` also writes a marked `## Compact Instructions` block into the repo's
   `CLAUDE.md` (created if missing; existing text kept).
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
   rewritten, `pm/` (folders, skeleton files), `pm/kinds/paper.md` and the
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
   outside the markers is never touched, never counts as DROPPED).
5. If `~/.claude/CLAUDE.md` already holds the `research-kit:global` block, show
   the `global-rules` dry-run diff; run it with `--write` only with consent.
6. Tell the user: AGENTS.md loads at session start, so running teammates and
   this session keep the old rules; start a new session.

## close (user says "close stage", or `/rk-close`)

No script. Full mode only (light has no stage folders: say so and stop).

1. Name the stage being closed: folder `pm/stages/NN-<kind>-<topic>/`. Several
   open stages (at most one per kind): ask which. A legacy stage path from the
   appendix is read-only: do not close it.
2. First check the stage's **Done when** condition mechanically; if it does
   not hold, stop and tell the user what is missing.
3. Read the repo's `AGENTS.md` section 3.4 "Stage close" (8 steps: step 1 is
   the Done when check, step 7 the kind's freeze steps from
   `pm/kinds/<kind>.md`, step 8 the chat archive) and run it exactly in the
   order given there. Do not work from memory or a copy: 3.4 is the single
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
