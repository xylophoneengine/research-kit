#!/bin/bash
# Self-check for guard-delete.sh: t <deny|none> '<command>' (main thread),
# ta <deny|none> '<command>' (subagent: hook input carries agent_id). Prints FAIL lines, exits 1 on any.
G="$(cd "$(dirname "$0")" && pwd)/guard-delete.sh"
export CLAUDE_PLUGIN_ROOT=/PLUG
W=/PLUG/skills/waste/waste.sh
fail=0
t() {
  local got
  local in
  in="$(jq -n --arg c "$2" --arg a "${3:-}" '{tool_input:{command:$c}} + (if $a == "" then {} else {agent_id:$a} end)')"
  got="$(printf '%s' "$in" | bash "$G" | jq -r '.hookSpecificOutput.permissionDecision // empty')"
  got="${got:-none}"
  [ "$got" = "$1" ] || { echo "FAIL want=$1 got=$got agent=${3:-}: $2"; fail=1; }
}
ta() { t "$1" "$2" a1b2c3; }
# deny
t deny 'git --no-pager clean -fd'; t deny 'git -c core.x=1 rm f'; t deny 'git -C d clean -fdx'; t deny 'git status; git clean -f'
t deny 'rm -rf x'; t deny 'cd a && rm f'; t deny "find . -name '*.pyc' -delete"
t deny "python3 -c \"import shutil; shutil.rmtree('x')\""; t deny 'git rm f'; t deny 'ls | xargs rm'
t deny 'xargs -0 rm'; t deny 'sudo rm -rf /x'; t deny 'FOO=1 rm f'; t deny '/bin/rm f'; t deny 'rmdir d'
t deny 'unlink f'; t deny 'find . -exec rm {} \;'; t deny 'for f in *; do rm $f; done'
t deny 'git -C d rm f'; t deny 'ls; (rm f)'; t deny 'echo $(rm f)'; t deny 'git clean -fdx'
t deny 'git worktree remove w'; t deny 'timeout 5 rm x'; t deny 'nice rm x'
t deny "bash -c 'rm -rf x'"; t deny 'sh -c "rm -rf x"'; t deny 'eval rm x'
t deny '/opt/py/bin/python -c "import shutil; shutil.rmtree(1)"'
t deny "$W sr1 \"t\" f && rm g"
# none
t none 'git --no-pager log -S clean'; t none 'git log -S rm'; t none 'git -C d diff -G clean'; t none 'git grep clean'; t none 'git show HEAD:rm'; t none 'git blame -L 1,2 clean'
t none 'echo confirm'; t none 'grep -rn rmdir .'; t none 'docker run --rm img'; t none 'ls -la'
t none 'git status'; t none "git commit -m 'rm stuff'"; t none 'echo rmate'; t none 'cat rm.txt'
t none "$W sr1 t f; ls"; t none "$W sr1 t f \$(whoami)"; t none "$W sr1 t f > o"
# no auto-allow any more: the helper gets the normal prompt (crit3 F2/F4/F7)
t none "bash $W sr1 \"t\" f"; t none "$W sr1 t f"; t none "sh $W sr1 t f"
t none "bash \"$W\" sr1 t f"; t none 'bash ${CLAUDE_PLUGIN_ROOT}/skills/waste/waste.sh sr1 t f'
t none "bash -c 'x' /x/skills/waste/waste.sh y"; t none 'bash /x/skills/waste/waste.sh sr1 t f'
t none "chmod -R 000 . $W y"; t none "echo $W y"; t none "bash -x $W sr1 t f"
t none "$W a b /r/*"; t none "$W a b ~/p/.env"
grep -q 'permissionDecision:"allow"' "$G" && { echo "FAIL guard still has an allow branch"; fail=1; }
reason="$(jq -n --arg c 'rm f' '{tool_input:{command:$c}}' | bash "$G" | jq -r '.hookSpecificOutput.permissionDecisionReason')"
case "$reason" in "Deleting is off. Subagent/teammate: put one line per item at column 0 of your report: TO-WASTE: <path> -- <reason>; the lead moves it. Lead: run the research-kit waste helper (bash /PLUG/skills/waste/waste.sh"*"it asks the user. Temp/scratchpad files: leave them. Never rephrase the delete to get around this.") ;;
  *) echo "FAIL deny reason text: $reason"; fail=1;; esac
# subagent (agent_id set): waste helper denied, deletes denied, other commands untouched
ta deny "bash $W sr1 t f"; ta deny "$W sr1 t f"; ta deny 'bash ${CLAUDE_PLUGIN_ROOT}/skills/waste/waste.sh a b c'
ta deny "bash -c 'bash /x/skills/waste/waste.sh a b c'"; ta deny 'cd /r && ./waste.sh a b c'
ta deny 'rm -rf x'; ta none 'ls -la'; ta none 'bash test-waste.sh'; ta none 'git status'
reason="$(jq -n '{tool_input:{command:"waste.sh a b c"},agent_id:"x"}' | bash "$G" | jq -r '.hookSpecificOutput.permissionDecisionReason')"
case "$reason" in *"Lead:"*|"") echo "FAIL subagent reason text: $reason"; fail=1;; esac
[ "$fail" = 0 ] && echo "guard tests ok"
exit "$fail"
