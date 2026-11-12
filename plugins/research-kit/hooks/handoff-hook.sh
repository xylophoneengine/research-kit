#!/bin/bash
# Compaction hooks for the research-kit plugin's surviving-compaction skill.
#   handoff-hook.sh pre    PreCompact: stdout becomes instructions for the compaction summary
#   handoff-hook.sh post   SessionStart, matcher "compact": stdout is added to the model's context
# Both look for the newest handoff-YYYY-MM-DD.md within 4 levels of the project root.
set -u
mode="${1:-}"
root="${CLAUDE_PROJECT_DIR:-$PWD}"

newest=""
newest_m=0
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
    echo "4. End with the single next step."
    ;;
  post)
    if [ -n "$newest" ]; then
      echo "[surviving-compaction] Context was just compacted. Before answering or taking any next step, invoke the research-kit:surviving-compaction skill with the Skill tool and run its Resume steps. Handoff file: $newest (modified $when)."
    else
      echo "[surviving-compaction] Context was just compacted and no handoff file (handoff-YYYY-MM-DD.md) was found under $root. Treat statements in the summary about running agents, running commands and uncommitted work as unverified; check them before acting."
    fi
    ;;
  *)
    echo "usage: handoff-hook.sh pre|post" >&2
    exit 1
    ;;
esac
exit 0
