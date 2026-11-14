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
  got="$(printf '%s' "$in" | "$BASH" "$G" | jq -r '.hookSpecificOutput.permissionDecision // empty')"
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
# heredocs are not parsed: a delete word at line start inside a heredoc body is denied too (hint in the reason says: use the Write tool)
t deny $'cat > f.md <<\'EOF\'\nrm src/App.css\ngit clean -fd\nEOF'
t deny $'cat > f.md <<EOF\nrm -rf dist\nEOF'
t deny $'cat <<\'EOF\' | tee f.md\nrm a\nEOF'
t deny $'cat >> f.md <<-EOF\n\trm a\n\tEOF'
t deny $'tee f.md <<"EOF" >/dev/null\nfind . -delete\nEOF'
t deny $'cat > f.md <<\\EOF\nrm a\nEOF\necho done'
t deny $'cat > f.md <<\'EOF\'\n$(rm a)\nEOF'
t deny $'cat > f.md <<EOF\n$(rm a)\nEOF'
t deny $'cat > f.md <<EOF\n`rm a`\nEOF'
t deny $'cat > f <<\'EOF\'\nx\nEOF\nrm f'
t deny $'cat > f <<\'EOF\' ; rm f\nx\nEOF'
t deny $'cat <<\'EOF\' \\\n; rm f\nx\nEOF'
t deny $'cat > f.md <<\'EOF\'\nx\nrm f'
t deny $'cat <<\'EOF\' > f && rm f\nx\nEOF'
t deny $'cat <<\'EOF\' | bash\nrm f\nEOF'
t deny $'cat <<\'EOF\' | tee f | sh -s\nrm f\nEOF'
t deny $'cat <<\'EOF\' | python3\nimport os; os.remove("f")\nEOF'
t deny $'bash <<\'EOF\'\nrm f\nEOF'
t deny $'sh <<EOF\nrm f\nEOF'
t deny $'zsh -s <<\'EOF\'\nrm f\nEOF'
t deny $'python3 - <<\'EOF\'\nimport shutil; shutil.rmtree("f")\nEOF'
t deny $'ssh h <<\'EOF\'\nrm f\nEOF'
t deny $'xargs sh <<\'EOF\'\nrm f\nEOF'
t deny $'eval "$(cat <<\'EOF\'\nrm f\nEOF\n)"'
t deny $'source <(cat <<\'EOF\'\nrm f\nEOF\n)'
t deny $'cat <<A <<B\nrm f\nA\nB'
# crit5 F1: write a script with a heredoc, then run it in the same command
for run in 'sh x.sh' 'bash x.sh' '. ./x.sh' 'source x.sh' 'chmod +x x.sh && ./x.sh' 'env sh x.sh' 'sh<x.sh' 'xargs -a x.sh sh -c' 'make' 'crontab x.sh'; do
  t deny $'cat > x.sh <<\'EOF\'\nrm f\nEOF\n'"$run"
  t deny $'tee x.sh <<\'EOF\' >/dev/null\nrm f\nEOF\n'"$run"
