#!/usr/bin/env bash
# waste.sh -- move files into <repo>/pm/waste/ (or <repo>/WASTE/ when the repo has no pm/)
# instead of deleting them, and log it.
#
#   waste.sh <who> "<reason>" <path> [<path> ...]
#
# Repo root = git toplevel of each path itself (not of $PWD); a path outside any git repo
# is refused. Each path is moved to
# <waste dir>/<UTC stamp>/<path relative to root> (structure kept, nothing overwritten)
# and one row per path is appended to <waste dir>/LEDGER.md.
# Waste dir = pm/waste if <root>/pm exists, else WASTE (legacy repos), per path root.
#
# Safety (paths are resolved with realpath / pwd -P and compared with -ef, so case and
# symlinked parents cannot dodge a check; a symlink argument is moved as the link itself):
# refuses the repo root, nested repo roots, anything that is or is inside a .git, .claude,
# .claude-plugin, .env or .env.* (not .env.example/.sample/.template; names compared
# case-insensitively), a directory holding any of those, any .gitignore, pm/ itself, the
# waste dirs and ledger, this script's own plugin dir (or a dir holding it), a symlinked
# pm / pm/waste / WASTE / LEDGER.md or symlinks inside the destination, a waste dir that
# git does not ignore, and who/reason/path text with control characters ('|' too in
# who/reason). GIT_* env vars are dropped so git sees the path's own repo.
set -euo pipefail
unset CDPATH
for v in $(compgen -e); do case "$v" in GIT_*) unset "$v";; esac; done

if [ "$#" -lt 3 ]; then
  echo "usage: waste.sh <who> \"<reason>\" <path> [<path> ...]" >&2
  exit 2
fi
who="$1"; reason="$2"; shift 2
case "$who$reason" in
  *[[:cntrl:]]*|*"|"*)
    echo "waste: who/reason must not contain '|' or control characters (newline, tab, ...)" >&2
    exit 2;;
esac

plugin="$(cd "$(dirname -- "$(realpath -- "${BASH_SOURCE[0]}")")/../.." && pwd -P)"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"

lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }

# protected <name>: print why a file/dir with this name is never wasted (empty: fine).
protected() {
  case "$(lower "$1")" in
    .git) echo ".git (repo history)";;
    .claude) echo ".claude (agent settings)";;
    .claude-plugin) echo ".claude-plugin (plugin manifest)";;
    .gitignore) echo ".gitignore (keeps the waste dir ignored)";;
    .env.example|.env.sample|.env.template) ;;
    .env|.env.*) echo ".env / .env.* (secrets)";;
  esac
}

# under <a> <b>: true if a is b or inside b (a and its parents compared with -ef).
under() {
  local c="$1"
  while :; do
    if [ "$c" -ef "$2" ]; then return 0; fi
    if [ "$c" = / ]; then return 1; fi
    c="$(dirname -- "$c")"
  done
}

status=0
p=""
fail() { echo "waste: $1: $p" >&2; status=1; }

