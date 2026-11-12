<!-- research-kit-kind reverse-eng: 2026-11-13a -->
# Kind: reverse-eng

Applies to reimplementing a vendor-closed component (driver, protocol, file
format, SDK) from the vendor's own material and observed behaviour. Read at
session start and after every compact. Pairs with the `software` kind for the
implementation stages; add it too. Core `AGENTS.md` still applies (evidence
tags CONFIRMED / LIKELY / GUESS, `pm/DECISIONS.md`, `pm/DEFERRED.md`).

Stage folder: `pm/stages/NN-reverse-eng-<topic>/` (full mode); notes inside
`notes/` are numbered `NN_<topic>.md`, a later note says which earlier lines it
supersedes. Light mode: the table is a checklist, no folders.

## The seven rules

1. Scope statement first, in the appendix: interoperability for devices the lab owns, OS compatibility, clean-room; no DRM, licensing or protection bypass, and agents stop and report if a path leads there: the work is only defensible inside that scope.
2. Vendor binaries, firmware, captures and calibration files are gitignored and pinned by sha256; a `vendor/README.md` says where to get them and which build is accepted: redistribution rights are not ours, and an unpinned build makes notes irreproducible.
3. Capture first, at the narrowest API the vendor code calls: static reading predicts, a capture of the vendor stack decides, and a narrow hook needs no admin rights and drops system noise.
4. `PROTOCOL.md` at repo root is the spec artifact: every command, framing rule and constant has an evidence tag and a cite, and code cites its section, so the document and the code stay tied.
5. Fake transport plus replay tests before any hardware: agents and CI cannot touch devices, and a replay catches what unit tests with a shared assumption cannot.
6. Hardware day starts read-only; the hardware rule in `pm/kinds/experiment.md` applies even if that kind is not active (agents never touch hardware unless the user explicitly tells them to): a wrong guess must not be able to damage the unit.
7. The vendor wrapper or library stays as a black-box oracle on the vendor OS and every divergence from it is written down: a silent copy or silent fix of a vendor bug cannot be audited later.

## Stages

| # | Stage | Done when |
|---|-------|-----------|
| 1 | Goal, non-goals, why not use the vendor stack, scope statement | User agreed to the scope statement |
| 2 | Recon: inventory of vendor material, sha256 pins, executable bitness, list of vendor calls actually used | Inventory reviewed by the user and every file has a hash |
| 3 | Static analysis notes with tagged claims and cites, `PROTOCOL.md` draft | Both critics YES after re-checking the notes against the raw evidence |
| 4 | Capture plan with predictions, then capture (user-run), then capture-tool review | The reader test parses every captured file |
| 5 | Implement test-first on the fake transport, safety guards in the first commit | Gate green and both critics YES |
| 6 | Replay and oracle comparison with an allowed-difference list | Zero unexplained differences |
| 7 | Hardware day (user-run), read-only first, every transfer logged as a fixture | Every checklist row ticked or stopped on the first surprise |
| 8 | Reconcile: `PROTOCOL.md` corrections, known divergences, open risks | Unverified list is current and each open risk names the step that settles it |
| 9 | Package, disclose, CI, hand-check list | The user's hand test passes |
| 10 | Release, tag, history hygiene | The user published |

## Extended (opt-in)

Add `Reverse-eng extended: yes` to the appendix to turn this section on.
The seven rules above are the whole kind otherwise. Use Extended for a
first-of-its-kind device or when a lab run cannot be repeated.

### Evidence

- Tag every protocol or behaviour claim CONFIRMED / LIKELY / GUESS with a source cite (disassembly address, decompiler line, manual page, capture file hash): later stages need to know what to test first.
- "Re-checked" means the reviewer read the raw evidence, not the earlier note: notes were wrong where driver and fake shared one assumption.
- Never execute vendor binaries during analysis, read them as data: reproducibility and safety.
- Read bitness and calling convention from the file headers, not from names or decorations: a name-based reading was wrong and would have broken the interpreter choice.
- Vendor example code is evidence, not truth: list its bugs (silent type skips, argument width mismatches, unchecked return codes) so the port does not copy them.
- Device observation beats static analysis: write the correction inline where the static claim stood and keep a "still unverified on the wire" list, so the document stays trustworthy.
- An unexplained replay difference is a finding, never a test to loosen: loosening hides real divergence.
- Transport limits are data: enforce the observed limit loudly (raise) until a capture shows real framing, because a guess here desyncs the device.
- Vendor firmware and protocol generations differ: expect and test a second generation, because it surfaced only after the driver was called complete.
- Positive checkpoint: before writing any register, opcode, timeout or command string not sourced from a manual or a capture, stop and ask.

### Safety on real devices

- Guards go in from the first commit: request allowlist, refuse writes, firmware and persistent-memory paths by default, pin the model and ID before any traffic, cap acquisition time, raise instead of silently clamping: a wrong guess must not brick the unit.
- First hardware contact is read-only and staged; write-type steps go one at a time and stop at the first surprise: surprises compound.
- A step that overwrites device state says so in its docstring: probe scripts get run casually.
- Keep the open-risks list as a section, each row naming the hardware step that settles it: it turns guesses into a checklist.
- Log schemas are versioned and failed or aborted records stay parseable: one null field once made a whole capture unreadable.
- Retire scaffolding (the vendor-library backend) only after the wire protocol is verified, and keep the analysis as provenance.

### Process

- Numbered static-analysis notes, one per layer (formats, transport, commands, processing chain), plus the dump script that produced each number, with its command in the docstring.
- Write the capture plan with expectations first, so every packet validates or rejects a guess.
- Critic review of capture and probe code that has never run, before the single lab run (exit path, dangling callbacks, clobbered error state), and a verdict line GO / GO WITH CONDITIONS with ranked findings and an owner each.
- Reference implementation used only as black-box oracle; store its output as plain-text fixtures regenerated by a script, so tests run without it and licences stay separate.
- Calibration and config files from the vendor are inputs: document each format as its own note and probe it with a script.

Optional static-analysis MCP: `https://github.com/morluto/rea` (MIT). Vet it
before installing; it covers static analysis of binaries and firmware only,
no live capture. Nothing here depends on it.
