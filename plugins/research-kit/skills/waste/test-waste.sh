#!/usr/bin/env bash
# Tests for waste.sh (bash test-waste.sh). Builds temp git repos under $WASTE_TEST_DIR
# (default: a new dir under $TMPDIR) and leaves them there (nothing is deleted).
# Prints FAIL lines, "waste tests ok" when all pass; exits 1 on any failure.
set -uo pipefail
unset CDPATH
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
W="$HERE/waste.sh"
base="${WASTE_TEST_DIR:-${TMPDIR:-/tmp}}"
T="$(mkdir -p "$base" && cd "$base" && pwd -P)/waste-test-$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir -p "$T"
fail=0
LOG="$T/last.log"

bad() { echo "FAIL $*"; [ -s "$LOG" ] && sed 's/^/    | /' "$LOG"; fail=1; }
# run <want: ok|no> <name> <args...>: run waste.sh, check the exit status.
run() {
  local want="$1" name="$2"; shift 2
  if bash "$W" "$@" >"$LOG" 2>&1; then got=ok; else got=no; fi
  [ "$got" = "$want" ] || bad "$name: want $want, got $got"
}
exists() { [ -e "$2" ] || [ -L "$2" ] || bad "$1: missing $2"; }
gone() { if [ -e "$2" ] || [ -L "$2" ]; then bad "$1: still there $2"; fi; }
# mkrepo <dir> [pm]: git repo with the waste dirs ignored (pm/ created when asked).
mkrepo() {
  mkdir -p "$1" && git -C "$1" init -q
  printf 'pm/waste/\nWASTE/\n' > "$1/.gitignore"
  if [ "${2:-}" = pm ]; then mkdir -p "$1/pm"; fi
}
stamps() { local i; for i in 0 1 2 3 4 5 6 7 8; do date -u -v+"${i}"S +%Y%m%dT%H%M%SZ; done; }

# ---- basics -------------------------------------------------------------------
r="$T/basic"; mkrepo "$r" pm; echo v > "$r/f.txt"; mkdir -p "$r/d"; echo x > "$r/d/g"
run ok basic_pm tester "old file" "$r/f.txt" "$r/d"
gone basic_pm "$r/f.txt"; gone basic_pm "$r/d"
ls "$r"/pm/waste/*/f.txt >/dev/null 2>&1 || bad "basic_pm: f.txt not in pm/waste/<stamp>/"
grep -q '^| [0-9TZ]* | tester | f.txt | pm/waste/[0-9TZ]*/f.txt | old file |$' "$r/pm/waste/LEDGER.md" \
  || bad "basic_pm: ledger row"

r="$T/legacy"; mkrepo "$r"; echo v > "$r/f.txt"
run ok basic_legacy_WASTE tester t "$r/f.txt"
ls "$r"/WASTE/*/f.txt >/dev/null 2>&1 || bad "basic_legacy_WASTE: not under WASTE/"

r="$T/link"; mkrepo "$r" pm; echo keep > "$r/target"; ln -s target "$r/lnk"
run ok symlink_arg_moved_as_link tester t "$r/lnk"
gone symlink_arg "$r/lnk"; exists symlink_arg "$r/target"
[ -L "$(ls -d "$r"/pm/waste/*/lnk)" ] || bad "symlink_arg: wasted item is not the link"

r="$T/refuse"; mkrepo "$r" pm; echo x > "$r/-rf"; mkdir -p "$T/norepo"; echo x > "$T/norepo/f"
run no repo_root tester t "$r"
run no repo_root_dot tester t "$r/."
run no outside_repo tester t "$T/norepo/f"
run no pm_itself tester t "$r/pm"
run no dot_git tester t "$r/.git"
run no dot_git_child tester t "$r/.git/HEAD"
run no missing tester t "$r/nope"
(cd "$r" && bash "$W" tester t ./-rf >"$LOG" 2>&1) || bad "leading_dash: ./-rf not wasted"
git -C "$r" rev-parse --git-dir >/dev/null 2>&1 || bad "refuse: repo broken"

