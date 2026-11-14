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
python3 -I "$RK" add task "first job" --owner sr1 --note n --repo "$R" >/dev/null
export CLAUDE_PROJECT_DIR="$R"
out="$(bash "$H" start)"; has start "Ledger tool" "$out"; has start "$RK" "$out"; has start "T-1" "$out"
# the function line: pasteable as given, real path, a function (a $RK variable does not word-split in zsh)
fl="$(printf '%s\n' "$out" | grep -m1 '^rk() ')"
[ "$fl" = 'rk() { python3 -I "'"$RK"'" "$@"; }' ] || { echo "FAIL fn-line is not exactly the function: $fl"; fail=1; }
lacks fn-line "#" "$fl"   # nothing after "}": a trailing comment would swallow a joined command
[ -f "$RK" ] || { echo "FAIL fn-line path does not exist: $RK"; fail=1; }
[ "$(printf '%s\n' "$out" | grep -c '^rk() ')" = 1 ] || { echo "FAIL start: not exactly one function line"; fail=1; }
# the line joined to a command with ";" runs the command, in bash and zsh (the form the text tells)
for sh in bash zsh; do
  command -v $sh >/dev/null 2>&1 || { echo "FAIL $sh not installed"; fail=1; continue; }
  got="$(cd "$R" && $sh -c "$fl; rk list" 2>&1)"; rc=$?
  has "fn-line;$sh" "T-1" "$got"; [ "$rc" = 0 ] || { echo "FAIL fn-line; rk list in $sh: rc $rc"; fail=1; }
  got="$(cd "$R" && $sh -c "$fl; rk show T-99" 2>&1)"; rc=$?
  [ "$rc" != 0 ] || { echo "FAIL fn-line; rk show T-99 in $sh: rc 0 (command swallowed?)"; fail=1; }
done
# the explanation is its own comment line: no persistence claim, says how to join, zsh pitfall named
ex="$(printf '%s\n' "$out" | grep -m1 '^# \[research-kit\] Ledger tool')"
has expl 'a Bash call keeps no shell state' "$ex"; has expl 'joined to the command by ";"' "$ex"
has expl 'rk() {...}; rk list' "$ex"; has expl 'zsh does not word-split' "$ex"
lacks expl "defines" "$ex"
# real rk.py: doctor --start prints its kit line (never "usage:"); jq on PATH: no notice
has start-doctor "kit " "$out"; lacks start-doctor "usage:" "$out"
command -v jq >/dev/null 2>&1 && lacks start-jq "jq not found" "$out"
out="$(bash "$H" post)"; has post "[surviving-compaction]" "$out"; has post "Decisions and done work" "$out"
has post "T-1" "$out"; has post "Ledger tool" "$out"
out="$(bash "$H" pre)"; has pre "Decisions and done work" "$out"; last pre "5. End with the single next step." "$out"
# session in a git worktree: the open list and recent entries come from the main ledger
M="$(mktemp -d)"; W="$(mktemp -d)"
mkdir -p "$M/pm" "$M/.git/worktrees/wt" "$W/pm"
: > "$M/pm/ledger.jsonl"; : > "$W/pm/ledger.jsonl"
printf 'gitdir: %s/.git/worktrees/wt\n' "$M" > "$W/.git"
python3 -I "$RK" add task "fresh in main" --note n --repo "$M" >/dev/null
out="$(CLAUDE_PROJECT_DIR="$W" bash "$H" start)"; has wt-start "fresh in main" "$out"
out="$(CLAUDE_PROJECT_DIR="$W" bash "$H" post)"
has wt-post "fresh in main" "$out"; has wt-post "Decisions and done work" "$out"
# stub plugin: doctor --start prints a stale-stamp report (a stub with a fixed output, so the cut at 3 lines is testable)
P="$(mktemp -d)"; mkdir -p "$P/skills/research-kit/scripts"
cat > "$P/skills/research-kit/scripts/rk.py" <<'EOF'
import sys
a = sys.argv[1:]
if a[:2] == ["doctor", "--start"]:
    print("kit 0.9.0 (stub)")
    print("AGENTS.md 2026-11-01a, kit 2026-11-13e: run /rk-sync")
    print("pm/kinds/paper.md 2026-11-01a, kit 2026-11-13b: run /rk-sync")
    print("fourth line")
elif a[:1] == ["list"]:
    print("open 0 (stub list)")
