## Compact Instructions

When summarizing this session for compaction:
- First line: the newest handoff file under `pm/handoffs/compact/` (if any) with "read it before any other step".
- Keep verbatim: the user's decisions and rules, file paths, commit hashes, error messages, test and log file paths.
- Keep per open stage: its folder `pm/stages/NN-<kind>-<topic>/` and the status of its `Done when` check.
- Mark every claim about running agents, running commands or uncommitted work "unverified after compact".
- Keep a section "Decisions and done work": every decision the user made and every work package reported done in this conversation, one line each, with its ledger id when a receipt ("logged D-41: ...") was shown, else "not logged".
- End with the single next step.
