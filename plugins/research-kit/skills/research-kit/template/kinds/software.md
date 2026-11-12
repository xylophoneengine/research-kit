<!-- research-kit-kind software: 2026-11-13a -->
# Kind: software

Applies to an app, library, tool or driver built with an orchestrator plus
implementer agents. Read at session start and after every compact. Core
`AGENTS.md` still applies: evidence tags (CONFIRMED / LIKELY / GUESS),
the ledger (core 4.2), critics, waste. These rules add to it,
never relax it.

Stage folder: `pm/stages/NN-software-<topic>/` (full mode). Light mode: use the
table as a checklist, no folders.

The `superpowers` plugin and the third-party `grilling` skill are optional
(README, "Optional external tools"). The table names their skills where they
fit; without them, run each stage by hand from the rules below.

## Stages

| # | Stage | Skill / tool | Done when |
|---|-------|--------------|-----------|
| 1 | Design: goal, non-goals, why not an existing tool, interfaces | `superpowers:brainstorming` or `grilling` | Spec written in stage notes and the user said yes |
| 2 | Plan: tasks sized to one sitting, signatures copied in | `superpowers:writing-plans` | Every task names its files, frozen signatures and a failing test; user approved the plan |
| 3 | Tests first: failing tests for each task | a `/team` teammate | Test command output shows the new tests red for the stated reason |
| 4 | Build: one task per implementer | `superpowers:subagent-driven-development` or `/team` | A named teammate ran the gate and the lead read the pasted tail: green |
| 5 | Review: two critics (core 2.1) | `/team` critics | Both critics YES (core 2.2) or every NO / PARTIAL finding has an owner |
| 6 | Fix and re-review | `/team` | Re-review read the raw diff; both critics YES, or leftovers escalated after 2 rounds |
| 7 | Verify on the real thing | the user | Hand-check list ticked by the user, failures turned into tasks |
| 8 | Package and release | the lead plus teammates | README, CHANGELOG, CI green; the user published |

## Spec and tests

1. Spec before code: no implementer starts without its spec section and signatures in the brief; cheap models make tests green, they do not decide what is correct.
2. Failing test first: a teammate writes red tests before any implementation; a test that was never red proves nothing.
3. Implementers may add test cases, never weaken, delete or reinterpret an assertion; if spec or test looks wrong they STOP and report (file, spec section, decision needed) because a precise stop beats a creative completion.
4. Size a task to one sitting (roughly 10 to 40 assertions) and give "read exactly these files": long context lists make agents wander.
5. Every brief carries a scope line ("you are doing task NN only; stage and stop"): neighbouring edits are the most common implementer failure.
6. Positive checkpoints: stop and ask before a new public symbol, a file not in the plan, or a choice between variants, because these decide the API.
7. Every constant, address, opcode or timing cites its source (manual page, capture file hash, spec section): uncited literals cannot be reviewed.
8. Snapshot or golden re-record is a gated, reviewed act (explicit flag, task allows it, diff read like code): goldens silently absorb regressions.
9. A unit test never needs real hardware, network or user data; use fakes, and add a demo mode to any GUI so agents and CI can run it.

## Gate and review

10. Gate script, not trust: allowed-files list, test files may only gain lines, boundary lint for forbidden imports and calls, the test filter must match at least one test; a named teammate runs it and the lead reads the pasted tail; an agent's success report is not evidence.
11. Three failed gate runs on one task means escalate with the output (`ESCALATE BLOCKED`, core 5.3), not a fourth try: loops hide a bad brief.
12. Frozen contracts file (public signatures, formats): only a task whose brief names it edits it, with a migration note, so parallel work stays mergeable.
13. Critics re-read the code and raw evidence, not the earlier review notes: shared assumptions between code and its fake are invisible to tests.
14. Code that runs only once on something expensive (a lab run, a release, a migration) gets a critic pass as hard as the product code beforehand: a failure there may not be repeatable.
15. State changed by a call (modes, formats, files) is restored in `finally` paths: silent corruption of later calls surfaces only in final review.
16. A second implementer model gets its own instruction file that states precedence over `AGENTS.md`: tool limits differ between models.

