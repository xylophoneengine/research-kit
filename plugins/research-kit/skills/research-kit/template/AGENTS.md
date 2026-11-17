<!-- research-kit: 2026-11-17c -->
# AGENTS.md - how we work on a research project (research-kit core)

Generic working method for every project kind (paper, software, reverse engineering, experiment, thesis), distilled from completed projects. Installed and updated by the `research-kit` plugin (`/rk-init`, `/rk-add-kind`, `/rk-upgrade`, `/rk-sync`, `/rk-close`). Everything above "Project appendix" is generic and replaced on sync: never edit it in a repo copy; repo-specific lines go into the appendix. Kind rules live in `pm/kinds/<kind>.md`, one file per active kind, listed in the kinds block of the appendix; they add to this file, never relax it. Every rule carries a one-clause reason so a later session can judge an edge case instead of obeying blind. Placeholders: `<ID>` = short project id (session prefix, appendix), `NN` = stage number, `<kind>` = kind id, `<topic>` = stage topic.

## 0. Session start

### 0.1 Every session (also after restart or compaction)

1. Read every kind file named in the appendix kinds block. Why: kind rules are not loaded automatically.
2. Read `pm/living/GOALS.md`, then `pm/README.md` "Load-bearing numbers" and "Do not quote / known traps". Why: facts established in later stages override earlier ones.
3. Read the open list (4.2): the research-kit SessionStart hook prints it; else `rk list`; full view `pm/STATUS.md` (generated). After a compaction also the newest `pm/handoffs/compact/handoff-*.md`. Note the appendix `Mode:` and `Git policy:` values: sections 3, 7 and 9 branch on them.

### 0.2 First session in a new repo

1. `/rk-init` asks kinds, mode and git policy, and whether `pm/` stays local only, then creates the `pm/` tree, the appendix fields, the kinds block and the `.gitignore` block (local-only: the exclude block instead). Verify they exist; never hand-build a second tree.
2. Root `CLAUDE.md` = two-line pointer: "read AGENTS.md and pm/README.md; AGENTS.md is the agent file, not CLAUDE.md". Add `**/.cache/` and credential files to `.gitignore` before the first fetch or import. Why: API keys land in caches and transcripts.
3. Skeleton file, headings only (lead): `pm/living/GOALS.md`.
4. Fill the rest of the appendix with the user via AskUserQuestion; open questions (title) stay plain text. No silent defaults: an unanswered item -> `rk add deferred "<item>" --owner user` (title: one line, 160 characters at most). Why: a guessed default becomes an unrecorded decision.
5. Run the first-session steps of each active kind file.
6. `pm/living/GOALS.md` (goal, scope, claims or targets; open questions are deferred entries, `--owner user`) is agreed with the user before any scan, build or run starts; the kind's stage table says which stage writes it (paper: after an optional seed). Why: work is screened against the goals.

## 1. Roles

- **User** = project owner. Decides scope, claims, targets, what is quotable, what touches hardware or costs money. All work is the user's work.
- **Teamlead** = main session. Plans, sizes team, writes briefs, routes messages, integrates, reports. Discusses goals/targets/issues with user. Session model not Opus or Fable: say so in one line, continue.
  Does NOT do teammates' work: no code, no diagnostics, no fetching, no edits of teammate-owned files, no file moves (except waste moves, section 7), no codebase search, no verification re-runs. Reading a deliverable to judge it is fine. Re-running tools to check it is not. One exception: command lines a teammate handed over in a file (2.3) are read and run inline, line by line, never as a command that executes the file.
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
| Architect | `arch1` (optional, one) | fable | interfaces between work items, rules a change touches; one design file, never code | shared output format, what each source set must answer, what counts as verified |
| Critic | `crit1`, `blind<round>` | opus | review only, never implement | review only, never write the report |

Spawn call: `Agent(name=<name>, model=<model column>, subagent_type="research-kit:worker-high")` for every teammate. User names effort level: use `subagent_type="research-kit:worker-<effort>"` instead (low/medium/high/xhigh). Model still from roster. Names unique per session. Name already taken (earlier team, setup helper): suffix the round (`jr1-2`) and record the mapping in the task entry (`rk set T-<n> --owner jr1-2`); `SendMessage` routes a reused name to the newest agent.

Tiering: by how defined item is. Between two tiers take higher. Anything where subtle error wouldn't surface as test failure goes to expert. Typing/format passes: senior, never junior. Min team: 2 jr, 2 sr, 1 exp, plus a loop critic and a disposable critic at review time. Sizes user types = final. `arch1` when the items of two or more workers meet at an interface, or the task changes or relaxes a rule that tests, code or texts already encode (else the lead writes INTERFACES and CHANGE IMPACT blocks into the briefs): it designs, delivers one design file (requirements and checks, interfaces, change impact, decisions) at the path the lead gives before any worker starts, never routes, spawns or implements, and after integration checks the result against its design and reports deviations to the lead. These triggers are the lead's recommendation in the design-step question (3.3), not the choice (question not asked, e.g. light mode or mid-stage: the lead asks it at team sizing); on a no the lead plans and writes the INTERFACES and CHANGE IMPACT blocks into the briefs itself.

