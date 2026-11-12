---
description: research-kit menu - pick init, add kind, upgrade, sync, close stage or compaction
---

Show the research-kit menu with the AskUserQuestion tool, then run the choice.
If `$ARGUMENTS` already names an action (init, add-kind, upgrade, sync, close,
prepare, resume), skip the menu and run it.

1. Look at the repo first (no other tool calls): does `AGENTS.md` exist with a
   `<!-- research-kit:` stamp (or a legacy `<!-- paper-playbook:` stamp)? Read
   its appendix `Mode:` line and the kinds block.
2. Ask one question, "What do you want to do?". In the same AskUserQuestion
   call, ONLY if neither `~/.claude/commands/rk.md` nor
   `~/.claude/commands/.rk-alias-declined` exists, add a second question
   "Install a /rk shortcut on this machine?" with options "Yes (Recommended)"
   (writes `~/.claude/commands/rk.md` so `/rk` ranks first in the slash menu),
   "Not now", "Never ask again". Yes -> Write `~/.claude/commands/rk.md` with
   exactly:

   ```
   ---
   description: research-kit menu (shortcut for /research-kit:rk)
   ---

   Invoke the Skill tool with skill `research-kit:rk` and args: $ARGUMENTS
   ```

   Never ask again -> Write an empty `~/.claude/commands/.rk-alias-declined`.
   Tell the user the shortcut works after a restart.

   Options of the first question (put the one that fits the repo state first,
   labelled `(Recommended)`):
   - **Set up / extend repo**: no research-kit `AGENTS.md` -> init; else add
     a kind, or upgrade light -> full.
   - **Sync with templates**: dry run first, then sort DROPPED lines.
   - **Close a stage**: run the close checklist on an open stage.
   - **Compaction handoff**: prepare before `/compact`, or resume after it.
3. Follow-up question only where the choice is ambiguous:
   - Set up / extend in an initialised repo: "Add a kind" or "Upgrade to full"
     (hide upgrade when `Mode: full`); for "Add a kind", ask which (multiSelect,
     only kinds not yet active).
   - Compaction: "Prepare" or "Resume".
   - Close a stage: if several stages are open, ask which (list folder names).
4. Run it:
   - init / add-kind / upgrade / sync / close: invoke the Skill tool with skill
     `research-kit:research-kit` and the mode (plus the kind or stage) as args.
   - prepare / resume: invoke the Skill tool with skill
     `research-kit:surviving-compaction` and the mode as args.
