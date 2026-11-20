#!/bin/bash
# UserPromptSubmit hook: when the user announces a compact ("get ready for compact", "I'm
# stopping here", ...), tell the model to run the surviving-compaction Prepare steps.
# Thin wrapper (D-131): the rule lives in rk_hook.py (prompt). Without a Python 3 it stays
# silent; the SessionStart hook already says the hooks are OFF.
case "$0" in */*) here="${0%/*}" ;; *) here=. ;; esac
. "$here/find-python.sh"
rk_find_python || exit 0
exec "${RK_PY[@]}" -I "$here/rk_hook.py" prompt