Critic lenses (always opus):
- `crit1` = loop critic, correctness / evidence: bugs, tests. Every claim traced to source that says it. Numbers, citations and evidence tags checked. Stays for the whole loop and re-reviews the fixes with its memory.
- `blind<round>` = disposable critic, outcome and intent: design, over-engineering, coverage gaps, conclusions outrunning evidence, "did we solve neighbouring problem?". A fresh agent every round, never reused or messaged again; sees only the diff or deliverable, the user's request verbatim and the goal statement, no worker reports. Why: worker reports anchor a critic on their framing.

### 2.2 Lifecycle of a team task

1. **Goal statement** (lead): problem or question, intended outcome, how to check (metric / test / observable behaviour; or question answered + decision it informs). Decompose into work items, tag each jr/sr/exp.
2. **Size + confirm**: propose sizes via AskUserQuestion (first option = proposal, recommended, with work-item split; plus one smaller, one larger). Confirmation also authorizes team to read user's code and files for this task. No further ask inside task.
3. **Spawn**: first one task per work item. An item the stage BRIEF lists already has its task (3.3): `rk set <label> --owner <name>`. Any other item: `rk add task "<item>" --owner <name> --note "<deliverable, scope>" [--label <stage code>/<item>] [--ref <brief file>] [--stage S-<n>]` (no `--note`: refused). Link every decision that binds the task (`--link D-<n>`); the brief's `TASK:` line names it by id or label, listed first (`TASK: T-12` or `TASK: 03b/W2, T-3`; a label after other words does not count). Then all workers in one message with brief template (2.3). A hook refuses a brief (a message with a `DELIVERABLE:` line, spawn or SendMessage) without an open task, and marks the task running.
4. **Work**: teammates talk via `SendMessage` only when their work touches another's. One writer per shared file. Concurrency cap: <= 7 sonnet + <= 5 opus at once.
5. **Review**: when workers report, the lead opens one review task for the round (`rk add task "review <what> r<k>" --owner lead --note "<what is reviewed, round k>"`), then briefs `crit1` and a fresh `blind<k>` in one message. Both critic briefs carry its `TASK: T-<n>`, never the work task under review. Both get user's original request verbatim and goal statement; `crit1` also worker report paths, `blind<k>` only the diff or deliverable paths. The lead closes the review task with the verdicts and review file paths (`rk close T-<n> --note "<verdicts>" --ref <review file>`). Each critic writes ONE review file:
   ```
   VERDICT (each: YES / PARTIAL / NO + evidence)
   - solves the stated problem / answers the question asked?
   - target actually improves / conclusion actually supported?
   - what was intended, or a neighbouring problem instead?
   FINDINGS: location (file:line or section), problem, BLOCKING or minor, concrete fix, owner (teammate name)
   ```
   Evidence = command run or number measured (engineering). Source opened and passage checked (research). YES without evidence counts as PARTIAL. The review file (stage `notes/` while a stage is open, else `pm/logs/team/<run>/`; 4.4) IS the critic's report file: no second copy among the team reports. Then SendMessage to lead, max ~1k chars: verdict lines, blocking findings (location, owner), review path. Final text = single line "Reported to lead (report file: <path>)."