# ---- F1: case-insensitive bypass (.GIT, nested root, waste dir) -----------------
r="$T/f1"; mkrepo "$r" pm; mkrepo "$r/Inner"; echo x > "$r/Inner/f"
run no F1_dot_GIT tester t "$r/.GIT"
run no F1_dot_Git_child tester t "$r/.Git/HEAD"
git -C "$r" status >/dev/null 2>&1 || bad "F1: repo lost its .git"
run no F1_nested_root_case tester t "$r/INNER"
run no F1_nested_root tester t "$r/Inner"
run no F1_nested_dot_git tester t "$r/Inner/.GIT"
exists F1_nested "$r/Inner/.git"
echo y > "$r/a"; run ok F1_setup tester t "$r/a"
run no F1_waste_dir_case tester t "$r/PM/WASTE"
run no F1_ledger_case tester t "$r/pm/Waste/ledger.md"
exists F1_ledger "$r/pm/waste/LEDGER.md"

# ---- F2: the helper's own plugin dir (guard hook lives there) ------------------
k="$T/kit"; mkrepo "$k"; P="$k/plugins/research-kit"
mkdir -p "$P/skills/waste" "$P/hooks"; cp "$W" "$P/skills/waste/waste.sh"
echo guard > "$P/hooks/guard-delete.sh"; echo x > "$k/other"
ln -s "$P/skills/waste/waste.sh" "$T/waste-link.sh"
for tgt in "$P/hooks/guard-delete.sh" "$P/HOOKS" "$P" "$k/plugins" "$P/skills/waste/waste.sh"; do
  if bash "$P/skills/waste/waste.sh" a b "$tgt" >"$LOG" 2>&1; then bad "F2_own_plugin: wasted $tgt"; fi
done
if bash "$T/waste-link.sh" a b "$P/hooks/guard-delete.sh" >"$LOG" 2>&1; then
  bad "F2_via_symlinked_script: wasted the guard"
fi
exists F2 "$P/hooks/guard-delete.sh"
bash "$P/skills/waste/waste.sh" a b "$k/other" >"$LOG" 2>&1 || bad "F2: other file in kit repo refused"

# ---- F3: symlinked ledger / waste dirs, control chars ---------------------------
out="$T/outside"; mkdir -p "$out/.ssh"; echo "OWNERKEY" > "$out/.ssh/authorized_keys"
r="$T/f3a"; mkrepo "$r"; mkdir -p "$r/WASTE"; ln -s "$out/.ssh/authorized_keys" "$r/WASTE/LEDGER.md"
echo j > "$r/junk"; echo j > "$r/junk2"
run no F3_ledger_symlink crit3 t "$r/junk"
run no F3_reason_newline crit3 $'x\nssh-ed25519 ATTACKERKEY evil\n#' "$r/junk2"
[ "$(cat "$out/.ssh/authorized_keys")" = OWNERKEY ] || bad "F3: outside file changed"
exists F3_ledger "$r/junk"; exists F3_reason_newline "$r/junk2"
r="$T/f3b"; mkrepo "$r"; mkdir -p "$out/w"; ln -s "$out/w" "$r/WASTE"; echo s > "$r/secret"
run no F3_WASTE_symlink crit3 t "$r/secret"
r="$T/f3c"; mkrepo "$r"; mkdir -p "$out/p"; ln -s "$out/p" "$r/pm"; echo s > "$r/secret"
run no F3_pm_symlink crit3 t "$r/secret"
r="$T/f3d"; mkrepo "$r" pm; mkdir -p "$out/pw"; ln -s "$out/pw" "$r/pm/waste"; echo s > "$r/secret"
run no F3_pm_waste_symlink crit3 t "$r/secret"
r="$T/f3e"; mkrepo "$r" pm; mkdir -p "$out/st" "$r/pm/waste"; echo s > "$r/secret"
for s in $(stamps); do ln -s "$out/st" "$r/pm/waste/$s"; done
run no F3_symlink_in_destination crit3 t "$r/secret"
[ -z "$(ls -A "$out/st")" ] || bad "F3_symlink_in_destination: wrote outside"
[ -z "$(find "$out/w" "$out/p" "$out/pw" -mindepth 1)" ] || bad "F3: something landed outside"
for s in "$r/secret"; do exists F3 "$s"; done
run no F3_reason_tab crit3 $'a\tb' "$r/secret"
run no F3_who_pipe 'a|b' t "$r/secret"
run no F3_reason_pipe a 'x | y' "$r/secret"

