#!/bin/bash
# Compaction hooks for the research-kit plugin's surviving-compaction skill.
#   handoff-hook.sh pre    PreCompact: stdout becomes instructions for the compaction summary
#   handoff-hook.sh post   SessionStart, matcher "compact": stdout is added to the model's context
#   handoff-hook.sh start  SessionStart, matcher "startup|resume|clear": ledger lines only
# pre/post look for the newest handoff-YYYY-MM-DD.md within 4 levels of the project root.
# In a repo with pm/ledger.jsonl (or a linked worktree whose main checkout has one) all three also print research-kit ledger lines
# (the rk() function line, doctor --start output when rk.py has it, a notice when jq is
# missing, the open list; after a compact the newest entries to compare with the summary).
# In such a repo "pre" also writes pm/handoffs/compact/auto-<UTC stamp>.md (rk list, rk recent -n 30,
# git status --short), machine-made, so a compact nobody announced still leaves a state file;
# "post" names the newest one. A failed write is silent and never changes the exit code.
set -u
mode="${1:-}"
root="${CLAUDE_PROJECT_DIR:-$PWD}"
plugin="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)}"
rk="$plugin/skills/research-kit/scripts/rk.py"
ledger=""
[ -f "$root/pm/ledger.jsonl" ] && ledger=1
# A linked worktree of a repo whose pm/ is local-only has no pm/ledger.jsonl of its own; rk finds the
# main checkout's ledger. Only a linked worktree (.git file naming .git/worktrees/), not a submodule.
if [ -z "$ledger" ] && [ -f "$root/.git" ] && grep -q '^gitdir: .*/worktrees/' "$root/.git" 2>/dev/null; then
  (cd "$root" && python3 -I "$rk" list --limit 1 >/dev/null 2>&1) && ledger=1
fi

ledger_block() {
  [ -n "$ledger" ] || return 0
  # The function line ends at "}" (nothing after it: a trailing comment would swallow a command
  # joined to it); the explanation is a comment line of its own.
  echo "rk() { python3 -I \"$rk\" \"\$@\"; }"
  echo "# [research-kit] Ledger tool: a Bash call keeps no shell state; start each Bash call that uses \"rk\" with the line above joined to the command by \";\" (rk() {...}; rk list); zsh does not word-split a \$RK variable; run from the repo root, teammates add --who <name>"
  # doctor --start: first 3 lines not starting with "spec: " (kit line + up to 2 sync lines), then every "spec: " line
  # in the order given; only on exit 0 (an older rk.py or any failure prints nothing).
  d="$(cd "$root" && python3 -I "$rk" doctor --start 2>/dev/null)" && [ -n "$d" ] && printf '%s\n' "$d" | awk '/^spec: /{s=s $0 "\n"; next} n<3{print; n++} END{printf "%s", s}'
  command -v jq >/dev/null 2>&1 || echo "jq not found: delete guard and brief check are OFF"
  (cd "$root" && python3 -I "$rk" list 2>&1)  # no --repo: a worktree reads the main ledger
}

auto_state() {
  # Machine-made state file at PreCompact. Each part keeps its own error text (2>&1), so a failing
  # rk.py shows in the file, never in the hook output.
  [ -n "$ledger" ] || return 0
  dir="$root/pm/handoffs/compact"
  mkdir -p "$dir" || return 0
  {
    echo "# Auto state $(date -u '+%Y-%m-%d %H:%M:%S') UTC (written by the PreCompact hook, not hand-kept)"
    echo "## rk list"
    (cd "$root" && python3 -I "$rk" list 2>&1)
    echo "## rk recent -n 30"
    (cd "$root" && python3 -I "$rk" recent -n 30 2>&1)
    echo "## git status --short"
    git -C "$root" status --short 2>&1
  } > "$dir/auto-$(date -u '+%Y%m%dT%H%M%SZ').md" 2>/dev/null
  return 0
}

newest_auto() {
  last=""
  for f in "$root"/pm/handoffs/compact/auto-*.md; do [ -f "$f" ] && last="$f"; done
  # only a file this compact's pre wrote (younger than an hour): an old one is not "the state at the compact"
  [ -n "$last" ] && [ -n "$(find "$last" -mmin -60 2>/dev/null)" ] && echo "$last"
  return 0
}

newest=""
newest_m=0
if [ "$mode" = pre ] || [ "$mode" = post ]; then
  while IFS= read -r -d '' f; do
    # GNU stat first: on Linux "stat -f %m" is a valid filesystem query that prints junk and exits 0
    m="$(stat -c %Y "$f" 2>/dev/null)" || m="$(stat -f %m "$f" 2>/dev/null)" || continue
    [[ "$m" =~ ^[0-9]+$ ]] || continue
    if [ -z "$newest" ] || [ "$m" -gt "$newest_m" ]; then
      newest="$f"
      newest_m="$m"
    fi
  done < <(find "$root" -maxdepth 4 \
    \( -name .git -o -name node_modules -o -name .build -o -name .worktrees -o -name .venv -o -name WASTE \) -prune \
    -o -path "$root/pm/waste" -prune \
    -o -type f -name 'handoff-[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].md' -print0 2>/dev/null)
fi

when=""
if [ -n "$newest" ]; then
  when="$(date -r "$newest_m" '+%Y-%m-%d %H:%M' 2>/dev/null || date -d "@$newest_m" '+%Y-%m-%d %H:%M' 2>/dev/null)"
fi

case "$mode" in
  pre)
    auto_state >/dev/null 2>&1 || true
    echo "Instructions for this summary (surviving-compaction hook):"
    if [ -n "$newest" ]; then
      echo "1. First line of the summary: \"Handoff file: $newest (modified $when). Read it before any other step.\""
    else
      echo "1. First line of the summary: \"No handoff file exists for this session; this summary is the only record.\""
    fi
    echo "2. Quote the user's decisions and safety rules verbatim."
    echo "3. Label every statement about a running agent, a running command or uncommitted work \"unverified after compact\"."
    n=4
    if [ -n "$ledger" ]; then
      echo "4. Keep a section \"Decisions and done work\": every decision the user made and every work package reported done in this conversation, one line each, with its ledger id when a receipt was shown, else \"not logged\"."
      n=5
    fi
    echo "$n. End with the single next step."
    ;;
  post)
    if [ -n "$newest" ]; then
      echo "[surviving-compaction] Context was just compacted. Before answering or taking any next step, invoke the research-kit:surviving-compaction skill with the Skill tool and run its Resume steps. Handoff file: $newest (modified $when)."
    else
      echo "[surviving-compaction] Context was just compacted and no handoff file (handoff-YYYY-MM-DD.md) was found under $root. Treat statements in the summary about running agents, running commands and uncommitted work as unverified; check them before acting."
    fi
    if [ -n "$ledger" ]; then
      a="$(newest_auto 2>/dev/null)"
      [ -n "$a" ] && echo "[surviving-compaction] State file written by this compact's PreCompact hook (stamp ${a##*/auto-}; ledger lists and git status as of the compact, machine-made): $a. Read it next to the handoff file."
      ledger_block
      echo "Compare the summary's \"Decisions and done work\" section with these newest entries; log what is missing (rk add decision ... / rk close ...) and show the user each receipt:"
      (cd "$root" && python3 -I "$rk" recent -n 15 2>&1)
    fi
    ;;
  start)
    ledger_block
    ;;
  *)
    echo "usage: handoff-hook.sh pre|post|start" >&2
    exit 1
    ;;
esac
exit 0
