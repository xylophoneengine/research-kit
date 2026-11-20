#!/bin/bash
# PreToolUse hook (matcher Bash|PowerShell): deny deleting commands. Never allows anything:
# every other command (incl. the waste helper) gets the normal permission prompt.
# Thin wrapper (D-131): the rules live in rk_hook.py (guard-delete); this file only finds
# a Python 3. Without one: a systemMessage warning (exit 0), the guard is OFF (and the
# SessionStart hook says so in the session).
case "$0" in */*) here="${0%/*}" ;; *) here=. ;; esac
. "$here/find-python.sh"
rk_find_python || rk_no_python_guard
exec "${RK_PY[@]}" -I "$here/rk_hook.py" guard-delete
