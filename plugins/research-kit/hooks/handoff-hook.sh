#!/bin/bash
# Compaction hooks for the research-kit plugin's surviving-compaction skill.
#   handoff-hook.sh pre    PreCompact: stdout becomes instructions for the compaction summary
#   handoff-hook.sh post   SessionStart, matcher "compact": stdout is added to the model's context
#   handoff-hook.sh start  SessionStart, matcher "startup|resume|clear": ledger lines only
# pre/post look for the newest handoff-YYYY-MM-DD.md within 4 levels of the project root.
# In a repo with pm/ledger.jsonl all three also print research-kit ledger lines
# (tool path, open list; after a compact the newest entries to compare with the summary).
set -u
mode="${1:-}"
root="${CLAUDE_PROJECT_DIR:-$PWD}"
plugin="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)}"
rk="$plugin/skills/research-kit/scripts/rk.py"
ledger=""
[ -f "$root/pm/ledger.jsonl" ] && ledger=1

ledger_block() {
  [ -n "$ledger" ] || return 0
  echo "[research-kit] Ledger tool (AGENTS.md calls it rk): python3 -I \"$rk\" <command>, run from the repo root; teammates add --who <name>."
  (cd "$root" && python3 -I "$rk" list 2>&1)  # no --repo: a worktree reads the main ledger
}

newest=""
newest_m=0
if [ "$mode" = pre ] || [ "$mode" = post ]; then
  while IFS= read -r -d '' f; do
    m="$(stat -f %m "$f" 2>/dev/null || stat -c %Y "$f" 2>/dev/null || echo 0)"
    if [ "$m" -gt "$newest_m" ]; then
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
