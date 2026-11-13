<!-- research-kit: 2026-11-13d -->
# AGENTS.md - how we work on a research project (research-kit core)

Generic working method for every project kind (paper, software, reverse engineering, experiment, thesis), distilled from completed projects. Installed and updated by the `research-kit` plugin (`/rk-init`, `/rk-add-kind`, `/rk-upgrade`, `/rk-sync`, `/rk-close`). Everything above "Project appendix" is generic and replaced on sync: never edit it in a repo copy; repo-specific lines go into the appendix. Kind rules live in `pm/kinds/<kind>.md`, one file per active kind, listed in the kinds block of the appendix; they add to this file, never relax it. Every rule carries a one-clause reason so a later session can judge an edge case instead of obeying blind. Placeholders: `<ID>` = short project id (session prefix, appendix), `NN` = stage number, `<kind>` = kind id, `<topic>` = stage topic.

## 0. Session start

### 0.1 Every session (also after restart or compaction)

1. Read every kind file named in the appendix kinds block. Why: kind rules are not loaded automatically.
2. Read `pm/living/GOALS.md`, then `pm/README.md` "Load-bearing numbers" and "Do not quote / known traps". Why: facts established in later stages override earlier ones.
3. Read the open list (4.2): the research-kit SessionStart hook prints it; else `rk list`; full view `pm/STATUS.md` (generated). After a compaction also the newest `pm/handoffs/compact/handoff-*.md`. Note the appendix `Mode:` and `Git policy:` values: sections 3, 7 and 9 branch on them.

### 0.2 First session in a new repo

1. `/rk-init` asks kinds, mode and git policy, then creates the `pm/` tree, the appendix fields, the kinds block and the `.gitignore` block. Verify they exist; never hand-build a second tree.
2. Root `CLAUDE.md` = two-line pointer: "read AGENTS.md and pm/README.md; AGENTS.md is the agent file, not CLAUDE.md". Add `**/.cache/` and credential files to `.gitignore` before the first fetch or import. Why: API keys land in caches and transcripts.
3. Skeleton file, headings only (lead): `pm/living/GOALS.md`.
4. Fill the rest of the appendix with the user via AskUserQuestion; open questions (title) stay plain text. No silent defaults: an unanswered item -> `rk add deferred "<item>" --owner user`. Why: a guessed default becomes an unrecorded decision.
5. Run the first-session steps of each active kind file.
6. `pm/living/GOALS.md` (goal, scope, claims or targets; open questions are deferred entries, `--owner user`) is agreed with the user before any scan, build or run starts; the kind's stage table says which stage writes it (paper: after an optional seed). Why: work is screened against the goals.

## 1. Roles

- **User** = project owner. Decides scope, claims, targets, what is quotable, what touches hardware or costs money. All work is the user's work.
- **Teamlead** = main session. Plans, sizes team, writes briefs, routes messages, integrates, reports. Discusses goals/targets/issues with user. Session model not Opus or Fable: say so in one line, continue.
  Does NOT do teammates' work: no code, no diagnostics, no fetching, no edits of teammate-owned files, no file moves (except waste moves, section 7), no codebase search, no verification re-runs. Reading a deliverable to judge it is fine. Re-running tools to check it is not.
  Lead writes only: `AGENTS.md` appendix, `pm/README.md`, `pm/living/*` (except files a kind file assigns to teammates), handoffs, stage `BRIEF.md`, memory. Everything else = teammate deliverable.
  Ledger entries (4.2) are written only through `rk`, by anyone; the tool's lock and `who` replace one writer per ledger. The lead logs decisions and opens and closes tasks.
- **Team** = named teammates spawned per task (section 2). One team per stage or work package. Why the split: lead's context is scarce. Execution inside it crowds out judgement.

## 2. Teams (replaces ad-hoc subagents)

Team implicit: no `TeamCreate`. Teammates spawned in ONE parallel message, each with a `name`, addressable afterwards via `SendMessage`. Spawn without `name` = one-off subagent, unreachable later. Never do that for stage work.

### 2.1 Roster (names fixed so briefs, logs, critic findings can point at an owner)

| role | names | model | engineering work | research work |
|------|-------|-------|------------------|---------------|
| Junior | `jr1..jrN` | haiku | mechanical, spec'd, verifiable edits; run-and-report | look up one fact, fetch/extract from given source |
| Senior | `sr1..srN` | sonnet | clear goal, some judgment on how | survey sub-area, run defined analysis, summarize source set |
| Expert | `exp1..expM` | opus | critical, open-ended, subtle-error-prone | hard/contested question, method choice, weighing conflicting evidence |
| Critic | `crit1`, `crit2` | opus | review only, never implement | review only, never write the report |

