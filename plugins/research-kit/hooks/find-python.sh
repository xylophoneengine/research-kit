# Sourced by the research-kit hook wrappers (bash 3.2 and up). rk_find_python sets
# RK_PY (an array: the command words) and exports RK_PY_CMD (the same words as one
# string, for the lines agents paste) to the first working Python 3 of: python3,
# python, py -3. On Windows (Git Bash / MSYS / Cygwin) each candidate is probed, which
# skips the Microsoft Store alias stub: it prints its install hint to stderr and nothing
# to stdout. Elsewhere a python3 on PATH is taken unprobed (one process less per hook).
# Returns 1 when none works.
rk_find_python() {
  local c out
  case "${OSTYPE:-}" in
    msys* | cygwin* | win*) ;;
    *)
      if command -v python3 >/dev/null 2>&1; then
        RK_PY=(python3); RK_PY_CMD=python3; export RK_PY_CMD; return 0
      fi
      ;;
  esac
  for c in python3 python "py -3"; do
    command -v "${c%% *}" >/dev/null 2>&1 || continue
    # shellcheck disable=SC2086  # word splitting of "py -3" is intended
    # end="": a native Windows Python ends print() with \r\n, and $(...) strips only \n
    out="$($c -I -c 'import sys; print(sys.version_info >= (3, 9), end="")' 2>/dev/null)"
    [ "$out" = True ] || continue
    # shellcheck disable=SC2206
    RK_PY=($c); RK_PY_CMD="$c"; export RK_PY_CMD; return 0
  done
  return 1
}

RK_NO_PYTHON="[research-kit] No Python 3.9+ found (tried python3, python, py -3): the ledger tool, the delete guard, the ledger guard, the brief check and the compaction hooks are OFF. Install Python 3 and restart the session."

# For the PreToolUse guards: exit 0 with a systemMessage (shown to the user, never
# blocks); an exit code other than 0 or 2 can block the tool call on Windows.
rk_no_python_guard() {
  printf '{"systemMessage": "%s"}\n' "$RK_NO_PYTHON"
  exit 0
}
