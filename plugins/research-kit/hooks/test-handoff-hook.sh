#!/bin/bash
# Self-check for handoff-hook.sh: ledger lines at session start and around a compaction.
# has / lacks <label> <needle> <text>. Temp dirs via mktemp -d, left in place.
# Prints FAIL lines, exits 1 on any.
HOOKS="$(cd "$(dirname "$0")" && pwd)"
H="$HOOKS/handoff-hook.sh"
export CLAUDE_PLUGIN_ROOT="$(cd "$HOOKS/.." && pwd)"
RK="$CLAUDE_PLUGIN_ROOT/skills/research-kit/scripts/rk.py"
fail=0
# "bash" below means the interpreter running this suite: /bin/bash <suite> tests the hook under 3.2
bash() { "$BASH" "$@"; }
has() { case "$3" in *"$2"*) ;; *) echo "FAIL $1 lacks: $2"; fail=1;; esac; }
lacks() { case "$3" in *"$2"*) echo "FAIL $1 has: $2"; fail=1;; esac; }
last() { [ "$(printf '%s\n' "$3" | tail -n 1)" = "$2" ] || { echo "FAIL $1 last line is not: $2"; fail=1; }; }

# no ledger: unchanged behaviour, start prints nothing
export CLAUDE_PROJECT_DIR="$(mktemp -d)"
out="$(bash "$H" start)"; [ -z "$out" ] || { echo "FAIL start without ledger printed: $out"; fail=1; }
out="$(bash "$H" pre)"; lacks pre "Decisions and done work" "$out"; last pre "4. End with the single next step." "$out"
out="$(bash "$H" post)"; has post "[surviving-compaction]" "$out"; lacks post "Ledger tool" "$out"

# ledger with T-1 open
R="$(mktemp -d)"
mkdir -p "$R/pm" && : > "$R/pm/ledger.jsonl"
python3 -I "$RK" add task "first job" --owner sr1 --note n --repo "$R" >/dev/null
export CLAUDE_PROJECT_DIR="$R"
out="$(bash "$H" start)"; has start "Ledger tool" "$out"; has start "$RK" "$out"; has start "T-1" "$out"
# the function line: pasteable as given, real path, a function (a $RK variable does not word-split in zsh)
fl="$(printf '%s\n' "$out" | grep -m1 '^rk() ')"
[ "$fl" = 'rk() { python3 -I "'"$RK"'" "$@"; }' ] || { echo "FAIL fn-line is not exactly the function: $fl"; fail=1; }
lacks fn-line "#" "$fl"   # nothing after "}": a trailing comment would swallow a joined command
[ -f "$RK" ] || { echo "FAIL fn-line path does not exist: $RK"; fail=1; }
[ "$(printf '%s\n' "$out" | grep -c '^rk() ')" = 1 ] || { echo "FAIL start: not exactly one function line"; fail=1; }
# the line joined to a command with ";" runs the command, in bash and zsh (the form the text tells)
for sh in bash zsh; do
  command -v $sh >/dev/null 2>&1 || { echo "FAIL $sh not installed"; fail=1; continue; }
  got="$(cd "$R" && $sh -c "$fl; rk list" 2>&1)"; rc=$?
  has "fn-line;$sh" "T-1" "$got"; [ "$rc" = 0 ] || { echo "FAIL fn-line; rk list in $sh: rc $rc"; fail=1; }
  got="$(cd "$R" && $sh -c "$fl; rk show T-99" 2>&1)"; rc=$?
  [ "$rc" != 0 ] || { echo "FAIL fn-line; rk show T-99 in $sh: rc 0 (command swallowed?)"; fail=1; }
