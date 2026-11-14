#!/usr/bin/env bash
# Tests for release_check.sh, anon_check.sh and githooks/pre-push. Builds
# throwaway repos under mktemp -d. Invented denylist terms only; fake leaks
# are assembled at run time so this file itself stays clean.
set -euo pipefail
S="$(cd "$(dirname "$0")" && pwd)"
T="$(cd "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$T"' EXIT
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
export GIT_AUTHOR_NAME=pat GIT_AUTHOR_EMAIL=pat@example.invalid
export GIT_COMMITTER_NAME=pat GIT_COMMITTER_EMAIL=pat@example.invalid
unset ANON_DENYLIST || true
unset $(git rev-parse --local-env-vars) # never act on a caller's repo
mkdir "$T/bin" # stub, so plugin validate runs without a real claude
printf '#!/bin/sh\nexit 0\n' >"$T/bin/claude"
chmod +x "$T/bin/claude"
export PATH="$T/bin:$PATH"

passed=0
failed=0
# expect <0|1|2|nz> <ERE the output must match, or -> <name> <cmd...>
expect() {
  local want="$1" pat="$2" name="$3" out rc=0
  shift 3
  out="$("$@" 2>&1)" || rc=$?
  if { [ "$want" = nz ] && [ "$rc" -ne 0 ]; } || [ "$want" = "$rc" ]; then
    if [ "$pat" = - ] || printf '%s\n' "$out" | grep -qE -- "$pat"; then
      passed=$((passed + 1))
      return 0
    fi
  fi
  failed=$((failed + 1))
  echo "FAIL: $name (exit $rc, want $want, pattern $pat)"
  printf '%s\n' "$out" | tail -n 15 | sed 's/^/    /'
}
put() { # <file> <text>: write and stage
  mkdir -p "$(dirname "$1")"
  printf '%s\n' "$2" >"$1"
  git add -A
}
commit() { # <file> <text> <message>
  put "$1" "$2"
  git commit -qm "$3"
}
branch() { git checkout -q -B "$1" origin/main; }
anon() { bash scripts/anon_check.sh "$@"; }
gate() { bash scripts/release_check.sh "$@"; }

# base repo: what origin/main already has
R="$T/repo"
TPL=plugins/research-kit/skills/research-kit/template
git init -q -b main "$R"
cd "$R"
mkdir -p scripts/githooks docs/private
cp "$S/release_check.sh" "$S/anon_check.sh" "$S/anon_check.py" scripts/
cp "$S/githooks/pre-push" scripts/githooks/
DEMO="demo@""corp.example.org" # assembled, so this file holds no address
printf '%s\n' '# test identity' 'pat@example.invalid' '# accepted example' "$DEMO" \
  >scripts/anon_allow.txt
printf 'docs/\n' >.gitignore
printf '# invented terms\nzorblax\nquuxington\n' >docs/private/denylist.txt
put plugins/research-kit/.claude-plugin/plugin.json '{"name": "research-kit", "version": "0.1.0"}'
put "$TPL/AGENTS.md" '<!-- research-kit: 2026-01-01a -->'
printf 'rule one\n' >>"$TPL/AGENTS.md"
commit notes.txt 'plain notes' 'base'
git update-ref refs/remotes/origin/main HEAD

# clean range passes the whole gate
branch clean
commit notes.txt 'more plain notes' 'notes: more'
expect 0 'release_check: PASS' 'clean range passes' gate
expect 0 'anon_check: clean' 'clean range, explicit range' anon origin/main..HEAD

# denylisted term in content, message, file name; output never repeats it
branch content
commit notes.txt 'we used ZorBlax here' 'notes: tool'
expect 1 'HIT denylist .* notes.txt:1: we used <denylist:2> here' 'term in content' anon
expect nz 'FAIL anon check' 'gate stops on anon hit' gate
if anon 2>&1 | grep -qi zorblax; then
  failed=$((failed + 1))
  echo "FAIL: output repeats a denylisted term"
fi
branch message
commit notes.txt 'fine text' 'notes: from quuxington'
expect 1 'HIT denylist .* message: notes: from <denylist:3>' 'term in message' anon
branch name
commit data/zorblax-list.txt 'fine text' 'data: list'
expect 1 'HIT denylist .* file name: data/<denylist:2>-list.txt' 'term in file name' anon