6. **Fix loop**: only a BLOCKING finding reopens the loop (minor ones do not justify a round of every agent) -> lead re-plans work items (not just patches). Findings go to owner via `SendMessage`. Critics never fix. `crit1` re-reviews the fixes, a new `blind<k>` reviews the fixed result. Max 2 fix rounds, then escalate leftovers to user (5.3). Resume `crit1` via `SendMessage` for v2/v3 rounds (keeps its context); a re-review reuses the review task while it is open, else the lead opens a new one. Done = no BLOCKING finding open from either critic AND every remaining minor finding logged as a debt entry (`rk add debt "<finding>" --ref <review file>`) or dropped with a reason in the close note. Why: an unlogged minor finding is lost at compaction. Any edit made after a YES, even a minor fix, is listed in the close note of the task it belongs to (`after YES: <file, what, why>`) or re-checked by the critic. Why: a YES covers the state the critic read, and nobody reviewed the later edits.
7. **Integrate + verify**: named teammate (jr for run-and-report, exp for judgment) runs checks and pastes tail. Lead reads it: an agent's success report is not evidence, the pasted output is. Teammate runs, not lead: deliberate, because of the lead rule in section 1. Research: lead spot-checks key claims by reading cited passage. Report: what built/found, verification, critic verdicts, open findings, roster used. The lead closes each task from its report: `rk close T-<n> --note "<outcome>" --ref <report path>`; a task whose work is not on the base branch is staged instead (`rk staged T-<n> --note "<branch, commit>" --ref <report path>`) and landed by id (`rk land T-<n>... --note "<merge commit>"`) when its branch lands; a bare `rk land` closes every staged entry.

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
Run yourself only one-line read commands, the named check, one-line `rk` commands, and one-line writes inside your own scratch folder; anything else goes as plain lines in a file to the lead.
Full report -> write to <REPORTS>/<name>-r<round>.md (required deliverable): what you produced (absolute paths), how verified, open points, every claim tagged CONFIRMED / LIKELY / GUESS with its cite, and one line per file to discard, at column 0, nothing before it (never move or delete it yourself):
TO-WASTE: <repo-relative path> -- <reason>
Then SendMessage to lead, max ~500 chars: DONE / BLOCKED, report path, blocking items only. Final text = single line "Reported to lead (report file: <path>)." (it reaches the lead too; never repeat the report).
Subagents you start: research-kit:fetcher for lookups, else a type that can Write; in the foreground, full result to <REPORTS>/<name>-r<round>-sub<k>.md. The file is the result (the Agent call may return only "no report delivered"); read it yourself.
```

`<REPORTS>` (absolute path in the brief): full mode with a stage open = `pm/stages/<stage folder>/notes/team/`; light mode or no open stage = `pm/logs/team/<run>/` (`<run>` = `YYYY-MM-DD-HHMM` of the first spawn); repo without `pm/` = the lead's scratchpad. `<round>` = next free number for that name there: never overwrite a report. Reports are tracked with the repo, never in `pm/waste/` (the user empties it; a ref to a report must outlive it).

Reusing an idle teammate via `SendMessage`: restate DELIVERABLE, TASK with its `rk show` lines, NOT IN SCOPE and the report lines with the new `<round>` (its first brief may predate them). Lead reads a report file only when a decision needs it. Report files are team comms (stage `notes/`: kept, never cited as a result), not deliverables.

Append what applies:
- One task per brief. Announce any bundling to user. No whole ledger, no whole BRIEF in a brief: the `rk show` lines carry the task and its decisions. Escalate with the ESCALATE block (5.3); no status narration.
- Research: every claim carries its source (DOI, URL or file:page) and an evidence tag (5.1). Unsourced claims stay out of deliverable.
- Code: simple Bash calls only. One command per call, no pipes / `&&` / heredocs (composed commands deadlock agents on permission prompts). Edits via Edit/Write, never `sed`/heredoc. Typing + quality bar of repo (appendix) and "run the check, paste the tail". Navigation: symbol tools (serena or equivalent) before reading whole files, if repo has them.
- A teammate that writes ledger entries (e.g. a fetch failure): the full tool path (4.2) and `--who <name>`. Those one-line `rk` commands, and under `orchestrator commits` the commits in its own worktree (7) when the brief says so, are the named exceptions to the brief's command line. Anything else is a file of plain lines with absolute paths (its files hold code under test, never operations); the lead runs the lines it understands inline, asks the user about the rest, splits over ~20 lines by step, and never hands a denied command on (2.4). Why: a teammate's prompt can sit unseen; a script hides its content from the safety check and the user. Kind files list their own brief appends; paste the ones that apply.

### 2.4 Permission denials

Blocked tool call reported to user (what, why needed). User approves, runs it via `! <cmd>`, or redirects. Nobody builds workaround harness unasked. Why: a one-line question is cheaper than a workaround and keeps the user's permission decision intact. Refusal text "a hook changed this call's input" (or "no verdict"): a hook rewrote the call after the permission check, so the teammate did nothing wrong and a retry fails again. Teammate stops and reports it; the lead names the rewriting hook to the user at once (which hook, what it rewrote to what, which settings file holds it) and asks how to go on. Why: the cause sits outside the kit, only the user can fix it, and every teammate that retries burns budget.

## 3. Stages (full mode; light mode: section 9)

Every step producing deliverables (scan, build, run, draft) is its OWN stage with own session, team, archive. Never fold second work step into open stage. Why: a stage is the unit of provenance and freezing.

### 3.1 Naming and sequence

- Folder `pm/stages/NN-<kind>-<topic>/`. NN = one shared chronological number across all kinds, the next free number when a stage opens. A planned stage has folder `pm/stages/P-<n>-<kind>-<topic>/` (n = its ledger id) and no NN; lists show a forecast `~NN`. Follow-ups (`--follows S-<m>`) take suffix letter (`03b`); an inserted stage takes the next NN, never a letter. Optional stages take a number only when they run. Renumber nothing that exists. Why: the forecast is computed, so planning ahead stores no number that a later stage could make wrong.
- Session name `<ID>_NN_<kind>_<topic>` (`/rename`), matching folder.
- At most one open stage per kind; stages of different kinds may run in parallel. `/rk-close` names the stage it closes.
- Stage sequence: the stage table in each kind file. Adapt the stage set per project; keep each row's Done when.
- **Done when**: every stage opens with a mechanical exit check, written in `BRIEF.md` (file exists, check exits 0, counts match, no BLOCKING critic finding open, minors logged as debt). The user sign-off is close step 7, never a Done-when item. Why: completion by judgment call cannot be verified by the lead.
- Planning a stage = `rk add stage "<kind>-<topic>"` (status `planned`; it creates the `P-` folder with its subfolders and records it as the stage ref; entries may join it, `rk start` on them is refused); opening = `rk stage-open S-<n>` or `rk add stage ... --open` (next NN, folder renamed, refs rewritten; `add stage --open` uses a stage folder that is there already, the receipt says `(uses the existing folder)`, while `stage-open` refuses one: folders are never merged); a hand-picked NN is refused; never `rk start` a stage. The stage entry is the only record of its state; only `rk stage-close` closes it.
- Legacy stage paths (appendix `Legacy stages:`) are frozen and read-only; new stages go to `pm/stages/`. Why: closed stages are cited by path.

### 3.2 Stage folder

```
pm/stages/NN-<kind>-<topic>/
  README.md        what the stage answers, how to rerun, caveats, what was left open, file index; human-first
  BRIEF.md         lead's single source of truth for the stage (3.3)
  deliverables/    products the NEXT stage consumes (scans, extracts, results, drafts)
  notes/           intermediates, lookups, critic reviews, fix logs, prior versions; team/ = teammate reports (2.3) - keep, never cite
  code/            frozen copies of any user-sandbox script this stage uses (+ sha256 in README)
  chat/            session archive (3.4 step 6); gitignored, raw transcripts are large