# ---- F4: agent settings and secrets (glob over several repos) -------------------
for n in p1 p2; do
  mkrepo "$T/projs/$n"; mkdir -p "$T/projs/$n/.claude"
  echo s > "$T/projs/$n/.claude/settings.json"; echo k > "$T/projs/$n/.env"
  echo k > "$T/projs/$n/.env.local"; echo f > "$T/projs/$n/f.txt"
done
mkdir -p "$T/projs/p1/sub"; echo k > "$T/projs/p1/sub/.ENV"; mkdir -p "$T/projs/p1/.CLAUDE2"
run no F4_claude_dir tester t "$T/projs/p1/.claude"
run no F4_claude_case tester t "$T/projs/p1/.Claude/settings.json"
run no F4_env tester t "$T/projs/p1/.env"
run no F4_env_local tester t "$T/projs/p1/.env.local"
run no F4_env_nested_case tester t "$T/projs/p1/sub/.ENV"
run no F4_root_gitignore tester t "$T/projs/p1/.GITIGNORE"
bash "$W" tester t "$T"/projs/*/{.[!.],}* >"$LOG" 2>&1
for n in p1 p2; do
  for f in .git .gitignore .claude/settings.json .env .env.local; do exists "F4_glob_$n" "$T/projs/$n/$f"; done
done
G="$HERE/../../hooks/guard-delete.sh"
for c in "bash $W a b $T/projs/*/*" "bash $W a b ~/*" "$W a b \$HOME/{.[!.],}*"; do
  d="$(jq -n --arg c "$c" '{tool_input:{command:$c}}' | bash "$G" | jq -r '.hookSpecificOutput.permissionDecision // empty')"
  [ "${d:-none}" = none ] || bad "F4_hook: '$c' -> $d (want none = normal prompt)"
done
for n in p1 p2; do gone "F4_glob_plain_files_$n" "$T/projs/$n/f.txt"; done

# ---- F5: ledger injection through file names ----------------------------------
r="$T/f5"; mkrepo "$r" pm; echo x > "$r/a | b | c |"; echo y > "$r/n"$'\n'"| 2020 | user | fake"
run ok F5_pipe_name tester t "$r/a | b | c |"
grep -qF '| tester | a \| b \| c \| | pm/waste/' "$r/pm/waste/LEDGER.md" || bad "F5_pipe_name: | not escaped"
run no F5_newline_name tester t "$r/n"$'\n'"| 2020 | user | fake"
exists F5_newline_name "$r/n"$'\n'"| 2020 | user | fake"
grep -q '| 2020 |' "$r/pm/waste/LEDGER.md" && bad "F5: forged row in ledger"

# ---- F6: waste dir must be gitignored -----------------------------------------
r="$T/f6"; mkdir -p "$r/pm" "$r/secrets"; git -C "$r" init -q; printf '/secrets/\n' > "$r/.gitignore"
echo key > "$r/secrets/key"
run no F6_waste_not_ignored tester t "$r/secrets"
exists F6 "$r/secrets/key"
r="$T/f6b"; mkrepo "$r"; printf 'WASTE/*\n!WASTE/LEDGER.md\n' > "$r/.gitignore"; echo x > "$r/f"
run ok F6_legacy_ignore_pattern tester t "$r/f"
[ -z "$(git -C "$r" status --porcelain --untracked-files=all | grep -v 'LEDGER.md\|.gitignore')" ] \
  || bad "F6: wasted file shows in git status"

# ---- F8: never overwrite an existing destination --------------------------------
r="$T/f8"; mkrepo "$r" pm; echo new > "$r/f"
for s in $(stamps); do mkdir -p "$r/pm/waste/$s"; echo old > "$r/pm/waste/$s/f"; done
run no F8_destination_exists tester t "$r/f"
[ "$(cat "$r/f")" = new ] || bad "F8: source changed"
for s in $(stamps); do [ "$(cat "$r/pm/waste/$s/f")" = old ] || bad "F8: old copy overwritten"; done

# ---- crit3 r2: N1-N5, U1 ------------------------------------------------------
mkrepo "$T/evil"; mkdir -p "$T/home/docs"; echo d > "$T/home/docs/a"
printf 'WASTE/\npm/waste/\n' >> "$T/evil/.git/info/exclude"  # ignore check passes too
if GIT_DIR="$T/evil/.git" GIT_WORK_TREE="$T/home" bash "$W" c t "$T/home/docs" >"$LOG" 2>&1; then
  bad "N1_GIT_env_redirect: wasted outside any repo"
fi
exists N1 "$T/home/docs/a"
r="$T/n2"; mkrepo "$r"; echo real > "$r/keep"; echo nl > "$r/keep"$'\n'
run no N2_trailing_newline_name c t "$r/keep"$'\n'
[ "$(cat "$r/keep")" = real ] || bad "N2: sibling 'keep' was moved"
exists N2 "$r/keep"$'\n'
r="$T/n3"; mkrepo "$r" pm
mkdir -p "$r/app1" "$r/app2/.Claude" "$r/vend/lib" "$r/app3/x" "$r/ok1" "$r/ok2" "$r/kit/.claude-plugin"
echo k > "$r/app1/.env"; echo s > "$r/app2/.Claude/settings.json"; git -C "$r/vend/lib" init -q
echo k > "$r/app3/x/.ENV.local"; echo e > "$r/ok1/.env.example"; echo e > "$r/ok2/.envrc"
run no N3_dir_holds_env c t "$r/app1"
run no N3_dir_holds_claude c t "$r/app2"
run no N3_dir_holds_nested_repo c t "$r/vend"
run no N3_dir_holds_env_local_deep c t "$r/app3"
run no N3_dir_holds_claude_plugin c t "$r/kit"
run ok N3_dir_with_env_example c t "$r/ok1"
run ok N3_dir_with_envrc c t "$r/ok2"
for d in app1/.env app2/.Claude/settings.json vend/lib/.git app3/x/.ENV.local kit/.claude-plugin; do
  exists N3 "$r/$d"
done
r="$T/n4"; mkrepo "$r" pm; printf 'waste/\n' > "$r/pm/.gitignore"; mkdir -p "$r/sub"
echo x > "$r/sub/.gitignore"
run no N4_pm_gitignore c t "$r/pm/.gitignore"
run no N4_sub_gitignore c t "$r/sub/.gitignore"
run no N4_root_gitignore_case c t "$r/.GitIgnore"
exists N4 "$r/pm/.gitignore"
r="$T/n5"; mkrepo "$r"; mkdir -p "$r/.claude-plugin"; echo m > "$r/.claude-plugin/marketplace.json"
run no N5_claude_plugin c t "$r/.claude-plugin"
run no N5_claude_plugin_child c t "$r/.Claude-Plugin/marketplace.json"
exists N5 "$r/.claude-plugin/marketplace.json"
r="$T/u1"; mkrepo "$r"
for f in .envrc .environment.yml .env.example .env.sample .env.template env.py .env.local .ENV.production .env; do
  echo x > "$r/$f"
done
for f in .envrc .environment.yml .env.example .env.sample .env.template env.py; do run ok "U1_allowed_$f" c t "$r/$f"; done
for f in .env.local .ENV.production .env; do run no "U1_refused_$f" c t "$r/$f"; exists U1 "$r/$f"; done
r="$T/msg"; mkdir -p "$r"; git -C "$r" init -q; echo x > "$r/f"
run no not_ignored_message c t "$r/f"
grep -q "rk-init" "$LOG" && grep -q "add the line 'WASTE/' to" "$LOG" || bad "not_ignored_message: not actionable"

echo "test repos left in $T"
[ "$fail" = 0 ] && echo "waste tests ok"
exit "$fail"
