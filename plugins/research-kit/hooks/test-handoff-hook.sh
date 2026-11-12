#!/bin/bash
# Self-check for handoff-hook.sh: ledger lines at session start and around a compaction.
# has / lacks <label> <needle> <text>. Temp dirs via mktemp -d, left in place.
# Prints FAIL lines, exits 1 on any.
HOOKS="$(cd "$(dirname "$0")" && pwd)"
H="$HOOKS/handoff-hook.sh"
export CLAUDE_PLUGIN_ROOT="$(cd "$HOOKS/.." && pwd)"
RK="$CLAUDE_PLUGIN_ROOT/skills/research-kit/scripts/rk.py"
fail=0
has() { case "$3" in *"$2"*) ;; *) echo "FAIL $1 lacks: $2"; fail=1;; esac; }
lacks() { case "$3" in *"$2"*) echo "FAIL $1 has: $2"; fail=1;; esac; }
last() { [ "$(printf '%s\n' "$3" | tail -n 1)" = "$2" ] || { echo "FAIL $1 last line is not: $2"; fail=1; }; }

# no ledger: unchanged behaviour, start prints nothing
export CLAUDE_PROJECT_DIR="$(mktemp -d)"
out="$(bash "$H" start)"; [ -z "$out" ] || { echo "FAIL start without ledger printed: $out"; fail=1; }
out="$(bash "$H" pre)"; lacks pre "Decisions and done work" "$out"; last pre "4. End with the single next step." "$out"
out="$(bash "$H" post)"; has post "[surviving-compaction]" "$out"; lacks post "Ledger tool" "$out"

# ledger with T-1 open
R="$(mktemp -d)"
mkdir -p "$R/pm" && : > "$R/pm/ledger.jsonl"
python3 -I "$RK" add task "first job" --owner sr1 --repo "$R" >/dev/null
export CLAUDE_PROJECT_DIR="$R"
out="$(bash "$H" start)"; has start "Ledger tool" "$out"; has start "$RK" "$out"; has start "T-1" "$out"
out="$(bash "$H" post)"; has post "[surviving-compaction]" "$out"; has post "Decisions and done work" "$out"
has post "T-1" "$out"; has post "Ledger tool" "$out"
out="$(bash "$H" pre)"; has pre "Decisions and done work" "$out"; last pre "5. End with the single next step." "$out"
# session in a git worktree: the open list and recent entries come from the main ledger
M="$(mktemp -d)"; W="$(mktemp -d)"
mkdir -p "$M/pm" "$M/.git/worktrees/wt" "$W/pm"
: > "$M/pm/ledger.jsonl"; : > "$W/pm/ledger.jsonl"
printf 'gitdir: %s/.git/worktrees/wt\n' "$M" > "$W/.git"
python3 -I "$RK" add task "fresh in main" --repo "$M" >/dev/null
out="$(CLAUDE_PROJECT_DIR="$W" bash "$H" start)"; has wt-start "fresh in main" "$out"
out="$(CLAUDE_PROJECT_DIR="$W" bash "$H" post)"
has wt-post "fresh in main" "$out"; has wt-post "Decisions and done work" "$out"
bash "$H" bogus >/dev/null 2>&1 && { echo "FAIL unknown mode exits 0"; fail=1; }

[ "$fail" = 0 ] && echo "handoff hook tests ok"
exit "$fail"