done
# the explanation is its own comment line: no persistence claim, says how to join, zsh pitfall named
ex="$(printf '%s\n' "$out" | grep -m1 '^# \[research-kit\] Ledger tool')"
has expl 'a Bash call keeps no shell state' "$ex"; has expl 'joined to the command by ";"' "$ex"
has expl 'rk() {...}; rk list' "$ex"; has expl 'zsh does not word-split' "$ex"
lacks expl "defines" "$ex"
# real rk.py: doctor --start prints its kit line (never "usage:"); jq on PATH: no notice
has start-doctor "kit " "$out"; lacks start-doctor "usage:" "$out"
command -v jq >/dev/null 2>&1 && lacks start-jq "jq not found" "$out"
out="$(bash "$H" post)"; has post "[surviving-compaction]" "$out"; has post "Decisions and done work" "$out"
has post "T-1" "$out"; has post "Ledger tool" "$out"
out="$(bash "$H" pre)"; has pre "Decisions and done work" "$out"; last pre "5. End with the single next step." "$out"
# P8: pre writes pm/handoffs/compact/auto-<UTC stamp>.md in a repo with a ledger; post names it
A="$R/pm/handoffs/compact"
# (the pre run above already wrote it: stdout holds no path, only the instructions)
lacks pre-auto "auto-" "$out"
n="$(ls "$A" 2>/dev/null | grep -c '^auto-[0-9]\{8\}T[0-9]\{6\}Z\.md$')"
[ "$n" -ge 1 ] || { echo "FAIL pre wrote no auto-<stamp>.md in $A"; fail=1; }
af="$(for x in "$A"/auto-*.md; do echo "$x"; done | tail -n 1)"
body="$(cat "$af" 2>/dev/null)"
has auto-file "## rk list" "$body"; has auto-file "T-1" "$body"
has auto-file "## rk recent -n 30" "$body"; has auto-file "## git status --short" "$body"
out="$(bash "$H" post)"; has post-auto "$af" "$out"; has post-auto "PreCompact hook" "$out"
# newest by name wins, an older one is not named
A3="$(mktemp -d)"; mkdir -p "$A3/pm" "$A3/pm/handoffs/compact"; : > "$A3/pm/ledger.jsonl"
: > "$A3/pm/handoffs/compact/auto-20200101T000000Z.md"; : > "$A3/pm/handoffs/compact/auto-20300101T000000Z.md"
out="$(CLAUDE_PROJECT_DIR="$A3" bash "$H" post)"
has post-newest "auto-20300101T000000Z.md" "$out"; lacks post-newest "auto-2020" "$out"
# stale (older than an hour): not named, as the compact's pre did not write it
touch -t 202001010000 "$A3/pm/handoffs/compact/auto-20300101T000000Z.md" "$A3/pm/handoffs/compact/auto-20200101T000000Z.md"
out="$(CLAUDE_PROJECT_DIR="$A3" bash "$H" post)"; lacks post-stale "auto-" "$out"; lacks post-stale "State file written" "$out"
has post-stale "[surviving-compaction]" "$out"
touch "$A3/pm/handoffs/compact/auto-20300101T000000Z.md"
out="$(CLAUDE_PROJECT_DIR="$A3" bash "$H" post)"; has post-fresh "stamp 20300101T000000Z.md" "$out"
# the file is named next to the hand-kept handoff
printf '# h\n' > "$A3/pm/handoffs/compact/handoff-2026-01-01.md"
out="$(CLAUDE_PROJECT_DIR="$A3" bash "$H" post)"
has post-both "handoff-2026-01-01.md" "$out"; has post-both "auto-20300101T000000Z.md" "$out"
# Simulate BSD stat: a failed GNU probe may still write to stdout.
bsd="$(mktemp -d)"
cat > "$bsd/stat" <<'EOF'
#!/bin/sh
case "$1:$2" in
  -f:%m) echo 1700000000 ;;
  *) echo 'partial output from failed probe'; exit 1 ;;
