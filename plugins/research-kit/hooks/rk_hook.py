"""research-kit hooks: the one implementation of their rules (D-131).

    rk_hook.py guard-delete     PreToolUse Bash|PowerShell: deny deleting commands
    rk_hook.py ledger-guard     PreToolUse Agent|SendMessage|Edit|Write|MultiEdit
    rk_hook.py handoff MODE     PreCompact / SessionStart: pre | post | start
    rk_hook.py prompt           UserPromptSubmit: a compact was announced

Run by the thin .sh wrappers next to this file, which find a Python 3 (find-python.sh)
and pass its command words in RK_PY_CMD for the lines agents paste (rk() and the deny
texts). Hook input is JSON on stdin; unparsable input means no opinion (exit 0).
stdlib only, json instead of jq, PureWindowsPath for paths. Python 3.9 (macOS system).
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
import time
from pathlib import Path, PureWindowsPath

WINDOWS: bool = sys.platform == "win32"  # the hook's Python runs natively there
# The bash version ran these through grep -E (linear time). Python's re backtracks, so
# each pattern below is the same language written without ambiguous repetition: a
# hook that runs past its timeout gives no decision, and the command runs.
# command position: start of a line, after ; & | ( { ` $( , optionally behind if/elif/
# while/until/coproc/!, then a wrapper word (and anything up to a blank) or VAR=x words
# (the grep form `(wrapper\s+([^;&|]*\s)?)?(VAR=x\s+)*` matches the same strings, but
# backtracks quadratically on `env A=b A=b ...`)
POS: str = (
    r"(^|[;&|(`{]|\$\()\s*((if|elif|while|until|coproc|!)\s+)*"
    r"((do|then|else|xargs|sudo|env|nohup|time|timeout|nice|ionice|stdbuf|command"
    r"|builtin|exec)\s([^;&|]*\s)?|([A-Za-z_][A-Za-z0-9_]*=\S*\s+)*)"
)  # wrapper\s(...\s)? = grep's wrapper\s+(...\s)?, without splitting a run of blanks
END: str = r"(\s|$|[;&|)])"
# rm / git rm|clean|worktree remove / find -delete|-exec rm at command position. git
# options: -C/-c takes the next word unless it starts with "-" (then both are options);
# grep's `-[Cc]\s+\S+|-\S+` matches the same, but backtracks exponentially on -C -C ...
# The directory before rm stops at a separator: a match with one inside also matches
# from that separator on (POS starts there), and `\S*/` rescanned the rest of a word
# from every separator in it (quadratic on ```` or ;;;;).
DIR: str = r"([^\s;&|(`{]*/)?"
SHDEL: tuple[str, ...] = (
    POS + r"\\?" + DIR + r"(rm|rmdir|unlink)" + END,
    POS + r"git(\s+(-[Cc]\s+[^-\s]\S*|-\S+))*\s+(rm|clean|worktree\s+remove)" + END,
    POS + r"find\s[^;&|]*\s-(delete|exec(dir)?\s+" + DIR + r"(rm|rmdir|unlink))" + END,
)
# PowerShell (case-insensitive): Remove-Item and its aliases at a command position
# (also behind & or .), cmd /c del|rd, and .NET Delete() calls
PS_DEL: tuple[str, ...] = (
    r"(?i)(^|[;|&({=,]|\$\(|@\()\s*([&.]\s*)?(microsoft\.powershell\.management\\)?"
    r"(remove-item|ri|rm|rmdir|rd|del|erase)(\s|$|[;|&()}])",
    r"(?i)(::|\.)delete\s*\(",
)
# pairs (both somewhere on one line; two searches, no `.*` between them): cmd /c|/k|/r
# (after other /x switches) with del|rd, % / ForEach-Object calling a Delete member,
# and PowerShell with an encoded command (it cannot be read: deny it)
PS_PAIRS: tuple[tuple[str, str], ...] = (
    (
        r"(?i)(^|[^\w.-])cmd(\.exe)?(\s+//?\w)*\s+//?[ckr]\b",
        r"(?i)\b(del|erase|rd|rmdir)\b",
    ),
    (
        r"(?i)(^|[;|&({]|\$\()\s*(%|foreach-object|foreach)\s",
        r"(?i)(^|[^\w.-])delete\b",
    ),
    (r"(?i)(^|[^\w.-])(powershell|pwsh)(\.exe)?\s", r"(?i)\s-(e|ec|enc\w*)(\s|$)"),
)
# PowerShell run by another word (powershell / pwsh with -Command or a positional
# command, iex) around a delete word
PS_WRAP: str = (
    r"(?i)(^|[^\w.-])(powershell(\.exe)?|pwsh(\.exe)?|iex|invoke-expression)\b"
)
PS_WORD: str = r"(?i)(^|[^\w.-])(remove-item|ri|rm|rmdir|rd|del|erase)(\s|$|[;|&)}'\"])"
# ponytail: a line over LONG characters, or every line of a command over TOTAL, is
# judged by delete words alone (it errs on the side of denying): some patterns still
# backtrack cubically on crafted lines (`(env find ` x 999: 22 s). A linear matcher
# would lift that, if long commands ever matter.
LONG: int = 2000
TOTAL: int = 8000
LONG_DEL: str = (
    r"(^|[^A-Za-z0-9_.-])(rm|rmdir|unlink|clean|remove|-delete|-exec)(\s|$|[;&|)'\"])"
)
LONG_SHELL: str = r"(^|[^A-Za-z0-9_.-])(bash|sh|zsh|eval)(\s|$)"
SEP: str = ";&|(){}"
CAP: int = 2000  # above it no quote relaxation is tried (deny as before)
SAFE: str = (
    r"(grep|egrep|fgrep|echo|printf|cat|head|tail|wc|ls|cd|jq"
    r"|git(\s+(-C\s+\S+|--no-pager))*\s+(commit|log|show|diff))(\s.*)?"
)
READ: str = (
    r"(grep|egrep|fgrep|wc|head|tail|cat|ls|cd"
    r"|git(\s+(-C\s+\S+|--no-pager))*\s+(diff|log|show))(\s.*)?"
    r"|sed\s+-n\s+[\"']?[0-9][0-9,$p_]*[\"']?(\s+[^-\s]\S*)*\s*"
)
TO_WASTE: str = (
    "Deleting is off. Subagent/teammate: put one line per item at column 0 of your "
    "report: TO-WASTE: <path> -- <reason>; the lead moves it."
)
COMPACT_RE: re.Pattern[str] = re.compile(
    r"get ready for (a |the )?compact|ready for compaction"
    r"|prepare (for )?(a |the )?compact|i.?m stopping here",
    re.I,
)
HANDOFF_RE: re.Pattern[str] = re.compile(r"handoff-[0-9]{4}-[0-9]{2}-[0-9]{2}\.md")
PRUNE: frozenset[str] = frozenset(
    {".git", "node_modules", ".build", ".worktrees", ".venv", "WASTE"}
)


# ---- shared -------------------------------------------------------------------


def _plugin() -> str:
    return os.environ.get("CLAUDE_PLUGIN_ROOT") or str(
        Path(__file__).resolve().parent.parent
    )


def _rk() -> str:
    return f"{_plugin()}/skills/research-kit/scripts/rk.py"


def _py_cmd() -> str:
    """The Python command words agents paste (find-python.sh decides them)."""
    return os.environ.get("RK_PY_CMD") or "python3"


def _deny(reason: str) -> int:
    out: dict[str, object] = {"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}
    print(json.dumps(out))
    return 0


def _stdin_json() -> dict[str, object] | None:
    try:
        data: object = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _field(data: dict[str, object], *keys: str) -> str:
    """data[k1][k2]... when it is a string, else "" (jq's `// empty` / `strings`)."""
    v: object = data
    for k in keys:
        v = v.get(k) if isinstance(v, dict) else None
    return v if isinstance(v, str) else ""


def _run(args: list[str], cwd: str, stdin: str = "", merge: bool = True,
         env: dict[str, str] | None = None) -> tuple[int, str]:
    """(exit code, stdout[+stderr]) of a command; (127, message) if it cannot start."""
    import subprocess  # here: the guard-delete path never needs it (one start per call)

    try:
        r: subprocess.CompletedProcess[bytes] = subprocess.run(
            args, cwd=cwd, input=stdin.encode("utf-8"), env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT if merge else subprocess.DEVNULL,
        )
    except OSError as e:
        return 127, f"{args[0]}: {e.strerror}\n"
    return r.returncode, r.stdout.decode("utf-8", "replace")


def _rk_run(args: list[str], cwd: str, merge: bool = True) -> tuple[int, str]:
    return _run([sys.executable, "-I", _rk(), *args], cwd, merge=merge)


def _worktree_ledger(root: str) -> bool:
    """A linked worktree (a .git file naming .git/worktrees/, not a submodule) whose
    rk finds the main checkout's ledger (pm/ local-only: none of its own)."""
    git: Path = Path(root) / ".git"
    try:
        text: str = git.read_text(encoding="utf-8", errors="replace")
    except OSError:  # a .git folder, or none
        return False
    if not re.search(r"^gitdir: .*[/\\]worktrees[/\\]", text, re.M):
        return False
    return _rk_run(["list", "--limit", "1"], root)[0] == 0


# ---- guard-delete -------------------------------------------------------------


def _hit(pattern: str, text: str, long: str = "") -> bool:
    """grep -Eq: a match on some line of `text`. `long`: the coarse pattern used for
    a line over LONG characters, or for all lines when `text` is over TOTAL, instead
    (POS backtracks on lines packed with separators and wrapper words). re.ASCII:
    \\s is grep's C-locale [[:space:]]; bash does not split words at U+00A0 etc."""
    coarse: bool = bool(long) and len(text) > TOTAL
    return any(
        re.search(long if long and (coarse or len(ln) > LONG) else pattern, ln, re.A)
        for ln in text.split("\n")
    )


def _shdel(text: str) -> bool:
    return any(_hit(p, text, LONG_DEL) for p in SHDEL)


def _blank_quoted(cmd: str) -> str:
    """`cmd` with ; & | ( ) { } inside '...' and "..." replaced by _ (bash quoting)."""
    out: list[str] = []
    q: str = ""
    i: int = 0
    while i < len(cmd):
        c: str = cmd[i]
        if not q:
            if c == "\\":
                out.append(c + cmd[i + 1:i + 2])
                i += 1
            else:
                q = c if c in "\"'" else ""
                out.append(c)
        elif c == q:
            q = ""
            out.append(c)
        elif q == '"' and c == "\\":
            out.append("__")
            i += 1
        else:
            out.append("_" if c in SEP else c)
        i += 1
    return "".join(out)


def _plain_line_of(cmd: str, pattern: str) -> str | None:
    """`cmd` with quoted separators blanked when it is one plain line of at most CAP
    characters (no newline, heredoc, $( ), backtick, $'', ${ }) and every command in it
    matches `pattern` in full; else None."""
    if len(cmd) > CAP or any(t in cmd for t in ("\n", "<<", "$(", "`", "$'", "${")):
        return None
    s: str = _blank_quoted(cmd).replace(">&", ">_").replace("<&", "<_")
    s = s.replace("&>", "_>")
    parts: list[str] = [
        m.group(0) for m in re.finditer(r"([;&|(){}]|^)[^;&|(){}]*", s) if m.group(0)
    ]
    if any(
        not re.fullmatch(r"[;&|(){}]?\s*(" + pattern + r")?", p, re.A) for p in parts
    ):
        return None
    return s


def _quoted_text_only(cmd: str) -> bool:
    """P9: the delete word only sits inside a quoted argument of text/read commands."""
    s: str | None = _plain_line_of(cmd, SAFE)
    return s is not None and not _shdel(s)


def _waste_read_only(cmd: str) -> bool:
    """P9: naming waste.sh in one plain line of read commands, with no redirection
    other than 2>/dev/null, >/dev/null, 2>&1, >&2."""
    s: str | None = _plain_line_of(cmd, READ)
    if s is None or "--output" in s:
        return False
    return all(
        re.fullmatch(r">(_[12]|/dev/null)", r) for r in re.findall(r">\S*", s, re.A)
    )


def deletes(cmd: str, powershell: bool = False) -> bool:
    """The heuristic on the command text; it errs on the side of denying. The
    PowerShell rules and the py launcher apply to the PowerShell tool and on Windows
    only: a Bash command on macOS or Linux is judged as by the bash version."""
    windows: bool = powershell or WINDOWS
    if powershell:  # PowerShell quoting differs (backtick, no \\ escape): no P9
        found: bool = _shdel(cmd)
    else:
        found = _shdel(cmd) and not _quoted_text_only(cmd)
        # a ; inside a quoted find argument hid -delete from the find rule
        if not found and len(cmd) <= CAP and _hit(POS + r"find\s", cmd, LONG_DEL):
            found = _shdel(_blank_quoted(cmd))
    if windows and (
        any(_hit(p, cmd) for p in PS_DEL)
        or any(_hit(a, cmd) and _hit(b, cmd) for a, b in PS_PAIRS)
        or (_hit(PS_WRAP, cmd) and _hit(PS_WORD, cmd))
    ):
        found = True
    py: str = r"(python[0-9.]*|py)" if windows else r"python[0-9.]*"
    if _hit(r"(^|[^A-Za-z0-9_.-])" + py + r"(\s|$)", cmd) and _hit(
        r"rmtree|os\.remove|os\.unlink|os\.rmdir|\.unlink\(", cmd
    ):
        found = True
    # bash -c / sh -c / eval wrapping a delete word
    shell: str = POS + r"(bash|sh|zsh)\s+(-[a-z]+\s+)*-c\s|" + POS + r"eval\s"
    if _hit(shell, cmd, LONG_SHELL) and _hit(
        r"(^|[^A-Za-z0-9_.-])(rm|rmdir|unlink)(\s|$|[;&|)'\"])", cmd
    ):
        found = True
    return found


def guard_delete() -> int:
    data: dict[str, object] | None = _stdin_json()
    if data is None:
        return 0
    cmd: str = _field(data, "tool_input", "command")
    if not cmd:
        return 0
    powershell: bool = _field(data, "tool_name") == "PowerShell"
    if deletes(cmd, powershell):
        return _deny(
            f"{TO_WASTE} Lead: run the research-kit waste helper (bash {_plugin()}"
            '/skills/waste/waste.sh <who> "<reason>" <path>); it asks the user. '
            "Temp/scratchpad files: leave them. If the delete word is only text (a "
            "report, a doc, a commit message), write that file with the Write tool "
            "instead of a heredoc. Never rephrase the delete to get around this."
        )
    # Subagents never run the waste helper: the lead does, so its prompt reaches the
    # user. (Naming it in a plain line of read commands is not running it.)
    if (
        _field(data, "agent_id")
        and _hit(r"(^|[^A-Za-z0-9_.-])waste\.sh([^A-Za-z0-9_.-]|$)", cmd)
        and not _waste_read_only(cmd)
    ):
        return _deny(f"{TO_WASTE} Never rephrase the delete to get around this.")
    return 0


# ---- ledger-guard -------------------------------------------------------------


def guarded_file(file_path: str) -> str | None:
    """"ledger" for pm/ledger.jsonl or pm/STATUS.md, "record" for
    pm/stages/<one folder>/LEDGER.md, else None. Any case, / or \\, doubled
    separators and . components (PureWindowsPath reads both separators)."""
    parts: list[str] = [p.lower() for p in PureWindowsPath(file_path).parts]
    if parts[-2:] in (["pm", "ledger.jsonl"], ["pm", "status.md"]):
        return "ledger"
    if len(parts) >= 4 and parts[-4:-2] == ["pm", "stages"]:
        return "record" if parts[-1] == "ledger.md" else None
    return None


def ledger_guard() -> int:
    data: dict[str, object] | None = _stdin_json()
    if data is None:
        return 0
    tool: str = _field(data, "tool_name")
    root: str = os.environ.get("CLAUDE_PROJECT_DIR") or _field(data, "cwd")
    if not tool or not root:
        return 0
    ledger: bool = (Path(root) / "pm" / "ledger.jsonl").is_file()
    if not ledger and not _worktree_ledger(root):
        return 0
    rk: str = f'{_py_cmd()} -I "{_rk()}"'
    if tool in ("Edit", "Write", "MultiEdit"):
        what: str | None = guarded_file(_field(data, "tool_input", "file_path"))
        if what == "ledger":
            return _deny(
                "pm/ledger.jsonl and pm/STATUS.md are written only by the ledger tool: "
                f"{rk} <add|start|close|drop|shelve|reopen|set|supersede|reref|"
                "stage-close|import> ... STATUS.md is regenerated after every write "
                "(render rebuilds it). A broken ledger line: run doctor "
                f"({rk} doctor), it names the line; the fix is by hand outside Claude, "
                "so ask the user."
            )
        if what == "record":
            return _deny(
                "pm/stages/<stage>/LEDGER.md is generated and written once by "
                f"stage-close ({rk} stage-close <S-n> ...), never by hand: an edit "
                "would make it differ from the ledger it records. A correction is a "
                "new ledger entry in the current stage (rk add, rk set), not a change "
                "to this file."
            )
        return 0
    if tool not in ("Agent", "SendMessage") or _field(data, "agent_id"):
        return 0  # only the lead hands out work
    text: str = _field(data, "tool_input", "prompt" if tool == "Agent" else "message")
    if "DELIVERABLE:" not in text:  # cheap pre-filter; brief-check applies the rule
        return 0
    env: dict[str, str] = dict(os.environ)
    if not env.get("CLAUDE_CODE_SESSION_ID") and _field(data, "session_id"):
        env["CLAUDE_CODE_SESSION_ID"] = _field(data, "session_id")  # sid on its event
    rc, out = _run(
        [sys.executable, "-I", _rk(), "brief-check", "--who", "hook"], root,
        stdin=text.rstrip("\n") + "\n", env=env,
    )
    if rc == 0:
        return 0
    out = out.rstrip("\n") or f"ledger brief check failed (rk.py brief-check exit {rc})"
    return _deny(out[:1000])


# ---- handoff ------------------------------------------------------------------


def _ledger_block(root: str) -> None:
    rk: str = _rk()
    # The function line ends at "}" (a trailing comment would swallow a joined command).
    print(f'rk() {{ {_py_cmd()} -I "{rk}" "$@"; }}')
    print(
        '# [research-kit] Ledger tool: a Bash call keeps no shell state; start each '
        'Bash call that uses "rk" with the line above joined to the command by ";" '
        "(rk() {...}; rk list); zsh does not word-split a $RK variable; run from the "
        "repo root, teammates add --who <name>"
    )
    # doctor --start: its first 3 lines not starting with "spec: ", then every "spec: "
    # line; only on exit 0 (an older rk.py or any failure prints nothing)
    rc, d = _rk_run(["doctor", "--start"], root, merge=False)
    d = d.rstrip("\n")
    if rc == 0 and d:
        lines: list[str] = d.split("\n")
        print("\n".join(
            [ln for ln in lines if not ln.startswith("spec: ")][:3]
            + [ln for ln in lines if ln.startswith("spec: ")]
        ))
    print(_rk_run(["list"], root)[1], end="")  # no --repo: a worktree reads the main


def _auto_state(root: str) -> None:
    """pm/handoffs/compact/auto-<UTC stamp>.md at PreCompact; any failure is silent."""
    try:
        d: Path = Path(root) / "pm" / "handoffs" / "compact"
        d.mkdir(parents=True, exist_ok=True)
        now: time.struct_time = time.gmtime()
        parts: list[str] = [
            f"# Auto state {time.strftime('%Y-%m-%d %H:%M:%S', now)} UTC (written by "
            "the PreCompact hook, not hand-kept)\n",
            "## rk list\n", _rk_run(["list"], root)[1],
            "## rk recent -n 30\n", _rk_run(["recent", "-n", "30"], root)[1],
            "## git status --short\n", _run(["git", "-C", root, "status", "--short"],
                                            root)[1],
        ]
        f: Path = d / f"auto-{time.strftime('%Y%m%dT%H%M%SZ', now)}.md"
        with f.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write("".join(parts))
    except OSError:
        pass


def _newest_auto(root: str) -> str:
    """The newest auto-*.md by name, only if written within the hour (by this compact's
    pre); else ""."""
    d: Path = Path(root) / "pm" / "handoffs" / "compact"
    try:
        names: list[str] = sorted(n for n in os.listdir(d) if
                                  n.startswith("auto-") and n.endswith(".md"))
        last: Path = d / names[-1]
        fresh: bool = last.is_file() and time.time() - last.stat().st_mtime < 3600
    except (OSError, IndexError):
        return ""
    return str(last) if fresh else ""


def _newest_handoff(root: str) -> tuple[str, int]:
    """(path, mtime) of the newest handoff-YYYY-MM-DD.md within 4 levels of `root`,
    outside .git, node_modules, .build, .worktrees, .venv, WASTE and pm/waste."""
    newest: str = ""
    newest_m: int = 0
    waste: str = os.path.join(root, "pm", "waste")
    for d, dirs, files in os.walk(root):
        depth: int = 0 if d == root else os.path.relpath(d, root).count(os.sep) + 1
        dirs[:] = [] if depth >= 3 else [
            x for x in dirs if x not in PRUNE and os.path.join(d, x) != waste
        ]
        for name in files:
            p: str = os.path.join(d, name)
            if not HANDOFF_RE.fullmatch(name) or os.path.islink(p):
                continue
            try:
                m: int = int(os.stat(p).st_mtime)
            except OSError:
                continue
            if not newest or m > newest_m:
                newest, newest_m = p, m
    return newest, newest_m


def handoff(mode: str) -> int:
    if mode not in ("pre", "post", "start"):
        print("usage: handoff-hook.sh pre|post|start", file=sys.stderr)
        return 1
    root: str = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    ledger: bool = (Path(root) / "pm" / "ledger.jsonl").is_file() or _worktree_ledger(
        root
    )
    if mode == "start":
        if ledger:
            _ledger_block(root)
        return 0
    newest, newest_m = _newest_handoff(root)
    when: str = time.strftime("%Y-%m-%d %H:%M", time.localtime(newest_m))
    if mode == "pre":
        if ledger:
            _auto_state(root)
        print("Instructions for this summary (surviving-compaction hook):")
        if newest:
            print(f'1. First line of the summary: "Handoff file: {newest} (modified '
                  f'{when}). Read it before any other step."')
        else:
            print('1. First line of the summary: "No handoff file exists for this '
                  'session; this summary is the only record."')
        print("2. Quote the user's decisions and safety rules verbatim.")
        print("3. Label every statement about a running agent, a running command or "
              'uncommitted work "unverified after compact".')
        if ledger:
            print('4. Keep a section "Decisions and done work": every decision the '
                  "user made and every work package reported done in this "
                  "conversation, one line each, with its ledger id when a receipt was "
                  'shown, else "not logged".')
        print(f"{5 if ledger else 4}. End with the single next step.")
        return 0
    if newest:
        print("[surviving-compaction] Context was just compacted. Before answering or "
              "taking any next step, invoke the research-kit:surviving-compaction "
              "skill with the Skill tool and run its Resume steps. Handoff file: "
              f"{newest} (modified {when}).")
    else:
        print("[surviving-compaction] Context was just compacted and no handoff file "
              f"(handoff-YYYY-MM-DD.md) was found under {root}. Treat statements in "
              "the summary about running agents, running commands and uncommitted "
              "work as unverified; check them before acting.")
    if ledger:
        a: str = _newest_auto(root)
        if a:
            print("[surviving-compaction] State file written by this compact's "
                  f"PreCompact hook (stamp {os.path.basename(a)[5:]}; ledger lists and "
                  f"git status as of the compact, machine-made): {a}. Read it next to "
                  "the handoff file.")
        _ledger_block(root)
        print('Compare the summary\'s "Decisions and done work" section with these '
              "newest entries; log what is missing (rk add decision ... / rk close "
              "...) and show the user each receipt:")
        print(_rk_run(["recent", "-n", "15"], root)[1], end="")
    return 0


# ---- prompt -------------------------------------------------------------------


def prompt() -> int:
    data: dict[str, object] | None = _stdin_json()
    text: str = _field(data, "prompt") if data is not None else ""
    if text and len(text) < 300 and COMPACT_RE.search(text):
        print("[surviving-compaction] The user announced a compact. Before anything "
              "else, invoke the Skill tool with skill "
              '"research-kit:surviving-compaction" and run its Prepare steps.')
    return 0


def _utf8_stdio() -> None:
    """Claude Code reads hook output as UTF-8; a Windows pipe defaults to the code page
    (cp1252), which cannot print most ledger titles (Python 3.14 and older)."""
    for s in (sys.stdout, sys.stderr):
        if isinstance(s, io.TextIOWrapper):
            s.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str]) -> int:
    _utf8_stdio()
    if argv[:1] == ["guard-delete"]:
        return guard_delete()
    if argv[:1] == ["ledger-guard"]:
        return ledger_guard()
    if argv[:1] == ["handoff"]:
        return handoff(argv[1] if len(argv) > 1 else "")
    if argv[:1] == ["prompt"]:
        return prompt()
    print("usage: rk_hook.py guard-delete|ledger-guard|handoff MODE|prompt",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
