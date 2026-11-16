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
reference is core AGENTS.md 4.2. `add` and `set` take `--label L` (form
`<stage code>/<item>`, e.g. `03b/W4`, the `/` is required; unique); a stage's
title is its folder name, changed only by `stage-rename`; every ID argument also takes a
label or a stage code (`03b`); receipts print the real ID and the entry's stage
(or `(no stage)`); `set --stage` with the stage the entry already has writes
nothing (`unchanged`); an `add` gets the single open stage by default; when there
is none (no stage open, or several) and the new entry is closed (a decision) and `--link`s a closed
stage, the receipt says `(no stage: S-n is closed)` (an open entry gets the plain
`(no stage)`). Only open tasks block a stage close, so for every type but task
and stage (debt, deferred, fetch, handoff, declared types) `stage` means "raised
in": an open one may be put into a closed stage (`add --stage`, `set --stage`,
an import row), and one already there may `start` or `reopen` (neither changes
`stage`); this backfills imported entries. An open or running task, and an open
stage, are refused: `S-n is closed (done); an open task cannot go into it: `
then `pick an open stage` (set), `pass --stage with an open stage` (add, import)
or `re-stage it first: set <id> --stage S-<x>` (start, reopen). Why: a closed
stage's record is frozen and shows what was known at close; such a `set` does not
rewrite it, `rk list --stage S-n
--all` shows the entry. A `TASK:` line in a
brief names its tasks by id or by label, listed first (a label after other words
does not count); titles are one line, 160 characters at most. `add task` without
`--note` is refused (imports exempt); `add stage "<kind>-<topic>"` plans a stage
(status `planned`, folder `P-<n>-<kind>-<topic>`, recorded as ref; `--open` or
`stage-open S-n [--follows S-m]` gives it the next NN and renames the folder;
`--before S-n` / `--after S-n` order planned stages; `stage-rename S-n
"<kind>-<topic>" [--note N]` renames a stage; `set S-n --status
planned|shelved|dropped` (`--note` required for shelved and dropped only);
`start` is refused for an entry of a
planned or shelved stage; such an entry stays stored `open` but is shown as
`planned` (`shelved`): out of the open list and counts, found by `list --status
planned` or `list --stage S-n`, open again by itself at `stage-open`; the
`planned N:` line of `list` gives each stage's entry count `(k entries)` and
`show` names the stored and the shown status). Every `--ref` (add, set, close, drop,
shelve, reopen, supersede, stage-close) must name an existing file, relative to the repo
root (a `://` URL, `doi:` or `arXiv:` passes; a path outside the repo is refused;
imports exempt; checked against the main checkout, so in a worktree merge first):
write the report first.
`shelve ID --note "<why>" [--ref P] [--link ID]` moves an open or running entry
(any type but decision and stage) to `shelved`: known, not planned now (deferred
= parked, waits on something). A shelved entry leaves every open count and view:
no `rk list` row unless `--all`, no stage-close block, its own `## Shelved`
section in STATUS.md. Out of shelved: `reopen` (open; the closed-stage rule
applies) or `drop`; `close`, `start` and a second `shelve` are refused. `add
--status shelved` only with `--imported`. Why: the reason is required, so
"not now" is a decision with its why, not a silent open item.
`staged ID... --note "<where: branch, commit>" [--ref P]` moves open or running
entries (any type but stage and decision) to `staged`: work done, not landed;
one write, one receipt line each; refused in a planned or shelved stage. A
staged entry stays in the open list (`list --status staged` shows only those),
is not running, and a staged task blocks `stage-close` and dropping a planned
stage like an open one. Out of staged: `close` or `land` (done), `start`
(running, more work), `reopen` (open). `land --note N [--ref P] [--stage S-n]
[ID...]` closes every staged entry, or the named ones (a named entry that is
not staged refuses the whole call); `landed 0` when there is none. `set --status
staged` is not offered. Why: DB-29 stayed `open` while its fix sat on a branch;
close only what is on the base branch.
`close`, `drop`, `shelve` and `reopen` also store their `--note` as the field
`reason` (why the entry has its current status; the next one replaces it; the
note still appends as before); `show` prints `reason: ...`, the stage record
shows it beside dropped and shelved entries. Old entries have none and print none;
a viewer may fall back to the last line of the note for entries written before the
field existed.
`set <id> --ref-drop <path>` (repeatable) removes a wrong ref. `show` takes
several ids and prints, under each history line, the kit version, session id and
rule stamps the tool wrote. `doctor [--stage S] [--limit N]` (N lines per group, default 20, 0 = all) is read-only: HARD findings
(ledger line that does not parse, missing ref, missing stage folder, ledger not
append-only against HEAD) exit 1; SOFT ones (ref in an ignored or waste folder, waste ref whose file is gone,
done stage not in HEAD, entry without a stage, task running over 24 h, imported
entries with missing refs, imported entries titled with a status word (OPEN, DONE,
TODO; dropped or superseded ones are skipped), done entries titled `open:` or
`OPEN ...`, ignored or outside-the-repo refs a clone would
lack, stage folder absent in a clone, rule file behind the kit, and with `--stage` the
decisions not owned by the user) are listed; no git repo: git checks are skipped. In a local-only repo (`pm/config.json`: `pm` = `local`) `doctor` starts with the line `pm: local only (pm/config.json): git checks on pm/ skipped`, runs no git check on a path under `pm/`, and a missing file (outside `pm/waste/`) or stage folder under `pm/` is HARD.
`reref OLD NEW [--dry-run]` replaces a leading path prefix in every ref that
starts with it, all or nothing (refuses and writes nothing if a new path does
not exist: move the files first). `stage-close` runs the stage checks and refuses on HARD; once closed it writes
`pm/stages/<stage folder>/LEDGER.md` (the stage's entries and those touched in its
window, decisions by owner, what stays open, the `kit`, `sid` and rule stamps seen):
generated, never hand-edited, written by nothing else (an existing file without
the generated first line is not overwritten). If the write fails after the close
line, or the file is missing, `stage-close S-n` on the done stage writes the
record only, no ledger line. Why: the stage's record on one page, read without
the ledger.
`doctor --start` feeds the SessionStart block (`kit <version>`, `pm: local only` in a local-only repo, a line per stale
rule file: run `/rk-sync` between stages, not inside one); the block also prints
the line `rk() { python3 -I "<path>/rk.py" "$@"; }` and a notice when `jq` is
missing. A Bash call keeps no shell state: start each call that uses `rk` with
that line joined to the command by `;` (`rk() {...}; rk list`); `rk` in rule
text means that command.

