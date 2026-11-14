#!/usr/bin/env bash
# Release gate over the commits about to be published. Stops at the first
# failure with a one-line reason. Run from any worktree of this repo.
#   bash scripts/release_check.sh [REV-LIST-ARGS]
# Default range: commits on HEAD that are on no origin/* ref. The pre-push
# hook (scripts/githooks/pre-push) passes exactly the pushed range.
# Checks, in order:
#   1. version: a plugin changed under plugins/<name>/ has a plugin.json
#      version that differs from origin/main's
#   2. stamp: a changed template file with a stamp line has a new stamp
#   3. anon check (scripts/anon_check.sh) over the range, allowlist read
#      from the tip being checked, not from the working tree
#   4. every test-*.sh / test_*.py under plugins/ and scripts/, run on an
#      export of the range's tip commit (not the working tree)
#   5. claude plugin validate for the marketplace and each plugin (skipped
#      with a warning when the claude binary is absent)
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
fail() { echo "release_check: FAIL $*" >&2; exit 1; }
[ $# -gt 0 ] || set -- HEAD --not --remotes=origin
cd "$(git rev-parse --show-toplevel)"
git rev-parse -q --verify 'origin/main^{commit}' >/dev/null ||
  fail "no origin/main ref to compare with (git fetch origin)"
count="$(git rev-list --count "$@")" || fail "bad range: $*"
if [ "$count" -eq 0 ]; then
  echo "release_check: no commits in range ($*), nothing to check"
  exit 0
fi
tip="$(git rev-list --topo-order --max-count=1 "$@")"
echo "release_check: $count commits ($*), tip ${tip:0:8}"

# 1. version rule
version() { # <rev:path> -> version, or nothing if the file is absent there
  git show "$1" 2>/dev/null |
    python3 -I -c 'import json, sys; print(json.load(sys.stdin)["version"])' \
      2>/dev/null || true
}
plugins="$(git log --format= --name-only --diff-merges=first-parent "$@" |
  sed -n 's#^plugins/\([^/]*\)/.*#\1#p' | sort -u)"
for p in $plugins; do
  pj="plugins/$p/.claude-plugin/plugin.json"
  new="$(version "$tip:$pj")"
  old="$(version "origin/main:$pj")"
  [ -n "$new" ] && [ -n "$old" ] || continue # plugin added or removed
  [ "$new" != "$old" ] ||
    fail "plugins/$p changed but $pj still has version $new, as on origin/main"
done
echo "release_check: version ok"

# 2. stamp rule (stamp line format: STAMP_RE in rk.py)
tpl=plugins/research-kit/skills/research-kit/template
stamp() { # <rev:path> -> stamp line, or nothing
  git show "$1" 2>/dev/null |
    grep -m1 -oE '<!-- (research-kit|research-kit-kind [^ ]+): [^ ]+ -->' || true
}
for base in $(git rev-list --boundary "$@" | sed -n 's/^-//p'); do
  for f in $(git diff --name-only "$base" "$tip" -- "$tpl"); do
    new="$(stamp "$tip:$f")"
    old="$(stamp "$base:$f")"
    [ -n "$new" ] && [ -n "$old" ] || continue # no stamp line, or file added
    [ "$new" != "$old" ] || fail "$f changed but its stamp is still $new"
  done
done
echo "release_check: stamps ok"

# 3. anon check
bash "$here/anon_check.sh" --allow-from "$tip" "$@" || fail "anon check (hits above)"

# 4. suites, on an export of the tip
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir "$work/tree"
git archive "$tip" | tar -x -C "$work/tree"
# A hook of a linked worktree gets GIT_DIR etc.; the suites' own git calls
# would then write into the pushing repo. From here on, no inherited repo.
unset $(git rev-parse --local-env-vars)
cd "$work/tree"
tests="$(for d in plugins scripts; do
  [ -d "$d" ] && find "$d" -type f \( -name 'test-*.sh' -o -name 'test_*.py' \) \
    -not -path '*/node_modules/*'
done | sort)"
for t in $tests; do
  case "$t" in
    *.py) run=(python3 -I "$t") ;;
    *) run=(bash "$t") ;;
  esac
  if ! "${run[@]}" >"$work/log" 2>&1 </dev/null; then
    tail -n 20 "$work/log" >&2
    fail "suite $t (last lines above)"
  fi
  echo "release_check: suite ok $t"
done

# 5. plugin validate
if command -v claude >/dev/null 2>&1; then
  for d in . plugins/*/; do
    [ -d "$d/.claude-plugin" ] || continue # marketplace (.) and each plugin
    claude plugin validate "$d" >"$work/log" 2>&1 || {
      tail -n 20 "$work/log" >&2
      fail "claude plugin validate $d"
    }
    echo "release_check: validate ok $d"
  done
else
  echo "release_check: WARNING claude binary not found, plugin validate SKIPPED" >&2
fi
echo "release_check: PASS"
