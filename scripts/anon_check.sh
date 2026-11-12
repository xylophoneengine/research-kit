#!/usr/bin/env bash
# Anonymity gate: scan the published tree for denylisted terms, emails, /Users/.
# Denylist: docs/private/denylist.txt (one term per line, case-insensitive,
# '#' comments and blank lines ignored). Exit 1 on any hit.
set -u
root="$(cd "$(dirname "$0")/.." && pwd)"
deny="$root/docs/private/denylist.txt"
if [ ! -f "$deny" ]; then
  echo "skip: no denylist"
  exit 0
fi
terms="$(mktemp)"
trap 'rm -f "$terms"' EXIT
grep -vE '^[[:space:]]*(#|$)' "$deny" > "$terms"
cd "$root" || exit 1
status=0
scan() { # label, grep args...
  local label="$1"; shift
  local out
  # skip .git, docs/private (only that one) and this script
  out="$(find . -path ./.git -prune -o -path ./docs/private -prune -o \
    -type f ! -path ./scripts/anon_check.sh -print0 |
    xargs -0 grep -nI "$@" /dev/null 2>/dev/null)"
  if [ -n "$out" ]; then
    echo "HIT ($label):"
    echo "$out" | cut -c1-200
    status=1
  fi
}
if [ -s "$terms" ]; then scan denylist -iF -f "$terms"; fi
scan email -E '[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}'
scan path -F '/Users/'
[ "$status" -eq 0 ] && echo "anon_check: clean"
exit "$status"
