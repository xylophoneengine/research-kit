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
| Architect | `arch1` (optional, at most one) | `opus` | Interfaces between work items, rules a change touches; one design file, never code | Shared output format, what each source set must answer, what counts as verified |
| Critic | `crit1`, `blind<round>` | `opus` | Review only, never implement | Review only, never write the report |

Every teammate: `Agent` with `name` (role + number, never a task name; an
unnamed spawn cannot be reached by `SendMessage`), `model` as above,
`subagent_type: "research-kit:worker-high"` (Zotero work:
`"research-kit-lit:zotero-worker"`, same model).
The roster holds for the whole session ("have a junior" = a named teammate
on that tier).

| Critic | Engineering lens | Research lens |
|--------|------------------|---------------|
| `crit1` (loop critic) | Correctness, bugs, tests | Evidence: each claim traced to a source that actually says it; numbers and citations checked |
| `blind<round>` (disposable critic) | Outcome and intent, design, over-engineering | Outcome and intent, coverage gaps, conclusions that outrun the evidence |

`crit1` stays for the whole loop and re-reviews the fixes with its memory.
The disposable critic is a fresh agent every round, never reused or
messaged again; it sees only the diff or deliverable, the user's request
verbatim and the goal statement. `blind<round>` names it and its report.
Extra critics asked for are loop critics `crit2..` (crit1 lens). Why: worker
reports anchor a critic on their framing; a fresh one judges the outcome.

**Architect.** Staff `arch1` only when the work items of two or more
workers meet at an interface (one consumes what another produces); else
write into the affected briefs yourself `INTERFACES:` (producer, consumer,
exact format, example) and `RULES CHANGED:` (each changed rule, every place
that encodes it, its owner). It thinks and designs: a design and interface
sheet at the path you give, before any worker starts. It never routes,
spawns or implements; it stays reachable for interface questions (via you)
and after integration checks the result against its design, reporting
deviations to you. Why: interfaces fixed first keep workers from building
to different formats; an architect that routes or builds is a second lead.

## Steps

1. **Read the task.** Classify it: engineering, research, or mixed (tag per
   work item). Write the **goal statement**: the problem or question, the
   intended outcome, and how to check it (engineering: metric, test,
   observable behavior; research: the question answered, the decision it
   informs). Decompose into work items; tag each junior / senior / expert
   by how defined it is. Between two tiers, take the higher. Note where
   items meet at an interface: that decides the architect (Roster).
2. **Size the team.** Default: 2 juniors, 2 seniors, 1 expert, 1 loop
   critic, 1 disposable critic; plus `arch1` when step 1 found an interface.
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
   (lookups before the build), never spawn it early. `arch1` goes first;
   workers start once its design file exists, each brief with its sheet block.

   In a repo with `pm/ledger.jsonl`, every work item has one task before its
   brief. An item the stage BRIEF lists already has it (opened with its label
   when the stage opened): hand it out with `python3 -I "${CLAUDE_PLUGIN_ROOT}/skills/research-kit/scripts/rk.py" set <label> --owner <name>`,
   and add no second task. Any other item gets a new one: `python3 -I "${CLAUDE_PLUGIN_ROOT}/skills/research-kit/scripts/rk.py" add task "<work item>" --owner <name> --note "<the brief's DELIVERABLE and NOT IN SCOPE lines>" [--ref <brief file>] [--label <stage code>/<item>] [--stage S-<n>] [--link D-<n>]...`.
   The note is required (a task without one is refused): the deliverable and
   what to leave alone, as in the brief. `--ref` when the brief is saved to a
   file; `--label` when the stage plan names the item (form `<stage code>/<item>`, e.g. `03b/W4`, the `/` is required; later
   commands may use it in place of the id). Link the decisions that bind the
   task now (`--link`). The receipt gives the real id; the brief's `TASK:` line
   carries that id (or the label, listed first: `TASK: 03b/W2`; a label after
   other words does not count). A hook refuses a brief (a message with a
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
   theirs.
   CHECK: <command that tests your work, or none>. Scratch: <lead's scratchpad>.
   Run yourself only one-line read commands, the named check, and one-line
   writes inside your own scratch folder; anything else goes as plain lines
   in a file to the lead. Prefix scratch files with your name.
   Full report → write to <REPORTS>/<name>-r<round>.md (a required
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

   `<REPORTS>` = absolute path, tracked with the repo, never `pm/waste/`
   (a ref to a report must outlive the waste folder):
   - `pm/` repo in full mode with an open stage: `<repo>/pm/stages/NN-<kind>-<topic>/notes/team/`;
   - `pm/` repo in light mode or with no open stage: `<repo>/pm/logs/team/<run>/`;
   - no `pm/`: `team-reports/<run>/` in the lead's scratchpad directory
     (fallback `$TMPDIR/team-reports/<run>/`).

   `<run>` = `YYYY-MM-DD-HHMM` when you first spawn this team; keep it for
   the whole team. `<round>` = the next free number for that name in
   `<REPORTS>`: a file is never overwritten (a stage folder holds the reports
   of every team of the stage). Create the folder with the first brief. This
   is for worker reports only; critic reviews go to `<REVIEWS>` (step 5).
   Reports live on disk, not in the lead's context; the lead reads a report
   only when a decision needs it, and then only the needed section.

   **Handed-over commands.** A teammate puts any other command as plain
   lines with absolute paths in a scratch file and sends you the path before
   any attempt; its files hold code under test, never operations. Run the
   lines you understand inline in your own Bash call, ask the user about
   the rest; over ~20 lines, split by step. Never a command that executes
   the file (`bash`, `sh`, `source`, `eval`, `python3`, `make`, `xargs` on
   it). A denied command is not handed to you; the teammate reports it.
   Why: a teammate's prompt can sit unseen (one missed the user over Remote
   Control); a script hides its content from the safety check and the user;
   running a denied command for a teammate overrides the user's denial; the
   name prefix tells whose a shared scratch file is.

   Append the lines that apply:
   - Repo with `.serena/project.yml`: "Use Serena symbols before Reading files."
   - Research: "Every claim carries its source (DOI, URL, or file:page).
     Mark what you verified in the source vs. inferred. Unsourced claims
     do not go in the deliverable."
   - Zotero without `research-kit-lit:zotero-worker` (may need a restart):
     `research-kit:worker-high` plus the "Stop conditions" of
     the `research-kit-lit:zotero` skill in the brief.

   Context explains how to do the task. It never suggests a bigger task.
5. **Review.** When workers report, brief both critics in one message.
   Both get the user's request verbatim and the goal statement; `crit1`
   also gets the worker report paths (not their contents), the disposable
   critic only the diff or deliverable paths. Each review round is one `task`
   entry: open it before briefing (`python3 -I "${CLAUDE_PLUGIN_ROOT}/skills/research-kit/scripts/rk.py" add task "review round <n>: <what>" --owner lead --note "<what is reviewed, round <n>>"`); both critic briefs carry its `TASK: T-<n>`, never the
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
   topic, `<name>` keeps the critics apart); without `pm/`,
   `<name>-r<round>.md`. Give critics the absolute path in the brief.

   ```
   VERDICT (each: YES / PARTIAL / NO + evidence)
   - Solves the stated problem / answers the question asked?
   - Target actually improves / conclusion actually supported?
   - Is this what was intended, or a neighboring problem/question instead?
   FINDINGS
   - location, problem, owner (teammate name), BLOCKING or minor
   ```

   NO = would not ship as is, and names at least one BLOCKING finding.
   Evidence = a command run or number measured, or a source opened and the
   passage checked. "YES" without it = PARTIAL.