## Running agents

17. Never run a command that can wait for input (`</dev/null`, no interactive tools) and kill every process you start by pid: one hung command blocked all agents.
18. Anything that cannot run unattended is parked per core 5.4 and work continues: unattended runs must not stall on prompts.
19. Runs that can touch real user data work only inside a gitignored sandbox dir, and destructive calls live in one allowlisted file enforced by lint: a critic once found a test using the real trash.
20. Agent GUI runs: pin the window to a named screen, drive by pid not by frontmost app, never open the user's own bundle: agents typed into other applications.
21. Scrub the agent environment and never set `GIT_DIR` or `GIT_WORK_TREE`: a leaked variable wrote config into the wrong repo.
22. One build at a time via a lock and a capped job count: parallel agent builds overheat a shared laptop.

## Repo hygiene and release

23. Third-party binaries, firmware, data and captures are gitignored; a README says where to get them and which build is accepted: redistribution rights are not ours.
24. Decide per artifact whether it is publishable (analysis notes may embed third-party strings): an accidental publish cannot be taken back.
25. Deleting follows core 7 (move to waste): vendored or generated files are no exception.
26. README near the top states what has been verified on the real target, plus AI assistance if the appendix attribution policy says so: readers judge provenance from it.
27. Commit messages carry a task id or area prefix and follow the appendix attribution policy: that policy is the owner's, not a kit default.
28. CI runs the smallest hardware-free test command on an OS and Python matrix: portability is the claim.
29. CHANGELOG is drawn from git history between tags; the hand-check list names exactly what the user must try and drops sections once passed: release notes written from memory drift.

## Git policy

Read `Git policy:` in the appendix of `AGENTS.md`; core section 7 defines both values (`user commits`, `orchestrator commits`). Software additions:

- `user commits`: implementers work in the working tree on disjoint file sets, so parallel tasks never edit the same file.
- `orchestrator commits`: only the lead merges into main (after both critics YES, the Done when check passes, and a named teammate has run the full suite with the lead reading the tail); one `task` entry per plan task; its note records Tests / Impl / Review / Merged (`rk set T-<n> --note ...`). There is one ledger per repo, in the main checkout: `rk` run inside a git worktree finds the main checkout's `pm/ledger.jsonl` by itself, so nobody passes a path and implementers in worktrees update their task as above. The lead stages `pm/ledger.jsonl` into each merge commit; no ledger-only commits; never commit `pm/ledger.jsonl` on a worktree branch.

## Benchmarks / computational experiments

Applies to any bench or timed run, in this or another kind (paper bench stages point here).

- New experiment code in its own module; multi-arm experiments = packages, one module per arm, never a monolith: arms stay separately reviewable.
- Experiments import the library's public API. Local reimplementation only when no public equivalent exists, marked `# local: no <lib> equivalent (<what was searched>)` and listed in the report. The user's own formulation is always its own arm via the public API: otherwise the numbers don't measure it.
- Timing protocol: one discarded warm-up call of EVERY timed path before the timed loop (check the plot for a first-point spike); record library versions per bench; check machine power mode and stray CPU hogs before trusting absolute times; compare ratios across sessions only; timed runs strictly sequential, nothing else running beside them: absolute times drift between sessions.
- Put both arms on the SAME feasible set from the start. Check solver status/convergence before calling solver output a reference. Multimodal problems: report spread beside deltas: otherwise deltas compare different problems.
- Result tables: no aggregate over directions that flip sign; every flagged row stays in the delta unless the exclusion is printed next to it: averages hide sign flips.
- Experiment prose (protocol text) lives in the bench README, not the report generator; the generator emits tables + data-derived lines + a pointer to the README at a stamped commit: prose in code drifts from the protocol.