```

- Deliverable vs note decided when file is created, not later. Stage frozen when its stage entry is `done` (`rk stage-close`, 3.4). Later corrections go into CURRENT stage with pointer back. Why: cited paths must keep meaning what they meant.
- Each stage README starts with: scope, provenance table (file | sha256 | role), run log (step | command | log path | start | end | status), results, caveats, what the stage left open, file index (written last, after the chat archive: it names `chat/` and every file); no status line, no hand-kept id lists (its decisions and tasks: `rk list --stage S-<n> --all`, `rk search <text>`). Teammate drafts README skeleton (junior enough).

### 3.3 Briefing a stage

- **Design step** (every kind; before any design or plan work of a stage): (1) the lead asks the user via AskUserQuestion whether the architect (`arch1`, 2.1) does the planning (yes = `arch1` writes the design file (2.1) before any worker starts; no = the lead plans and writes the INTERFACES and CHANGE IMPACT blocks (2.1) into the briefs; the user's answer wins over the triggers of 2.1); (2) the lead itself holds the design talk with the user: one question at a time, discrete options via AskUserQuestion, recommended option first (section 8); (3) the spec is a file in the stage `notes/`; no code and no implementer brief before the user said yes to it; (4) the yes is logged as `rk add decision "<spec approved>" --owner user --label <stage code>/SPEC --ref <spec file>` (stage code = the prefix of the stage folder (03, 03b), e.g. `03/SPEC`); a revised spec is approved with `rk supersede <decision in force> "<spec v2 approved>" --owner user` (the label stays on the old decision; the start line stays away); a stage with no design step gets that label on a decision "no spec needed": only the user decides it, the lead asks via AskUserQuestion and logs the answer `--owner user`. While an open stage has no such decision, the session start block prints `spec: S-<n> <stage> has no user decision labelled <stage code>/SPEC (AGENTS.md 3.3)`; no `rk` command is refused. Why: sessions skipped the design talk or let an ad-hoc subagent plan.
- `BRIEF.md` (lead) = inputs, Done when, rules, kind skill + mode if the kind file names one. Its decisions live in the ledger (4.2), not in a hand-kept id list: `rk list --stage S-<n> --all`, `rk search <text>`. When the stage opens, every work item of the BRIEF gets a task `rk add task "<item>" --label <stage code>/<item> --note "<deliverable and scope, 1-3 lines>" --ref <the stage BRIEF.md>`, owner `lead` until work is handed out (2.2 step 3 reuses it), and the BRIEF's work-item list carries the task id next to each label. Titles, notes and messages may use a label only if it exists in the ledger. Why: a label that names nothing cannot be resolved later. Update in place with dated "update" sections. Decisions made in conversation: `rk add decision` at once, and show the user the receipt line. Why: conversation is lost at compaction; the ledger is not.

### 3.4 Stage close (user says "close stage"; `/rk-close`)

Checklist, this order, each step with owner. Ledger events cannot be in the archive, so the two that end the stage (sign-off, `stage-close`) come after it, and the main transcript is copied last. Why: a step that needs the stage open (the archive task) must run before `stage-close`; sign-off needs the finished record in front of the user.
1. Done when check run, output tail pasted into stage README (teammate runs, lead reads). Not met -> stage stays open, or user accepts the gap, logged as a user decision linking the stage (5.3).
2. Every task of the stage done, dropped, shelved, re-staged or deferred: `rk list --stage S-<n>` shows no open or staged task (lead; land the stage's staged tasks by id once their branch is on the base branch, `rk land T-<n>...`; `--stage S-<n>` lands every staged entry of the stage); shelved tasks (`--all`) are named to the user at sign-off, they do not block the close. A task closed on a report or review carries it as `--ref`.
3. `pm/README.md`: every quotable number stage produced or refuted gets row in "Load-bearing numbers". Update "Do not quote / known traps". Update the appendix lines this stage made stale (stage sequence state, current scripts and checkers, gaps now closed) (lead).
4. Executed handoffs: jr moves the file to `pm/handoffs/done/`, then `rk reref pm/handoffs/open/HANDOFF_<topic>.md pm/handoffs/done/HANDOFF_<topic>.md`, then `rk close H-<n> --note "<outcome>"` (lead). A moved file with its old ref is a HARD finding at step 8.
5. Kind-specific freeze steps named in the kind file (owner as named there).
6. Chat archive into the stage's `chat/` (lead, copy only, never digest in `notes/`; a teammate copying `~/.claude` transcripts is refused by the permission classifier). Open its task first, while the stage is open: `rk add task "chat archive" --owner lead --stage S-<n> --note "<what is copied>"`; close it when done.
   - teammate transcripts `~/.claude/projects/<sanitized-cwd>/<session-id>/subagents/agent-*.jsonl` + `*.meta.json`; plus `tasks/*.output` from any scratchpad `tasks/` dir if present (team session may have none; write that into INDEX.md instead of leaving it silent);
   - secret scan of every copied file (API keys, tokens; grep the key prefixes listed in appendix). Scrub in the copy only, record it in `INDEX.md`;
   - size check: each transcript < 100 MB (push limit of common git hosts; one stage once produced a 112 MB file);
   - the raw main session JSONL `~/.claude/projects/<sanitized-cwd>/<session-id>.jsonl` last of the transcript copies (snapshot at copy time; sign-off and `stage-close` are not in it; the user may run `/export` into the same folder);
   - rendered `session.md` and `INDEX.md` (what was copied, what was absent, snapshot time); then the stage README file index.
7. User sign-off (lead): ask with AskUserQuestion; the question shows the output of `rk doctor --stage S-<n>` (hard findings fixed first, soft ones listed, the stage's decisions not owned by the user, each with its owner and the decisions it links). Changes asked: redo the steps they touch, ask again. Only after the user answered: `rk add decision "<sign-off>" --owner user --link S-<n> --note "<the answer>"`.
8. `rk stage-close S-<n> --sign-off D-<m>` (lead), last. It refuses on open or staged tasks and on a missing ref or stage folder (`rk doctor --stage` also checks the ledger against HEAD) and prints the soft findings; fix what it names, rerun. Stage table, open list, task view and the stage's `LEDGER.md` are generated from the ledger; nothing to rewrite by hand, and a hand-edited `LEDGER.md` is wrong by definition (a correction is a new ledger event in the current stage). It shows what was known at close and is not rewritten by a later `set`. Why: a hand-kept copy drifts from the ledger.

## 4. Documentation set

```
pm/
  README.md          finding aid: "Load-bearing numbers" + "Do not quote / known traps" + "Where is what"; lead updates it at stage close
  ledger.jsonl       the store: tasks, decisions, deferred, stages, ... (4.2); written only through `rk`, committed
  STATUS.md          generated open view + shelved; gitignored, never edited
  living/            one current version each, edited in place, never copied into stages
    GOALS.md         goal, scope, claims or targets (open questions: deferred entries)
  kinds/             active kind files (replaced on sync; never edit locally)
  stages/            section 3 (full mode only)
  handoffs/open/     work packages for later sessions (HANDOFF_<topic>.md), committed; handoffs/done/ at close step 4
  handoffs/compact/  compaction handoffs (handoff-YYYY-MM-DD.md; hook-made auto-<stamp>.md), gitignored
  logs/              run and impl logs, committed; team/<run>/ = teammate reports and critic reviews outside a stage (2.3)
  reviews/           older critic reviews made outside stages (light mode), gitignored
  scratch/           throwaway work, gitignored
  waste/             discarded files + LEDGER.md (section 7), gitignored
```

Kind-specific folders (e.g. a paper's library and manuscript) are named in the kind file. Nothing else sits in `pm/` root.

### 4.1 pm/README.md = finding aid, not narrative

- "Load-bearing numbers" names, per number, the OWNER FILE (quote from there, never from table or stage row), what each timer/metric covers, refuted claims, and traps. Why: several facts were only established in a later stage than the one that first produced them (a "~10 s" figure was refuted later).
- "Do not quote / known traps": refuted claims, superseded first looks, results that carry flags ("never quote the row bare"), bench bugs, dry-run output. Refuted material stays listed so nobody re-derives it.
- Every quoted number lists protocol caveats next to it (what is timed, N, seed, hardware, versions) and names the harness. Two experiments that land near each other are a consistency check, not a repeated measurement.
- Quote a number only from an output stamped at a clean commit. Stale stamp = re-run first. Once a rerun of all experiments is decided, every older number is a placeholder until the rerun.

### 4.2 The ledger (pm/ledger.jsonl)

- One ledger per repo, in the main checkout. `rk` in rule text = `python3 -I "<path>/rk.py"`, run from the repo root. The SessionStart block prints it as the line `rk() { python3 -I "<path>/rk.py" "$@"; }`; a Bash call keeps no shell state, so start each call that uses `rk` with that line joined to the command by `;` (`rk() {...}; rk list`; skills spell the full command); inside a git worktree it finds the main checkout's `pm/ledger.jsonl` by itself. The block also names a rule file behind the kit (run `/rk-sync` between stages, not inside one) and warns when `jq` is missing (guards off). Teammates add `--who <name>`. Every write prints a receipt line (`logged D-4: ...`): show it to the user. The tool stamps every event with the kit version and the session id (`rk show` prints them): the way from an entry to the archived transcript.
- Types (id prefix): task T, decision D, deferred DF, fetch F, debt DB, handoff H, stage S; a kind file may declare more with `<!-- rk:type <name> <PREFIX> -->`. Statuses: open, running, staged (work done on a branch, not landed; it stays in the open list), planned (stages only: made, not yet open), shelved, done, dropped, superseded. Deferred = parked, waits on something; shelved = known, not planned now; given up = dropped with the user's decision. A planned or shelved entry is neither open nor closed: it is not in the open list or its counts (STATUS.md shows planned stages in `## Planned stages`, shelved entries in `## Shelved`). An open entry in a planned (shelved) stage is stored open but shown as planned (shelved): same, listed by `rk list --status planned` or `--stage S-<n>`, open again by itself at `rk stage-open`. `imported` entries are unverified.
- Granularity: an entry is a unit of work or a ruling; a file edit, a one-line fix or a test rerun is not. The user's own work: `rk add task "<what>" --owner user --status done --note ...`. Never hand-edit `ledger.jsonl` or `STATUS.md` (a hook blocks it); corrections are new events. `ledger.jsonl` is committed together with the work (section 7); the tool never changes git state (only `doctor` and `stage-close` read it).
- `rk add <type> "<title>" [--owner N] [--label L] [--stage S-<n>] [--note T] [--link ID]... [--ref PATH]... [--status S]`: new entry. A `task` without `--note` is refused (imports exempt); `rk add stage "<kind>-<topic>"` plans a stage and creates its `P-` folder; `--open` opens it at once (refused while a stage of its kind is open, 3.1), `--follows S-<m>` gives it a suffix letter, `--before|--after S-<n>` places it among the planned stages (3.1)
- `rk start ID`: open / staged -> running, for tasks and other work entries, never a stage, and refused for an entry of a planned or shelved stage (`rk stage-open` first; the brief hook does it for the brief's `TASK:` ids and is refused alike). Why: work runs only in an open stage
- `rk close ID --note "<outcome>" [--ref PATH] [--link ID]`: done (also lands a staged entry); close only what is on the base branch, else `rk staged`. Why: unlanded work must not read as finished or as untouched; not for stages (`stage-close`) or decisions (`supersede` / `drop`). Every `--ref` (add, set, close, drop, shelve, reopen, supersede, stage-close) must name an existing file, relative to the repo root (a `://` URL, `doi:` or `arXiv:` passes; a path outside the repo is refused; imports exempt; checked against the main checkout, so in a worktree merge first): the report or review is written before the task closes on it
- `rk drop ID --note "<why>" [--link ID]`: dropped (also from shelved or staged); `rk shelve ID --note "<why>" [--ref PATH] [--link ID]`: open / running / staged -> shelved, any type except decision and stage (a done entry that should come back is reopened first; refused without `--note`); `rk reopen ID --note "<why>"`: done / dropped / shelved / staged -> open (a done stage too: refused while another stage of its kind is open or if it has no folder; its next `stage-close` needs a new sign-off and rewrites its `LEDGER.md`); `rk staged ID... --note "<where: branch, commit>" [--ref PATH]`: open / running -> staged (any type except stage and decision; refused in a planned or shelved stage); `rk land --note N [--ref PATH] [--stage S-<n>] [ID...]`: closes every staged entry, or the named ones (a named entry that is not staged refuses all), in one write; `rk supersede D-<n> "<new>" --owner N [--note T]`: replaces a decision in one call
- Label `L` = `<stage code>/<item>` (e.g. `03b/W4`; the `/` is required): unique, stored on the entry, never containing an ID form (`03b/T-1` is refused); a stage's title is its folder name, changed only by `rk stage-rename` (`set --title` on a stage is refused); every command that takes an ID also takes a label or a stage code (`03b`); an ID always wins; ambiguity is refused; a label resolves only as written (`03b/W2`, not `W2`; `rk search W2` finds it); receipts print the real ID
- `rk set ID [--title T] [--owner N] [--label L] [--stage S-<n>] [--note T | --note-replace T] [--link ID] [--ref PATH] [--ref-drop PATH] [--status planned|shelved|dropped] [--before|--after S-<n>]`: change fields, status kept; on a stage `--status` moves planned <-> shelved and planned or shelved -> dropped (`--note` required for shelved and dropped, stored as `reason`; a drop is refused while an entry of the stage is open or running; after a drop the lead moves the `P-` folder to `pm/waste` by the usual waste step (the tool never moves files, its receipt only names it); only `rk stage-open` opens and `stage-close` closes), `--before|--after` move a planned stage in the queue. Every `--note` (set, close, drop, shelve, reopen) appends a line to the entry's note, and close, drop, shelve and reopen also store it whole as the entry's `reason` (the why of its current status); only `--note-replace T` replaces it; `--ref-drop PATH` (repeatable) removes a wrong ref (a new event, history keeps it). `--stage` on an entry of every type but task and stage (e.g. debt, deferred, fetch, handoff, declared types) means "raised in": while open it may be put into a closed stage by add, set or import (`rk set DB-5 --stage S-7`), and `start` and `reopen` work there; an open or running task cannot. Why: only open tasks block a stage close, and a debt keeps the stage it was raised in
- Read: `rk list [--type T] [--owner N] [--stage S-<n>] [--status S] [--all]` (open entries, short, staged ones included (`--status staged` = work not yet landed), then a line `planned N: ~NN <title> (k entries), ...` while stages are planned; `--status S` lists entries of that status, `planned` in queue order; `--all` adds closed, shelved and planned ones); `rk show ID [ID ...]` (fields, stored and shown status, history with kit version, session id and rule stamps, one line per linked entry, both directions); `rk search TEXT` (titles, notes, labels, every status); `rk recent [-n N]` (newest events)
- `rk doctor [--stage S] [--limit N]`: read-only, writes nothing; exit 1 on a HARD finding. Groups, HARD first, N lines each (default 20, 0 = all). HARD = the record is broken (ledger line that does not parse, missing ref or stage folder, ledger not append-only against HEAD); SOFT = suspect or unfinished (ref in a git-ignored or waste folder, ref into `pm/waste/` whose file the user emptied (`--ref-drop`), done stage not in HEAD, entry without a stage, task running over 24 h, imported entries with missing refs, an ignored or outside-the-repo ref that a clone would lack, a stage folder absent in a clone, rule file behind the kit, the stage's decisions not owned by the user): a group that has a fix names it in its heading. No git repo: git checks are skipped, with a line saying so
- `rk reref OLD NEW [--dry-run]`: replaces the leading path prefix OLD by NEW in every ref that starts with it (all entries, imported, done and closed stages included), all or nothing: refuses and writes nothing if a new path does not exist, so move the files first; prints one line per ref
- `rk stage-open S-<n> [--follows S-<m>]` opens a planned stage (next NN, folder renamed, refs rewritten); `rk stage-rename S-<n> "<kind>-<topic>" [--note N]` renames the kind-topic part of a stage title, its folder and refs (NN or `P-<n>` stays; a done stage needs `--note`: text outside the ledger keeps the old path); `rk stage-close S-<n> --sign-off D-<m> [--ref PATH]`: the only way to close a stage (3.4); it runs the `doctor --stage` checks first, refuses on a HARD finding (missing ref, missing stage folder) and prints the SOFT ones

### 4.3 Handoffs

- Work package `HANDOFF_<topic>.md` in `pm/handoffs/open/`: self-contained package for a later or side session. Goal, inputs (exact paths), spec of deliverable, Done when, what is out of scope, what feeds it. One `handoff` entry per open handoff: `rk add handoff "<topic>" --ref pm/handoffs/open/HANDOFF_<topic>.md`, closed when executed (move the file, `rk reref`, then `rk close`). Declined by the user: `rk drop H-<n> --note "<user decision>"` (file stays parked, never deleted).
- Compaction handoff `pm/handoffs/compact/handoff-YYYY-MM-DD.md`: session state for the next context, written by the `research-kit:surviving-compaction` skill and hooks. Gitignored; never cite it. Why: it is a memory aid, not a record.

### 4.4 Notes, critic reviews, logs

- Filenames carry a date: `critic_review_<what>_v2_<date>.md`, `run_log_<date>.md`, `impl_log_<date>.md`. Critic reviews kept in stage `notes/` (no open stage: `pm/logs/team/<run>/`) with version suffix. Owner's fix log sits beside them (`fix_round_<what>_<date>.md`). Run and impl logs outside a stage go to `pm/logs/`.
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

- One `decision` entry per decision: `rk add decision "<what>" --owner <user / lead / name> --note "<why>" [--stage S-<n>] [--link ID]...`; `--owner` = who decided. A decision is in force when logged: a change = `rk supersede D-<n> "<new>" --owner ...` (never a re-add), a withdrawal = `rk drop`; never closed. Includes decisions already taken (do not reopen without the user). An open question for the user is not a decision: it is a `deferred` entry with `--owner user` (5.4). Stage sign-off = a user decision that links the stage, `--link S-<n>` (`--stage S-<n>` alone does not count: decisions default to the open stage); the lead asks (3.4 step 7) and logs it only after the user gave it. A lead decision that narrows or reinterprets a user decision links it (`--link D-<m>`) and is shown at sign-off. Why: later sessions must tell user calls from agent calls.
- Scope test: escalate only if a choice changes output, public surface, claims, or files named in the brief; otherwise decide, log one entry. Clusters of agent rows against one stage signal a bad brief.
- Escalation (teammate -> lead, lead -> user) is one ESCALATE block, nothing around it:
  ```
  ESCALATE <BLOCKED | NEEDS-SOURCE | AMBIGUOUS | SPEND>: <one line>
  Tried: <what was tried, tagged + cited>
  Needs: <the decision or input wanted, with a recommended default>
  State: <files touched, what is safe to keep, what is half-done>
  ```

### 5.4 Deferred items and the stop rule

- Anything that needs approval, hardware, money, a hand fetch or an unanswered question is parked: `rk add deferred "<item>" --note "needs: ...; blocks: ..."` (`--owner user` when it waits on them, always for a question to the user). Other work continues. Why: one waiting item must not stall a team. Items leave only via `rk close` (with pointer), `rk shelve` (with its reason) or `rk drop` (with the user's decision), never silently: absence looks like a result. A fetch the user cannot obtain and accepts as unread: `rk drop F-<n> --note "<what was tried>" --link D-<m>` (D-<m> = that user decision): given up = dropped with the user's decision; a fetch or item that is known but not planned now is shelved (`rk shelve ID --note "<why>"`), not given up. Why: an open fetch means "still to fetch", a shelved one waits on nobody, and only a dropped one linked to the user's decision reads as "given up on purpose".
- Stop rule: a session or teammate stops or refuses mid-task -> lead logs it as a deferred entry (what, exact refusal text, state left) and asks the user. No rephrase/retry loop. Why: rephrasing around a refusal hides the problem and burns budget.

## 6. Code and computation

- Repo code read-only for lead and research teammates. Code edited only when the brief names file and change (software stages name them by design). Brief quotes that decision with its date. User's own scripts = sandbox: stage using one keeps own frozen copy in its `code/` (sha256 at copy time in README), runs import copy, never original.
- No-go dirs (appendix) never read, grepped, edited, imported unless user names file. Agents never install packages. User owns environment. Any change to shared code re-runs checks of its dependents (appendix lists them).
- Long runs persist everything first: curves, meta, argv, git stamp, sha256 of inputs/outputs go to disk before any multi-hour run. Re-render paths never overwrite main outputs without explicit gate. Never launch multi-hour run unless brief says so. Report command, user launches it.
- Each stage rerun carries run sheet in its README: ordered commands, expected outputs, pass criteria. Commands run from repo root with explicit output dirs (never rely on defaults pointing at old stage). Frozen older stages keep old commands, valid at pinned commits.
- Benchmarks and timed runs (arms, timing protocol, solver checks, result tables): rules live in the software kind file, section "Benchmarks / computational experiments"; a repo that runs benches activates it (`/rk-add-kind software`). Why: only bench repos pay for them.
- Quality gate for changed code: lint + format check + type check, fully type-hinted, tail pasted into report (exact commands in appendix). New logic leaves one runnable check (`selfcheck` / assert).

## 7. Git policy and waste

The appendix `Git policy:` line decides; never infer it from habit. Local-only repo (`pm/config.json`: `pm` = `local`; the session start block says `pm: local only`): `pm/` is never committed or force-added; skip every step that commits a `pm/` file. Why: the repo is public or shared and its record is not.
- `user commits` (default): agents run no git command that changes state (commit, push, branch, checkout, reset, stash, rebase); read-only `status` / `diff` / `log` are fine. User commits. Why: the user owns history.
- `orchestrator commits`: each implementer works in its own git worktree on its own branch (`isolation: "worktree"`) and commits only there. Only the lead merges into the main branch, after no BLOCKING critic finding is open, minors are logged (2.2 step 6) and the Done when check passes. The ledger stays one file in the main checkout (4.2): the lead carries it in each merge commit, never a ledger-only commit: `git merge --no-ff --no-commit <branch>`, then `git add pm/ledger.jsonl`, then `git commit` (staged before the merge, git refuses the merge; a fast-forward leaves no merge commit to carry it); `rk init` sets `pm/ledger.jsonl merge=union` in `.gitattributes`. Nobody pushes, force-pushes or rewrites history unless the user asks. Why: one merger keeps parallel work reviewable.
- Never delete files, under either policy: move them to `pm/waste/` with the `research-kit:waste` skill (waste ledger row first; no `rm`, `git rm`, overwrite-to-clear). User empties it. Legacy `WASTE/` (appendix `Legacy waste:`) stays as is; new waste goes to `pm/waste/`. Why: deletions cannot be reviewed.
- Only the lead runs the waste helper; teammates never do. They list each file in their report as one line at column 0, `TO-WASTE: <repo-relative path> -- <reason>`; the lead collects them with `grep -h '^TO-WASTE: ' <reports>`, moves them and the user approves the prompt. A file an entry refs: after the move `rk reref <path> <waste path>` or `rk set ID --ref-drop <path>` (else a HARD finding at close). Why: a teammate's permission prompt may never reach the user (e.g. over remote control).

## 8. Rules of thumb

- Questions to user with discrete options go through AskUserQuestion, recommended option first. A decision is its own call, never a line in a status message (chat text is buried under teammate notes). Commands user must run are written in their own message (text before a question box is hidden). Each question stands alone: one topic, the work named in plain words with DOI or path (never a bare label or id), what each option changes. Why: the user reads it later, between other things.
- Idle pings, confirmations and duplicate notifications get no user message: write to the user only when something finished, failed or needs them.
- A decision that changes one a teammate holds goes to every teammate holding the old one, in one message. Why: teammates acted on a stale decision and each needed a correction.
- After a burst of teammate hand-backs: one summary message with no question in it, then each open question as its own AskUserQuestion call, each with a default.
- Never label user impatient. Never offer to relay between user and teammate. Brief interactive teammate to ask user itself.
- Build locally. Publish nothing to web unless user asks. Analyses = scripts saved next to project's other scripts so output can be regenerated, not one-offs.
- Repo visibility: record per repo (public / private-until-publication) in appendix. Public repos never mention private ones.

## 9. Light vs full mode

The appendix `Mode:` line decides; `full` = everything above.
- `light`: no stage folders, no stage tables, no close checklist (3.1-3.4 skipped; a kind file's stage table is a checklist only). Kept: roles, teams and the critics, Done when per work package (written in its handoff or task note), evidence tags, the ledger (no stage entries), `pm/logs/`, handoffs, waste, git policy. Critic reviews go to `pm/logs/team/<run>/`. Why: small repos need the discipline, not the paperwork.
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
- API key prefixes to scrub (3.4 step 6):
- Pre-commit hooks (ASCII etc.):
- Repo visibility:
- Known environment traps: (local library patches, RAM limits, power mode, ...)
- Model preferences / overrides:
- Project-specific rules:
