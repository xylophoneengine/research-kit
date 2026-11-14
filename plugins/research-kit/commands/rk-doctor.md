---
description: Check the ledger and its refs (rk doctor); read-only
argument-hint: "[--stage S-n] [--limit N]"
---

Run the ledger check and change nothing:

`python3 -I "${CLAUDE_PLUGIN_ROOT}/skills/research-kit/scripts/rk.py" doctor $ARGUMENTS`

Show the user the last line (`doctor: N hard, M soft`), every HARD finding in
full, and the SOFT groups with their counts. Propose a fix per group; apply
none before the user says so. No ledger in this repo: say so and stop.