The command argument says the mode: init, add-kind, upgrade, sync or close.

## init (repo has no `AGENTS.md`)

1. Ask the user with AskUserQuestion in two calls (one call takes at most four
   questions): the first four in one call, then the global note in a second:
   - kinds (`multiSelect: true`; the five ids above);
   - mode: `full` (stage folders, close checklist) or `light` (no stage
     folders; critics, the ledger, logs, handoffs stay);
   - git policy: `user` (the user commits) or `orchestrator` (the lead commits
     and merges);
   - local only: "Keep pm/ and the rule files out of git (local only)?" no
     (recommended) / yes; yes gives `--pm local` in step 2;
   - global note: "Add the research-kit team-roles note to your global
     `~/.claude/CLAUDE.md`?" yes (recommended) / no. Run `global-rules` (dry
     run) first; if it prints "up to date", drop this question and step 5.
2. Run `init <repo_dir> --kinds <k1,k2> --mode <full|light> --git <user|orchestrator> --pm <local|tracked>` (`tracked` unless the local-only answer is yes).
   Exit 1 = repo already initialised or unknown kind: tell the user, stop.
3. Follow each kind file's first-session section with the user where it has
   one (no section = nothing to ask), then the appendix lines (project name,
   repo tag).
4. `init` also writes a marked `## Compact Instructions` block into the repo's
   `CLAUDE.md` (created if missing; existing text kept), creates an empty
   `pm/ledger.jsonl`, ignores `pm/STATUS.md` and writes a marked block into
   `.gitattributes` with `pm/ledger.jsonl merge=union` (branch merges of the
   append-only ledger then do not conflict). With `--pm local` it writes `pm/config.json` (`{"pm": "local"}`) and a marked block in `.git/info/exclude` instead of the `.gitignore` and `.gitattributes` blocks; that block hides `/pm/`, `/AGENTS.md`, `/CLAUDE.md` and `/**/_dry/` from git.
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
   a DROPPED list: repo lines the template lacks. `up to date` = done. `sync <repo_dir> --pm local|tracked [--write]` switches the repo: `local` writes `pm/config.json` and the exclude block, no `.gitignore` or `.gitattributes`; it is refused (exit 1, nothing written) while `pm/` has files in git, which the user untracks first. A repo that already excludes `/pm/`, `/AGENTS.md`, `/CLAUDE.md` and `/**/_dry/` by hand gets a second copy of them in the block; the hand lines can then go.
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
   diff summary, then run `sync <repo_dir> --write --accept-drop` (add `--pm local|tracked` when step 1 used it). Without
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
value). Later notes on an entry append (`set|close|drop|shelve|reopen --note`);
`set --note-replace TEXT` replaces.
After an import, entries from repo-wide lists (debt, deferred, fetch) get their
origin stage with `rk.py set ID --stage S-n` when it can be traced (the source
line, the git blame date, the stage dates); `stage` of such an entry means
"raised in" and may point at a closed stage while the entry is open. Why: only
open tasks block a stage close, and a debt keeps the stage it was raised in.
`rk.py import --help` has the full key list and example rows.