# allowlist: excuses exactly the span it matches, nothing around it
branch allowed
commit notes.txt "write to $DEMO" 'notes: demo'
expect 0 'anon_check: clean' 'allowlisted line passes' anon
commit notes.txt "$DEMO and zorblax" 'notes: both'
expect 1 'HIT denylist' 'allowlist does not hide the rest of a line' anon
branch allowed
commit notes.txt "write to x$DEMO" 'notes: longer address'
expect 1 'HIT email' 'allowlist entry excuses only its exact span' anon
branch allowed
commit notes.txt "write to zorblax@""corp.example.org" 'notes: term as local part'
printf 're:[a-z]+@corp\\.example\\.org\n' >>scripts/anon_allow.txt
expect 1 'HIT denylist' 'regex entry around a term does not hide it' anon
for bad in 're:.*' 're:x?' 're:zorb.*' 'ZorBlax' 're:q[u]+xington'; do
  git checkout -q -- scripts/anon_allow.txt
  printf '%s\n' "$bad" >>scripts/anon_allow.txt
  expect 2 'empty string|matches denylist term' "allowlist entry refused: $bad" anon
done
git checkout -q -- scripts/anon_allow.txt
printf 're:.*\n' >>scripts/anon_allow.txt
expect 2 'empty string' 'empty-matching entry refused without a denylist too' anon --no-denylist
git checkout -q -- scripts/anon_allow.txt
branch allowed
commit notes.txt "to bob@""corp.example.org" 'notes: wider entry'
printf 're:to [a-z]+@corp\\.example\\.org\n' >>scripts/anon_allow.txt
expect 1 'HIT email' 'entry wider than the hit does not excuse it' anon
git checkout -q -- scripts/anon_allow.txt

# lockfile integrity hashes: a term inside the random base64 is not a hit
branch lockfile
h="sha512-AbCdEfGh0123zorblaxIjKlMnOp4567QrStUvWx89=="
commit ui/package-lock.json "      \"integrity\": \"$h\"," 'ui: lockfile'
expect 0 'anon_check: clean' 'term inside an integrity hash' anon
commit ui/package-lock.json "      \"resolved\": \"zorblax\"," 'ui: lockfile'
expect 1 'HIT denylist' 'term outside the hash still hits' anon

# annotated tags pointing into the range: message and tagger are scanned
branch tagged
commit notes.txt 'plain' 'notes: tagged'
git tag -a v9 -m 'release for quuxington'
expect 1 'HIT denylist .* tag v9 message' 'annotated tag message' anon
git tag -d v9 >/dev/null

# pattern scans: home path, temp path, secret, email, session id
branch patterns
commit notes.txt "data in /Us""ers/alice/data" 'notes: path'
expect 1 'HIT home-path' 'home path' anon
branch patterns
commit notes.txt "log at /private/tmp/clau""de-501/x" 'notes: tmp'
expect 1 'HIT temp-path' 'temp path' anon
branch patterns
commit notes.txt "key gh""p_abcdefghijklmnopqrstuvwxyz0123456789" 'notes: key'
expect 1 'HIT secret ' 'fake token' anon
branch patterns
commit notes.txt "api_""key = 'abcd1234efgh5678'" 'notes: key'
expect 1 'HIT secret-assign' 'key assignment' anon
branch patterns
commit notes.txt "mail bob@""corp.example.org" 'notes: mail'
expect 1 'HIT email' 'email address' anon
branch patterns
commit notes.txt "session 1b2c3d4e-0000-4abc-8def-""0123456789ab" 'notes: sid'
expect 1 'HIT session-id' 'session id' anon

# author and committer must match origin/main's tip
branch author
put notes.txt 'plain'
GIT_AUTHOR_NAME=someone git commit -qm 'notes: other author'
expect 1 'HIT author' 'wrong author' anon
branch committer
put notes.txt 'plain'
GIT_COMMITTER_NAME=someone git commit -qm 'notes: other committer'
expect 1 'HIT author' 'wrong committer' anon

# denylist missing or empty: hard fail; --no-denylist runs the patterns loudly
git checkout -q clean
mv docs/private/denylist.txt "$T/dl.txt"
expect 2 'denylist .* missing' 'missing denylist fails' anon
expect nz 'FAIL anon check' 'gate fails without denylist' gate
expect 0 'WITHOUT denylist' 'no-denylist flag on a clean range' anon --no-denylist
git checkout -q patterns
expect 1 'HIT session-id' 'no-denylist still runs the patterns' anon --no-denylist
git checkout -q clean
printf '# comments only\n\n' >docs/private/denylist.txt
expect 2 'no terms' 'empty denylist fails' anon
expect 0 "denylist $T/dl.txt" 'ANON_DENYLIST override' env ANON_DENYLIST="$T/dl.txt" \
  bash scripts/anon_check.sh
mv "$T/dl.txt" docs/private/denylist.txt

# --all scans history that the default range skips
branch pushed
commit notes.txt 'zorblax once' 'notes: old'
git update-ref refs/remotes/origin/pushed HEAD
expect 0 'anon_check: 0 commits' 'default range skips pushed commits' anon
expect 1 'HIT denylist' '--all scans all history' anon --all
git update-ref -d refs/remotes/origin/pushed

# version rule
branch version
commit plugins/research-kit/README.md 'readme' 'plugin: readme'
expect 1 'FAIL plugins/research-kit changed .* version 0.1.0' 'plugin change without bump' gate
commit plugins/research-kit/.claude-plugin/plugin.json \
  '{"name": "research-kit", "version": "0.1.1"}' 'plugin: 0.1.1'
expect 0 'release_check: PASS' 'plugin change with bump' gate

# stamp rule (version bumped, so only the stamp rule can fail)
branch stamp
put plugins/research-kit/.claude-plugin/plugin.json '{"name": "research-kit", "version": "0.1.1"}'
put "$TPL/AGENTS.md" '<!-- research-kit: 2026-01-01a -->'
printf 'rule one, changed\n' >>"$TPL/AGENTS.md"
git add -A
git commit -qm 'template: rule one'
expect 1 'FAIL .*AGENTS.md changed but its stamp' 'template change without stamp' gate
put "$TPL/AGENTS.md" '<!-- research-kit: 2026-01-02a -->'
printf 'rule one, changed\n' >>"$TPL/AGENTS.md"
git add -A
git commit -qm 'template: stamp'
expect 0 'release_check: PASS' 'template change with stamp' gate

# a linked worktree finds the main checkout's denylist
git worktree add -q "$T/wt" -b wt origin/main
(
  cd "$T/wt"
  commit notes.txt 'plain' 'notes: wt'
  expect 0 "denylist $R/docs/private/denylist.txt" 'worktree finds the denylist' anon
  commit notes.txt 'quuxington' 'notes: wt term'
  expect 1 'HIT denylist' 'worktree catches a term' anon
  exit "$failed"
) || failed=$((failed + $?))

# pre-push hook: real pushes to a bare remote
git init -q --bare "$T/remote.git"
git remote add origin "$T/remote.git"
git push -q origin main
git config core.hooksPath scripts/githooks
expect nz 'push refused' 'hook refuses a new branch with a term' git push -q origin content
expect 0 - 'hook passes a clean new branch' git push -q origin clean
git checkout -q clean
commit notes.txt 'quuxington' 'notes: term on pushed branch'
expect nz 'push refused' 'hook refuses an update with a term' git push -q origin clean
git reset -q --hard HEAD~1
commit notes.txt 'still plain' 'notes: plain update'
expect 0 - 'hook passes a clean update' git push -q origin clean
expect 0 - 'hook skips a branch deletion' git push -q origin :clean
git tag -a v8 -m 'release for quuxington' origin/main
expect nz 'push refused' 'hook refuses an annotated tag on a pushed commit' git push -q origin v8
git tag zorblax-1 origin/main
expect nz 'push refused' 'hook refuses a tag name on a pushed commit' git push -q origin zorblax-1
git tag -a v7 -m 'release' origin/main
expect 0 - 'hook passes a clean tag on a pushed commit' git push -q origin v7
git tag -d v8 zorblax-1 >/dev/null

# the gate never acts on the repo named by inherited GIT_* variables: a suite
# that runs git in its own temp dir must not commit into the pushing repo
branch probe
commit scripts/test-probe.sh 'cd "$(mktemp -d)" && git init -q && git commit -q --allow-empty -m junk && git checkout -q -b junk' 'scripts: probe suite'
snap() { git rev-parse HEAD; git for-each-ref --format='%(refname) %(objectname)' refs/heads refs/tags; git status --porcelain; }
before="$(snap)"
expect 0 'suite ok scripts/test-probe.sh' 'gate with GIT_DIR, GIT_WORK_TREE, GIT_INDEX_FILE set' \
  env GIT_DIR="$R/.git" GIT_WORK_TREE="$R" GIT_INDEX_FILE="$R/.git/index" bash scripts/release_check.sh
[ "$(snap)" = "$before" ] || { failed=$((failed + 1)); echo "FAIL: gate changed the repo it was run on"; }
# the same through a real push from a linked worktree (git sets GIT_DIR there)
git -C "$T/wt" checkout -q -b probe-wt probe
before="$(cd "$T/wt" && snap)"
expect 0 - 'push from a linked worktree runs the suites safely' git -C "$T/wt" push -q origin probe-wt
[ "$(cd "$T/wt" && snap)" = "$before" ] || { failed=$((failed + 1)); echo "FAIL: push from a worktree changed the repo"; }

echo "test-release-check: $passed passed, $failed failed"
[ "$failed" -eq 0 ]