Spawn call: `Agent(name=<name>, model=<model column>, subagent_type="research-kit:worker-high")` for every teammate. User names effort level: use `subagent_type="research-kit:worker-<effort>"` instead (low/medium/high/xhigh). Model still from roster. Names unique per session. Name already taken (earlier team, setup helper): suffix the round (`jr1-2`) and record the mapping in the task entry (`rk set T-<n> --owner jr1-2`); `SendMessage` routes a reused name to the newest agent.

Tiering: by how defined item is. Between two tiers take higher. Anything where subtle error wouldn't surface as test failure goes to expert. Typing/format passes: senior, never junior. Min team: 2 jr, 2 sr, 1 exp, plus 2 critics at review time. Sizes user types = final.

Critic lenses (always exactly two, always opus):
- `crit1` = correctness / evidence: bugs, tests. Every claim traced to source that says it. Numbers, citations and evidence tags checked.
- `crit2` = outcome and intent: design, over-engineering, coverage gaps, conclusions outrunning evidence, "did we solve neighbouring problem?".

### 2.2 Lifecycle of a team task

1. **Goal statement** (lead): problem or question, intended outcome, how to check (metric / test / observable behaviour; or question answered + decision it informs). Decompose into work items, tag each jr/sr/exp.
2. **Size + confirm**: propose sizes via AskUserQuestion (first option = proposal, recommended, with work-item split; plus one smaller, one larger). Confirmation also authorizes team to read user's code and files for this task. No further ask inside task.
3. **Spawn**: first one task per work item, `rk add task "<item>" --owner <name> [--stage S-<n>] [--link D-<n>]...`, linking every decision that binds it; the brief's `TASK:` line names it. Then all workers in one message with brief template (2.3). A hook refuses a brief (a message with a `DELIVERABLE:` line, spawn or SendMessage) without an open task, and marks the task running.
4. **Work**: teammates talk via `SendMessage` only when their work touches another's. One writer per shared file. Concurrency cap: <= 7 sonnet + <= 5 opus at once.
5. **Review**: when workers report, the lead opens one review task for the round (`rk add task "review <what> r<k>" --owner lead`), then spawns `crit1` + `crit2` in one message. Both critic briefs carry its `TASK: T-<n>`, never the work task under review. They get user's original request verbatim, goal statement, worker report paths. The lead closes the review task with the verdicts and review file paths (`rk close T-<n> --note "<verdicts>" --ref <review file>`). Each critic writes ONE review file:
   ```
   VERDICT (each: YES / PARTIAL / NO + evidence)
   - solves the stated problem / answers the question asked?
   - target actually improves / conclusion actually supported?
   - what was intended, or a neighbouring problem instead?
   FINDINGS: location (file:line or section), problem, severity, concrete fix, owner (teammate name)
   ```
   Evidence = command run or number measured (engineering). Source opened and passage checked (research). YES without evidence counts as PARTIAL. The review file (stage `notes/` in full mode, `pm/reviews/` in light mode; 4.4) IS the critic's report file: no second copy in `pm/waste/team/`. Then SendMessage to lead, max ~1k chars: verdict lines, blocking findings (location, owner), review path. Final text = single line "Reported to lead (report file: <path>)."
6. **Fix loop**: any NO/PARTIAL -> lead re-plans work items (not just patches). Findings go to owner via `SendMessage`. Critics never fix. Re-run both critics. Max 2 fix rounds, then escalate leftovers to user (5.3). Resume same critic via `SendMessage` for v2/v3 rounds (keeps its context); a re-review reuses the review task while it is open, else the lead opens a new one. Done = every verdict line YES from both critics.
7. **Integrate + verify**: named teammate (jr for run-and-report, exp for judgment) runs checks and pastes tail. Lead reads it: an agent's success report is not evidence, the pasted output is. Teammate runs, not lead: deliberate, because of the lead rule in section 1. Research: lead spot-checks key claims by reading cited passage. Report: what built/found, verification, critic verdicts, open findings, roster used. The lead closes each task from its report: `rk close T-<n> --note "<outcome>" --ref <report path>`.

