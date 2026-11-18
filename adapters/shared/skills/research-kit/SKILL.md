---
name: research-kit
description: Set up research projects, stages, ledgers and handoffs.
---

# Research-kit

Work from the target git root. In these rules `rk` means
`python3 -I "${XDG_DATA_HOME:-$HOME/.local/share}/research-kit/core/scripts/rk.py"`.
Use the full invocation in each shell call (ordinary terminal users can
define an alias). If missing, point to `scripts/install_adapter.py` in the
kit checkout. Read project `AGENTS.md`, active `pm/kinds/` and `pm/README.md`
as applicable. At session start run `rk list`; `rk doctor` checks rule stamps
and ledger consistency. Only use `rk` to change the ledger or its generated
views; print the receipts. These adapters do not install automatic guards.
In Hermes, `/research-kit <operation>` selects a workflow; if none is
given, offer the workflows below.

## Setup and updates

- **init**: ask for kinds (`paper`, `software`, `reverse-eng`, `experiment`,
  `thesis`), `light` or `full`, who commits (`user` or `orchestrator`), and
  `pm` visibility (`tracked` or `local`). Run `rk init . --no-claude --kinds
  <comma-list> --mode <mode> --git <policy> --pm <visibility>`. Follow
  `AGENTS.md` §0.2 and active kind first-session steps; don't create a
  Claude pointer. If already initialized, suggest sync.
- **add-kind**: if unspecified, ask for an inactive kind; `rk add-kind .
  <kind>`. Read the new kind's first-session rules when it is added.
- **upgrade**: `rk upgrade .` switches light to full; report the outcome.
- **sync**: preview `rk sync . --no-claude` first; pass `--pm` only when
  requested. Show the diff summary, move project-specific DROPPED lines into
  the appendix, and ask about ambiguous lines. Apply with `--write` only
  when authorized, and `--accept-drop` only after remaining drops were
  reviewed. Read the new rules before continuing.
- **doctor**: `rk doctor` with any requested `--stage` or `--limit`.
- **viewer**: use `rk ui --status` to check existing viewers; run `rk ui`
  as a lead-owned background process, or give the user the terminal command
  if background serving is unavailable. Use only the localhost URL. Do not
  stop other sessions' viewers.

## Close a stage

Full mode only. Select the open stage and follow the project's `AGENTS.md`
§3.4 in order. For the chat archive use exports for the current harness,
not paths from another harness. Copy the main transcript last where
available; keep the secret scan, size check and `chat/INDEX.md`. If exports
aren't available, record exactly what's missing and ask the user whether to
accept a partial archive before proceeding. Keep the user-owner sign-off
and `rk stage-close` gates intact.

## Handoff and waste

Before a deliberate compact or stop, write a session-specific file under
`pm/handoffs/compact/`: verbatim user decisions and rules, done with
evidence, in-flight names/handles and brief/report paths, open questions,
instructions given to the user, and next step with its precondition.
After restart/compaction, reopen it and check ledger, git, reports and live
children before resuming; don't start a second writer if state is unknown.
There are no automatic compaction hooks here.

Never delete files. Only the lead, after explicit user approval, may run
`bash "${XDG_DATA_HOME:-$HOME/.local/share}/research-kit/waste.sh" lead
"<reason>" <paths>`; update ledger refs after the move as in `AGENTS.md` §7.