EOF
out="$(CLAUDE_PLUGIN_ROOT="$P" bash "$H" start)"
has stub-doctor "kit 0.9.0 (stub)" "$out"; has stub-doctor "run /rk-sync" "$out"
has stub-doctor "pm/kinds/paper.md 2026-11-01a" "$out"
lacks stub-doctor "fourth line" "$out"; has stub-list "open 0 (stub list)" "$out"
[ "$(printf '%s\n' "$out" | wc -l | tr -d ' ')" -le 6 ] || { echo "FAIL stub block longer than function + explanation + 3 doctor + list"; fail=1; }
out="$(CLAUDE_PLUGIN_ROOT="$P" bash "$H" post)"; has stub-post "run /rk-sync" "$out"; has stub-post "[surviving-compaction]" "$out"
# doctor fails (exit 2, text on stdout): nothing from it, the rest intact, exit 0
cat > "$P/skills/research-kit/scripts/rk.py" <<'EOF'
import sys
a = sys.argv[1:]
if a[:1] == ["doctor"]:
    print("usage: rk.py ...  (error: invalid choice: 'doctor')"); sys.exit(2)
if a[:1] == ["list"]:
    print("open 0 (stub list)")
EOF
out="$(CLAUDE_PLUGIN_ROOT="$P" bash "$H" start)"; rc=$?
lacks doctor-fails "invalid choice" "$out"; has doctor-fails "open 0 (stub list)" "$out"; has doctor-fails "rk() " "$out"
[ "$rc" = 0 ] || { echo "FAIL doctor-fails exit $rc"; fail=1; }
# rk.py missing: session start still succeeds, function line kept
NOPLUG="$(mktemp -d)"
out="$(CLAUDE_PLUGIN_ROOT="$NOPLUG" bash "$H" start)"; rc=$?
[ "$rc" = 0 ] || { echo "FAIL missing rk.py exit $rc"; fail=1; }; has no-rk "rk() " "$out"
out="$(CLAUDE_PLUGIN_ROOT="$NOPLUG" bash "$H" post)"; rc=$?
[ "$rc" = 0 ] || { echo "FAIL missing rk.py post exit $rc"; fail=1; }; has no-rk-post "[surviving-compaction]" "$out"
# PATH without jq: the notice appears, nothing else breaks
NJ="$(mktemp -d)"
for t in python3 dirname find stat date head tail cat grep wc tr sed; do ln -s "$(command -v $t)" "$NJ/$t" 2>/dev/null; done
out="$(PATH="$NJ" /bin/bash "$H" start)"; rc=$?
has no-jq "jq not found: delete guard and brief check are OFF" "$out"; has no-jq "T-1" "$out"
[ "$rc" = 0 ] || { echo "FAIL no-jq exit $rc"; fail=1; }
out="$(PATH="$NJ" /bin/bash "$H" post)"; has no-jq-post "jq not found" "$out"
# the claim behind the notice: both guards exit 0 and print nothing without jq
g="$(PATH="$NJ" /bin/bash "$HOOKS/guard-delete.sh" <<<'{"tool_input":{"command":"git clean -fd"}}'; echo "rc=$?")"
[ "$g" = "rc=0" ] || { echo "FAIL guard-delete without jq: $g"; fail=1; }
g="$(PATH="$NJ" /bin/bash "$HOOKS/ledger-guard.sh" <<<'{"tool_name":"Write","tool_input":{"file_path":"x/pm/ledger.jsonl"}}'; echo "rc=$?")"
[ "$g" = "rc=0" ] || { echo "FAIL ledger-guard without jq: $g"; fail=1; }
# no ledger: no function line, no jq notice
out="$(CLAUDE_PROJECT_DIR="$(mktemp -d)" PATH="$NJ" /bin/bash "$H" start)"; [ -z "$out" ] || { echo "FAIL no ledger, no jq printed: $out"; fail=1; }
out="$(CLAUDE_PROJECT_DIR="$(mktemp -d)" PATH="$NJ" /bin/bash "$H" post)"; lacks no-ledger-post "jq not found" "$out"; lacks no-ledger-post "rk() " "$out"
bash "$H" bogus >/dev/null 2>&1 && { echo "FAIL unknown mode exits 0"; fail=1; }

[ "$fail" = 0 ] && echo "handoff hook tests ok"
exit "$fail"
