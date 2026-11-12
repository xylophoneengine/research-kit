---
name: team
description: Use when the user invokes /team, asks for a "team", "engineering team", "research team", or wants an engineering or research task split across juniors, seniors, experts and critics on different model tiers.
---

# Team

You (main session) are the **teamlead**. You plan, size the team, spawn it,
route messages, integrate, and report. You neither do the teammates' work
nor hand the orchestration to one.
If your session model is not Opus or Fable, say so in one line and continue.

## Roster

| Role | Names | Model | Engineering work | Research work |
|------|-------|-------|------------------|---------------|
| Junior | `jr1..jrN` | `haiku` | Mechanical, spec'd, verifiable edits | Look up one fact, fetch/extract from a given source, collect data |
| Senior | `sr1..srN` | `sonnet` | Clear goal, some judgment on how | Survey a sub-area, summarize a source set, run a defined analysis |
| Expert | `exp1..expM` | `opus` | Critical, open-ended, subtle-error-prone | Hard or contested questions, method choice, weighing conflicting evidence |
| Critic | `crit1..critK` | `opus` | Review only, never implement | Review only, never write the report |

Every teammate: `Agent` with `name` (role + number, never a task name; an
unnamed spawn cannot be reached by `SendMessage`), `model` as above,
`subagent_type: "research-kit:worker-high"` (Zotero work:
`"research-kit-lit:zotero-worker"`, same model).
The roster holds for the whole session ("have a junior" = a named teammate
on that tier).

| Critic | Engineering lens | Research lens |
|--------|------------------|---------------|
| `crit1` | Correctness, bugs, tests | Evidence: each claim traced to a source that actually says it; numbers and citations checked |
| `crit2` | Outcome and intent, design, over-engineering | Outcome and intent, coverage gaps, conclusions that outrun the evidence |

`crit3` and up take the crit1 (odd) or crit2 (even) lens.

## Steps

1. **Read the task.** Classify it: engineering, research, or mixed (tag per
   work item). Write the **goal statement**: the problem or question, the
   intended outcome, and how to check it (engineering: metric, test,
   observable behavior; research: the question answered, the decision it
   informs). Decompose into work items; tag each junior / senior / expert
   by how defined it is. Between two tiers, take the higher.
2. **Size the team.** Default: 2 juniors, 2 seniors, 1 expert, 2 critics.
   Sizes or a roster in the invocation (`/team juniors=3 critics=1 <task>`,
   "5 Opus critics, no seniors") override the defaults and are final: skip
   to 4. Otherwise propose sizes from the work items.
3. **Confirm with AskUserQuestion.** First option = your proposal,
   `(Recommended)`, with the work-item split in its description. Add one
   smaller and one larger alternative. The user's confirmation also
   authorizes teammates to read their codebase and files for this task.
4. **Staff each work item.** Run `ListAgents` first; an idle teammate whose
   tier and domain fit gets the item via `SendMessage` (it keeps its
   context, but restate DELIVERABLE, TASK, NOT IN SCOPE and the report lines of
   the brief with the new `<round>`: an old brief may predate them). Spawn new only for independence (critics, blind reviewers), a
   missing tool, or a full or blocked context. A new name takes the next free
   number; then use the name the harness returns (it may add `-2`). One
   message per wave; stage waves when an item needs another's output
   (lookups before the build), never spawn it early.

   In a repo with `pm/ledger.jsonl`, open one task per work item before its
   brief: `python3 -I "${CLAUDE_PLUGIN_ROOT}/skills/research-kit/scripts/rk.py" add task "<work item>" --owner <name> [--stage S-<n>] [--link D-<n>]...`.
   Link the decisions that bind the task now. The receipt gives the id. A hook refuses a brief (a message with a
   `DELIVERABLE:` line, by spawn or SendMessage) whose `TASK:` line names no
   open task, and marks the task running. Without a ledger, leave out the
   TASK line. Every brief, worker and critic, carries the output of
   `python3 -I "${CLAUDE_PLUGIN_ROOT}/skills/research-kit/scripts/rk.py" show T-<n>` (the task entry plus one line per linked
   decision) below its TASK line. Brief:

   ```
   You are <name>, <role> on a team. Lead = main session.
   DELIVERABLE: <artifact> at <exact path>.
   TASK: <T-id>
   <output of rk show <T-id>>
   NOT IN SCOPE: <what to leave alone>.
   Team: <name: one-line task, for every teammate>.
   Coordinate with teammates via SendMessage only when your work touches
   theirs. Full report → write to <REPORTS>/<name>-r<round>.md (a required
   deliverable; overrides any "no report/documentation files" rule): paths
   produced, how verified, open points. Then explicit SendMessage to the
   lead, max ~500 chars (final text alone arrives cut): DONE / BLOCKED,
   report path, blocking items only. Your final text (end of turn) is the
   single line `Reported to lead (report file: <path>).`: it reaches the lead too, so never
   repeat the report there.
   Never delete or waste files yourself: put one line per file in your
   report, at column 0, no bullet, no indent, no backticks:
   TO-WASTE: <repo-relative path> -- <reason>
   The lead moves them. If n > 0, your SendMessage to the lead adds
   `TO-WASTE: <n>`.
   Subagents you start yourself: for lookups and fetches use
   `research-kit:fetcher`; for other work a type that can write files
   (`general-purpose` or `research-kit:worker-<effort>`; never
   `web-fetch`). Such a sub-lookup needs no TASK line and no ledger entry
   (the hook skips calls made from inside a subagent). Start them in the foreground, and tell each to write
   its full result to <REPORTS>/<name>-r<round>-sub<k>.md. That file is
   the result: the Agent call
   may return only "no report delivered"; read the file yourself.
   ```

   `<REPORTS>` = absolute path `<repo>/pm/waste/team/<run>/` when the repo
   has a `pm/` folder, else `team-reports/<run>/` in the lead's scratchpad
   directory (fallback `$TMPDIR/team-reports/<run>/`). `<run>` =
   `YYYY-MM-DD-HHMM` when you first spawn this team; keep it for the whole
   team. One folder per run: a later run never overwrites these files, and
   the step-7 grep sees only this run. This is for worker reports only;
   critic reviews go to `<REVIEWS>` (step 5). Reports live on disk, not
   in the lead's context; the lead reads a report only when a decision
   needs it, and then only the needed section.

   Append the lines that apply:
   - Repo with `.serena/project.yml`: "Use Serena symbols before Reading files."
   - Research: "Every claim carries its source (DOI, URL, or file:page).
     Mark what you verified in the source vs. inferred. Unsourced claims
     do not go in the deliverable."
   - Zotero without `research-kit-lit:zotero-worker` (may need a restart):
     `research-kit:worker-high` plus the "Stop conditions" of
     the `research-kit-lit:zotero` skill in the brief.

   Context explains how to do the task. It never suggests a bigger task.