esac
EOF
chmod +x "$bsd/stat"
out="$(CLAUDE_PROJECT_DIR="$A3" PATH="$bsd:$PATH" bash "$H" post 2>&1)"
has bsd-both "handoff-2026-01-01.md" "$out"; has bsd-both "auto-20300101T000000Z.md" "$out"
lacks bsd-both "integer expression" "$out"
# git status goes into the file in a git repo
G="$(mktemp -d)"; mkdir -p "$G/pm"; : > "$G/pm/ledger.jsonl"; git init -q "$G" 2>/dev/null
CLAUDE_PROJECT_DIR="$G" bash "$H" pre >/dev/null
body="$(cat "$G"/pm/handoffs/compact/auto-*.md 2>/dev/null)"; has auto-git "?? pm/" "$body"
# no ledger: no file, no folder
E="$(mktemp -d)"; mkdir -p "$E/pm"
CLAUDE_PROJECT_DIR="$E" bash "$H" pre >/dev/null
[ -e "$E/pm/handoffs" ] && { echo "FAIL pre without ledger created pm/handoffs"; fail=1; }
out="$(CLAUDE_PROJECT_DIR="$E" bash "$H" post)"; lacks post-no-ledger "State file written" "$out"
# a write that fails: silent, exit 0, the usual instructions still printed
F="$(mktemp -d)"; mkdir -p "$F/pm"; : > "$F/pm/ledger.jsonl"; : > "$F/pm/handoffs"   # a file where the folder must go
out="$(CLAUDE_PROJECT_DIR="$F" bash "$H" pre 2>&1)"; rc=$?
[ "$rc" = 0 ] || { echo "FAIL pre with blocked folder exit $rc"; fail=1; }
has pre-blocked "Instructions for this summary" "$out"; lacks pre-blocked "mkdir" "$out"; lacks pre-blocked "File exists" "$out"
# rk.py missing: file still written (with the error text inside), hook output unchanged, exit 0
out="$(CLAUDE_PLUGIN_ROOT="$(mktemp -d)" CLAUDE_PROJECT_DIR="$A3" bash "$H" pre 2>&1)"; rc=$?
[ "$rc" = 0 ] || { echo "FAIL pre without rk.py exit $rc"; fail=1; }; lacks pre-no-rk "Traceback" "$out"; lacks pre-no-rk "No such file" "$out"
# session in a git worktree: the open list and recent entries come from the main ledger
M="$(mktemp -d)"; W="$(mktemp -d)"
mkdir -p "$M/pm" "$M/.git/worktrees/wt" "$W/pm"
: > "$M/pm/ledger.jsonl"; : > "$W/pm/ledger.jsonl"
printf 'gitdir: %s/.git/worktrees/wt\n' "$M" > "$W/.git"
python3 -I "$RK" add task "fresh in main" --note n --repo "$M" >/dev/null
out="$(CLAUDE_PROJECT_DIR="$W" bash "$H" start)"; has wt-start "fresh in main" "$out"
out="$(CLAUDE_PROJECT_DIR="$W" bash "$H" post)"
has wt-post "fresh in main" "$out"; has wt-post "Decisions and done work" "$out"
# Local-only worktree: pm is absent here, the .git file names .git/worktrees/: the main ledger still counts.
W2="$(mktemp -d)"; cp "$W/.git" "$W2/.git"
out="$(CLAUDE_PROJECT_DIR="$W2" bash "$H" start)"; has wt-local "fresh in main" "$out"
# A submodule's .git file does not name .git/worktrees/: no ledger lines, even though rk could answer
S2="$(mktemp -d)"; printf 'gitdir: %s/.git/modules/sub\n' "$M" > "$S2/.git"
out="$(CLAUDE_PROJECT_DIR="$S2" bash "$H" start)"; lacks submodule-local "fresh in main" "$out"
# stub plugin: doctor --start prints a stale-stamp report (a stub with a fixed output, so the cut at 3 lines is testable)
P="$(mktemp -d)"; mkdir -p "$P/skills/research-kit/scripts"
cat > "$P/skills/research-kit/scripts/rk.py" <<'EOF'
import sys
a = sys.argv[1:]
if a[:2] == ["doctor", "--start"]:
    print("kit 0.9.0 (stub)")
    print("AGENTS.md 2026-11-01a, kit 2026-11-13e: run /rk-sync")
    print("pm/kinds/paper.md 2026-11-01a, kit 2026-11-13b: run /rk-sync")
    print("fourth line")
elif a[:1] == ["list"]:
    print("open 0 (stub list)")
EOF
out="$(CLAUDE_PLUGIN_ROOT="$P" bash "$H" start)"
has stub-doctor "kit 0.9.0 (stub)" "$out"; has stub-doctor "run /rk-sync" "$out"
has stub-doctor "pm/kinds/paper.md 2026-11-01a" "$out"
lacks stub-doctor "fourth line" "$out"; has stub-list "open 0 (stub list)" "$out"
[ "$(printf '%s\n' "$out" | wc -l | tr -d ' ')" -le 6 ] || { echo "FAIL stub block longer than function + explanation + 3 doctor + list"; fail=1; }
out="$(CLAUDE_PLUGIN_ROOT="$P" bash "$H" post)"; has stub-post "run /rk-sync" "$out"; has stub-post "[surviving-compaction]" "$out"
# doctor --start with 4 kit lines then 2 "spec: " lines: the cut keeps 3 kit lines, every spec: line passes
cat > "$P/skills/research-kit/scripts/rk.py" <<'EOF'
import sys
a = sys.argv[1:]
if a[:2] == ["doctor", "--start"]:
    print("kit 0.9.0 (stub)")
    print("kit line two")
    print("kit line three")
    print("kit line four")
    print("spec: S-4 03-software-local-only-mode has no user decision labelled 03/SPEC (AGENTS.md 3.3)")
    print("spec: S-5 04-paper-x has no user decision labelled 04/SPEC (AGENTS.md 3.3)")
elif a[:1] == ["list"]:
    print("open 0 (stub list)")
EOF
out="$(CLAUDE_PLUGIN_ROOT="$P" bash "$H" start)"
has stub-spec "kit line three" "$out"; lacks stub-spec "kit line four" "$out"
has stub-spec "spec: S-4 03-software-local-only-mode" "$out"; has stub-spec "spec: S-5 04-paper-x" "$out"
[ "$(printf '%s\n' "$out" | grep -c '^spec: ')" = 2 ] || { echo "FAIL stub-spec: not exactly 2 spec: lines"; fail=1; }
# doctor fails (exit 2, text on stdout): nothing from it, the rest intact, exit 0
cat > "$P/skills/research-kit/scripts/rk.py" <<'EOF'
import sys
a = sys.argv[1:]
if a[:1] == ["doctor"]:
    print("usage: rk.py ...  (error: invalid choice: 'doctor')"); sys.exit(2)
if a[:1] == ["list"]:
    print("open 0 (stub list)")
EOF
out="$(CLAUDE_PLUGIN_ROOT="$P" bash "$H" start)"; rc=$?
lacks doctor-fails "invalid choice" "$out"; has doctor-fails "open 0 (stub list)" "$out"; has doctor-fails "rk() " "$out"
[ "$rc" = 0 ] || { echo "FAIL doctor-fails exit $rc"; fail=1; }
# rk.py missing: session start still succeeds, function line kept
NOPLUG="$(mktemp -d)"
out="$(CLAUDE_PLUGIN_ROOT="$NOPLUG" bash "$H" start)"; rc=$?
[ "$rc" = 0 ] || { echo "FAIL missing rk.py exit $rc"; fail=1; }; has no-rk "rk() " "$out"
out="$(CLAUDE_PLUGIN_ROOT="$NOPLUG" bash "$H" post)"; rc=$?
[ "$rc" = 0 ] || { echo "FAIL missing rk.py post exit $rc"; fail=1; }; has no-rk-post "[surviving-compaction]" "$out"
# PATH without jq (D-131: the hooks no longer use it): no notice, and both guards still decide
NJ="$(mktemp -d)"
for t in python3 dirname find stat date head tail cat grep wc tr sed awk; do ln -s "$(command -v $t)" "$NJ/$t" 2>/dev/null; done
out="$(PATH="$NJ" /bin/bash "$H" start)"; rc=$?
lacks no-jq "jq not found" "$out"; has no-jq "T-1" "$out"
[ "$rc" = 0 ] || { echo "FAIL no-jq exit $rc"; fail=1; }
out="$(PATH="$NJ" /bin/bash "$H" post)"; lacks no-jq-post "jq not found" "$out"; has no-jq-post "T-1" "$out"
g="$(PATH="$NJ" /bin/bash "$HOOKS/guard-delete.sh" <<<'{"tool_input":{"command":"git clean -fd"}}')"
has guard-delete-no-jq '"permissionDecision": "deny"' "$g"
g="$(PATH="$NJ" /bin/bash "$HOOKS/ledger-guard.sh" <<<'{"tool_name":"Write","tool_input":{"file_path":"x/pm/ledger.jsonl"}}')"
has ledger-guard-no-jq '"permissionDecision": "deny"' "$g"
# the UserPromptSubmit hook (was an inline jq | grep in hooks.json)
g="$(PATH="$NJ" /bin/bash "$HOOKS/prompt-hook.sh" <<<'{"prompt":"ok, Get ready for the compact"}')"
has prompt-no-jq "research-kit:surviving-compaction" "$g"
g="$(PATH="$NJ" /bin/bash "$HOOKS/prompt-hook.sh" <<<'{"prompt":"compact the table"}')"
[ -z "$g" ] || { echo "FAIL prompt hook fired on: compact the table"; fail=1; }
long="$(printf '%0300d' 0)"
g="$(PATH="$NJ" /bin/bash "$HOOKS/prompt-hook.sh" <<<"{\"prompt\":\"get ready for compact $long\"}")"
[ -z "$g" ] || { echo "FAIL prompt hook fired on a prompt of 300+ characters"; fail=1; }
# no ledger: no function line
out="$(CLAUDE_PROJECT_DIR="$(mktemp -d)" PATH="$NJ" /bin/bash "$H" start)"; [ -z "$out" ] || { echo "FAIL no ledger, no jq printed: $out"; fail=1; }
out="$(CLAUDE_PROJECT_DIR="$(mktemp -d)" PATH="$NJ" /bin/bash "$H" post)"; lacks no-ledger-post "jq not found" "$out"; lacks no-ledger-post "rk() " "$out"
# no Python at all: never a silent guard. start, post and pre tell the session the tools and
# guards are OFF (exit 0); the guards print it as a systemMessage (exit 0: on Windows any
# other code than 0 or 2 can block the tool call).
NP="$(mktemp -d)"   # an empty PATH dir: the wrappers need only bash builtins to get there
for m in start post pre; do
  out="$(PATH="$NP" /bin/bash "$H" $m)"; rc=$?
  has "no-python-$m" "No Python 3.9+ found" "$out"; [ "$rc" = 0 ] || { echo "FAIL no-python $m exit $rc"; fail=1; }
done
for g in guard-delete ledger-guard; do
  out="$(PATH="$NP" /bin/bash "$HOOKS/$g.sh" <<<'{"tool_name":"Write","tool_input":{"command":"rm f","file_path":"x/pm/ledger.jsonl"}}' 2>/dev/null)"; rc=$?
  has "no-python-$g" '{"systemMessage": "[research-kit] No Python 3.9+ found' "$out"
  has "no-python-$g" "the delete guard, the ledger guard" "$out"; [ "$rc" = 0 ] || { echo "FAIL no-python $g exit $rc"; fail=1; }
  printf '%s' "$out" | jq -e .systemMessage >/dev/null || { echo "FAIL no-python $g not JSON: $out"; fail=1; }
done
# the finder on Windows (simulated: OSTYPE=msys): python3 is the Microsoft Store alias stub
# (install hint on stderr, nothing on stdout), there is no python, py -3 works: py -3 is
# used, in the rk() line and the deny texts too, and the hooks run through it
FB="$(mktemp -d)"; FS="$(mktemp -d)"; REALPY="$(command -v python3)"
printf '#!/bin/sh\necho "Python was not found; run without arguments to install from the Microsoft Store" >&2\nexit 9009\n' > "$FB/python3"
# py acts as a native Windows Python for the probe: print() ends lines with \r\n in a pipe
cat > "$FB/py" <<EOF
#!/bin/sh
[ "\$1" = -3 ] && shift
case "\$*" in
  *version_info*) "$REALPY" "\$@" | "$REALPY" -c 'import sys; sys.stdout.buffer.write(sys.stdin.buffer.read().replace(b"\\n", b"\\r\\n"))' ;;
  *) exec "$REALPY" "\$@" ;;
esac
EOF
cp "$FB/python3" "$FS/python3"; chmod +x "$FB/python3" "$FB/py" "$FS/python3"
out="$(OSTYPE=msys PATH="$FB" /bin/bash "$H" start)"
fl="$(printf '%s\n' "$out" | grep -m1 '^rk() ')"
[ "$fl" = 'rk() { py -3 -I "'"$RK"'" "$@"; }' ] || { echo "FAIL finder: rk() line is not py -3: $fl"; fail=1; }
has finder-list "T-1" "$out"; lacks finder-stub "Microsoft Store" "$out"
g="$(OSTYPE=msys PATH="$FB" /bin/bash "$HOOKS/guard-delete.sh" <<<'{"tool_input":{"command":"rm f"}}')"
has finder-guard '"permissionDecision": "deny"' "$g"
g="$(OSTYPE=msys PATH="$FB" /bin/bash "$HOOKS/ledger-guard.sh" <<<'{"tool_name":"Edit","tool_input":{"file_path":"C:\\r\\pm\\ledger.jsonl"}}')"
has finder-ledger-text 'py -3 -I' "$g"
# only the stub on PATH: no Python, said so
out="$(OSTYPE=msys PATH="$FS" /bin/bash "$H" start)"; has finder-stub-only "No Python 3.9+ found" "$out"
# not on Windows: python3 on PATH is taken without a probe (no extra process per hook)
printf '#!/bin/sh\necho x >> "%s/probes"\nexec "%s" "$@"\n' "$FS" "$REALPY" > "$FS/python3"
out="$(OSTYPE=darwin23 PATH="$FS" /bin/bash -c '. "$1/find-python.sh"; rk_find_python; echo "$RK_PY_CMD"' _ "$HOOKS")"
[ "$out" = python3 ] && [ ! -e "$FS/probes" ] || { echo "FAIL finder off Windows: $out, probes: $(cat "$FS/probes" 2>/dev/null)"; fail=1; }
bash "$H" bogus >/dev/null 2>&1 && { echo "FAIL unknown mode exits 0"; fail=1; }

[ "$fail" = 0 ] && echo "handoff hook tests ok"
exit "$fail"
