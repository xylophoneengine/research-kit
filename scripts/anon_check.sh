#!/usr/bin/env bash
# Anonymity gate over what git would publish: added lines, added file names,
# messages, author and committer of the commits in a range. Details and
# options: scripts/anon_check.py (or anon_check.sh --help).
set -euo pipefail
exec python3 -I "$(cd "$(dirname "$0")" && pwd)/anon_check.py" "$@"