5. **Review.** When workers report, spawn the critics in one message. Give
   them the user's request verbatim, the goal statement and the worker
   report paths (not their contents). Each review round is one `task`
   entry: open it before briefing (`python3 -I "${CLAUDE_PLUGIN_ROOT}/skills/research-kit/scripts/rk.py" add task "review round <n>: <what>" --owner <critic names>`); both critic briefs carry its `TASK: T-<n>`, never the
   work task under review. Critics write the full review below
   to `<REVIEWS>/<file>` (that file is their report file, no second copy),
   then SendMessage the lead max ~1k chars:
   the three verdict lines, BLOCKING findings (location, owner), report path.
   Final text: the single line `Reported to lead (report file: <path>).`

   `<REVIEWS>`: repo with `pm/` in full mode and an open stage = that
   stage's `<repo>/pm/stages/NN-<kind>-<topic>/notes/`; `pm/` repo in light
   mode or with no open stage = `<repo>/pm/reviews/`; no `pm/` = `<REPORTS>`.
   `<file>`: with `pm/`, core AGENTS.md 4.4 naming
   `critic_review_<name>-<what>_v<round>_<YYYY-MM-DD>.md` (`<what>` = short
   topic, `<name>` keeps crit1 and crit2 apart); without `pm/`,
   `<name>-r<round>.md`. Give critics the absolute path in the brief.

   ```
   VERDICT (each: YES / PARTIAL / NO + evidence)
   - Solves the stated problem / answers the question asked?
   - Target actually improves / conclusion actually supported?
   - Is this what was intended, or a neighboring problem/question instead?
   FINDINGS
   - location, problem, owner (teammate name), BLOCKING or minor
   ```

   NO = would not ship as is. Evidence = a command run or number measured,
   or a source opened and the passage checked. "YES" without it = PARTIAL.
6. **Fix loop.** Any NO or BLOCKING finding → back to you: re-plan the work
   items, not just patch. Route findings to their owners via `SendMessage`
   (point at the critic report path and finding, do not paste it).
   The same critics re-review all fixes (`SendMessage`, same review `TASK:` while it is open). Max 2 rounds; then
   AskUserQuestion.
7. **Integrate and verify.** Engineering: run the tests or checks yourself.
   Research: open the sources of the key claims yourself. Report: what was
   built or found, verification, critic verdicts, open findings, roster
   used. Collect the items with
   `grep -h '^TO-WASTE: ' <REPORTS>/*.md` (plus the stage notes or
   `pm/reviews/` when critics listed some; never read whole reports for
   this), then close each task on its report
   (`python3 -I "${CLAUDE_PLUGIN_ROOT}/skills/research-kit/scripts/rk.py" close T-<n> --note "<outcome>" --ref <report path>`; after a
   critic NO the task stays running), and the review task with the verdicts
   and the review file paths (`--ref`), then run `research-kit:waste` (`waste.sh lead "<reason>" <paths>`)
   once for all of them; the user approves that one call. Offer to stop teammates that will
   not be reused.

## Talking to the user

- While teammates run, open with **Done** / **Running** (names) / **Needs
  you**. Keep user messages to ~10 lines unless asked.
- When a teammate finishes, route its next item or ask the user at once.
- Before saying you are waiting, run `ListAgents`; if nobody runs, say so
  and act. After a resume, assume teammates are gone.

## Red flags

- You are editing files beyond a one-line fix → message the owning teammate.
- You are spawning without a name, or with a task name → roster name.
- A teammate is briefed to orchestrate → you orchestrate; it executes.