6. **Fix loop.** Only a BLOCKING finding reopens the loop (minor ones go to
   your report as open; why: they do not justify a round of every agent).
   Re-plan the work items, not just patch. Route findings to their owners
   via `SendMessage` (point at the critic report path and finding, do not
   paste it). `crit1` re-reviews all fixes (`SendMessage`, same review
   `TASK:` while it is open); a new `blind<round>` reviews the fixed result.
   Max 2 rounds; then AskUserQuestion.
7. **Integrate and verify.** Engineering: run the tests or checks yourself.
   Research: open the sources of the key claims yourself; `arch1` checks
   the result against its design. Report: what was built or found,
   verification, critic verdicts, open findings, roster used. Collect the
   items with `grep -h '^TO-WASTE: ' <the report paths named in this wave's DONE messages>`
   (plus the stage notes or `pm/reviews/` when critics listed some;
   never read whole reports for this; a line already in `pm/waste/LEDGER.md`
   is done), then close each task on its report
   (`python3 -I "${CLAUDE_PLUGIN_ROOT}/skills/research-kit/scripts/rk.py" close T-<n> --note "<outcome>" --ref <report path>`; after a
   critic NO the task stays running), and the review task with the verdicts
   and the review file paths (`--ref`), then run `research-kit:waste` (`waste.sh lead "<reason>" <paths>`)
   once for all of them; the user approves that one call. Offer to stop teammates that will
   not be reused.

## Talking to the user

- While teammates run, open with **Done** / **Running** (names) / **Needs
  you**. Keep user messages to ~10 lines unless asked.
- When a teammate finishes, route its next item or ask the user at once.
- The always-on rules for talking to the user are in core AGENTS.md section 8
  (read at every session start; this skill does not replace them): a decision
  is its own `AskUserQuestion` call, never a line in a status message; idle
  pings and duplicate notifications get no user message; each question stands
  alone (one topic, the work named in plain words with DOI or path, what each
  option changes); a changed decision goes to every teammate holding the old
  one, in one message. Procedure on top of them:
- No discrete options: offer your recommended answer plus one alternative
  ("Other" covers the rest). Under **Needs you** write only a pointer to what
  you asked.
- A question that does not block yet: in a repo with `pm/ledger.jsonl` log
  it (`rk add deferred "<question>" --owner user`, shown under STATUS
  "Needs you"); ask when it starts to block or at the next natural stop, one
  `AskUserQuestion` call per question, in a row.
- Before saying you are waiting, run `ListAgents`; if nobody runs, say so
  and act. After a resume, assume teammates are gone.

## Red flags

- You are editing files beyond a one-line fix → message the owning teammate.
- You are spawning without a name, or with a task name → roster name.
- A teammate is briefed to orchestrate → you orchestrate; it executes.
- A teammate hands you a script, or you run `bash <file>` → run lines inline.