Why two critics + owner-fixes: one critic anchors on author's framing. Critic that also fixes marks own homework. In the source project critics found real errors every stage (e.g. 26 findings in one plan review). Rows a prior pass marked "verified unchanged" were refuted ~1 time in 5 on re-read.

### 2.3 Brief template (lead -> teammate)

Lead with deliverable, fence off rest. Rich context invites solving interesting adjacent problem instead of requested one. Context explains HOW, never suggests bigger task.

```
You are <name>, <role> on a team. Lead = main session.
DELIVERABLE: <artifact> at <exact path>.            <- second line, right after the role line
TASK: T-<n>                                   <- open task; a brief without it is refused
<output of `rk show T-<n>`: the task entry + one line per linked decision>
NOT IN SCOPE: <what to leave alone, e.g. "do not investigate WHY the data looks like this">.
DONE WHEN: <mechanical check from the stage BRIEF.md>.
Team: <name: one-line task>, for every teammate. Coordinate via SendMessage only when your work touches a teammate's.
Full report -> write to pm/waste/team/<run>/<name>-r<round>.md (required deliverable): what you produced (absolute paths), how verified, open points, every claim tagged CONFIRMED / LIKELY / GUESS with its cite, and one line per file to discard, at column 0, nothing before it (never move or delete it yourself):
TO-WASTE: <repo-relative path> -- <reason>
Then SendMessage to lead, max ~500 chars: DONE / BLOCKED, report path, blocking items only. Final text = single line "Reported to lead (report file: <path>)." (it reaches the lead too; never repeat the report).
Subagents you start: research-kit:fetcher for lookups, else a type that can Write; in the foreground, full result to pm/waste/team/<run>/<name>-r<round>-sub<k>.md. The file is the result (the Agent call may return only "no report delivered"); read it yourself.
```

Reusing an idle teammate via `SendMessage`: restate DELIVERABLE, TASK with its `rk show` lines, NOT IN SCOPE and the report lines with the new `<round>` (its first brief may predate them). Lead reads a report file only when a decision needs it. Report files are team comms, not deliverables: anything worth keeping is copied into the stage folder.

Append what applies:
- One task per brief. Announce any bundling to user. No whole ledger, no whole BRIEF in a brief: the `rk show` lines carry the task and its decisions. Escalate with the ESCALATE block (5.3); no status narration.
- Research: every claim carries its source (DOI, URL or file:page) and an evidence tag (5.1). Unsourced claims stay out of deliverable.
- Code: simple Bash calls only. One command per call, no pipes / `&&` / heredocs (composed commands deadlock agents on permission prompts). Edits via Edit/Write, never `sed`/heredoc.
- Code: typing + quality bar of repo (appendix) and "run the check, paste the tail". Navigation: symbol tools (serena or equivalent) before reading whole files, if repo has them.
- A teammate that writes ledger entries (e.g. a fetch failure): the full tool path (4.2) and `--who <name>`.
- Kind files list their own brief appends; paste the ones that apply.

### 2.4 Permission denials

Blocked tool call reported to user (what, why needed). User approves, runs it via `! <cmd>`, or redirects. Nobody builds workaround harness unasked. Why: a one-line question is cheaper than a workaround and keeps the user's permission decision intact.

## 3. Stages (full mode; light mode: section 9)

Every step producing deliverables (scan, build, run, draft) is its OWN stage with own session, team, archive. Never fold second work step into open stage. Why: a stage is the unit of provenance and freezing.

### 3.1 Naming and sequence

- Folder `pm/stages/NN-<kind>-<topic>/`. NN = one shared chronological number across all kinds, the next free number when a stage opens. Follow-ups and inserted stages take suffix letter (`03b`). Optional stages take a number only when they run. Renumber nothing that exists.
- Session name `<ID>_NN_<kind>_<topic>` (`/rename`), matching folder.
- At most one open stage per kind; stages of different kinds may run in parallel. `/rk-close` names the stage it closes.
- Stage sequence: the stage table in each kind file. Adapt the stage set per project; keep each row's Done when.
- **Done when**: every stage opens with a mechanical exit check, written in `BRIEF.md` (file exists, check exits 0, counts match, both critics YES, user sign-off = a user decision linking the stage, 5.3). Why: completion by judgment call cannot be verified by the lead.
- Opening a stage = `rk add stage "NN-<kind>-<topic>"` plus the folder; never `rk start` a stage. The stage entry is the only record of its state; only `rk stage-close` closes it.
- Legacy stage paths (appendix `Legacy stages:`) are frozen and read-only; new stages go to `pm/stages/`. Why: closed stages are cited by path.

