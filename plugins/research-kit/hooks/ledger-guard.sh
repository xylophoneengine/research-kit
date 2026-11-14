#!/bin/bash
# PreToolUse hook (matcher Agent|SendMessage|Edit|Write|MultiEdit) for the research-kit
# ledger. Does nothing unless <project>/pm/ledger.jsonl exists. Never allows anything:
# it denies or stays silent (the normal permission flow continues).
#  - Edit/Write/MultiEdit of pm/ledger.jsonl or pm/STATUS.md: deny; only rk.py writes them.
#  - Agent prompt / SendMessage message with a DELIVERABLE: line (a team brief): rk.py
#    brief-check; refused -> deny with its text. A passing brief marks its task running.
#    Not checked inside a subagent (.agent_id set): only the lead hands out work.
# Reads the hook JSON on stdin. bash + jq + python3. Unparsable input -> silent exit 0.
set -u
in="$(cat)"
tool="$(jq -r '.tool_name // empty' <<<"$in" 2>/dev/null)" || exit 0
root="${CLAUDE_PROJECT_DIR:-}"
[ -n "$root" ] || root="$(jq -r '.cwd // empty' <<<"$in" 2>/dev/null)" || exit 0
{ [ -n "$root" ] && [ -f "$root/pm/ledger.jsonl" ]; } || exit 0
plugin="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)}"
rk="$plugin/skills/research-kit/scripts/rk.py"

deny() {
  jq -n --arg r "$1" \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}' 2>/dev/null
  exit 0
}

case "$tool" in
  Edit|Write|MultiEdit)
    fp="$(jq -r '.tool_input.file_path // empty' <<<"$in" 2>/dev/null)" || exit 0
    lc="$(printf '%s' "$fp" | tr '[:upper:]' '[:lower:]')"
    s=/  # a variable: bash 3.2 keeps the backslash of an escaped slash in the replacement
    while [[ "$lc" == *//* || "$lc" == */./* ]]; do  # pm//x, pm/./x -> pm/x
      lc="${lc//$s$s/$s}"; lc="${lc//$s.$s/$s}"
    done
    case "$lc" in
      */pm/ledger.jsonl|*/pm/status.md|pm/ledger.jsonl|pm/status.md)
        deny "pm/ledger.jsonl and pm/STATUS.md are written only by the ledger tool: python3 -I \"$rk\" <add|start|close|drop|reopen|set|supersede|reref|stage-close|import> ... STATUS.md is regenerated after every write (render rebuilds it). A broken ledger line: run doctor (python3 -I \"$rk\" doctor), it names the line; the fix is by hand outside Claude, so ask the user."
        ;;
    esac
    ;;
  Agent|SendMessage)
    [ -n "$(jq -r '.agent_id // empty' <<<"$in" 2>/dev/null)" ] && exit 0
    q='.tool_input.prompt | strings'
    [ "$tool" = SendMessage ] && q='.tool_input.message | strings'
    text="$(jq -r "$q" <<<"$in" 2>/dev/null)" || exit 0
    # cheap pre-filter; rk.py brief-check applies the exact rule (line start)
    case "$text" in *DELIVERABLE:*) ;; *) exit 0 ;; esac
    # the events brief-check writes carry the session id (sid): the hook's env may lack
    # CLAUDE_CODE_SESSION_ID, the input JSON has session_id
    if [ -z "${CLAUDE_CODE_SESSION_ID:-}" ]; then
      sid_in="$(jq -r '.session_id // empty' <<<"$in" 2>/dev/null)"
      [ -n "$sid_in" ] && export CLAUDE_CODE_SESSION_ID="$sid_in"
    fi
    # run from the root without --repo: the tool's own lookup (a worktree -> main ledger)
    out="$(cd "$root" && printf '%s\n' "$text" | python3 -I "$rk" brief-check --who hook 2>&1)"
    rc=$?
    [ "$rc" = 0 ] && exit 0
    [ -n "$out" ] || out="ledger brief check failed (rk.py brief-check exit $rc)"
    deny "${out:0:1000}"
    ;;
esac
exit 0
