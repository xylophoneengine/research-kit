---
name: waste
description: Lead (main session) only. Use instead of rm/rmdir/git rm whenever a file or folder inside a repo should be deleted, cleaned up, replaced, or discarded (stale outputs, superseded PDFs, failed runs, scratch files in the repo). Moves it to <repo>/pm/waste/ (<repo>/WASTE/ when the repo has no pm/) with a ledger row; the user empties it by hand.
---

# Waste, don't delete

Never delete files in a repo. Move them to the waste dir with the helper (`pm/waste/` if the repo has a `pm/` folder, else `WASTE/`); the user reviews and empties it.

**Who runs it: only the lead (main session).** Teammates and subagents never run the helper and never delete: their permission prompts do not reach the owner. A teammate lists each file in its report as one line at column 0 (no bullet, indent or backticks): `TO-WASTE: <repo-relative path> -- <reason>`, and adds `TO-WASTE: <n>` to its message to the lead when n > 0. The lead collects the items with `grep -h '^TO-WASTE: ' <reports>/*.md` and runs the helper once for all of them (the user approves that one call).

```bash
${CLAUDE_PLUGIN_ROOT}/skills/waste/waste.sh <who> "<reason>" <path> [<path> ...]
```

- The repo root is the git toplevel of each path itself, not of the cwd: call it from any cwd with absolute paths. A path outside any git repo is refused (non-zero exit).
- Each path lands at `<waste dir>/<UTC stamp>/<original relative path>`; nothing is overwritten.
- One row per path is appended to `<waste dir>/LEDGER.md`: `| when | who | from | to | reason |`.
- Refuses (non-zero exit):
  - paths outside the repo root, paths already in the waste dir, missing paths;
  - the repo root, a nested repo root, `pm/` itself, the waste dirs and the ledger;
  - names (case-insensitive) `.git`, `.claude`, `.claude-plugin`, any `.gitignore`, `.env` and `.env.*` (except `.env.example`, `.env.sample`, `.env.template`), as the path or any parent of it; `.envrc` and `.environment.yml` are allowed;
  - a directory that holds any of those names anywhere inside (so nested repos are refused);
  - a waste dir that git does not ignore (run `rk-init` or `rk-sync --write`, or add `pm/waste/` to `.gitignore`; legacy `WASTE/*` plus `!WASTE/LEDGER.md` also passes);
  - a symlinked `pm`, `pm/waste`, `WASTE` or ledger, and symlinks in the destination;
  - this plugin's own files or a directory holding them (so in the research-kit repo itself, files under `plugins/research-kit/` cannot be wasted with the helper: move them by hand);
  - control characters in who, reason or path (a `|` in a path is escaped in the ledger; `|` in who or reason is refused);
  - any call from a subagent or teammate: the PreToolUse guard denies `waste.sh` when the hook input carries an `agent_id`. Only the lead's call goes through (with the owner's approval).
  `GIT_*` environment variables are ignored.
- Restore: `mv <waste dir>/<stamp>/<rel> <rel>` and note it under the ledger table.
- `<who>`: the requesting teammate's name (or `lead`, `user`). `<reason>`: one short line. Neither may contain `|`.

Rules:
- No `rm`, `rmdir`, `git rm`, `rm -rf`, `find -delete`, or overwriting a file to "clear" it. Use this helper.
- Files outside any repo (session scratchpad, /tmp): leave them; do not delete.
- To replace a file (e.g. a newer PDF version): waste the old one first, then write the new one.

Repo setup (once per repo):
- `.gitignore`: `rk-init` ignores `pm/waste/` for you. Legacy repos without `pm/`: `WASTE/*` and `!WASTE/LEDGER.md` (ledger tracked, contents not).
- If the repo uses asciify, the ledger is ASCII as long as paths/reasons are.
- Permission: the plugin's PreToolUse hook (`hooks/guard-delete.sh`) denies delete commands (`rm`, `rmdir`, `unlink`, `git rm`, `find -delete`, python `rmtree`/`os.remove`/`unlink`). The helper itself is not auto-allowed: the owner approves the lead's call. Do not rephrase a delete to get around the block.
