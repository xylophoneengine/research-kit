#!/bin/bash
# Self-check for ledger-guard.sh: t <deny|none> <tool_name> <tool_input field> <value>
# (string value), tj <deny|none> <tool_name> '<tool_input JSON>'. Temp repos via mktemp -d,
# left in place. Prints FAIL lines, exits 1 on any.
HOOKS="$(cd "$(dirname "$0")" && pwd)"
G="$HOOKS/ledger-guard.sh"
export CLAUDE_PLUGIN_ROOT="$(cd "$HOOKS/.." && pwd)"
RK="$CLAUDE_PLUGIN_ROOT/skills/research-kit/scripts/rk.py"
fail=0
decision() { bash "$G" | jq -r '.hookSpecificOutput.permissionDecision // empty'; }
t() {
  local got
  got="$(jq -n --arg t "$2" --arg f "$3" --arg v "$4" '{tool_name:$t,tool_input:{($f):$v},cwd:"/nowhere"}' | decision)"
  got="${got:-none}"
  [ "$got" = "$1" ] || { echo "FAIL want=$1 got=$got root=$CLAUDE_PROJECT_DIR: $2 $3=$4"; fail=1; }
}
tj() {
  local got
  got="$(jq -n --arg t "$2" --argjson i "$3" '{tool_name:$t,tool_input:$i,cwd:"/nowhere"}' | decision)"
  got="${got:-none}"
  [ "$got" = "$1" ] || { echo "FAIL want=$1 got=$got: $2 $3"; fail=1; }
}
reason() {
  jq -n --arg t "$1" --arg f "$2" --arg v "$3" '{tool_name:$t,tool_input:{($f):$v}}' |
    bash "$G" | jq -r '.hookSpecificOutput.permissionDecisionReason // empty'
}

R="$(mktemp -d)"
mkdir -p "$R/pm" && : > "$R/pm/ledger.jsonl"
python3 -I "$RK" add task "work" --owner sr1 --repo "$R" >/dev/null
python3 -I "$RK" add task "old" --repo "$R" >/dev/null
python3 -I "$RK" close T-2 --note done --repo "$R" >/dev/null
export CLAUDE_PROJECT_DIR="$R"

deny_cases() {
  t "$1" Agent prompt $'You are sr1\nDELIVERABLE: x'
  t "$1" Agent prompt $'DELIVERABLE: x\nTASK: T-9'
  t "$1" SendMessage message $'DELIVERABLE: x\nTASK: T-2'
  t "$1" Edit file_path "$R/pm/ledger.jsonl"
  t "$1" Write file_path "$R/pm/STATUS.md"
  t "$1" Edit file_path "$R/pm/Status.md"
  t "$1" MultiEdit file_path "$R/pm/ledger.jsonl"
}
deny_cases deny

# pass: open task named, chat without DELIVERABLE, object message, other files, other tools
t none Agent prompt $'You are sr1\nDELIVERABLE: x\nTASK: T-1'
python3 -I "$RK" show T-1 --repo "$R" | grep -q '^status: running' ||
  { echo "FAIL T-1 not running after a passing brief"; fail=1; }
t none Agent prompt 'look up one fact, no brief'
t none SendMessage message 'DONE, report at r.md'
tj none SendMessage '{"to":"sr1","message":{"type":"shutdown_request"}}'
t none Edit file_path "$R/pm/README.md"
t none Write file_path "$R/pm/ledger.jsonl.bak"
t none Bash command 'ls'

case "$(reason Edit file_path "$R/pm/ledger.jsonl")" in
  *"$RK"*) ;; *) echo "FAIL edit reason lacks the rk.py path"; fail=1;; esac
case "$(reason Agent prompt $'DELIVERABLE: x')" in
  "refused:"*"TASK: T-"*) ;; *) echo "FAIL brief reason text"; fail=1;; esac

# CLAUDE_PROJECT_DIR unset: the payload's cwd is the root
got="$(env -u CLAUDE_PROJECT_DIR bash -c "jq -n --arg c '$R' '{tool_name:\"Agent\",tool_input:{prompt:\"DELIVERABLE: x\"},cwd:\$c}' | bash '$G'" |
  jq -r '.hookSpecificOutput.permissionDecision // empty')"
[ "$got" = deny ] || { echo "FAIL cwd fallback: got=${got:-none}"; fail=1; }

# repo without a ledger: the hook does nothing
CLAUDE_PROJECT_DIR="$(mktemp -d)"
deny_cases none

[ "$fail" = 0 ] && echo "ledger guard tests ok"
exit "$fail"