for p in "$@"; do
  case "$p" in *[[:cntrl:]]*) fail "path contains control characters, refusing"; continue;; esac
  if [ ! -e "$p" ] && [ ! -L "$p" ]; then fail "no such path"; continue; fi
  base="$(basename -- "$p")"
  if [ "$base" = . ] || [ "$base" = .. ] || [ "$base" = / ]; then
    abs="$(cd -- "$p" && pwd -P)"
  elif [ -L "$p" ]; then
    abs="$(cd -- "$(dirname -- "$p")" && pwd -P)/$base"  # the link itself, never followed
  else
    abs="$(realpath -- "$p")"  # canonical, incl. the on-disk case of the last component
  fi

  root="$(git -C "$(dirname -- "$abs")" rev-parse --show-toplevel 2>/dev/null)" || root=""
  if [ -z "$root" ]; then fail "not inside a git repo, refusing"; continue; fi
  root="$(cd -- "$root" && pwd -P)"
  case "$abs" in
    "$root"/*) ;;
    *) fail "refusing the repo root or a path outside it ($root)"; continue;;
  esac
  rel="${abs#"$root"/}"
  case "$rel" in *[[:cntrl:]]*) fail "path contains control characters, refusing"; continue;; esac
  if [ "$abs" -ef "$root" ]; then fail "refusing the repo root"; continue; fi

  # Every component from the path up to (not incl.) the root.
  why=""
  c="$abs"
  while [ "$c" != "$root" ]; do
    up="$(dirname -- "$c")"
    why="$(protected "$(basename -- "$c")")"
    if [ -z "$why" ] && [ "$c" -ef "$up/.git" ]; then why=".git (repo history)"; fi
    if [ -z "$why" ] && [ "$c" -ef "$up/.claude" ]; then why=".claude (agent settings)"; fi
    if [ -z "$why" ] && { [ "$c" -ef "$root/pm/waste" ] || [ "$c" -ef "$root/WASTE" ]; }; then
      why="the waste dir or its contents"
    fi
    if [ -n "$why" ]; then break; fi
    c="$up"
  done
  if [ -n "$why" ]; then fail "refusing $why"; continue; fi
  if [ "$abs" -ef "$root/pm" ]; then fail "refusing pm/ itself (holds the waste dir)"; continue; fi
  if [ -d "$abs" ] && [ ! -L "$abs" ]; then
    sub="$(git -C "$abs" rev-parse --show-toplevel 2>/dev/null)" || sub=""
    if [ -n "$sub" ] && [ "$sub" -ef "$abs" ]; then fail "refusing a nested repo root"; continue; fi
    # Same names inside a wasted directory (find never follows symlinks here).
    hit="$(find "$abs" -mindepth 1 \( -iname .git -o -iname .claude -o -iname .claude-plugin \
      -o -iname .env -o \( -iname '.env.*' ! -iname .env.example ! -iname .env.sample \
      ! -iname .env.template \) \) -print -quit 2>/dev/null)" || hit=""
    if [ -n "$hit" ]; then
      fail "refusing a directory that holds $(protected "$(basename -- "$hit")") at ${hit#"$abs"/}"
      continue
    fi
  fi
  if under "$abs" "$plugin" || under "$plugin" "$abs"; then
    fail "refusing the waste helper's own plugin dir ($plugin)"; continue
  fi

  if [ -L "$root/pm" ] || [ -L "$root/pm/waste" ] || [ -L "$root/WASTE" ]; then
    fail "pm, pm/waste or WASTE is a symlink, refusing"; continue
  fi
  if [ -d "$root/pm" ]; then wname="pm/waste"; else wname="WASTE"; fi
  waste="$root/$wname"
  ledger="$waste/LEDGER.md"
  if [ -L "$ledger" ] || { [ -e "$ledger" ] && [ ! -f "$ledger" ]; }; then
    fail "$wname/LEDGER.md is a symlink or not a regular file, refusing"; continue
  fi
  if ! git -C "$root" check-ignore -q "$wname/$stamp/x"; then
    fail "refusing: $wname/ is not gitignored, so wasted files could be committed. Fix: run rk-init (or rk-sync --write) in this repo, or add the line '$wname/' to $root/.gitignore"
    continue
  fi
  dest="$waste/$stamp/$rel"
  if [ -e "$dest" ] || [ -L "$dest" ]; then fail "destination exists, skipping ($dest)"; continue; fi
  c="$(dirname -- "$dest")"
  while [ "$c" != "$root" ]; do
    if [ -L "$c" ]; then why="symlink in the destination path ($c)"; break; fi
    c="$(dirname -- "$c")"
  done
  if [ -n "$why" ]; then fail "refusing: $why"; continue; fi

  mkdir -p -- "$(dirname -- "$dest")"
  if [ ! -e "$ledger" ]; then
    (set -C; printf '# WASTE ledger\n\nFiles moved here instead of deleted. Restore with `mv <waste dir>/<to> <from>`.\n\n| when (UTC) | who | from | to | reason |\n|---|---|---|---|---|\n' > "$ledger")
  fi
  mv -n -- "$abs" "$dest"
  if [ -e "$abs" ] || [ -L "$abs" ]; then fail "not moved (destination appeared meanwhile)"; continue; fi
  relq="${rel//|/\\|}"
  printf '| %s | %s | %s | %s | %s |\n' "$stamp" "$who" "$relq" "$wname/$stamp/$relq" "$reason" >> "$ledger"
  echo "wasted: $rel -> $wname/$stamp/$rel"
done
exit "$status"