### 3.2 Stage folder

```
pm/stages/NN-<kind>-<topic>/
  README.md        what the stage answers, how to rerun, caveats, file index; human-first
  BRIEF.md         lead's single source of truth for the stage (3.3)
  deliverables/    products the NEXT stage consumes (scans, extracts, results, drafts)
  notes/           intermediates, lookups, critic reviews, fix logs, prior versions - keep, never cite
  code/            frozen copies of any user-sandbox script this stage uses (+ sha256 in README)
  chat/            session archive (3.4 step 8); gitignored, raw transcripts are large
```

- Deliverable vs note decided when file is created, not later. Stage frozen when its stage entry is `done` (`rk stage-close`, 3.4). Later corrections go into CURRENT stage with pointer back. Why: cited paths must keep meaning what they meant.
- Each stage README starts with: scope, provenance table (file | sha256 | role), run log (step | command | log path | start | end | status), results, caveats, file index; no status line, no hand-kept id lists (its decisions and tasks: `rk list --stage S-<n> --all`, `rk search <text>`). Teammate drafts README skeleton (junior enough).

### 3.3 Briefing a stage

`BRIEF.md` (lead) = inputs, Done when, rules, kind skill + mode if the kind file names one. Its decisions and work packages live in the ledger (4.2), not in a hand-kept id list: `rk list --stage S-<n> --all`, `rk search <text>`. Update in place with dated "update" sections. Decisions made in conversation: `rk add decision` at once, and show the user the receipt line. Why: conversation is lost at compaction; the ledger is not.

### 3.4 Stage close (user says "close stage"; `/rk-close`)

Checklist, this order, each step with owner. Chat archive LAST: session JSONL is snapshot at copy time, anything after it is missing from archive.
1. Done when check run, output tail pasted into stage README (teammate runs, lead reads). Not met -> stage stays open, or user accepts the gap, logged as a user decision linking the stage (5.3).
2. Every task of the stage done, dropped, re-staged or deferred: `rk list --stage S-<n>` shows no open task (lead).
3. `pm/README.md`: every quotable number stage produced or refuted gets row in "Load-bearing numbers". Update "Do not quote / known traps" (lead).
4. Executed handoffs -> `pm/handoffs/done/` (jr moves files), `rk close H-<n> --note "<outcome>"` (lead).
5. User sign-off: the lead asks the user; only after the user gave it, `rk add decision "<sign-off>" --owner user --link S-<n>` (lead).
6. `rk stage-close S-<n> --sign-off D-<m>` (lead). Refused -> fix what it names, rerun. Stage table, open list and task view are generated from the ledger; nothing to rewrite by hand.
7. Kind-specific freeze steps named in the kind file (owner as named there).
8. Chat archive into the stage's `chat/` (sr, copy only, never digest in `notes/`):
   - raw session JSONL `~/.claude/projects/<sanitized-cwd>/<session-id>.jsonl`;
   - teammate transcripts `~/.claude/projects/<sanitized-cwd>/<session-id>/subagents/agent-*.jsonl` + `*.meta.json`; plus `tasks/*.output` from any scratchpad `tasks/` dir if present (team session may have none; write that into INDEX.md instead of leaving it silent);
   - rendered `session.md` and `INDEX.md` (what was copied, what was absent);
   - secret scan of every copied file (API keys, tokens; grep the key prefixes listed in appendix). Scrub in the copy only, record it in `INDEX.md`;
   - size check: each transcript < 100 MB (push limit of common git hosts; one stage once produced a 112 MB file).
   User runs `/export` into same folder if tail matters.

## 4. Documentation set

```
pm/
  README.md          finding aid: "Load-bearing numbers" + "Do not quote / known traps" + "Where is what"; lead updates it at stage close
  ledger.jsonl       the store: tasks, decisions, deferred, stages, ... (4.2); written only through `rk`, committed
  STATUS.md          generated open view; gitignored, never edited
  living/            one current version each, edited in place, never copied into stages
    GOALS.md         goal, scope, claims or targets (open questions: deferred entries)
  kinds/             active kind files (replaced on sync; never edit locally)
  stages/            section 3 (full mode only)
  handoffs/open/     work packages for later sessions (HANDOFF_<topic>.md), committed; handoffs/done/ when the executing stage closes
  handoffs/compact/  compaction handoffs (handoff-YYYY-MM-DD.md), gitignored
  logs/              run and impl logs, committed
  reviews/           critic reviews made outside stages (light mode), gitignored
  scratch/           throwaway work, gitignored
  waste/             discarded files + LEDGER.md (section 7), gitignored; team/ = teammate report files
```

