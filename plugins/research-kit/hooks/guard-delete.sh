#!/bin/bash
# PreToolUse hook (matcher Bash): deny deleting commands. Never allows anything: every
# other command (incl. the waste helper) gets the normal permission prompt.
# Reads the hook JSON on stdin. bash + jq + grep only. Any failure -> silent exit 0 (no opinion).
# Heuristic on the command text: it also catches a delete word quoted inside an argument
# (e.g. after ";" in a commit message); that errs on the side of denying.
# agent_id: in the hook input only when the call comes from a subagent (absent on the main thread).
in="$(cat)"
cmd="$(jq -r '.tool_input.command // empty' <<<"$in" 2>/dev/null)" || exit 0
agent="$(jq -r '.agent_id // empty' <<<"$in" 2>/dev/null)" || agent=""
[ -n "$cmd" ] || exit 0

root="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)}"
S='[[:space:]]'
# command position: start of a line, after ; & | ( { ` $( , optionally behind a wrapper word and VAR=x
POS="(^|[;&|(\`{]|\\\$\\()$S*((do|then|else|xargs|sudo|env|nohup|time|timeout|nice|ionice|stdbuf|command|exec)$S+([^;&|]*$S)?)?([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*$S+)*"
END="($S|\$|[;&|)])"
hit() { printf '%s\n' "$cmd" | grep -Eq "$1"; }

del=0
hit "${POS}\\\\?([^[:space:]]*/)?(rm|rmdir|unlink)${END}" && del=1
hit "${POS}git($S+(-[Cc]$S+[^[:space:]]+|-[^[:space:]]+))*$S+(rm|clean|worktree$S+remove)${END}" && del=1
hit "${POS}find$S[^;&|]*$S-(delete|exec(dir)?$S+([^[:space:]]*/)?(rm|rmdir|unlink))${END}" && del=1
if hit '(^|[^[:alnum:]_.-])python[0-9.]*([[:space:]]|$)' &&
   hit 'rmtree|os\.remove|os\.unlink|os\.rmdir|\.unlink\('; then del=1; fi
# bash -c / sh -c / eval wrapping a delete word: deny
if hit "${POS}(bash|sh|zsh)$S+(-[a-z]+$S+)*-c$S|${POS}eval$S" &&
   hit "(^|[^[:alnum:]_.-])(rm|rmdir|unlink)($S|\$|[;&|)'\"])"; then del=1; fi

if [ "$del" = 1 ]; then
  jq -n --arg r "Deleting is off. Subagent/teammate: put one line per item at column 0 of your report: TO-WASTE: <path> -- <reason>; the lead moves it. Lead: run the research-kit waste helper (bash $root/skills/waste/waste.sh <who> \"<reason>\" <path>); it asks the user. Temp/scratchpad files: leave them. Never rephrase the delete to get around this." \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}' 2>/dev/null
  exit 0
fi

# Subagents never run the waste helper: the lead does, so the prompt reaches the user.
if [ -n "$agent" ] && hit '(^|[^[:alnum:]_.-])waste\.sh([^[:alnum:]_.-]|$)'; then
  jq -n --arg r "Deleting is off. Subagent/teammate: put one line per item at column 0 of your report: TO-WASTE: <path> -- <reason>; the lead moves it. Never rephrase the delete to get around this." \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}' 2>/dev/null
  exit 0
fi
exit 0