## close (user says "close stage", or `/rk-close`)

Full mode only (light has no stage entries: say so and stop).

1. Name the stage being closed: the open stages are
   `rk.py list --type stage`; its folder is `pm/stages/NN-<kind>-<topic>/`.
   Several open stages (at most one per kind): ask which. A legacy stage path from the
   appendix is read-only: do not close it.
2. First check the stage's **Done when** condition mechanically; if it does
   not hold, stop and tell the user what is missing. (Sign-off is not part of
   it: it is step 7 of the checklist.)
3. Read the repo's `AGENTS.md` section 3.4 "Stage close" (8 steps: 1 Done when
   check, 2 tasks, 3 `pm/README.md` and appendix state lines, 4 handoffs, 5 the
   kind's freeze steps from `pm/kinds/<kind>.md`, 6 chat archive with its task
   opened while the stage is open and the main transcript copied last, 7 user
   sign-off by AskUserQuestion showing `rk.py doctor --stage S-<n>`, 8
   `rk.py stage-close S-<n> --sign-off D-<m>` last; a handoff moved at step 4 needs
   `rk.py reref <old path> <new path>` before it is closed) and run it exactly in the
   order given there. A `stage-close` refusal prints what is missing: fix it
   and rerun. Do not work from memory or a copy: 3.4 is the single source.
4. One todo per step, with the owner the checklist names. Lead steps: the lead
   does them. Teammate steps: brief a named teammate.
5. Confirm each step's output exists before the next step. The archive and its
   README file index come before the sign-off question, so the user sees the
   finished record; the sign-off and `stage-close` events are not in the
   archive. After closing, the stage folder is frozen; a stage closed too
   early: `rk reopen S-<n> --note "<why>"`, then the checklist again with a
   new sign-off.
6. End by telling the user what is left for them: optional `/export` into
   the stage's chat folder (it holds the tail the archive lacks), and committing.

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