done
t deny $'cat > x.sh <<\'EOF\' ; sh x.sh\nrm f\nEOF'
t deny $'cat > x.sh <<\'EOF\' && sh x.sh\nrm f\nEOF'
t deny $'tee x.sh <<\'EOF\' | sh\nrm f\nEOF'
t deny $'tee >(sh) <<\'EOF\'\nrm f\nEOF'
t deny $'cat <<\'EOF\' > >(sh)\nrm f\nEOF'
t deny $'cat <<-\'EOF\' > x\n\trm f\n\tEOF\nsh x'
t deny $'cat <<"EOF" > x\nrm f\nEOF\nsh x'
t deny $'cat <<EOF > x\nrm f\nEOF\nsh x'
t deny $'cat <<A > x\nrm f\nA\ncat <<B\nhi\nB\nsh x'
t deny $'cat > Makefile <<\'EOF\'\nall:\n\trm f\nEOF\nmake'
t deny $'cat > x.py <<\'EOF\'\nimport shutil; shutil.rmtree("f")\nEOF\npython3 x.py'
t deny $'cat > .git/hooks/pre-commit <<\'EOF\'\nrm f\nEOF\nchmod +x .git/hooks/pre-commit; git commit -m x'
# crit5 F2: a << that is quoted or in a comment is not a heredoc; bash runs the following lines
t deny $'cat f "<<EOF"\nrm f\nEOF'
t deny $'cat f \'<<EOF\'\nrm -rf src\nEOF'
t deny $'cat f # <<EOF\nrm f\nEOF'
t deny $'echo "<<EOF"\nrm f\nEOF'
# crit5 F3: bash ends the body at the whole delimiter word, not at its first word characters
t deny $'cat > f <<E\\OF\nx\nEOF\nrm f\nE'
t deny $'cat > f <<"E"OF\nx\nEOF\nrm f\nE'
t deny $'cat > f <<\'E\'OF\nx\nEOF\nrm f\nE'
t deny $'cat <<\'EOF\' <<\'X\'\na\nEOF\nb\nX\nrm f'
t deny $'cat <<\'EOF\'\nhi\nEOF\nrm f'
t deny $'cat <<\'EOF\' ||\nx\nEOF\nrm f'
t deny $'git commit -m "$(cat <<\'EOF\'\ncleanup\nrm stale files\nEOF\n)"'
# P9: a separator inside a quoted argument of a text/read command is not a command position
t none 'grep -E "a|b|unlink|rmtree" file'; t none 'grep -E "a\|b\|unlink" f';t none "grep -E 'x|unlink|y' f"; t none "grep -rnE 'rmtree|unlink|rm -rf' . | head -20"
t none 'echo "a; rm b"'; t none "git commit -m 'fix: x; rm stale y'"; t none 'git commit -m "a (rm b)"'
t none "git --no-pager log --format='%h|rm' -n 3"; t none 'grep -E "a|rm" f 2>&1 | head'; t none $'echo \'a\'"; rm f"'
t none "printf '%s\n' 'x && git clean -f' >&2"; t none "cd d && grep -c 'a;rm' f"
# P9 bypass probes: every one must still deny
t deny "echo 'a'; rm f"; t deny 'echo "a" && rm f'; t deny 'echo "a" || rm f'; t deny "grep 'a' f & rm f"
t deny 'echo "$(rm f)"'; t deny 'echo "`rm f`"'; t deny 'echo "${x:-a; rm b}"'; t deny "echo \$'a\\'b'; rm f; echo 'x'"
t deny "echo a\\'; rm f; echo \\'"; t deny 'echo "a\\"; rm f; echo ""'; t deny $'echo "x"\nrm f'; t deny $'echo x # it\'s\nrm f'
t deny "echo 'a; rm b' | sh"; t deny 'echo "a; rm b" | bash'; t deny "FOO=1 echo 'a'; rm f"; t deny "echo 'a' | xargs rm"
t deny "echo 'a'; command rm f"; t deny "echo 'a'; builtin rm f"; t deny "echo 'a'; /bin/rm f"; t deny "echo 'a'; \\rm f"
t deny "{ echo 'a'; rm f; }"; t deny '(echo "a"; rm f)'; t deny "git -c alias.x='!a; rm f' x"; t deny "ssh h 'cd x; rm f'"
t deny "docker exec c sh -c 'x; rm y'"; t deny 'git commit -m "a; rm b" && rm c'; t deny "echo 'a' >&2; rm f"
t deny "find . -name 'a;b' -delete"; t deny "git log --format='%h'; git clean -f"; t deny "git --no-pager log -S 'a; rm b' | sh"
t deny "cat <<<'a; rm b'"; t deny "eval 'a; rm b'"; t deny "watch 'a; rm b'"; t deny "awk '{print}'; rm f"
grep -q 'permissionDecision:"allow"' "$G" && { echo "FAIL guard still has an allow branch"; fail=1; }
reason="$(jq -n --arg c 'rm f' '{tool_input:{command:$c}}' | "$BASH" "$G" | jq -r '.hookSpecificOutput.permissionDecisionReason')"
case "$reason" in "Deleting is off. Subagent/teammate: put one line per item at column 0 of your report: TO-WASTE: <path> -- <reason>; the lead moves it. Lead: run the research-kit waste helper (bash /PLUG/skills/waste/waste.sh"*"it asks the user. Temp/scratchpad files: leave them. If the delete word is only text (a report, a doc, a commit message), write that file with the Write tool instead of a heredoc. Never rephrase the delete to get around this.") ;;
  *) echo "FAIL deny reason text: $reason"; fail=1;; esac
case "$reason" in *"write that file with the Write tool"*"TO-WASTE:"*|*"TO-WASTE:"*"write that file with the Write tool"*) ;; *) echo "FAIL deny hint missing: $reason"; fail=1;; esac
# subagent (agent_id set): waste helper denied, deletes denied, other commands untouched
ta deny "bash $W sr1 t f"; ta deny "$W sr1 t f"; ta deny 'bash ${CLAUDE_PLUGIN_ROOT}/skills/waste/waste.sh a b c'
ta deny "bash -c 'bash /x/skills/waste/waste.sh a b c'"; ta deny 'cd /r && ./waste.sh a b c'
ta deny 'rm -rf x'; ta none 'ls -la'; ta none 'bash test-waste.sh'; ta none 'git status'
# P9: naming the helper in a read command is not running it; running, sourcing or copying it is
ta none 'sed -n 1,5p skills/waste/SKILL.md skills/waste/waste.sh'; ta none "grep -n reason $W | head"; ta none 'wc -l waste.sh'
ta none 'bash skills/waste/test-waste.sh'; ta none "git diff -- $W"
ta deny "\"$W\" a b c"; ta deny "echo x; $W a b c"; ta deny $'echo x\n'"$W a"; ta deny "( $W a )"; ta deny "command $W a"
ta deny "env FOO=1 $W a b c"; ta deny "source $W"; ta deny ". $W"; ta deny "cat $W | bash -s a b c"; ta deny "sed -n 1p $W | sh"
ta deny "xargs -a list $W"; ta deny "cp $W /tmp/w && /tmp/w a b c"; ta deny "chmod +x $W; ls"; ta deny "\$(echo $W) a b c"
ta deny "\`echo $W\` a b c"; ta deny "X=$W; \"\$X\" a b c"; ta deny "ln -s $W w"; ta deny "/bin/sh $W a"
reason="$(jq -n '{tool_input:{command:"waste.sh a b c"},agent_id:"x"}' | "$BASH" "$G" | jq -r '.hookSpecificOutput.permissionDecisionReason')"
case "$reason" in *"Lead:"*|"") echo "FAIL subagent reason text: $reason"; fail=1;; esac
[ "$fail" = 0 ] && echo "guard tests ok"
exit "$fail"
