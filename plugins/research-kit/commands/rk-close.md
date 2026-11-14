---
description: Close the current stage with the close checklist
argument-hint: "[stage]"
---

Close a stage. The steps are here, so no second skill load is needed. Arguments: $ARGUMENTS

Full mode only (light has no stage entries: say so and stop). `rk` below = `python3 -I "${CLAUDE_PLUGIN_ROOT}/skills/research-kit/scripts/rk.py"`, run from the repo root.

1. Name the stage: open stages are `rk list --type stage`; its folder is `pm/stages/NN-<kind>-<topic>/`. Several open: ask which (AskUserQuestion). A legacy stage path from the appendix is read-only: do not close it.
2. Check the stage's Done when mechanically. Not met: stop and tell the user what is missing. Sign-off is not part of it.
3. Read the repo's `AGENTS.md` section 3.4 "Stage close" and run its 8 steps in the order given there, one todo per step, with the owner the checklist names. Why: 3.4 is the single source; never work from memory or a copy.
4. Confirm each step's output exists before the next. The chat archive and the stage README file index come before the sign-off question; sign-off and `stage-close` come last and are not in the archive.
5. `rk stage-close S-<n> --sign-off D-<m>` writes `pm/stages/<stage folder>/LEDGER.md` itself: generated, frozen with the stage, never hand-edited or hand-written (a correction is a new ledger event in the current stage). Why: a hand-kept copy drifts from the ledger and the stage record stops being one page you can trust.
6. A refusal prints what is missing: fix it and rerun. Edits made after a critic's YES go into the close note of their task (AGENTS.md 2.2 step 6).
7. End by telling the user what is left for them: optional `/export` into the stage's `chat/` folder (it holds the tail the archive lacks), and committing.
