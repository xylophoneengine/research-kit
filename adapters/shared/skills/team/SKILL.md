---
name: team
description: Run a scoped team with workers and independent critics.
---

# Team

You are the lead. Read `references/transport.md` from this installed skill
before dispatch and load the `research-kit` skill for the CLI path. In
Hermes, try `skill_view(name="team", path="references/transport.md")`.
If the skill loader resolves links to the source checkout, read the
references from the installed `skills/team/` directory: under
`${XDG_CONFIG_HOME:-$HOME/.config}/opencode` or `${HERMES_HOME:-$HOME/.hermes}`.
Apply `AGENTS.md` §2 for roles, roster confirmation, briefs, review and
verification, and §7 for git and waste. For a repo without kit rules, use
§2 of the installed core's `template/AGENTS.md` and omit ledger operations
if no ledger exists. Use the installed adapter transport in place of any
Claude-specific tools, model names or hooks, including in an older project; suggest
sync between stages.

- Resolve staffing against the active transport before dispatch. Show each
  staffed role's profile or route, and model if the harness exposes it.
  Say when all roles share one model; separate critic sessions are not
  separate models. Show the mapping even when staffing was already given.
  If an explicit choice is unavailable, or the project requires different
  models and you cannot verify the distinction, ask before dispatching.
- Confirm scope and staffing before delegation unless explicitly selected.
  State the acceptance check. For the optional architect, read
  `references/architect.md`; get the design before dispatching implementers.
  Stage dependent work in waves, one writer per path. Give each child only
  its authorized scope, absolute workspace and output paths. Do not let
  children delegate, delete files, or widen permissions; the lead handles
  questions, handoffs and integration. Preserve the project's git policy:
  if it requires isolated implementers, arrange authorized worktrees before
  dispatch; if isolation is unavailable, stop rather than share a checkout.
- Keep briefs and reports on disk. Save each brief under the run's report
  directory with a distinct `*-brief.md` name. A worker writes its report
  under stage `notes/team/` (full mode, chosen open stage) or
  `pm/logs/team/<run>/`; without `pm/` use a private run directory in your
  scratch area. Choose unused paths, including on retries. With a ledger,
  assign/create the task and include its `TASK:` and `rk show` lines in the
  brief. **Run `rk brief-check < <brief-file>` before every dispatch or
  follow-up** and stop on refusal; this is the same gate Claude invokes via
  a hook. When several stages are open, confirm which owns the work and
  pass its ID explicitly. Only the lead updates task status.
- The child returns a short `DONE` or `BLOCKED` with its report path after
  writing the file. Delivery notifications are wakeups, not evidence.
  Check the expected file and its evidence, not just the chat result.
  If a child completed without the report or failed, surface the blocker;
  don't close that task. End the turn while waiting for background results.
  On resume reconcile files, ledger and live handles; if uncertain, ask
  before retrying work that might still be running.
- Review only after the relevant reports arrive. Use a separate ledger
  task for the review; give each critic an exact review path and the
  verdict format from §2.2. `crit1` may see prior reports and re-review
  from its earlier review; `blind<round>` is always fresh, gets only the
  request, goal and artifact/diff (plus its own task and output path),
  and must not read earlier reports. Critics never implement fixes.
  Route blockers back to owners; at most two fix rounds, then ask the user.
  Follow §2.2 for independent verification, minor findings, review-task
  closure and work tasks (`staged` if not landed). Leave blockers open.
