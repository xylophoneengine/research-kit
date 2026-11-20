#!/bin/bash
# Compaction hooks for the research-kit plugin's surviving-compaction skill.
#   handoff-hook.sh pre    PreCompact: stdout becomes instructions for the compaction summary
#   handoff-hook.sh post   SessionStart, matcher "compact": stdout is added to the model's context
#   handoff-hook.sh start  SessionStart, matcher "startup|resume|clear": ledger lines only
# pre/post look for the newest handoff-YYYY-MM-DD.md within 4 levels of the project root.
# In a repo with pm/ledger.jsonl (or a linked worktree whose main checkout has one) all three
# also print research-kit ledger lines (the rk() function line, doctor --start output, the
# open list; after a compact the newest entries to compare with the summary). In such a
# repo "pre" also writes pm/handoffs/compact/auto-<UTC stamp>.md (rk list, rk recent -n 30,
# git status --short); "post" names the newest one. A failed write is silent.
# Thin wrapper (D-131): the logic lives in rk_hook.py (handoff MODE); this file only finds
# a Python 3. Without one it prints that the kit's tools and guards are OFF, so the
# session sees it, and exits 0.
case "$0" in */*) here="${0%/*}" ;; *) here=. ;; esac
. "$here/find-python.sh"
rk_find_python || { echo "$RK_NO_PYTHON"; exit 0; }
exec "${RK_PY[@]}" -I "$here/rk_hook.py" handoff "$@"
