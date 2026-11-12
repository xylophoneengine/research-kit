<!-- research-kit-kind experiment: 2026-11-13a -->
# Kind: experiment

Rules for projects that measure something (rig, instrument, simulator, lab
bench). They add to the core `AGENTS.md`; they never relax it. Stage folders
are `pm/stages/NN-experiment-<topic>/` (full mode); in light mode the stage
table is a checklist only. Evidence tags are CONFIRMED / LIKELY / GUESS.

## Hardware rule

Agents never touch hardware unless the user explicitly tells them to.

- Agents write, dry-run, test against simulators and analyse; the user or an
  operator flashes, connects, runs and swaps parts. Why: rig time and device
  state are irreversible, and an agent cannot see the bench.
- A task that needs a device call is parked as `rk add deferred ... --owner user --note "<exact command; operator; what to bring back>"`. Why: it must not block work.
- Teammates get no device access and make no commits; the lead briefs the user
  for lab steps. Why: one accountable operator per lab session.

## Stage table

Number stages with the shared NN; at most one open stage per kind. Re-open
stages 4-5 before every new lab day, and stage 6 after any hardware, firmware
or calibration-source change. "Operator-run" means the user runs it.

| # | Stage | Driver | Deliverable | Done when |
|---|-------|--------|-------------|-----------|
| 1 | spec | lead + user | `spec.md`: goal, scope, reference, pass criteria, unit conventions, decisions table, frozen section ids | user approves it in writing; no open "decide later" without an owner |
| 2 | build (driver, firmware, rig code, design) | implementer | code or design, device doc with "Hardware-verified" and "Open questions" | tests and simulator contract tests pass |
| 3 | dry run (simulated rig, same scripts) | implementer | `_dry/` output, run-script tests, frozen lab folder | a critic reviewed the lab folder line by line; the static test passes |
| 4 | bench smoke (operator-run) | user | expected-values table, bench note with conditions | every checklist item is PASS or has a logged cause |
| 5 | calibrate (operator-run) | user + analyst | dated calibration file, explanation note, script, raw folder, generated numbers file | residual or linearity criteria from the spec are met |
| 6 | measure (operator-run, config-driven) | user | run folders with start and end records, queue log | each run meets its per-run pass criteria or is moved aside |
| 7 | analyse | analyst | write-once analysis folders, `pm/README.md` "Load-bearing numbers" and "Do not quote" updated | a critic confirmed labels against code; a rerun matches by hash |
| 8 | close | lead | stage README, debt and handoff entries current | user says "close stage"; the core close checklist is done |

## Rules

### Before the rig

1. Freeze the lab folder and have a critic review it before it goes to the rig. Why: rig time is the scarce resource.
2. Check run scripts line by line against the last accepted ones, with a static test that they differ only in the scenario. Why: copy-edit drift ruins a lab day.
3. Dry-run is a first-class switch of the same script; it swaps the rig, shortens durations and writes only to a gitignored `_dry/` folder. Why: dry and real output must never sit side by side.
4. Dry-run output is never quotable, even when it later matches the real result. Why: only a stamped real run is a result.
5. A simulator reproduces what was measured on the device, failure modes included, and each quirk gets one contract test run against the simulator and, when a port variable is set, the real device. Why: a simulator written from assumptions passes while the device fails.
6. Keep an honest list of what the simulator does not model. Why: dry runs then check plumbing only, and readers must know.
7. Configure runs in a config file with units in the key names; committed configs are examples with placeholders and real values live in an ignored `local/` folder. Why: no hardcoded constants, no site values in the repo.
8. Acquisition parameters fixed for a run are chosen by hand on the bench and written into the config; a run never auto-picks them. Why: a silent pick makes runs incomparable.
9. Never commit vendor SDKs, site configs, raw device logs or secrets; secrets come from environment variables only. Why: they leak and cannot be taken back.

### On the rig (user-run, agents prepare)

10. Write the run record before the device is touched and again at the end, with an `aborted` flag and reason. Why: a crash must still leave an interpretable record.
11. Resume is mechanical: finished means flag false plus the full output set; anything else is moved to `_aborted_<timestamp>/` and rerun, and a hard kill is stated as not resumable. Why: partial and complete data must never mix, and nothing is deleted.
12. Stop is safe-state first (source off, actuator parked, file marked), and the doc names what the controller cannot stop. Why: operators panic at the rig.
13. Ask the operator for what software cannot check (source state, alignment, warm-up done); gate on a measurable condition where one exists. Why: unchecked manual state is the commonest silent error.
14. A self-check at run start fails the run, never warns; later drift checks only warn. Why: a broken shutter once produced plausible data.
15. An implausible sensor value (missing, non-finite, out of range) aborts at once. Why: a stop that depends on that sensor can no longer be trusted.
16. Parameters that must match between two stages are compared by sha256 and refused on mismatch; after a change, redo the reference run and name the older runs it invalidates. Why: mixed calibrations give apparent contradictions.
17. Calibration blocks use a drift-cancelling order, drop samples after each setting change, take reference or baseline readings at start and end, and exclude out-of-range blocks by a stated rule. Why: drift and settling bias every number.
18. Tolerance violations are flagged, not dropped; exclusion is a documented analysis rule. Why: run-time deletion cannot be audited.

### Provenance and analysis

19. Run output goes next to the script that made it, one folder per run, never to a default path of an older stage. Why: stale paths overwrite accepted data.
20. A number carries its environment: library hash, scenario, n, units and convention label; decide a convention once, record it, and label everything, never convert. Why: two definitions once produced apparently conflicting numbers.
21. Write tables as Arrow files, arrays as `.npz`, metadata as `.json`; the device's native log stays gitignored. Why: no pickle, formats must outlive the code.
22. Write result files atomically (temp file, then rename). Why: a crash once corrupted a result.
23. Analysis is a pure function of a frozen run file; its output folder is created once (never `exist_ok`) and records the source path, source sha256, tool version and every setting. Why: results stay traceable and nothing is overwritten.
24. Never rerun analysis in place over frozen outputs: give the output directory an argument (default unchanged), rerun at a clean commit into a new folder, diff by hash. Why: an in-place rerun destroys the baseline.
25. Stamp results with the commit that produced them; after a restamp say which stamp is final and whether the data is bit-identical. Why: reports otherwise cite stale code.
26. State n = 1 as n = 1, and mark a judgement call as the owner's judgement, not a measured spread. Why: readers over-read single runs.
27. Bench notes name the conditions that make a result unrepresentative (drifting ambient, wrong source, bad geometry). Why: later readers over-read pass or fail.
28. Device docs keep "Hardware-verified" (date, firmware) apart from "From vendor docs", plus "Open questions". Why: vendor docs and the real unit disagree.

### Bookkeeping

29. List assistant-originated claims that had no source under `pm/README.md` "Do not quote" too. Why: they read as fact when they return.
30. Add quoting rules beside each result block (per target, never a ranking, floors next to what they bound). Why: the critic who read the data writes the safest wording.
31. Log each shortcut as `rk add debt "<what>" --note "pay when: <trigger>"`; when paid, `rk close DB-<n> --note "<evidence>"`. Why: shortcuts otherwise rot into "later means never".
32. Log runs and lab-day steps under `pm/logs/` (step, command, log, start, end, status); pull data back from the rig into an ignored folder first, then import. Why: the record must show what really ran.
