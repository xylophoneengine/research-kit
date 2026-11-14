#!/usr/bin/env bash
# Release gate over the commits about to be published. Stops at the first
# failure with a one-line reason. Run from any worktree of this repo.
#   bash scripts/release_check.sh [REV-LIST-ARGS]
# Default range: what a push of this branch to its upstream would send
# (@{upstream}..HEAD; origin/main..HEAD when the branch has no upstream).
# The pre-push hook (scripts/githooks/pre-push) passes exactly the pushed range.
# Checks, in order:
#   1. version: a plugin changed under plugins/<name>/ has a plugin.json
#      version that differs from origin/main's
#   2. stamp: a changed template file with a stamp line has a new stamp
#   3. anon check (scripts/anon_check.sh) over the range, allowlist read
#      from the tip being checked, not from the working tree
#   4. every test-*.sh / test_*.py under plugins/ and scripts/, run on an
#      export of the range's tip commit (not the working tree); run a second
#      time with /bin/bash and /usr/bin/python3 in a bare environment when
#      those differ from the bash and python3 on PATH
#   5. claude plugin validate for the marketplace and each plugin (skipped
#      with a warning when the claude binary is absent)
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
fail() { echo "release_check: FAIL $*" >&2; exit 1; }
cd "$(git rev-parse --show-toplevel)"
if [ $# -eq 0 ]; then
  up="$(git rev-parse -q --symbolic-full-name '@{upstream}' 2>/dev/null)" || up=""
  set -- "${up:-origin/main}..HEAD"
fi
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
# Second pass with the system tools (macOS: bash 3.2, Python 3.9). Why: a
# push from a GUI client runs the hook with them, and they found bugs that
# every run with the tools on PATH had passed. Tests may point these elsewhere.
sys_bash="${RK_SYSTEM_BASH:-/bin/bash}"
sys_py="${RK_SYSTEM_PYTHON:-/usr/bin/python3}"
passes="path"
if [ ! -x "$sys_bash" ] || [ ! -x "$sys_py" ]; then
  echo "release_check: no $sys_bash or $sys_py, system pass SKIPPED"
elif [ "$(command -v bash)" -ef "$sys_bash" ] &&
  [ "$(command -v python3)" -ef "$sys_py" ]; then
  echo "release_check: bash and python3 on PATH are the system ones, one pass"
else
  passes="path system"
fi
for pass in $passes; do
  for t in $tests; do
    case "$pass:$t" in
      path:*.py) run=(python3 -I "$t") ;;
      path:*) run=(bash "$t") ;;
      *.py) run=(env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin HOME="$HOME" "$sys_py" -I "$t") ;;
      *) run=(env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin HOME="$HOME" "$sys_bash" "$t") ;;
    esac
    tag=""
    [ "$pass" = path ] || tag=" ($pass)"
    if ! "${run[@]}" >"$work/log" 2>&1 </dev/null; then
      tail -n 20 "$work/log" >&2
      fail "suite $t$tag (last lines above)"
    fi
    echo "release_check: suite ok $t$tag"
  done
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
