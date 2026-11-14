#!/bin/bash
# PreToolUse hook (matcher Bash): deny deleting commands. Never allows anything: every
# other command (incl. the waste helper) gets the normal permission prompt.
# Reads the hook JSON on stdin. bash + jq + grep only. Any failure -> silent exit 0 (no opinion).
# Heuristic on the command text: it also catches a delete word quoted inside an argument
# (e.g. after ";" in a commit message), except in plain text/read commands (P9 below);
# that errs on the side of denying.
# agent_id: in the hook input only when the call comes from a subagent (absent on the main thread).
in="$(cat)"
cmd="$(jq -r '.tool_input.command // empty' <<<"$in" 2>/dev/null)" || exit 0
agent="$(jq -r '.agent_id // empty' <<<"$in" 2>/dev/null)" || agent=""
[ -n "$cmd" ] || exit 0

root="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)}"
S='[[:space:]]'
# command position: start of a line, after ; & | ( { ` $( , optionally behind a wrapper word and VAR=x
POS="(^|[;&|(\`{]|\\\$\\()$S*((do|then|else|xargs|sudo|env|nohup|time|timeout|nice|ionice|stdbuf|command|builtin|exec)$S+([^;&|]*$S)?)?([A-Za-z_][A-Za-z0-9_]*=[^[:space:]]*$S+)*"
END="($S|\$|[;&|)])"
hit() { printf '%s\n' "$cmd" | grep -Eq "$1"; }
# rm / git rm|clean|worktree remove / find -delete|-exec rm at command position in $1
shdel() {
  printf '%s\n' "$1" | grep -Eq \
    -e "${POS}\\\\?([^[:space:]]*/)?(rm|rmdir|unlink)${END}" \
    -e "${POS}git($S+(-[Cc]$S+[^[:space:]]+|-[^[:space:]]+))*$S+(rm|clean|worktree$S+remove)${END}" \
    -e "${POS}find$S[^;&|]*$S-(delete|exec(dir)?$S+([^[:space:]]*/)?(rm|rmdir|unlink))${END}"
}
# $cmd with ; & | ( ) { } inside '...' and "..." replaced by _ (bash quoting, one line only).
blank_quoted() {
  local out="" q="" c i n=${#cmd}
  for ((i = 0; i < n; i++)); do
    c="${cmd:i:1}"
    if [ -z "$q" ]; then
      case "$c" in
        \\) out="$out$c${cmd:i+1:1}"; i=$((i + 1)) ;;
        \"|\') q="$c"; out="$out$c" ;;
        *) out="$out$c" ;;
      esac
    elif [ "$c" = "$q" ]; then q=""; out="$out$c"
    elif [ "$q" = '"' ] && [ "$c" = '\' ]; then out="${out}__"; i=$((i + 1))
    else
      case "$c" in [\;\&\|\(\)\{\}]) out="${out}_" ;; *) out="$out$c" ;; esac
    fi
  done
  printf '%s\n' "$out"
}
# P9: a separator inside a quoted argument is not a command position (grep -E 'a|unlink',
# echo "x; rm y"). Only for one plain line (no newline, heredoc, $( ), backtick, $'', ${ }:
# there the quotes may not be what they seem, or run) where every command is a text or read
# command that never runs its arguments. Anything else keeps the old reading: deny.
SAFE="grep|egrep|fgrep|echo|printf|cat|head|tail|wc|ls|cd|jq|git($S+(-C$S+[^[:space:]]+|--no-pager))*$S+(commit|log|show|diff)"
quoted_text_only() {
  local s
  case "$cmd" in *$'\n'* | *'<<'* | *'$('* | *'`'* | *"\$'"* | *'${'*) return 1 ;; esac
  s="$(blank_quoted)"
  s="${s//>&/>_}"; s="${s//<&/<_}"; s="${s//&>/_>}"
  printf '%s\n' "$s" | grep -Eo '(^|[;&|(){}])[^;&|(){}]*' |
    grep -Evq "^[;&|(){}]?$S*(($SAFE)($S.*)?)?\$" && return 1
  ! shdel "$s"
}

del=0
shdel "$cmd" && del=1
[ "$del" = 1 ] && quoted_text_only && del=0
# a ; inside a quoted find argument hid -delete from the find rule (find . -name 'a;b' -delete)
[ "$del" = 0 ] && hit "${POS}find$S" && shdel "$(blank_quoted)" && del=1
if hit '(^|[^[:alnum:]_.-])python[0-9.]*([[:space:]]|$)' &&
   hit 'rmtree|os\.remove|os\.unlink|os\.rmdir|\.unlink\('; then del=1; fi
# bash -c / sh -c / eval wrapping a delete word: deny
if hit "${POS}(bash|sh|zsh)$S+(-[a-z]+$S+)*-c$S|${POS}eval$S" &&
   hit "(^|[^[:alnum:]_.-])(rm|rmdir|unlink)($S|\$|[;&|)'\"])"; then del=1; fi

if [ "$del" = 1 ]; then
  jq -n --arg r "Deleting is off. Subagent/teammate: put one line per item at column 0 of your report: TO-WASTE: <path> -- <reason>; the lead moves it. Lead: run the research-kit waste helper (bash $root/skills/waste/waste.sh <who> \"<reason>\" <path>); it asks the user. Temp/scratchpad files: leave them. If the delete word is only text (a report, a doc, a commit message), write that file with the Write tool instead of a heredoc. Never rephrase the delete to get around this." \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}' 2>/dev/null
  exit 0
fi

# Subagents never run the waste helper: the lead does, so the prompt reaches the user.
# P9: naming waste.sh is not running it (sed -n 1p skills/waste/waste.sh). Deny when it or a
# $variable sits at command position, when the line has $( ) or a backtick, or when any
# command could run or copy it (shell, source, eval, xargs, env, cp, chmod, ...).
RUN="bash|sh|zsh|dash|ksh|fish|source|\\.|eval|exec|xargs|env|sudo|nohup|time|timeout|nice|cp|ln|mv|install|rsync|ditto|chmod|tee|python[0-9.]*|perl|ruby|node"
if [ -n "$agent" ] && hit '(^|[^[:alnum:]_.-])waste\.sh([^[:alnum:]_.-]|$)' &&
   { hit "${POS}[\"']?(\\\$|([^[:space:]]*/)?waste\\.sh)" || hit "${POS}([^[:space:]]*/)?($RUN)${END}" ||
     hit '\$\(|`'; }; then
  jq -n --arg r "Deleting is off. Subagent/teammate: put one line per item at column 0 of your report: TO-WASTE: <path> -- <reason>; the lead moves it. Never rephrase the delete to get around this." \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}' 2>/dev/null
  exit 0
fi
exit 0