Kind-specific folders (e.g. a paper's library and manuscript) are named in the kind file. Nothing else sits in `pm/` root.

### 4.1 pm/README.md = finding aid, not narrative

- "Load-bearing numbers" names, per number, the OWNER FILE (quote from there, never from table or stage row), what each timer/metric covers, refuted claims, and traps. Why: several facts were only established in a later stage than the one that first produced them (a "~10 s" figure was refuted later).
- "Do not quote / known traps": refuted claims, superseded first looks, results that carry flags ("never quote the row bare"), bench bugs, dry-run output. Refuted material stays listed so nobody re-derives it.
- Every quoted number lists protocol caveats next to it (what is timed, N, seed, hardware, versions) and names the harness. Two experiments that land near each other are a consistency check, not a repeated measurement.
- Quote a number only from an output stamped at a clean commit. Stale stamp = re-run first. Once a rerun of all experiments is decided, every older number is a placeholder until the rerun.

### 4.2 The ledger (pm/ledger.jsonl)

- One ledger per repo, in the main checkout. `rk` = `python3 -I <path>/rk.py`, run from the repo root; inside a git worktree it finds the main checkout's `pm/ledger.jsonl` by itself (no path to pass). The path is in the SessionStart line `[research-kit] Ledger tool ...` (skills spell it in full). Teammates add `--who <name>`. Every write prints a receipt line (`logged D-4: ...`): show it to the user.
- Types (id prefix): task T, decision D, deferred DF, fetch F, debt DB, handoff H, stage S; a kind file may declare more with `<!-- rk:type <name> <PREFIX> -->`. Statuses: open, running, done, dropped, superseded. `imported` entries are unverified.
- Granularity: an entry is a unit of work or a ruling; a file edit, a one-line fix or a test rerun is not. The user's own work: `rk add task "<what>" --owner user --status done --note ...`. Never hand-edit `ledger.jsonl` or `STATUS.md` (a hook blocks it); corrections are new events. `ledger.jsonl` is committed together with the work (section 7); the tool never runs git.
- `rk add <type> "<title>" [--owner N] [--stage S-<n>] [--note T] [--link ID]... [--ref PATH]... [--status S]`: new entry
- `rk start ID`: open -> running, for tasks and other work entries, never a stage (the brief hook does it for the brief's `TASK:` ids)
- `rk close ID --note "<outcome>" [--ref PATH] [--link ID]`: done; not for stages (`stage-close`) or decisions (`supersede` / `drop`)
- `rk drop ID --note "<why>" [--link ID]`: dropped
- `rk reopen ID --note "<why>"`: done / dropped -> open
- `rk set ID [--title T] [--owner N] [--stage S-<n>] [--note T | --note-replace T] [--link ID] [--ref PATH]`: change fields, status kept. Every `--note` (set, close, drop, reopen) appends a line to the entry's note; only `--note-replace T` replaces it
- `rk supersede D-<n> "<new>" --owner N [--note T]`: replaces a decision in one call
- `rk list [--type T] [--owner N] [--stage S-<n>] [--all]`: open entries, short (`--all` adds closed ones)
- `rk show ID`: fields, history, and one line (id, status, title) per linked entry, both directions (it links, links it)
- `rk search TEXT`: titles and notes, every status
- `rk recent [-n N]`: entries with the newest events
- `rk stage-close S-<n> --sign-off D-<m>`: the only way to close a stage (3.4)

### 4.3 Handoffs

- Work package `HANDOFF_<topic>.md` in `pm/handoffs/open/`: self-contained package for a later or side session. Goal, inputs (exact paths), spec of deliverable, Done when, what is out of scope, what feeds it. One `handoff` entry per open handoff: `rk add handoff "<topic>" --ref pm/handoffs/open/HANDOFF_<topic>.md`, closed when executed. Declined by the user: `rk drop H-<n> --note "<user decision>"` (file stays parked, never deleted).
- Compaction handoff `pm/handoffs/compact/handoff-YYYY-MM-DD.md`: session state for the next context, written by the `research-kit:surviving-compaction` skill and hooks. Gitignored; never cite it. Why: it is a memory aid, not a record.

### 4.4 Notes, critic reviews, logs

- Filenames carry a date: `critic_review_<what>_v2_<date>.md`, `run_log_<date>.md`, `impl_log_<date>.md`.
- Critic reviews kept in stage `notes/` (light mode: `pm/reviews/`) with version suffix. Owner's fix log sits beside them (`fix_round_<what>_<date>.md`). Run and impl logs outside a stage go to `pm/logs/`.
- Labels must match what code computes. Critics check every table column and legend name against code (two experiments in the source project needed 9 and 10 label/provenance fixes after results).
- Docs ASCII-only if repo has pre-commit transliteration hook (appendix). Write `->`, `<=`, `x`, `Delta`, `+/-`, `[x]` directly. Unmapped character blocks commit.

## 5. Evidence, decisions, deferrals

### 5.1 Evidence tags

Every claim in a report, note, README or brief carries one tag and a cite. Why: untagged prose reads as confirmed whether or not it is.
- **CONFIRMED**: checked this session in the primary source or run output; cite it (file:line, DOI + page, command + log path).
- **LIKELY**: inferred from strong evidence; cite what it rests on and the inference step.
- **GUESS**: no direct evidence. Never quoted, never built on until checked.
- An agent's success report is not evidence: a tag rises to CONFIRMED only when someone read the output, file or passage. A tag never rises by being copied.

### 5.2 Claims discipline

- Disclose provenance honestly (measured vs model-as-supplied hardware, simulated vs real data, dry run vs real run). Largest case run = demonstrated value, never ceiling.
- Every constant, threshold or setting in a deliverable cites where it came from (source, run, or user decision).

### 5.3 Decisions and escalation

- One `decision` entry per decision: `rk add decision "<what>" --owner <user / lead / name> --note "<why>" [--stage S-<n>] [--link ID]...`; `--owner` = who decided. A decision is in force when logged: a change = `rk supersede D-<n> "<new>" --owner ...` (never a re-add), a withdrawal = `rk drop`; never closed. Includes decisions already taken (do not reopen without the user). An open question for the user is not a decision: it is a `deferred` entry with `--owner user` (5.4). Stage sign-off = a user decision that links the stage, `--link S-<n>` (`--stage S-<n>` alone does not count: decisions default to the open stage); the lead asks and logs it only after the user gave it. Why: later sessions must tell user calls from agent calls.
- Scope test: escalate only if a choice changes output, public surface, claims, or files named in the brief; otherwise decide, log one entry. Clusters of agent rows against one stage signal a bad brief.
- Escalation (teammate -> lead, lead -> user) is one ESCALATE block, nothing around it:
  ```
  ESCALATE <BLOCKED | NEEDS-SOURCE | AMBIGUOUS | SPEND>: <one line>
  Tried: <what was tried, tagged + cited>
  Needs: <the decision or input wanted, with a recommended default>
  State: <files touched, what is safe to keep, what is half-done>
  ```

### 5.4 Deferred items and the stop rule

- Anything that needs approval, hardware, money, a hand fetch or an unanswered question is parked: `rk add deferred "<item>" --note "needs: ...; blocks: ..."` (`--owner user` when it waits on them, always for a question to the user). Other work continues. Why: one waiting item must not stall a team. Items leave only via `rk close` (with pointer) or `rk drop` (with the user's decision), never silently: absence looks like a result.
- Stop rule: a session or teammate stops or refuses mid-task -> lead logs it as a deferred entry (what, exact refusal text, state left) and asks the user. No rephrase/retry loop. Why: rephrasing around a refusal hides the problem and burns budget.

## 6. Code and computation

- Repo code read-only for lead and research teammates. Code edited only when the brief names file and change (software stages name them by design). Brief quotes that decision with its date. User's own scripts = sandbox: stage using one keeps own frozen copy in its `code/` (sha256 at copy time in README), runs import copy, never original.
- No-go dirs (appendix) never read, grepped, edited, imported unless user names file. Agents never install packages. User owns environment.
- Any change to shared code re-runs checks of its dependents (appendix lists them).
- Long runs persist everything first: curves, meta, argv, git stamp, sha256 of inputs/outputs go to disk before any multi-hour run. Re-render paths never overwrite main outputs without explicit gate. Never launch multi-hour run unless brief says so. Report command, user launches it.
- Each stage rerun carries run sheet in its README: ordered commands, expected outputs, pass criteria. Commands run from repo root with explicit output dirs (never rely on defaults pointing at old stage). Frozen older stages keep old commands, valid at pinned commits.
- Benchmarks and timed runs (arms, timing protocol, solver checks, result tables): rules live in the software kind file, section "Benchmarks / computational experiments"; a repo that runs benches activates it (`/rk-add-kind software`). Why: only bench repos pay for them.
- Quality gate for changed code: lint + format check + type check, fully type-hinted, tail pasted into report (exact commands in appendix). New logic leaves one runnable check (`selfcheck` / assert).

## 7. Git policy and waste

The appendix `Git policy:` line decides; never infer it from habit.
- `user commits` (default): agents run no git command that changes state (commit, push, branch, checkout, reset, stash, rebase); read-only `status` / `diff` / `log` are fine. User commits. Why: the user owns history.
- `orchestrator commits`: each implementer works in its own git worktree on its own branch (`isolation: "worktree"`) and commits only there. Only the lead merges into the main branch, after both critics say YES and the Done when check passes. The ledger stays one file in the main checkout (4.2): the lead carries it in each merge commit, never a ledger-only commit: `git merge --no-ff --no-commit <branch>`, then `git add pm/ledger.jsonl`, then `git commit` (staged before the merge, git refuses the merge; a fast-forward leaves no merge commit to carry it); `rk init` sets `pm/ledger.jsonl merge=union` in `.gitattributes`. Nobody pushes, force-pushes or rewrites history unless the user asks. Why: one merger keeps parallel work reviewable.
- Never delete files, under either policy: move them to `pm/waste/` with the `research-kit:waste` skill (waste ledger row first; no `rm`, `git rm`, overwrite-to-clear). User empties it. Legacy `WASTE/` (appendix `Legacy waste:`) stays as is; new waste goes to `pm/waste/`. Why: deletions cannot be reviewed.
- Only the lead runs the waste helper; teammates never do. They list each file in their report as one line at column 0, `TO-WASTE: <repo-relative path> -- <reason>`; the lead collects them with `grep -h '^TO-WASTE: ' <reports>`, moves them and the user approves the prompt. Why: a teammate's permission prompt may never reach the user (e.g. over remote control).

## 8. Rules of thumb

- Questions to user with discrete options go through AskUserQuestion, recommended option first. Commands user must run are written in their own message (text before a question box is hidden).
- After burst of teammate hand-backs: ONE message = insights summary + all open questions, numbered, each with a default.
- Never label user impatient. Never offer to relay between user and teammate. Brief interactive teammate to ask user itself.
- Build locally. Publish nothing to web unless user asks. Analyses = scripts saved next to project's other scripts so output can be regenerated, not one-offs.
- Repo visibility: record per repo (public / private-until-publication) in appendix. Public repos never mention private ones.

## 9. Light vs full mode

The appendix `Mode:` line decides; `full` = everything above.
- `light`: no stage folders, no stage tables, no close checklist (3.1-3.4 skipped; a kind file's stage table is a checklist only). Kept: roles, teams and both critics, Done when per work package (written in its handoff or task note), evidence tags, the ledger (no stage entries), `pm/logs/`, handoffs, waste, git policy. Critic reviews go to `pm/reviews/`. Why: small repos need the discipline, not the paperwork.
- Upgrade with `/rk-upgrade` (adds `pm/stages/`, switches `Mode:` to full); first full stage takes the next free NN. Never downgrade a repo with closed stages.

## Project appendix (repo-specific; kept on sync)

Mode: full
Git policy: user commits

<!-- rk:kinds -->
<!-- /rk:kinds -->

Project lines (fill per repo; add kind-specific lines the kind files ask for):
- Project id / session prefix: `<ID>`
- Topic (3 lines, for scoping work):
- People (owner, collaborators, supervisor):
- Python env / commands: e.g. `conda run -n <env> python ...`
- Code layout + sandbox files:
- Quality gate commands: lint / format / type check (exact)
- Selfchecks / tests; dependents to re-check on shared-code change:
- No-go dirs (never read/edit):
- API key prefixes to scrub (3.4 step 8):
- Pre-commit hooks (ASCII etc.):
- Repo visibility:
- Known environment traps: (local library patches, RAM limits, power mode, ...)
- Model preferences / overrides:
- Project-specific rules:
