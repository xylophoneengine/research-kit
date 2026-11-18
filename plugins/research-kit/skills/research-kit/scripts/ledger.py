"""Ledger store for research-kit: pm/ledger.jsonl, an append-only event log.

Each line is one event on one entry: {"ts", "who", "ev": "add"|"set", "id", "f"}.
Current state of an entry = its events folded in file order. Nothing is ever
rewritten. Reached through rk.py (store subcommands). Every event also carries
"kit" (plugin version) and, when the session id is known, "sid"; a stage's add
and close carry "rules" (stamps of the repo's rule files). Readers ignore
unknown top-level keys. git: read-only commands in doctor (and in the checks
stage-close borrows from it) only; every other command never runs git.
"""

from __future__ import annotations

import argparse
import difflib
import fcntl
import functools
import itertools
import json
import math
import os
import re
import shutil
import string
import subprocess
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from datetime import date, datetime
from fractions import Fraction
from pathlib import Path

LEDGER_REL: str = "pm/ledger.jsonl"
STATUS_REL: str = "pm/STATUS.md"
STAGE_RECORD: str = "LEDGER.md"  # in the stage folder, written by stage-close
# line 2 of the record of a reopened stage: which close the record is of
RECORD_MARK: str = "<!-- rk:stage-record {sid} close {end} -->"
RECORD_MARK_RE: re.Pattern[str] = re.compile(
    r"^<!-- rk:stage-record \S+ close [0-9]+ -->$", re.M
)
STATUSES: tuple[str, ...] = (
    "open", "running", "staged", "done", "dropped", "superseded", "planned",
    "shelved",
)
OPEN_STATUSES: tuple[str, ...] = ("open", "running", "staged")  # not done
BUILTIN_TYPES: dict[str, str] = {
    "task": "T",
    "decision": "D",
    "deferred": "DF",
    "fetch": "F",
    "debt": "DB",
    "handoff": "H",
    "stage": "S",
}
ID_RE: re.Pattern[str] = re.compile(r"^([A-Z]{1,3})-([1-9][0-9]*)$")
TYPE_DECL_RE: re.Pattern[str] = re.compile(
    r"^<!-- rk:type ([a-z][a-z0-9-]*) ([A-Z]{1,3}) -->$"
)
NAME_RE: re.Pattern[str] = re.compile(r"^[A-Za-z0-9_.-]+$")
LABEL_RE: re.Pattern[str] = re.compile(r"^[A-Za-z0-9_./-]{1,40}$")
TOKEN_SEP_RE: re.Pattern[str] = re.compile(r"[\s,]+")
STAGE_RE: re.Pattern[str] = re.compile(
    r"^[0-9]{2,}[a-z]?-[a-z][a-z0-9]*-[A-Za-z0-9_.-]+$"
)
STAGE_FORM: str = "NN[letter]-<kind>-<topic>, e.g. 03b-paper-scan"
PLAN_RE: re.Pattern[str] = re.compile(r"^[a-z][a-z0-9]*-[A-Za-z0-9_.-]+$")
PLAN_FORM: str = "<kind>-<topic>, e.g. paper-scan"
# the subfolders of template/AGENTS.md 3.2 (pinned by test_stage_dirs_match_agents)
STAGE_DIRS: tuple[str, ...] = ("deliverables", "notes", "code", "chat")
TASK_NOTE: str = (
    "add task needs --note: the deliverable and its scope, one to three lines "
    "(what comes out and where, what is not in it); the title alone does not "
    "explain the task later"
)
COMMANDS: frozenset[str] = frozenset(
    {
        "add", "start", "close", "drop", "shelve", "reopen", "set", "supersede",
        "list", "show", "search", "recent", "render", "stage-close", "brief-check",
        "import", "doctor", "reref", "stage-open", "stage-rename", "staged", "land",
    }
)
BRIEF_RE: re.Pattern[str] = re.compile(r"^[ \t]*DELIVERABLE:", re.M)
TASK_LINE_RE: re.Pattern[str] = re.compile(r"^[ \t]*TASK:(.*)$", re.M)
ANY_ID_RE: re.Pattern[str] = re.compile(r"\b[A-Z]{1,3}-[1-9][0-9]*\b")
HINT: str = (
    "fix the line by hand outside Claude (agents' edits of the ledger are blocked)"
)
STR_FIELDS: tuple[str, ...] = ("type", "title", "status", "owner", "stage", "note")
LIST_FIELDS: tuple[str, ...] = ("links", "refs")
LIST_LIMIT: int = 30
SEARCH_LIMIT: int = 20
LINE_MAX: int = 80
TITLE_MAX: int = 160
LIST_MAX_BYTES: int = 2600  # proposed bound (spec 9), pinned by test_list_size_bound
RECENT_DECISIONS: int = 5
SCRIPT: Path = Path(__file__).resolve()
KIT_JSON: Path = SCRIPT.parents[3] / ".claude-plugin" / "plugin.json"
TEMPLATE_DIR: Path = SCRIPT.parents[1] / "template"
SID_ENV: str = "CLAUDE_CODE_SESSION_ID"
# stamp on line 1 of AGENTS.md and kind files (rk.py sync reads the same)
STAMP_RE: re.Pattern[str] = re.compile(
    r"<!-- (?:research-kit|research-kit-kind \S+|paper-playbook): (\S+) -->"
)
GIT_READ: frozenset[str] = frozenset(  # the only git subcommands the tool runs
    {"status", "diff", "ls-files", "check-ignore", "show", "rev-parse"}
)
WASTE_DIRS: tuple[str, ...] = ("pm/waste/", "WASTE/")
# refs the kit prescribes into a folder its .gitignore block ignores on purpose
# (stage chat archive, AGENTS 3.4 step 6: transcripts stay local): no finding.
# pm/reviews/ (older repos; team reviews now go to pm/logs/team/) stays a finding.
KIT_IGNORED_RE: re.Pattern[str] = re.compile(r"^pm/stages/[^/]+/chat(/|$)")
# git environment that would point git at another repo or index (crit6 m1);
# the list of `git rev-parse --local-env-vars`
GIT_LOCAL_ENV: tuple[str, ...] = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG", "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_COUNT", "GIT_OBJECT_DIRECTORY", "GIT_DIR", "GIT_WORK_TREE",
    "GIT_IMPLICIT_WORK_TREE", "GIT_GRAFT_FILE", "GIT_INDEX_FILE",
    "GIT_NO_REPLACE_OBJECTS", "GIT_REPLACE_REF_BASE", "GIT_PREFIX",
    "GIT_SHALLOW_FILE", "GIT_COMMON_DIR",
)
NON_PATH_RE: re.Pattern[str] = re.compile(r"^(doi|arxiv):", re.I)
GROUP_CAP: int = 20
RUNNING_MAX_H: int = 24


class LedgerError(Exception):
    """User-facing error; str(e) is the whole message."""


@dataclass
class Entry:
    id: str
    type: str
    title: str
    status: str
    owner: str
    stage: str
    note: str
    links: list[str]
    refs: list[str]
    created: str
    updated: str
    extra: dict[str, str | bool]
    lines: list[int]
    started: str = ""  # ts of the newest event that set status running


# ---- reading and folding ----------------------------------------------------


def _bad(n: int, what: str) -> LedgerError:
    return LedgerError(f"{LEDGER_REL}:{n}: {what}; {HINT}")


def _main_checkout(d: Path) -> Path:
    """The main checkout when `d` is a git worktree whose main checkout holds the
    ledger (`.git` file -> <main>/.git/worktrees/<name>, nothing below it); else
    `d`, e.g. for a submodule, also one inside a worktree. Never runs git."""
    git: Path = d / ".git"
    if not git.is_file():
        return d
    try:
        text: str = git.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return d
    m: re.Match[str] | None = re.match(r"gitdir:[ \t]*(\S.*)", text)
    if m is None:
        return d
    gitdir: str = str((d / m.group(1).strip()).resolve())
    head, _, name = gitdir.partition("/.git/worktrees/")
    if not name or "/" in name:  # no /.git/worktrees/, or a path below <name>
        return d
    main: Path = Path(head)
    return main if (main / LEDGER_REL).is_file() else d


def find_repo(start: Path, explicit: bool = False) -> Path:
    """Dir holding pm/ledger.jsonl: `start` itself, or (not explicit) a parent.

    Not explicit: in a git worktree, the main checkout's ledger is the one used,
    also when the worktree has no pm/ (local-only: pm/ is not in git).
    """
    start = start.resolve()
    for d in [start] if explicit else [start, *start.parents]:
        if (d / LEDGER_REL).is_file():
            return d if explicit else _main_checkout(d)
    for d in [] if explicit else [start, *start.parents]:
        if os.path.lexists(d / ".git"):  # the nearest git root: a worktree?
            main: Path = _main_checkout(d)
            if main != d:
                return main
            break
    where: str = "" if explicit else " or above"
    raise LedgerError(
        f"no {LEDGER_REL} in {start}{where}; run rk.py init or pass --repo"
    )


def known_types(repo: Path) -> dict[str, str]:
    """Builtin types plus `<!-- rk:type <name> <PREFIX> -->` lines in pm/kinds/."""
    types: dict[str, str] = dict(BUILTIN_TYPES)
    kinds: Path = repo / "pm" / "kinds"
    paths: list[Path] = sorted(kinds.glob("*.md")) if kinds.is_dir() else []
    for path in paths:
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.startswith("<!-- rk:type"):
                continue
            where: str = f"{path.relative_to(repo)}:{n}"
            m: re.Match[str] | None = TYPE_DECL_RE.match(line.rstrip())
            if m is None:
                raise LedgerError(
                    f"{where}: malformed type declaration {line.strip()!r}; "
                    "want <!-- rk:type <name> <PREFIX> -->"
                )
            name, prefix = m.group(1), m.group(2)
            if name in types or prefix in types.values():
                raise LedgerError(
                    f"{where}: type '{name}' or prefix '{prefix}' already in use"
                )
            types[name] = prefix
    return types


def check_type(name: str, types: dict[str, str]) -> str:
    if name in types:
        return name
    close: list[str] = difflib.get_close_matches(name, list(types), n=1)
    hint: str = f"; did you mean '{close[0]}'?" if close else ""
    raise LedgerError(f"unknown type '{name}'; known: {', '.join(types)}{hint}")


def _parse(raw: bytes) -> list[tuple[int, dict[str, object]]]:
    out: list[tuple[int, dict[str, object]]] = []
    for n, bline in enumerate(raw.split(b"\n"), 1):
        if not bline.strip():
            continue
        try:
            obj: object = json.loads(bline.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise _bad(n, "not a JSON line") from None
        if not isinstance(obj, dict):
            raise _bad(n, "not a JSON object")
        out.append((n, obj))
    return out


def read_events(repo: Path) -> list[tuple[int, dict[str, object]]]:
    return _parse((repo / LEDGER_REL).read_bytes())


def _apply(e: Entry, f: dict[str, object], n: int) -> None:
    for key, val in f.items():
        if key in STR_FIELDS:
            if not isinstance(val, str):
                raise _bad(n, f"field {key} must be a string")
            setattr(e, key, val)
        elif key in LIST_FIELDS:
            if not isinstance(val, list) or not all(isinstance(v, str) for v in val):
                raise _bad(n, f"field {key} must be a list of strings")
            setattr(e, key, [str(v) for v in val])
        elif isinstance(val, (str, bool)):
            e.extra[key] = val
            if key == "date" and isinstance(val, str):
                e.created = val
        else:
            raise _bad(n, f"field {key} must be a string or boolean")


def fold(
    events: list[tuple[int, dict[str, object]]],
    state: dict[str, Entry] | None = None,
) -> dict[str, Entry]:
    """Fold events into a new state, or into `state` in place when given."""
    state = {} if state is None else state
    for n, ev in events:
        ts, who, kind, eid, f = (ev.get(k) for k in ("ts", "who", "ev", "id", "f"))
        if not (
            isinstance(ts, str)
            and isinstance(who, str)
            and isinstance(eid, str)
            and isinstance(f, dict)
        ):
            raise _bad(n, "needs string ts, who, id and an object f")
        if kind not in ("add", "set"):
            raise _bad(n, f"unknown ev {kind!r}")
        if not ID_RE.match(eid):
            raise _bad(n, f"bad id {eid!r}")
        status: object = f.get("status")
        if status is not None and status not in STATUSES:
            raise _bad(n, f"unknown status {status!r}")
        queue: object = f.get("queue")
        if queue is not None:  # a Fraction string, read by _queue
            try:
                Fraction(queue if isinstance(queue, str) else "")
            except (ValueError, ZeroDivisionError):
                raise _bad(
                    n, f"bad queue {queue!r}: want a number like 2 or 3/2"
                ) from None
        if kind == "add":
            if eid in state:
                raise LedgerError(
                    f"{LEDGER_REL}: duplicate id {eid}: lines "
                    f"{state[eid].lines[0]} and {n}; {HINT}"
                )
            if not (
                isinstance(f.get("type"), str)
                and isinstance(f.get("title"), str)
                and status is not None
            ):
                raise _bad(n, "an add needs type, title and status")
            entry: Entry = Entry(
                eid, "", "", "", "", "", "", [], [], ts, ts, {}, []
            )
            state[eid] = entry
        else:
            found: Entry | None = state.get(eid)
            if found is None:
                raise _bad(n, f"set on unknown id {eid}")
            entry = found
        _apply(entry, f, n)
        if status == "running":
            entry.started = ts
        entry.updated = ts
        entry.lines.append(n)
    return state


def load(repo: Path) -> dict[str, Entry]:
    return fold(read_events(repo))


# ---- writing ----------------------------------------------------------------


def next_id(state: dict[str, Entry], prefix: str) -> str:
    nums: list[int] = [
        int(m.group(2))
        for eid in state
        if (m := ID_RE.match(eid)) is not None and m.group(1) == prefix
    ]
    return f"{prefix}-{max(nums, default=0) + 1}"


@functools.cache
def kit_version() -> str:
    """The plugin version from .claude-plugin/plugin.json; 'unknown' if unreadable."""
    try:
        v: object = json.loads(KIT_JSON.read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError, AttributeError):
        return "unknown"
    return v if isinstance(v, str) and v else "unknown"


def _line1_stamp(path: Path) -> str | None:
    try:
        with path.open(encoding="utf-8") as fh:
            first: str = fh.readline()
    except (OSError, UnicodeDecodeError):
        return None
    m: re.Match[str] | None = STAMP_RE.search(first)
    return m.group(1) if m else None


def rule_stamps(repo: Path) -> dict[str, str]:
    """Stamp on line 1 of AGENTS.md and of each pm/kinds/*.md, by repo path."""
    kinds: Path = repo / "pm" / "kinds"
    files: list[Path] = [
        repo / "AGENTS.md", *(sorted(kinds.glob("*.md")) if kinds.is_dir() else [])
    ]
    return {
        str(p.relative_to(repo)): s for p in files if (s := _line1_stamp(p)) is not None
    }


def stamps_behind(repo: Path) -> list[tuple[str, str, str]]:
    """(repo file, its stamp, kit template stamp) for each file behind the kit."""
    out: list[tuple[str, str, str]] = []
    for rel, have in rule_stamps(repo).items():
        tpl: Path = TEMPLATE_DIR / (
            "AGENTS.md" if rel == "AGENTS.md" else f"kinds/{Path(rel).name}"
        )
        want: str | None = _line1_stamp(tpl)
        if want is not None and have < want:  # stamps: YYYY-MM-DD + letter
            out.append((rel, have, want))
    return out


def make_event(
    who: str, ev: str, eid: str, fields: dict[str, object]
) -> dict[str, object]:
    ts: str = datetime.now().astimezone().isoformat(timespec="seconds")
    out: dict[str, object] = {
        "ts": ts, "who": who, "ev": ev, "id": eid, "f": fields, "kit": kit_version()
    }
    sid: str = next((value for key in ("RK_SESSION_ID", SID_ENV, "OPENCODE_SESSION_ID")
                     if (value := os.environ.get(key, "").strip())), "")
    if sid:
        out["sid"] = sid
    return out


def append(
    repo: Path,
    build: Callable[[dict[str, Entry]], list[dict[str, object]]],
    undo: Callable[[], None] | None = None,
) -> dict[str, Entry]:
    """Lock, fold, build events from the current state, append them.

    A LedgerError from `build` (or from validating its events) writes nothing.
    `undo` runs, still under the lock, when anything fails before the lines are
    written (flushed), never after: a failure after it leaves the ledger and
    what `build` did both new.
    """
    path: Path = repo / LEDGER_REL
    if not path.is_file():
        raise LedgerError(f"no {LEDGER_REL} in {repo}; run rk.py init")
    with path.open("ab+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        written: bool = False
        try:
            fh.seek(0)
            raw: bytes = fh.read()
            state: dict[str, Entry] = fold(_parse(raw))
            new: list[dict[str, object]] = build(state)
            if not new:
                written = True  # nothing to write, nothing to undo
                write_status(repo, state)
                return state
            data: bytes = "".join(json.dumps(e) + "\n" for e in new).encode("ascii")
            if raw and not raw.endswith(b"\n"):
                data = b"\n" + data
            new_state: dict[str, Entry] = fold(_parse(raw + data))
            fh.write(data)
            fh.flush()
            written = True
            os.fsync(fh.fileno())
            write_status(repo, new_state)
        finally:
            if not written and undo is not None:
                undo()
            fcntl.flock(fh, fcntl.LOCK_UN)
    return new_state


def _matches(state: dict[str, Entry], ref: str) -> list[Entry]:
    """Entries `ref` names other than by id: its label, or for a stage its exact
    title or its code (the title up to the first '-', `03b` of `03b-paper-x`). A
    planned title (<kind>-<topic>) has no code; an imported one keeps its own."""
    return [
        x
        for x in state.values()
        if x.extra.get("legacy_id") == ref
        or (
            x.type == "stage"
            and (
                ref == x.title
                or (
                    ref == x.title.split("-", 1)[0]
                    and (_imported(x) or bool(STAGE_RE.match(x.title)))
                )
            )
        )
    ]


def _ambiguous(ref: str, hits: list[Entry]) -> LedgerError:
    cands: str = "; ".join(f"{x.id} {x.title}" for x in hits)
    return LedgerError(f"'{ref}' names more than one entry ({cands}); pass the id")


def resolve(state: dict[str, Entry], ref: str, stage: bool = False) -> str:
    """The real id for `ref`: an id (always wins), else the single entry `ref`
    names by label, stage title or stage code. `stage`: it must be a stage, and
    only stages count as matches when one does."""
    e: Entry | None = state.get(ref)
    if e is None:
        hits: list[Entry] = _matches(state, ref)
        if stage:
            hits = [x for x in hits if x.type == "stage"] or hits
        if len(hits) > 1:
            raise _ambiguous(ref, hits)
        if not hits:
            raise LedgerError(f"no stage '{ref}'" if stage else f"no such entry {ref}")
        e = hits[0]
    if stage and e.type != "stage":
        name: str = ref if ref == e.id else f"{ref} ({e.id})"
        raise LedgerError(f"{name} is a {e.type}, not a stage")
    return e.id


def _default_stage(state: dict[str, Entry], typ: str, imported: bool) -> str:
    """The single open stage, if exactly one; else ''."""
    if imported or typ == "stage":
        return ""
    open_: list[str] = [
        e.id for e in state.values() if e.type == "stage" and e.status == "open"
    ]
    return open_[0] if len(open_) == 1 else ""


def _name(value: str, flag: str) -> str:
    if not NAME_RE.match(value):
        raise LedgerError(f"{flag} '{value}': letters, digits, _ . - only")
    return value


def _title(value: str) -> str:
    title: str = value.strip()
    if not title or "\n" in title or "\r" in title:
        raise LedgerError("the title is one non-empty line")
    if len(title) > TITLE_MAX:
        raise LedgerError(
            f"the title has {len(title)} characters (at most {TITLE_MAX}); "
            "put detail in --note"
        )
    return title


def _label(value: str, flag: str) -> str:
    if not LABEL_RE.match(value):
        raise LedgerError(
            f"{flag} '{value}': letters, digits, _ . - / only, at most 40 characters"
        )
    if ANY_ID_RE.search(value):  # an id inside it would count on a TASK: line
        raise LedgerError(
            f"{flag} '{value}' has the form of an entry id or contains one; use "
            "the form <stage code>/<work item>, e.g. 03b/W4"
        )
    if flag == "--label" and "/" not in value:  # imported legacy ids: free form
        raise LedgerError(
            f"--label '{value}': want the form <stage code>/<work item>, e.g. "
            "03b/W4 (a / is required)"
        )
    return value


def _check_label(state: dict[str, Entry], label: str, eid: str) -> None:
    """Refuse a label that already names another entry (label, stage title/code)."""
    others: list[Entry] = [x for x in _matches(state, label) if x.id != eid]
    if others:
        o: Entry = others[0]
        hint: str = (
            f"; {o.id} is {o.status}: free the label first with "
            f"`rk set {o.id} --label <other>`"
            if o.status in ("dropped", "superseded")
            else ""
        )
        raise LedgerError(
            f"--label '{label}' already names {o.id} ({o.title}); "
            f"labels are unique{hint}"
        )


def _check_names(
    state: dict[str, Entry], typ: str, title: str, a: argparse.Namespace
) -> None:
    """The other direction of label uniqueness. A new stage's title and code must
    not name an entry already; an imported one only not a --label label (legacy
    stage numbers may overlap new ones). An imported legacy id must not name an
    entry that is not imported (legacy duplicates are tolerated)."""
    checks: list[tuple[str, str, bool]] = []  # (what, name, labels only)
    if typ == "stage":
        what: str = f"stage '{title}'"
        coded: bool = a.imported or bool(STAGE_RE.match(title))  # as `_matches`
        names: list[str] = [title, title.split("-", 1)[0]] if coded else [title]
        checks += [(what, n, a.imported) for n in names]
    if a.imported and a.legacy_id is not None:
        checks.append((f"legacy id '{a.legacy_id}'", a.legacy_id, False))
    for what, n, labels_only in checks:
        hits: list[Entry] = [
            x
            for x in _matches(state, n)
            if not (a.imported and _imported(x))
            and not (labels_only and x.extra.get("legacy_id") != n)
        ]
        if hits:
            raise LedgerError(
                f"{what}: '{n}' already names {hits[0].id} ({hits[0].title}); "
                "stage codes, stage titles and labels are unique"
            )


def _links(state: dict[str, Entry], links: list[str]) -> list[str]:
    """`links` as real ids, each resolved like any id argument; no duplicates."""
    out: list[str] = []
    for link in links:
        try:
            out.append(resolve(state, link))
        except LedgerError as e:
            raise LedgerError(f"--link {link}: {e}") from None
    return list(dict.fromkeys(out))


def _is_path(ref: str) -> bool:
    """A ref that names a file or folder (not a URL, not doi:...)."""
    return "://" not in ref and not NON_PATH_RE.match(ref)


def _worktree(repo: Path) -> Path | None:
    """The git worktree checkout the cwd is in, when its ledger was redirected
    to `repo`, the main checkout (find_repo); else None."""
    for d in [Path.cwd().resolve(), *Path.cwd().resolve().parents]:
        if (d / LEDGER_REL).is_file():
            main: Path = _main_checkout(d).resolve()
            return d if d != repo.resolve() and main == repo.resolve() else None
    return None


def _abs_rel(r: str, roots: list[Path]) -> str | None:
    """Absolute path `r` relative to the first of `roots` it lies under (a
    trailing / kept); None if under none."""
    for root in roots:
        try:
            rel: str = Path(r).resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            continue
        return rel + ("/" if r.endswith("/") and rel != "." else "")
    return None


def _outside(ref: str) -> bool:
    """A stored path ref that breaks in a clone: absolute, or above the root."""
    return _is_path(ref) and (
        Path(ref).is_absolute() or os.path.normpath(ref).split("/")[0] == ".."
    )


def _rel_refs(
    repo: Path, refs: list[str], flag: str = "--ref", strict: bool = True
) -> list[str]:
    """`refs` with absolute paths under the repo root (or under the worktree the
    cwd is in) made repo-relative (the ledger is committed: no home paths in
    it). `strict`: refuse an empty ref and a path outside the repo (absolute or
    ../); else such a ref stays as given (--ref-drop must be able to name an
    old bad ref)."""
    wt: Path | None = _worktree(repo)
    roots: list[Path] = [repo] if wt is None else [repo, wt]
    out: list[str] = []
    for r in refs:
        if strict and not r.strip():
            raise LedgerError(f"{flag} '': empty; give a path, a URL or doi:...")
        rel: str = r
        if _is_path(r) and Path(r).is_absolute():
            rel = _abs_rel(r, roots) or r
        if strict and _outside(rel):
            raise LedgerError(
                f"{flag} {r}: outside the repo {repo.resolve()}; a ref is a path "
                "relative to the repo root, a URL (://) or doi:..."
            )
        out.append(rel)
    return out


def _there(p: Path) -> bool:
    """True if p exists; an over-long name is absent, not an error.

    Path.exists() raises OSError for it before Python 3.12.
    """
    return os.path.exists(p)


def _check_refs(repo: Path, refs: list[str]) -> list[str]:
    """`refs` made repo-relative (_rel_refs); refused if a path does not exist
    in the checkout that holds the ledger."""
    refs = _rel_refs(repo, refs)
    missing: list[str] = [r for r in refs if _is_path(r) and not _there(repo / r)]
    wt: Path | None = _worktree(repo)
    only_wt: list[str] = [r for r in missing if wt is not None and _there(wt / r)]
    if only_wt:
        raise LedgerError(
            f"--ref {', '.join(only_wt)}: exists in this worktree {wt} but not in "
            f"the main checkout {repo}, which holds the ledger: merge first, then "
            "add the ref"
        )
    if missing:
        raise LedgerError(
            f"--ref {', '.join(missing)}: no such file or folder (relative to the "
            f"repo root {repo}); write it first, or give a URL (://) or doi:..."
        )
    return refs


def _note_plus(old: str, text: str) -> str:
    """`text` on a new line after the old note; notes are never cut."""
    return f"{old}\n{text}" if old else text


def _check_stage_open(
    state: dict[str, Entry],
    sid: str,
    typ: str,
    status: str,
    fix: str,
    imported: bool = False,
) -> None:
    """Refuse putting an open or running task (or stage) into a stage that is
    done. Only tasks block a stage close; for any other type `stage` means
    "raised in", and an open one may sit in (or be set into) a closed stage. A
    stage entry keeps the old rule: no open stage inside a done one. D-32 (work
    runs only in an open stage): a dropped stage takes no entry, a planned or
    shelved one no running or staged entry; both not for `imported` history (as
    it was)."""
    st: Entry | None = state.get(sid) if sid else None
    if st is not None and not imported and st.status == "dropped":
        raise LedgerError(f"{sid} is dropped and takes no entry: {fix}")
    if (
        st is not None
        and not imported
        and status in ("running", "staged")
        and st.status in ("planned", "shelved")
    ):
        way: str = "open the stage: " + (
            f"rk stage-open {sid}" if st.status == "planned"
            else f"rk set {sid} --status planned, then rk stage-open {sid}"
        )
        if _imported(st):  # an imported shelved stage is not planned again
            way = fix
        raise LedgerError(
            f"{sid} is {st.status}: a {status} {typ} cannot go into it (work runs "
            f"only in an open stage): close or shelve it first, or {way}"
        )
    if (
        typ in ("task", "stage")
        and st is not None
        and status in OPEN_STATUSES
        and st.status == "done"
    ):
        art: str = "an" if status == "open" else "a"
        raise LedgerError(
            f"{sid} is closed (done); {art} {status} {typ} cannot go into it: {fix}"
        )


def _check_stage_startable(state: dict[str, Entry], e: Entry) -> None:
    """Refuse starting `e` (rk start, brief-check) while its stage is planned or
    shelved: work runs only in an open stage. An imported shelved stage cannot
    be planned again, so its text gives no way back."""
    st: Entry | None = state.get(e.stage) if e.stage else None
    if st is None or st.status not in ("planned", "shelved"):
        return
    if st.status == "planned":
        raise LedgerError(f"stage {st.id} is planned: rk stage-open {st.id} first")
    way: str = (
        "" if _imported(st)
        else f": rk set {st.id} --status planned, then rk stage-open {st.id}"
    )
    raise LedgerError(f"stage {st.id} is shelved{way}")


def _stage_kind(title: str) -> str | None:
    """The <kind> of a stage title NN[letter]-<kind>-<topic>; None for another
    title (an imported stage may have any)."""
    return title.split("-")[1] if STAGE_RE.match(title) else None


def _max_nn(state: dict[str, Entry]) -> int:
    """The highest NN of a stage title NN[letter]-<kind>-<topic>, imported stages
    too (else the next NN can hit a legacy folder); 0 if none."""
    return max(
        (
            int(x.title.split("-", 1)[0].rstrip(string.ascii_lowercase))
            for x in state.values()
            if x.type == "stage" and STAGE_RE.match(x.title)
        ),
        default=0,
    )


def _stage_dir(e: Entry) -> str:
    """The folder of stage `e`: pm/stages/P-<n>-<kind>-<topic>/ (n of S-n) for a
    planned title (not imported), else pm/stages/<title>/."""
    if not _imported(e) and PLAN_RE.match(e.title):
        return f"pm/stages/P-{_num(e.id)}-{e.title}/"
    return f"pm/stages/{e.title}/"


def _queue(state: dict[str, Entry]) -> list[Entry]:
    """The plan queue: the planned stages by their `queue` value (a Fraction as
    a string), then by id. A shelved stage's stale value is not looked at."""
    return sorted(
        (x for x in state.values() if x.type == "stage" and x.status == "planned"),
        key=lambda x: (Fraction(str(x.extra.get("queue", "0"))), _num(x.id)),
    )


def _queue_end(state: dict[str, Entry]) -> str:
    """The queue value of a newly planned stage: after the last planned one."""
    q: list[Entry] = _queue(state)
    if not q:
        return "1"
    return str(math.floor(Fraction(str(q[-1].extra.get("queue", "0")))) + 1)


def _queue_slot(
    state: dict[str, Entry], before: str | None, after: str | None
) -> str:
    """The queue value for a place: midway between planned stage `before` and its
    predecessor (its value - 1 when it is first), or between `after` and its
    successor (its value + 1 when it is last); the end when neither is given.
    The caller leaves the moved stage out of `state`."""
    ref: str | None = before if before is not None else after
    if ref is None:
        return _queue_end(state)
    flag: str = "--before" if before is not None else "--after"
    tid: str = resolve(state, ref, stage=True)
    if state[tid].status != "planned":
        raise LedgerError(
            f"{flag} {ref}: {tid} is {state[tid].status}; the target must be a "
            "planned stage"
        )
    q: list[Entry] = _queue(state)
    vals: list[Fraction] = [Fraction(str(x.extra.get("queue", "0"))) for x in q]
    i: int = [x.id for x in q].index(tid)
    if before is not None:
        return str((vals[i - 1] + vals[i]) / 2 if i else vals[i] - 1)
    return str((vals[i] + vals[i + 1]) / 2 if i + 1 < len(vals) else vals[i] + 1)


def _forecast(state: dict[str, Entry]) -> dict[str, str]:
    """`~NN` of each planned stage in queue order, as stage-open would give it
    now: the next free NN after `_max_nn` per plain stage; a follow-up (field
    `follows`, a stage with an NN) takes the next free letter of that NN and no
    place in the count. Shelved stages have none. Nothing is stored."""
    used: set[str] = set()
    out: dict[str, str] = {}
    for e in _queue(state):
        t: Entry | None = state.get(str(e.extra.get("follows", "")))
        codes: Iterator[str] = (
            f"{n:02d}" for n in itertools.count(_max_nn(state) + 1)
        )
        if t is not None and STAGE_RE.match(t.title):
            nn: str = t.title.split("-", 1)[0].rstrip(string.ascii_lowercase)
            codes = iter([nn + c for c in string.ascii_lowercase[1:]])
        code: str | None = next(
            (c for c in codes if c not in used and not _matches(state, c)), None
        )
        if code is not None:  # none: the letters b to z are all taken
            used.add(code)
            out[e.id] = f"~{code}"
    return out


# public names for the viewer (ui.py); the private ones stay for the tests
plan_queue = _queue
plan_forecast = _forecast


def _open_title(state: dict[str, Entry], topic: str, follows: str | None) -> str:
    """The title of `add stage <kind>-<topic> --open`: the next NN, or with
    `follows` (a stage NN[letter]-...) its NN plus the next letter from b. A code
    that already names an entry (a label, an imported stage) is skipped."""
    codes: Iterator[str] = (f"{n:02d}" for n in itertools.count(_max_nn(state) + 1))
    if follows is not None:
        st: Entry = state[resolve(state, follows, stage=True)]
        if st.status == "planned":
            raise LedgerError(
                f"--follows {follows}: {st.id} ({st.title}) is planned and has no NN "
                "yet; follow an opened stage"
            )
        if st.status not in ("open", "done"):
            raise LedgerError(
                f"--follows {follows}: {st.id} ({st.title}) is {st.status}; follow an "
                "open or done stage"
            )
        if not STAGE_RE.match(st.title):
            raise LedgerError(
                f"--follows {follows}: {st.id} ({st.title}) has no NN title "
                f"({STAGE_FORM})"
            )
        nn: str = st.title.split("-", 1)[0].rstrip(string.ascii_lowercase)
        codes = iter([nn + c for c in string.ascii_lowercase[1:]])
    for code in codes:
        if not _matches(state, code):
            return f"{code}-{topic}"
    raise LedgerError(f"--follows {follows}: the letters b to z are all taken")


def _check_one_per_kind(state: dict[str, Entry], title: str, what: str) -> None:
    """Refuse `what` ("reopen S-n", "add stage T") for a stage titled `title`
    while another stage of its kind is open (at most one open stage per kind,
    template AGENTS.md 3.1)."""
    kind: str | None = _stage_kind(title)
    for x in state.values():
        if (
            kind is not None
            and x.type == "stage"
            and x.status == "open"
            and _stage_kind(x.title) == kind
        ):
            raise LedgerError(
                f"cannot {what}: {x.id} ({x.title}) is open, and at most "
                f"one {kind} stage may be open: stage-close {x.id} first"
            )


def _repo(a: argparse.Namespace) -> Path:
    return find_repo(a.repo, explicit=True) if a.repo else find_repo(Path.cwd())


# ---- views ------------------------------------------------------------------


def age(ts: str, now: datetime) -> str:
    """'45m', '5h' or '3d'; a date-only ts counts from local midnight."""
    try:
        then: datetime = datetime.fromisoformat(ts).astimezone()
    except ValueError:
        return "?"
    secs: int = max(int((now - then).total_seconds()), 0)
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h"
    return f"{secs // 86400}d"


def _since(e: Entry) -> str:
    """Age base: a running entry counts from its latest start, others from creation."""
    return e.started if e.status == "running" and e.started else e.created


def _num(eid: str) -> int:
    return int(eid.rsplit("-", 1)[1])


def _is_open(e: Entry) -> bool:
    """Stored: what checks decide on (drop, stage-close, start, records)."""
    return e.status in OPEN_STATUSES


def shown_status(state: dict[str, Entry], e: Entry) -> str:
    """The status shown (D-56; display only, nothing stored): an open entry
    that is not a stage, in a planned or shelved stage, shows that stage's
    status; any other entry its stored status."""
    st: Entry | None = state.get(e.stage) if e.stage else None
    if e.type != "stage" and e.status == "open" and st is not None:
        if st.status in ("planned", "shelved"):
            return st.status
    return e.status


def _shown_open(state: dict[str, Entry], e: Entry) -> bool:
    """In the open list and its counts (rk list, STATUS.md): shown open."""
    return shown_status(state, e) in OPEN_STATUSES


def _imported(e: Entry) -> bool:
    return e.extra.get("imported") is True


def _sort_key(e: Entry) -> tuple[int, int, str, int]:
    """Running first, then open, then the rest; then type order, then id number."""
    rank: int = 0 if e.status == "running" else 1 if _is_open(e) else 2
    builtin: list[str] = list(BUILTIN_TYPES)
    trank: int = builtin.index(e.type) if e.type in builtin else len(builtin)
    return (rank, trank, e.type, _num(e.id))


def _clip(line: str, width: int = LINE_MAX) -> str:
    return line if len(line) <= width else line[: width - 3] + "..."


def _item(e: Entry, now: datetime, width: int = LINE_MAX) -> str:
    return _clip(
        f"- {e.id} ({e.owner}, {age(_since(e), now)}) {e.title}"
        + (" [imported]" if _imported(e) else ""),
        width,
    )


def _staged_item(e: Entry, now: datetime) -> str:
    """Staged block line: the item, then ` -- ` and the note. Over LINE_MAX the
    note (first line, at most 40 characters) stays whole and the title is cut."""
    reason: str = str(e.extra.get("reason") or "-")
    line: str = f"{_item(e, now)} -- {_cut(reason)}"
    if len(line) <= LINE_MAX:
        return line
    tail: str = f" -- {reason.splitlines()[0][:40]}"
    return _clip(_item(e, now, LINE_MAX - len(tail)) + tail)


def _stage_line(e: Entry, state: dict[str, Entry], now: datetime) -> str:
    mine: list[Entry] = [
        x for x in state.values() if x.type == "task" and x.stage == e.id
    ]
    parts: list[str] = [
        f"{n} {s}"
        for s in OPEN_STATUSES[::-1]
        if (n := sum(1 for x in mine if x.status == s))
    ]
    tasks: str = ", ".join(parts) or "none"
    return _clip(
        f"- {e.id} {e.title} ({e.status} {age(_since(e), now)}; tasks: {tasks})"
    )


def _open_entries(state: dict[str, Entry], stage: Entry) -> int:
    """How many open or running entries (any type) belong to `stage`."""
    return sum(1 for x in state.values() if x.stage == stage.id and _is_open(x))


def _planned_line(state: dict[str, Entry]) -> str:
    """`planned 3: ~03 paper-scan (2 entries), ~04 paper-draft (1), ...` in
    queue order, the open entries of each stage when not 0 (D-56; the first such
    count names its unit), cut between items to LINE_MAX with `+k more`; ""
    when no stage is planned."""
    fc: dict[str, str] = _forecast(state)
    items: list[str] = []
    first: bool = True  # the first count names its unit
    for e in _queue(state):
        k: int = _open_entries(state, e)
        unit: str = (" entry" if k == 1 else " entries") if first else ""
        first = first and not k
        tail: str = f" ({k}{unit})" if k else ""
        items.append(f"{fc.get(e.id, '~?')} {e.title}{tail}")
    n: int = len(items)
    line: str = ""
    for k in range(n, -1, -1):  # k = items shown; k = 0 always fits
        more: list[str] = (
            [f"+{n - k} more: rk list --status planned"] if k < n else []
        )
        line = f"planned {n}: " + ", ".join(items[:k] + more)
        if len(line) <= LINE_MAX:
            break
    return line if n else ""


def render_status(state: dict[str, Entry], now: datetime) -> str:
    open_: list[Entry] = sorted(  # shown open: D-56
        (e for e in state.values() if _shown_open(state, e)), key=_sort_key
    )
    stages: list[Entry] = [e for e in open_ if e.type == "stage"]
    rest: list[Entry] = [e for e in open_ if e.type != "stage"]
    stamp: str = now.isoformat(timespec="seconds")
    out: list[str] = [
        "# Status (generated)",
        "",
        f"Generated from {LEDGER_REL} by rk.py at {stamp}. "
        f"Do not edit: hand edits are blocked and overwritten. Open: {len(open_)}.",
    ]

    def section(title: str, lines: list[str]) -> None:
        if lines:
            out.extend(["", f"## {title}", *lines])

    section("Stages", [_stage_line(e, state, now) for e in stages])
    section(  # D-49: work done, not on the base branch yet; the note says where
        "Staged (done, not landed)",
        [_staged_item(e, now) for e in rest if e.status == "staged"],
    )
    section(
        "Running",
        [_item(e, now) for e in rest if e.status == "running" and e.owner != "user"],
    )
    section(
        "Needs you",
        [_item(e, now) for e in rest if e.owner == "user" and e.status != "staged"],
    )
    fixed: dict[str, str] = {
        "task": "Open tasks",
        "fetch": "Open fetches",
        "debt": "Open debt",
        "handoff": "Open handoffs",
        "deferred": "Deferred",
    }
    declared: list[str] = sorted({e.type for e in rest} - set(BUILTIN_TYPES))
    for typ, title in [*fixed.items(), *((t, f"Open {t}") for t in declared)]:
        section(
            title,
            [
                _item(e, now)
                for e in rest
                if e.type == typ and e.status == "open" and e.owner != "user"
            ],
        )
    fc: dict[str, str] = _forecast(state)
    planned: list[str] = []
    for e in _queue(state):  # each stage, then its entries shown planned (D-56)
        planned.append(
            _clip(
                f"- {fc.get(e.id, '~?')} {e.id} {e.title} "
                f"(entries: {_open_entries(state, e)})"
            )
        )
        planned += [
            _clip(f"  {_item(x, now)}")
            for x in sorted(state.values(), key=_sort_key)
            if x.stage == e.id and shown_status(state, x) == "planned"
        ]
    section("Planned stages", planned)
    shelved: list[Entry] = sorted(  # known, not planned now: not in the open view
        (e for e in state.values() if shown_status(state, e) == "shelved"),
        key=_sort_key,
    )
    section("Shelved", [_item(e, now) for e in shelved])
    decs: list[Entry] = [
        e for e in state.values() if e.type == "decision" and e.status == "done"
    ]
    decs.sort(key=lambda e: e.lines[0], reverse=True)
    section(
        "Recent decisions",
        [
            _clip(f"- {e.id} ({e.owner}, {e.created[:10]}) {e.title}")
            for e in decs[:RECENT_DECISIONS]
        ],
    )
    return "\n".join(out) + "\n"


def write_status(repo: Path, state: dict[str, Entry]) -> None:
    path: Path = repo / STATUS_REL
    tmp: Path = path.with_name(path.name + ".tmp")
    tmp.write_text(
        render_status(state, datetime.now().astimezone()), encoding="utf-8"
    )
    os.replace(tmp, path)


def _list_key(
    state: dict[str, Entry], e: Entry
) -> tuple[int, int, tuple[int, int, str, int]]:
    """Shown open before the rest (D-56); within each: stages, handoffs, owner
    user, the rest."""
    group: int = (
        0 if e.type == "stage"
        else 1 if e.type == "handoff"
        else 2 if e.owner == "user"
        else 3
    )
    return (0 if _shown_open(state, e) else 1, group, _sort_key(e))


def _more(k: int) -> str:
    return f"+{k} more: narrow with --type/--owner/--stage, or --limit 0"


def format_list(
    state: dict[str, Entry],
    now: datetime,
    *,
    type_: str | None,
    owner: str | None,
    stage: str | None,
    limit: int,
    include_closed: bool,
    status: str | None = None,
) -> str:
    rows: list[Entry] = [
        e
        for e in state.values()
        if (type_ is None or e.type == type_)
        and (owner is None or e.owner == owner)
        and (stage is None or e.stage == stage)
        and (status is None or shown_status(state, e) == status)
    ]
    opens: list[Entry] = [e for e in rows if _shown_open(state, e)]  # D-56
    listed: list[Entry] = opens if stage is None else [  # --stage: its entries too
        e for e in rows if _is_open(e)
    ]
    shown: list[Entry] = sorted(
        rows if include_closed or status is not None else listed,
        key=lambda e: _list_key(state, e),
    )
    fc: dict[str, str] = _forecast(state)
    if status in ("planned", "shelved"):  # each stage, then its entries (D-56)
        order: list[str] = (
            [x.id for x in _queue(state)] if status == "planned"  # queue order
            else [x.id for x in shown if x.type == "stage"]
        )

        def at(e: Entry) -> tuple[int, int]:
            anchor: str = e.id if e.type == "stage" else e.stage
            pos: int = order.index(anchor) if anchor in order else len(order)
            return (pos, 0 if e.type == "stage" else 1)

        shown.sort(key=at)  # stable: the list order within one stage
    # --status of a not-open status: its own head, counts in list order (DB-41)
    closed_view: bool = status is not None and status not in OPEN_STATUSES
    counts: dict[str, int] = {}
    for e in shown if closed_view else sorted(opens, key=_sort_key):
        counts[e.type] = counts.get(e.type, 0) + 1
    running: int = sum(1 for e in opens if e.status == "running")
    staged: int = sum(1 for e in opens if e.status == "staged")
    parts: list[str] = [f"{t} {c}" for t, c in counts.items()]
    head: str = ""
    for k in range(len(parts), -1, -1):  # within LINE_MAX, cut between counts
        shown_parts: list[str] = parts[:k] + (["..."] if k < len(parts) else [])
        if closed_view:
            head = f"{status} {len(shown)}"
        else:
            head = f"open {len(opens)} (running {running}"
            head += f", staged {staged})" if staged else ")"
        head += ": " + ", ".join(shown_parts) if shown_parts else ""
        if len(head) <= LINE_MAX:
            break
    lines: list[str] = [head]
    unfiltered: bool = type_ is None and owner is None and stage is None
    planned: str = _planned_line(state) if unfiltered and status is None else ""
    if planned:  # line 2: the session-start hook prints this list as it is
        lines.append(planned)
    cap: list[Entry] = shown[:limit] if limit else shown
    for e in cap:
        title: str = ("[imp] " if _imported(e) else "") + e.title
        if e.status == "planned":  # forecast and entries, as in STATUS.md (D-56)
            m: int = _open_entries(state, e)
            title = f"{fc.get(e.id, '~?')} {title} ({m} entr{'y' if m == 1 else 'ies'})"
        lines.append(
            _clip(
                f"{e.id:<5} {shown_status(state, e):<7} {e.owner[:8]:<8} "
                f"{age(_since(e), now):>4}  {title}"
            )
        )
    if len(cap) < len(shown):
        lines.append(_more(len(shown) - len(cap)))
    return "\n".join(lines)


# ---- commands ---------------------------------------------------------------


def _add_step(
    a: argparse.Namespace, types: dict[str, str], key_links: bool = False
) -> Callable[[dict[str, Entry]], tuple[str, dict[str, object]]]:
    """Validate an add (what needs no ledger state now); the returned step checks
    the rest against a state and gives (new id, event fields). Shared by add and
    import. `key_links`: links "@KEY" pass unchecked (import resolves them)."""
    typ: str = check_type(a.type, types)
    title: str = _title(a.title)
    if typ == "decision" and a.owner is None:
        raise LedgerError(
            "a decision needs --owner (who decided: user, lead or a teammate name)"
        )
    owner: str = _name(a.owner or "lead", "--owner")
    import_only: list[str] = [
        flag
        for flag, val in (
            ("--date", a.date),
            ("--legacy-id", a.legacy_id),
            ("--source", a.source),
        )
        if val is not None
    ]
    if a.status == "planned":
        raise LedgerError(
            "--status planned: a stage is planned by add stage <kind>-<topic> "
            "without --status; no other add and no import row sets it"
        )
    if a.status == "staged":  # D-50: one way in
        raise LedgerError(
            "--status staged: an entry is staged by rk staged ID --note TEXT, no "
            "add sets it"
        )
    if a.status in ("superseded", "shelved"):  # shelved needs a reason: rk shelve
        import_only.append(f"--status {a.status}")
    if import_only and not a.imported:
        raise LedgerError(f"{', '.join(import_only)}: only with --imported")
    if a.imported and not a.source:
        raise LedgerError("--imported needs --source FILE:LINE")
    if a.date is not None:
        try:
            date.fromisoformat(a.date)
        except ValueError:
            raise LedgerError(f"--date '{a.date}': want YYYY-MM-DD") from None
    new_stage: bool = typ == "stage" and not a.imported
    plain: str = "planned" if new_stage and not a.open else "open"
    status: str = a.status or ("done" if typ == "decision" else plain)
    if typ == "decision" and status in OPEN_STATUSES:
        raise LedgerError(
            "a decision is in force when logged (status done); an open question "
            'for the user is a deferred entry: add deferred "<question>" --owner user'
        )
    if new_stage and status != plain:
        raise LedgerError(
            f"--status {status}: a new stage is planned (add stage <kind>-<topic>) "
            "or opened with --open, and closed with stage-close; another status "
            "only with --imported"
        )
    if typ == "task" and not a.imported and not a.note.strip():
        raise LedgerError(TASK_NOTE)
    if (a.open or a.follows is not None) and not new_stage:
        raise LedgerError(
            "--open and --follows: only on a new stage, add stage <kind>-<topic> "
            "[--open] [--follows S-m]"
        )
    if (a.before is not None or a.after is not None) and (not new_stage or a.open):
        raise LedgerError(
            "--before/--after: only when a stage is planned (add stage "
            "<kind>-<topic>, without --open)"
        )
    if a.open and not PLAN_RE.match(title):
        raise LedgerError(
            f"stage title '{title}' with --open: want {PLAN_FORM}, the NN is "
            "computed (letters, digits, _ . - in the topic)"
        )
    if new_stage and not a.open and STAGE_RE.match(title):
        raise LedgerError(
            f"stage title '{title}' has an NN: use <kind>-<topic>; the NN comes at "
            "stage-open; to open it now: rk add stage <kind>-<topic> --open"
        )
    if new_stage and not PLAN_RE.match(title):
        raise LedgerError(
            f"stage title '{title}' is not a stage name; want {PLAN_FORM} "
            "(letters, digits, _ . - in the topic)"
        )
    label: str | None = _label(a.label, "--label") if a.label is not None else None

    def step(state: dict[str, Entry]) -> tuple[str, dict[str, object]]:
        name: str = _title(_open_title(state, title, a.follows)) if a.open else title
        eid: str = next_id(state, types[typ])
        folder: list[str] = []
        if new_stage:  # the P- form of `_stage_dir` while planned
            pre: str = f"P-{_num(eid)}-" if status == "planned" else ""
            folder = [f"pm/stages/{pre}{name}/"]
        refs: list[str] = list(dict.fromkeys([*folder, *a.ref]))
        links: list[str] = [  # "@KEY" links stay as given; import resolves them
            x if key_links and x.startswith("@") else _links(state, [x])[0]
            for x in a.link
        ]
        stage: str = (
            resolve(state, a.stage, stage=True)
            if a.stage
            else _default_stage(state, typ, a.imported)
        )
        _check_stage_open(  # imported history: as it was
            state, stage, typ, status, "pass --stage with an open stage", a.imported
        )
        if label is not None:
            _check_label(state, label, eid)
        _check_names(state, typ, name, a)
        if typ == "stage" and not a.imported:  # imported history: as it was
            _check_one_per_kind(state, name, f"add stage {name}")
        f: dict[str, object] = {
            "type": typ,
            "title": name,
            "status": status,
            "owner": owner,
            "stage": stage,
            "note": a.note,
            "links": list(dict.fromkeys(links)),
            "refs": refs,
        }
        if label is not None:
            f["legacy_id"] = label
        if status == "planned":
            f["queue"] = _queue_slot(state, a.before, a.after)
            if a.follows is not None:  # stage-open falls back to it
                _open_title(state, name, a.follows)  # the target must have an NN
                f["follows"] = resolve(state, a.follows, stage=True)
        if a.imported:
            f["imported"] = True
            f["source"] = a.source
            if a.legacy_id is not None:
                f["legacy_id"] = a.legacy_id
            if a.date is not None:
                f["date"] = a.date
        return eid, f

    return step


def _cmd_add(a: argparse.Namespace) -> int:
    repo: Path = _repo(a)
    who: str = _name(a.who, "--who")
    if not a.imported:  # imported history may name files that are gone
        a.ref = _check_refs(repo, a.ref)
    step: Callable[[dict[str, Entry]], tuple[str, dict[str, object]]] = _add_step(
        a, known_types(repo)
    )
    made: list[str] = []

    def build(state: dict[str, Entry]) -> list[dict[str, object]]:
        eid, f = step(state)
        made.append(eid)
        ev: dict[str, object] = make_event(who, "add", eid, f)
        if f["type"] == "stage" and not a.imported:
            ev["rules"] = rule_stamps(repo)
        return [ev]

    state: dict[str, Entry] = append(repo, build)
    e: Entry = state[made[0]]
    print(f"logged {e.id}: {e.title}{_add_tail(e, state)}")
    if e.type == "stage" and not a.imported:  # after the write: a refused add
        folder: Path = repo / _stage_dir(e)  # makes no folder
        # D-119: `add stage --open` uses an NN folder that is there; say so
        there: str = " (uses the existing folder)" if a.open and folder.is_dir() else ""
        try:
            for sub in STAGE_DIRS:
                (folder / sub).mkdir(parents=True, exist_ok=True)
        except OSError as err:
            raise LedgerError(
                f"{e.id} is logged, but the folder {folder} could not be made: "
                f"{err.strerror}; make it by hand"
            ) from None
        dirs: str = " ".join(f"{s}/" for s in STAGE_DIRS)
        print(f"folder {_stage_dir(e)} ({dirs}){there}")
    return 0


IMPORT_STR_KEYS: tuple[str, ...] = (
    "type", "title", "source", "owner", "stage", "note", "status", "legacy_id", "label",
    "date", "key",
)
IMPORT_LIST_KEYS: tuple[str, ...] = ("link", "ref")
IMPORT_DESCRIPTION: str = """\
Import history as imported entries, all or nothing: every row of every FILE is
checked first; one bad row and nothing is written. Errors print as
FILE:LINE: message. Each FILE is JSON Lines: one JSON object per line, blank
lines skipped. Several FILEs are one batch, read in the order given: a stage
row in an earlier file can be named by "stage" in a later one (--dry-run too).
"stage" takes a stage id, title or code, never @KEY; the stage row must come
before the row that names it in the batch (earlier in the same file, or in a
file given earlier), a stage row further down fails with "no stage".
"""
IMPORT_EPILOG: str = """\
row keys (required: type, title, source; every value a string, link and ref a
list of strings):
  type       entry type: task, decision, stage, ... or a type declared in
             pm/kinds/
  title      one line, at most 160 characters
  source     where the row came from, e.g. "pm/living/TASKS.md:44"
  status     open (default; a decision: done), running, done, dropped,
             superseded or shelved (known, not planned now)
  owner      name, default lead; a decision needs it (who decided)
  stage      a stage id, the exact title of one stage, its code (03b) or
             its label; default: no stage. A done (closed) stage refuses
             only a task or stage row that is open or running (such a row
             fails the whole batch); every other row may name it
             (backfill)
  note       free text
  legacy_id  the row's id in the old system; it is the entry's label
  label      same as legacy_id (give one of them): letters, digits, _ . - /,
             at most 40 characters; not checked for uniqueness
  date       YYYY-MM-DD, the original date (becomes the entry's created)
  link       entry ids or labels; "@KEY" names the row with that key in this
             batch (it may come later in the batch)
  ref        paths
  key        name for "@KEY" links: letters, digits, _ . - only; unique in
             the batch; not stored in the entry

A row already imported (same source and legacy_id, or same source and title
when it has no legacy_id), in the ledger or earlier in the batch, is refused.
Example FILE, one row per line (the task links the fetch by its key):
  {"type": "stage", "title": "01-pilot", "source": "A.md:3", "status": "done"}
  {"type": "task", "title": "port", "source": "A.md:5", "link": ["@s20"]}
  {"type": "fetch", "title": "smith2020", "source": "A.md:9", "key": "s20"}
"""


def _import_row(obj: object, who: str) -> argparse.Namespace:
    """A JSONL row as the namespace `add --imported` would have parsed."""
    if not isinstance(obj, dict):
        raise LedgerError("not a JSON object")
    unknown: list[str] = [k for k in obj if k not in IMPORT_STR_KEYS + IMPORT_LIST_KEYS]
    if unknown:
        raise LedgerError(f"unknown key {', '.join(map(repr, unknown))}")
    for key in ("type", "title", "source"):
        if key not in obj:
            raise LedgerError(f"missing key {key!r}")
    for key in IMPORT_STR_KEYS:
        if key in obj and not isinstance(obj[key], str):
            raise LedgerError(f"{key} must be a string")
    for key in IMPORT_LIST_KEYS:
        val: object = obj.get(key, [])
        if not isinstance(val, list) or not all(isinstance(v, str) for v in val):
            raise LedgerError(f"{key} must be a list of strings")
    if obj.get("status", "open") not in STATUSES:
        raise LedgerError(f"status '{obj['status']}': one of {', '.join(STATUSES)}")
    if "key" in obj:
        _name(obj["key"], "key")
    row: dict[str, object] = dict(obj)
    if "label" in row:
        if "legacy_id" in row:
            raise LedgerError("give label or legacy_id, not both")
        row["legacy_id"] = _label(str(row.pop("label")), "label")
    fields: dict[str, object] = {
        "who": who, "imported": True, "owner": None, "stage": None, "note": "",
        "link": [], "ref": [], "status": None, "legacy_id": None, "label": None,
        "date": None, "key": None, "open": False, "follows": None, "before": None,
        "after": None,
    }
    return argparse.Namespace(**{**fields, **row})


def _import_key(source: object, legacy: object, title: object) -> tuple[str, str, str]:
    """What the re-run guard compares: source plus legacy id, else title."""
    return str(source), "id" if legacy else "title", str(legacy or title)


def _import_summary(made: list[tuple[str, str, str]], dry: bool) -> list[str]:
    """One line per type (status counts, id range), then the total."""
    out: list[str] = []
    for typ in dict.fromkeys(t for t, _, _ in made):
        rows: list[tuple[str, str, str]] = [m for m in made if m[0] == typ]
        counts: str = ", ".join(
            f"{s} {sum(1 for r in rows if r[1] == s)}"
            for s in STATUSES
            if any(r[1] == s for r in rows)
        )
        out.append(f"{typ}: {len(rows)} ({counts}) {rows[0][2]}..{rows[-1][2]}")
    verb: str = "would be imported (dry run, nothing written)" if dry else "imported"
    return [*out, f"total {len(made)} {verb}"]


def _cmd_import(a: argparse.Namespace) -> int:
    repo: Path = _repo(a)
    who: str = _name(a.who, "--who")
    types: dict[str, str] = known_types(repo)
    rows: list[tuple[str, bytes]] = []  # (FILE:LINE, line) over the whole batch
    errs: list[tuple[int, str]] = []  # (index into rows, message): sorted on print
    for file in a.files:
        try:
            raw: bytes = Path(file).read_bytes()
        except OSError as e:
            raise LedgerError(f"{file}: {e.strerror}") from None
        lines: list[tuple[str, bytes]] = [
            (f"{file}:{n}", b) for n, b in enumerate(raw.split(b"\n"), 1) if b.strip()
        ]
        if not lines:
            errs.append((len(rows), f"{file}: no rows"))
        rows.extend(lines)
    made: list[tuple[str, str, str]] = []

    def plan(state: dict[str, Entry]) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        seen: dict[tuple[str, str, str], str] = {
            _import_key(e.extra.get("source"), e.extra.get("legacy_id"), e.title): e.id
            for e in state.values()
            if e.extra.get("imported")
        }
        keys: dict[str, str] = {}  # row key -> FILE:LINE of its row
        ids: dict[str, str] = {}  # row key -> id given to its row
        linked: list[tuple[int, dict[str, object], list[str]]] = []
        for i, (where, bline) in enumerate(rows):
            try:
                try:
                    obj: object = json.loads(bline.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    raise LedgerError("not a JSON line") from None
                ns: argparse.Namespace = _import_row(obj, who)
                rkey: str | None = ns.key
                if rkey is not None:
                    if rkey in keys:
                        raise LedgerError(
                            f"duplicate key '{rkey}' (first at {keys[rkey]})"
                        )
                    keys[rkey] = where
                eid, f = _add_step(ns, types, key_links=True)(state)
                key: tuple[str, str, str] = _import_key(
                    f["source"], f.get("legacy_id"), f["title"]
                )
                if key in seen:
                    raise LedgerError(f"already imported as {seen[key]}")
                seen[key] = eid
                if rkey is not None:
                    ids[rkey] = eid
                ev: dict[str, object] = make_event(who, "add", eid, f)
                fold([(i + 1, ev)], state)
                events.append(ev)
                made.append((str(f["type"]), str(f["status"]), eid))
                linked.append((i, f, ns.link))
            except LedgerError as e:
                errs.append((i, f"{where}: {e}"))
        for i, f, links in linked:  # "@KEY" -> id, now that every row has one
            out: list[str] = []
            for link in links:
                if link.startswith("@") and link[1:] not in keys:
                    errs.append((i, f"{rows[i][0]}: link {link}: no row with that key"))
                # a key whose row failed stays unresolved: the batch is refused
                out.append(ids.get(link[1:], link) if link.startswith("@") else link)
            f["links"] = list(dict.fromkeys(out))
        if errs:
            raise LedgerError("import refused")
        return events

    try:
        if a.dry_run:
            plan(load(repo))
        else:
            append(repo, plan)
    except LedgerError:
        if not errs:
            raise
        print("\n".join(m for _, m in sorted(errs, key=lambda x: x[0])))
        return 1
    print("\n".join(_import_summary(made, a.dry_run)))
    return 0


def _in_stage(e: Entry) -> str:
    """Receipt tail: the stage an entry went into; none for a stage itself."""
    return "" if e.type == "stage" else f" ({_stage_word(e)})"


def _stage_word(e: Entry) -> str:
    return f"stage {e.stage}" if e.stage else "no stage"


def _add_tail(e: Entry, state: dict[str, Entry]) -> str:
    """Receipt tail of an add. A closed entry linked to a closed stage gets no
    stage (the default is the open stage); say why. No `set --stage` hint: for
    an entry that is done a late fact belongs to the stage now open, and the
    closed stage's LEDGER.md is frozen. An open entry gets the plain tail (its
    stage is the default one, or none; it may be set into a closed stage)."""
    if e.type == "stage" and e.status == "planned":
        return " (planned)"
    if e.stage or e.type == "stage" or e.status in OPEN_STATUSES:
        return _in_stage(e)
    for x in (state.get(i) for i in e.links):
        if x is not None and x.type == "stage" and x.status == "done":
            return f" (no stage: {x.id} is closed)"
    return _in_stage(e)


def _entry(state: dict[str, Entry], ref: str) -> Entry:
    return state[resolve(state, ref)]


def _need_note(a: argparse.Namespace) -> str:
    note: str = (a.note or "").strip()
    if not note:
        raise LedgerError(f"{a.cmd} needs --note")
    return note


def _cut(note: str) -> str:
    return note.splitlines()[0][:60]


def _union(old: list[str], new: list[str]) -> list[str]:
    return list(dict.fromkeys([*old, *new]))


def _cmd_start(a: argparse.Namespace) -> int:
    repo: Path = _repo(a)
    who: str = _name(a.who, "--who")
    owner: str | None = _name(a.owner, "--owner") if a.owner else None
    out: list[str] = []

    def build(state: dict[str, Entry]) -> list[dict[str, object]]:
        e: Entry = _entry(state, a.id)
        if e.type == "stage":
            raise LedgerError(
                f"{e.id} is a stage: stages are not started; it stays open "
                "until stage-close"
            )
        if e.status == "running":
            out.append(f"{e.id} already running")
            return []
        if e.status not in ("open", "staged"):  # staged: more work, a fix round
            raise LedgerError(f"{e.id} is {e.status}: use reopen first")
        _check_stage_startable(state, e)  # first: its text names stage-open
        _check_stage_open(
            state, e.stage, e.type, "running",
            f"re-stage it first: set {e.id} --stage S-<x>",
        )
        f: dict[str, object] = {"status": "running"}
        if owner is not None:
            f["owner"] = owner
        out.append(f"started {e.id}: {e.title}")
        return [make_event(who, "set", e.id, f)]

    append(repo, build)
    print(out[0])
    return 0


def _close_drop_reopen(a: argparse.Namespace) -> int:
    repo: Path = _repo(a)
    who: str = _name(a.who, "--who")
    note: str = _need_note(a)
    a.ref = _check_refs(repo, a.ref)
    cmd: str = a.cmd
    new: str = {
        "close": "done", "drop": "dropped", "shelve": "shelved", "reopen": "open"
    }[cmd]
    ids: list[str] = []

    def build(state: dict[str, Entry]) -> list[dict[str, object]]:
        e: Entry = _entry(state, a.id)
        ids.append(e.id)
        if e.type == "stage" and cmd != "reopen" and e.status == "planned":
            raise LedgerError(
                f"{e.id} is a planned stage: use rk set {e.id} --status "
                "shelved|dropped --note ..."
            )
        if e.type == "stage" and cmd != "reopen" and e.status == "shelved":
            back: str = "" if _imported(e) else " (or --status planned)"
            raise LedgerError(
                f"{e.id} is a shelved stage: use rk set {e.id} --status dropped "
                f"--note ...{back}"
            )
        if e.type == "stage" and cmd != "reopen":
            raise LedgerError(f"{e.id} is a stage: use stage-close")
        if e.type == "decision" and cmd != "drop":  # shelve: Q1, every type but this
            raise LedgerError(
                f"{e.id} is a decision; decisions are in force when logged: "
                "supersede or drop"
            )
        allowed: tuple[str, ...] = {
            "close": OPEN_STATUSES,
            "drop": OPEN_STATUSES + ("shelved",)
            + (("done",) if e.type == "decision" else ()),
            "shelve": OPEN_STATUSES,
            "reopen": (
                ("done",) if e.type == "stage"
                else ("done", "dropped", "shelved", "staged")
            ),
        }[cmd]
        if e.status not in allowed:
            how: str = ""
            if cmd == "reopen" and e.type == "stage" and not _imported(e):
                how = {
                    "planned": f": rk stage-open {e.id}",
                    "shelved": f": rk set {e.id} --status planned, then rk "
                    f"stage-open {e.id}",
                }.get(e.status, "")
            raise LedgerError(f"cannot {cmd} {e.id}: it is {e.status}{how}")
        if cmd == "reopen":
            _check_stage_open(
                state, e.stage, e.type, "open",
                f"re-stage it first: set {e.id} --stage S-<x>",
            )
        if cmd == "reopen" and e.type == "stage":
            if e.title in (".", "..") or not NAME_RE.match(e.title):
                raise LedgerError(
                    f"cannot reopen {e.id}: its title '{e.title}' is no folder "
                    "name, so it can have no stage record (an imported stage); add "
                    "a new stage"
                )
            folder: Path | None = _record_folder(repo, e)
            if folder is None or not folder.is_dir():
                raise LedgerError(
                    f"cannot reopen {e.id}: no folder {_stage_dir(e)} (an "
                    "imported or folderless stage); restore it or add a new stage"
                )
            _check_one_per_kind(state, e.title, f"reopen {e.id}")
        f: dict[str, object] = {
            "status": new,
            "note": _note_plus(e.note, note),
            "reason": note,  # why it has this status now; the next one replaces it
        }
        if a.ref:
            f["refs"] = _union(e.refs, a.ref)
        links: list[str] = _links(state, [] if cmd == "reopen" else a.link)
        if links:
            f["links"] = _union(e.links, links)
        return [make_event(who, "set", e.id, f)]

    state: dict[str, Entry] = append(repo, build)
    verb: str = {
        "close": "closed", "drop": "dropped", "shelve": "shelved", "reopen": "reopened"
    }[cmd]
    print(f"{verb} {ids[0]}: {_cut(note)}{_in_stage(state[ids[0]])}")
    return 0


def _cmd_staged_land(a: argparse.Namespace) -> int:
    """`staged ID...`: open or running -> staged (D-49/D-50, work done, not
    landed). `land [ID...] [--stage S]`: staged -> done, all staged entries or
    the named ones, within one stage with --stage (D-51). One locked write, one
    receipt line per entry; any refusal refuses the whole call."""
    repo: Path = _repo(a)
    who: str = _name(a.who, "--who")
    note: str = _need_note(a)
    a.ref = _check_refs(repo, a.ref)
    staging: bool = a.cmd == "staged"
    ids: list[str] = []

    def build(state: dict[str, Entry]) -> list[dict[str, object]]:
        sid: str = resolve(state, a.stage, stage=True) if a.stage else ""
        named: list[str] = list(dict.fromkeys(resolve(state, i) for i in a.ids))
        if not staging and not named:
            named = [
                e.id
                for e in sorted(state.values(), key=lambda x: x.lines[0])
                if e.status == "staged" and (not sid or e.stage == sid)
            ]
        for i in named:
            e: Entry = state[i]
            if staging and e.type == "stage":
                raise LedgerError(f"{i} is a stage: a stage closes with stage-close")
            if staging and e.type == "decision":
                raise LedgerError(
                    f"{i} is a decision: decisions are in force when logged"
                )
            if staging and e.status not in ("open", "running"):
                raise LedgerError(f"cannot stage {i}: it is {e.status}")
            if not staging and e.status != "staged":
                raise LedgerError(f"cannot land {i}: it is {e.status}, not staged")
            if not staging and sid and e.stage != sid:
                raise LedgerError(
                    f"cannot land {i}: it is in {e.stage or 'no stage'}, not {sid}"
                )
            if staging:  # D-32: no work in a planned or shelved stage
                st: Entry | None = state.get(e.stage) if e.stage else None
                if st is not None and st.status in ("planned", "shelved"):
                    way: str = (
                        f"rk stage-open {st.id}" if st.status == "planned"
                        else f"re-stage it: rk set {i} --stage S-<x>" if _imported(st)
                        else f"rk set {st.id} --status planned, then rk stage-open "
                        f"{st.id}"
                    )
                    raise LedgerError(
                        f"cannot stage {i}: its stage {st.id} is {st.status} (work "
                        f"runs only in an open stage): {way}"
                    )
                _check_stage_open(
                    state, e.stage, e.type, "staged", "pick an open stage"
                )
        ids[:] = named
        return [
            make_event(who, "set", i, {
                "status": "staged" if staging else "done",
                "note": _note_plus(state[i].note, note),
                "reason": note,  # where the work sits / where it landed
                **({"refs": _union(state[i].refs, a.ref)} if a.ref else {}),
            })
            for i in named
        ]  # fmt: skip

    state: dict[str, Entry] = append(repo, build)
    verb: str = "staged" if staging else "landed"
    for i in ids:
        print(f"{verb} {i}: {_cut(note)}{_in_stage(state[i])}")
    if not ids:
        print(f"{verb} 0")
    return 0


def _stage_status(
    state: dict[str, Entry], e: Entry, status: str
) -> dict[str, object]:
    """The fields of `set S-n --status`: planned -> shelved, shelved -> planned
    (at the queue end, the old reason cleared), planned or shelved -> dropped (no
    open entry left in the stage). Anything else is refused with the command that
    does it; the caller adds the note as `reason`."""
    if e.type != "stage":
        raise LedgerError(
            f"--status {status}: set gives a status to a stage only; for {e.id} "
            "use close, drop, shelve, staged or reopen"
        )
    if status == "open":
        raise LedgerError(f"--status open: only stage-open opens: rk stage-open {e.id}")
    if status == "done":
        raise LedgerError(
            f"--status done: a stage closes with its sign-off: use stage-close {e.id}"
        )
    if (e.status, status) not in (
        ("planned", "shelved"), ("shelved", "planned"),
        ("planned", "dropped"), ("shelved", "dropped"),
    ):
        raise LedgerError(
            f"cannot set {e.id} from {e.status} to {status}: set --status takes "
            "planned -> shelved, shelved -> planned, planned or shelved -> dropped"
        )
    if status == "planned" and _imported(e):  # Q5: a legacy path, no P- folder
        raise LedgerError(
            f"{e.id} is imported: it has no P- folder and is not planned again; "
            "drop it or plan a new stage"
        )
    if status == "dropped":
        busy: list[Entry] = sorted(
            (x for x in state.values() if x.stage == e.id and _is_open(x)),
            key=lambda x: x.lines[0],
        )
        if busy:
            raise LedgerError(
                f"cannot drop {e.id}: entries of it are not closed: "
                + ", ".join(x.id for x in busy)
                + "; close, drop or re-stage each (set ID --stage S-x) first"
            )
    f: dict[str, object] = {"status": status}
    if status == "planned":
        f["queue"] = _queue_end(state)
        f["reason"] = ""
    return f


def _cmd_set(a: argparse.Namespace) -> int:
    repo: Path = _repo(a)
    who: str = _name(a.who, "--who")
    title: str | None = _title(a.title) if a.title is not None else None
    owner: str | None = _name(a.owner, "--owner") if a.owner is not None else None
    label: str | None = _label(a.label, "--label") if a.label is not None else None
    if not (
        title is not None
        or owner is not None
        or label is not None
        or a.stage is not None
        or a.note is not None
        or a.note_replace is not None
        or a.link
        or a.ref
        or a.ref_drop
        or a.before is not None
        or a.after is not None
        or a.status is not None
    ):
        raise LedgerError(
            "nothing to set (give --title, --owner, --label, --stage, --status, "
            "--note, --note-replace, --link, --ref, --ref-drop, --before or --after)"
        )
    if a.status in ("shelved", "dropped") and a.note is None:  # Q4
        raise LedgerError(
            f"--status {a.status} needs --note: why (it is stored as the reason)"
        )
    a.ref = _check_refs(repo, a.ref)
    a.ref_drop = _rel_refs(repo, a.ref_drop, "--ref-drop", strict=False)
    if a.note is not None and not a.note.strip():
        raise LedgerError(
            "--note adds a line to the note and needs text; "
            "--note-replace '' clears the note"
        )
    keys: list[str] = []
    ids: list[str] = []

    def build(state: dict[str, Entry]) -> list[dict[str, object]]:
        e: Entry = _entry(state, a.id)
        ids.append(e.id)
        f: dict[str, object] = {}
        if a.status is not None:
            f.update(_stage_status(state, e, a.status))
            if a.note is not None:
                f["reason"] = a.note  # why it has this status now
        if a.before is not None or a.after is not None:
            if e.type != "stage" or e.status != "planned":
                what: str = e.status if e.type == "stage" else f"a {e.type}"
                raise LedgerError(
                    f"{e.id} is {what}: --before/--after move a planned stage"
                )
            flag: str = "--before" if a.before is not None else "--after"
            ref: str = a.before if a.before is not None else a.after
            if resolve(state, ref, stage=True) == e.id:
                raise LedgerError(
                    f"{flag} {ref}: a stage cannot move relative to itself"
                )
            others: dict[str, Entry] = {k: v for k, v in state.items() if k != e.id}
            f["queue"] = _queue_slot(others, a.before, a.after)
        if title is not None:
            if e.type == "stage" and not _imported(e):
                raise LedgerError(
                    f"{e.id} is a stage: its title is its folder name "
                    f"({_stage_dir(e)}) and gives its code; rename it with rk "
                    f"stage-rename {e.id} <kind>-<topic>"
                )
            f["title"] = title
        if owner is not None:
            f["owner"] = owner
        if label is not None:
            old: object = e.extra.get("legacy_id")
            if _imported(e) and old not in (None, label):
                raise LedgerError(
                    f"{e.id} is imported with legacy id '{old}', its label and the "
                    "key that stops a second import of its row; it keeps it"
                )
            _check_label(state, label, e.id)
            f["legacy_id"] = label
        if a.stage is not None:
            sid: str = resolve(state, a.stage, stage=True)
            if sid != e.stage:  # the same stage again: no event
                _check_stage_open(state, sid, e.type, e.status, "pick an open stage")
                f["stage"] = sid
        if a.note is not None:
            f["note"] = _note_plus(e.note, a.note)
        elif a.note_replace is not None:
            f["note"] = a.note_replace
        links: list[str] = _links(state, a.link)
        if links:
            f["links"] = _union(e.links, links)
        if a.ref or a.ref_drop:
            unknown: list[str] = [r for r in a.ref_drop if r not in e.refs]
            if unknown:
                have: str = ", ".join(e.refs) or "none"
                raise LedgerError(
                    f"--ref-drop {', '.join(unknown)}: not a ref of {e.id} "
                    f"(refs: {have})"
                )
            kept: list[str] = [r for r in e.refs if r not in a.ref_drop]
            f["refs"] = _union(kept, a.ref)
        keys.extend("label" if k == "legacy_id" else k for k in f)
        return [make_event(who, "set", e.id, f)] if f else []

    state: dict[str, Entry] = append(repo, build)
    tail: str = _in_stage(state[ids[0]])
    print(f"updated {ids[0]}: {', '.join(keys)}{tail}" if keys
          else f"unchanged {ids[0]}{tail}")
    folder: str = _stage_dir(state[ids[0]])
    if a.status == "dropped" and "/P-" in folder and (repo / folder).is_dir():
        print(f"folder {folder} is left: move it to pm/waste")  # the waste step
    return 0


def _cmd_supersede(a: argparse.Namespace) -> int:
    repo: Path = _repo(a)
    who: str = _name(a.who, "--who")
    title: str = _title(a.title)
    if a.owner is None:
        raise LedgerError(
            "supersede needs --owner (who decided: user, lead or a teammate name)"
        )
    owner: str = _name(a.owner, "--owner")
    a.ref = _check_refs(repo, a.ref)
    made: list[str] = []

    def build(state: dict[str, Entry]) -> list[dict[str, object]]:
        old: Entry = _entry(state, a.id)
        if old.type != "decision":
            raise LedgerError(f"{old.id} is a {old.type}, not a decision")
        if old.status != "done":
            raise LedgerError(f"{old.id} is {old.status}, not in force")
        links: list[str] = _links(state, a.link)
        eid: str = next_id(state, BUILTIN_TYPES["decision"])
        f: dict[str, object] = {
            "type": "decision",
            "title": title,
            "status": "done",
            "owner": owner,
            "stage": _default_stage(state, "decision", False),
            "note": a.note or "",
            "links": _union([old.id], links),
            "refs": _union([], a.ref),
            "supersedes": old.id,
        }
        made.extend([eid, old.id])
        return [
            make_event(who, "add", eid, f),
            make_event(
                who, "set", old.id, {"status": "superseded", "superseded_by": eid}
            ),
        ]

    new: Entry = append(repo, build)[made[0]]
    print(f"logged {made[0]}: {title} (supersedes {made[1]}; {_stage_word(new)})")
    return 0


def _moved_ref(repo: Path, r: str, old: str, new: str) -> str | None:
    """`r` with the leading path `old` (whole path components, compared after
    normpath, so ./pm/x matches pm/x) replaced by `new`; None if no match. `old`
    and `new`: normpath'd repo paths."""
    if not _is_path(r):
        return None
    n: str = os.path.normpath(_rel_refs(repo, [r], strict=False)[0])
    if n != old and not n.startswith(old + "/"):
        return None
    return new + n[len(old):] + ("/" if r.endswith("/") else "")


def _refs_moved(
    repo: Path, state: dict[str, Entry], old: str, new: str
) -> tuple[dict[str, list[str]], int]:
    """The new refs of each entry with a ref under folder `old` (moved to `new`),
    by id, and how many ref strings change."""
    out: dict[str, list[str]] = {}
    k: int = 0
    for e in sorted(state.values(), key=lambda x: x.lines[0]):
        pairs: list[tuple[str, str | None]] = [
            (r, _moved_ref(repo, r, old, new)) for r in e.refs
        ]
        hits: int = sum(1 for _, m in pairs if m is not None)
        if hits:
            k += hits
            out[e.id] = list(dict.fromkeys(m or r for r, m in pairs))
    return out, k


def _append_renaming(
    repo: Path,
    build: Callable[[dict[str, Entry]], list[dict[str, object]]],
    moves: list[tuple[Path, Path]],
) -> dict[str, Entry]:
    """`append`; the folder renames `build` made (it lists them in `moves`, as
    its last step) are undone, under the lock, when anything fails before the
    ledger lines are written. A failure after that keeps them: the ledger and
    the folder are both new, and the error goes on."""

    def undo() -> None:
        for src, dst in reversed(moves):
            os.rename(dst, src)

    return append(repo, build, undo)


def _cmd_stage_open(a: argparse.Namespace) -> int:
    """Open planned stage S-n in one locked step: the next NN (a letter with
    --follows), its P- folder renamed to the NN folder, every ref under it
    rewritten; the rename is undone if anything fails before the ledger line is
    written, and kept if something fails after it."""
    repo: Path = _repo(a)
    who: str = _name(a.who, "--who")
    moves: list[tuple[Path, Path]] = []
    said: list[str] = []

    def build(state: dict[str, Entry]) -> list[dict[str, object]]:
        sid: str = resolve(state, a.id, stage=True)
        st: Entry = state[sid]
        if st.status != "planned":
            how: str = (
                f": rk set {sid} --status planned first"
                if st.status == "shelved" and not _imported(st) else ""
            )
            raise LedgerError(
                f"{sid} is {st.status}: only a planned stage opens{how}"
            )
        kept: object = st.extra.get("follows")  # given at plan time
        follows: str | None = (
            a.follows if a.follows is not None
            else kept if isinstance(kept, str) else None
        )
        title: str = _title(_open_title(state, st.title, follows))
        _check_names(state, "stage", title, a)
        _check_one_per_kind(state, title, f"stage-open {sid}")
        old: str = _stage_dir(st)
        new: str = f"pm/stages/{title}/"
        refs, k = _folder_move_refs(repo, state, f"stage-open {sid}", old, new)
        ev: dict[str, object] = make_event(
            who, "set", sid,
            {"status": "open", "title": title, "refs": refs.pop(sid, st.refs)},
        )  # fmt: skip
        ev["rules"] = rule_stamps(repo)
        evs: list[dict[str, object]] = [ev] + [
            make_event(who, "set", i, {"refs": r}) for i, r in refs.items()
        ]
        _rename_folder(repo, f"stage-open {sid}", old, new, moves)
        said[:] = [f"opened {sid}: {title}", f"folder {old} -> {new}"]
        said.append(f"refs: {k} rewritten")
        return evs

    _append_renaming(repo, build, moves)
    print("\n".join(said))
    return 0


def _folder_move_refs(
    repo: Path, state: dict[str, Entry], what: str, old: str, new: str
) -> tuple[dict[str, list[str]], int]:
    """Before stage folder `old` becomes `new` (`what`: the command and id, for
    the refusals): refuse a missing `old` or a `new` that is there (folders are
    never merged); then `_refs_moved` of the two."""
    if not (repo / old).is_dir():
        raise LedgerError(f"cannot {what}: no folder {old}; restore it first")
    same: bool = (  # a case-only rename where the file system ignores case
        old.lower() == new.lower()
        and not os.path.islink(repo / new)
        and os.path.lexists(repo / new)
        and os.path.samefile(repo / old, repo / new)
    )
    if os.path.lexists(repo / new) and not same:
        raise LedgerError(
            f"cannot {what}: {new} is there already; folders are not merged: move "
            "it away first"
        )
    return _refs_moved(repo, state, old.rstrip("/"), new.rstrip("/"))


def _rename_folder(
    repo: Path, what: str, old: str, new: str, moves: list[tuple[Path, Path]]
) -> None:
    """The last step of a `build` under `_append_renaming`: rename `old` to `new`
    and list it in `moves`; nothing may fail in `build` after it."""
    try:
        os.rename(repo / old, repo / new)
    except OSError as err:
        raise LedgerError(f"cannot {what}: {old} -> {new}: {err.strerror}") from None
    moves.append((repo / old, repo / new))


def _renamed_title(e: Entry, topic: str) -> str:
    """Stage `e`'s title with its kind-topic part replaced by `topic`: the
    NN[letter]- prefix of an opened or done stage stays; a planned or shelved one
    (no NN; its P-<n> is in the folder name) is just `topic`."""
    if STAGE_RE.match(e.title):
        return f"{e.title.split('-', 1)[0]}-{topic}"
    return topic


def _cmd_stage_rename(a: argparse.Namespace) -> int:
    """Rename a stage's kind-topic in one locked step: the NN or P-<n> stays,
    the folder is renamed, every ref under it rewritten (as stage-open); a done
    stage needs --note and gets its record written again."""
    repo: Path = _repo(a)
    who: str = _name(a.who, "--who")
    if not PLAN_RE.match(a.topic):
        raise LedgerError(
            f"stage-rename {a.id} '{a.topic}': want {PLAN_FORM} (letters, digits, "
            "_ . - in the topic); the NN or P-<n> stays"
        )
    if a.note is not None and not a.note.strip():
        raise LedgerError("--note needs text")
    moves: list[tuple[Path, Path]] = []
    said: list[str] = []
    done: list[str] = []

    def build(state: dict[str, Entry]) -> list[dict[str, object]]:
        sid: str = resolve(state, a.id, stage=True)
        st: Entry = state[sid]
        if _imported(st):
            raise LedgerError(
                f"{sid} is imported: its folder is a legacy path and keeps its name"
            )
        if st.status in ("dropped", "superseded"):
            raise LedgerError(
                f"{sid} is {st.status}: a dropped or superseded stage is not renamed"
            )
        if st.status == "done" and a.note is None:
            raise LedgerError(
                f"{sid} is done: renaming a closed stage needs --note: why (text "
                "outside the ledger keeps the old path)"
            )
        title: str = _title(_renamed_title(st, a.topic))
        if title == st.title:
            raise LedgerError(f"{sid} is named {title} already: nothing to rename")
        others: dict[str, Entry] = {k: v for k, v in state.items() if k != sid}
        _check_names(others, "stage", title, a)  # its own code stays its own
        if st.status == "open":
            _check_one_per_kind(others, title, f"stage-rename {sid}")
        old: str = _stage_dir(st)
        new: str = _stage_dir(replace(st, title=title))
        refs, k = _folder_move_refs(repo, state, f"stage-rename {sid}", old, new)
        f: dict[str, object] = {"title": title, "refs": refs.pop(sid, st.refs)}
        if a.note is not None:
            f["note"] = _note_plus(st.note, a.note)
        evs: list[dict[str, object]] = [make_event(who, "set", sid, f)] + [
            make_event(who, "set", i, {"refs": r}) for i, r in refs.items()
        ]
        _rename_folder(repo, f"stage-rename {sid}", old, new, moves)
        said[:] = [f"renamed {sid}: {st.title} -> {title}", f"folder {old} -> {new}"]
        said.append(f"refs: {k} rewritten")
        done[:] = [sid] if st.status == "done" else []
        return evs

    state: dict[str, Entry] = _append_renaming(repo, build, moves)
    print("\n".join(said))
    if done:  # its record is written again with the stage-close writer
        print(_write_stage_record(repo, state[done[0]]))
    return 0


def _cmd_reref(a: argparse.Namespace) -> int:
    repo: Path = _repo(a)
    who: str = _name(a.who, "--who")
    if not a.old.strip() or not a.new.strip():
        raise LedgerError("reref needs a non-empty OLD and NEW")
    # NEW as any --ref (absolute inside the repo made relative; outside refused);
    # OLD made relative the same way, but may name an old ref outside the repo
    old: str = os.path.normpath(_rel_refs(repo, [a.old], "OLD", strict=False)[0])
    new: str = os.path.normpath(_rel_refs(repo, [a.new], "NEW")[0])
    if new == old or new.startswith(old + "/"):
        raise LedgerError(
            f"reref: NEW {a.new} lies inside OLD {a.old}; a second run would apply "
            "again: move to a path outside OLD"
        )

    changed: list[tuple[str, str, str]] = []  # (id, old ref, new ref)

    def plan(state: dict[str, Entry]) -> list[dict[str, object]]:
        changed.clear()
        out: list[dict[str, object]] = []
        for e in sorted(state.values(), key=lambda x: x.lines[0]):
            pairs: list[tuple[str, str | None]] = [
                (r, _moved_ref(repo, r, old, new)) for r in e.refs
            ]
            hits: list[tuple[str, str]] = [(r, m) for r, m in pairs if m is not None]
            if not hits:
                continue
            refs: list[str] = list(dict.fromkeys(m or r for r, m in pairs))
            changed.extend((e.id, r, m) for r, m in hits)
            out.append(make_event(who, "set", e.id, {"refs": refs}))
        missing: list[str] = [
            f"{i} {n}" for i, _, n in changed if _is_path(n) and not _there(repo / n)
        ]
        if missing:
            more: str = f"\n  +{len(missing) - 20} more" if len(missing) > 20 else ""
            lines: str = "\n  ".join(missing[:20])
            raise LedgerError(
                f"reref refused, nothing written: {len(missing)} new path(s) do not "
                f"exist (move the files first):\n  {lines}{more}"
            )
        return out

    if a.dry_run:
        plan(load(repo))
    else:
        append(repo, plan)
    if not changed:
        print(f"no ref starts with '{a.old}'; nothing written")
        return 0
    for eid, o, n in changed:
        print(f"{eid} {o} -> {n}")
    n_ids: int = len({i for i, _, _ in changed})
    verb: str = "would change" if a.dry_run else "changed"
    tail: str = " (dry run, nothing written)" if a.dry_run else ""
    print(f"{verb} {len(changed)} refs of {n_ids} entries{tail}")
    return 0


def _nonneg(value: int, flag: str) -> int:
    if value < 0:
        raise LedgerError(f"{flag} must not be negative")
    return value


def _cmd_list(a: argparse.Namespace) -> int:
    repo: Path = _repo(a)
    state: dict[str, Entry] = load(repo)
    typ: str | None = check_type(a.type, known_types(repo)) if a.type else None
    stage: str | None = resolve(state, a.stage, stage=True) if a.stage else None
    print(
        format_list(
            state,
            datetime.now().astimezone(),
            type_=typ,
            owner=a.owner,
            stage=stage,
            limit=_nonneg(a.limit, "--limit"),
            include_closed=a.all,
            status=a.status,
        )
    )
    return 0


def _val(v: object) -> str:
    s: str = v if isinstance(v, str) else json.dumps(v)
    return s.replace("\n", "\\n")[:60]


def _meta(ev: dict[str, object]) -> str:
    """kit, sid and rules of an event as one line ('' when it has none)."""
    parts: list[str] = []
    for k in ("kit", "sid", "rules"):
        v: object = ev.get(k)
        if k == "rules" and isinstance(v, dict):
            v = ",".join(f"{f}:{s}" for f, s in v.items()) or "none"
        if v is not None:
            parts.append(f"{k}={v if isinstance(v, str) else json.dumps(v)}")
    return " ".join(parts)


def _cmd_show(a: argparse.Namespace) -> int:
    repo: Path = _repo(a)
    events: list[tuple[int, dict[str, object]]] = read_events(repo)
    state: dict[str, Entry] = fold(events)
    entries: list[Entry] = [_entry(state, ref) for ref in a.id]  # all or none
    for i, e in enumerate(entries):
        if i:
            print()
        _show_one(e, state, events)
    return 0


def _show_one(
    e: Entry, state: dict[str, Entry], events: list[tuple[int, dict[str, object]]]
) -> None:
    fields: list[tuple[str, str]] = [  # the legacy_id field shows as label
        ("id", e.id), ("label", str(e.extra.get("legacy_id", ""))),
        ("type", e.type), ("title", e.title), ("status", e.status),
        *(  # D-56: one line when the shown status differs
            [("shown", f"{s} (stage {e.stage} is {s})")]
            if (s := shown_status(state, e)) != e.status else []
        ),
        ("owner", e.owner), ("stage", e.stage),
        ("note", e.note.replace("\n", "\\n")),
        ("links", ", ".join(e.links)), ("refs", ", ".join(e.refs)),
        ("created", e.created), ("updated", e.updated),
        *(
            (k, str(v).replace("\n", "\\n"))
            for k, v in e.extra.items()
            if k != "legacy_id" and (k != "queue" or e.status == "planned")
        ),
    ]
    for k, v in fields:
        print(f"{k}: {v}")
    linked: list[str] = _union(
        e.links, [x.id for x in state.values() if e.id in x.links]
    )
    if linked:
        print("linked:")
        for lid in linked:
            x: Entry | None = state.get(lid)
            print(
                _clip(f"  {lid} {shown_status(state, x)}: {x.title}") if x
                else f"  {lid} unknown"
            )
    print("history:")
    for _, ev in events:
        if ev.get("id") != e.id:
            continue
        f: object = ev.get("f")
        pairs: str = ", ".join(
            f"{k}={_val(v)}" for k, v in (f.items() if isinstance(f, dict) else [])
        )
        print(f"  {ev.get('ts')} {ev.get('who')} {ev.get('ev')} {pairs}")
        meta: str = _meta(ev)
        if meta:
            print(f"    {meta}")


def _cmd_search(a: argparse.Namespace) -> int:
    repo: Path = _repo(a)
    state: dict[str, Entry] = load(repo)
    typ: str | None = check_type(a.type, known_types(repo)) if a.type else None
    exact: bool = a.source is not None or a.legacy_id is not None
    if a.text is None and not exact:
        raise LedgerError("search needs TEXT, --source or --label")
    needle: str = (a.text or "").lower()
    hits: list[Entry] = [
        e
        for e in state.values()
        if (typ is None or e.type == typ)
        and (a.source is None or e.extra.get("source") == a.source)
        and (a.legacy_id is None or e.extra.get("legacy_id") == a.legacy_id)
        and any(
            needle in str(s).lower()
            for s in (e.title, e.note, e.extra.get("legacy_id", ""),
                      e.extra.get("source", ""))
        )
    ]
    limit: int = _nonneg(a.limit, "--limit")
    cap: list[Entry] = hits[:limit] if limit else hits
    for e in cap:
        src: str = f" [src {e.extra['source']}]" if _imported(e) else ""
        print(f"{e.id} {shown_status(state, e)}: {e.title}{src}")
    if len(cap) < len(hits):
        print(_more(len(hits) - len(cap)))
    return 0


def _cmd_recent(a: argparse.Namespace) -> int:
    repo: Path = _repo(a)
    events: list[tuple[int, dict[str, object]]] = read_events(repo)
    state: dict[str, Entry] = fold(events)
    if a.n < 1:
        raise LedgerError("-n must be at least 1")
    seen: set[str] = set()
    for _, ev in reversed(events):
        eid: str = str(ev["id"])
        if eid in seen:
            continue
        seen.add(eid)
        e: Entry = state[eid]
        print(
            _clip(
                f"{str(ev['ts'])[:16]} {ev['who']} {ev['ev']} {eid} "
                f"{e.status}: {e.title}"
            )
        )
        if len(seen) == a.n:
            break
    return 0


def _cmd_render(a: argparse.Namespace) -> int:
    repo: Path = _repo(a)
    state: dict[str, Entry] = append(repo, lambda s: [])
    n: int = sum(1 for e in state.values() if _shown_open(state, e))  # D-56
    print(f"wrote {STATUS_REL} ({n} open)")
    return 0


def _sign_off_problems(
    state: dict[str, Entry], sid: str, sign: str | None, reopened: int = 0
) -> list[str]:
    """Why `sign` is not a valid sign-off for stage `sid` (empty = valid).
    `reopened`: ledger line of the stage's last reopen (0: never reopened); a
    sign-off logged before it signed off the earlier close, not this one."""
    fix: str = (
        f"ask the user to sign off {sid}; only after the user has given it, log "
        f'it (add decision "sign-off: {state[sid].title}" --owner user --link '
        f"{sid}) and pass its id. Never log a sign-off the user has not given"
    )
    if not sign:
        return [f"needs --sign-off D-<m>, a user decision with --link {sid}; {fix}"]
    d: Entry | None = state.get(sign)
    if d is None or d.type != "decision":
        return [f"{sign} is not a decision; {fix}"]
    out: list[str] = []
    if d.owner != "user":
        out.append(f"{sign} has owner {d.owner}; the sign-off needs owner user")
    if d.status != "done":
        out.append(f"{sign} is {d.status}, not in force")
    if sid not in d.links:  # its stage field alone is not enough: decisions
        # default to the single open stage, so any user decision would pass
        out.append(f"{sign} does not link {sid} (--link {sid}); {fix}")
    if d.lines[0] < reopened:
        out.append(
            f"{sign} was logged before {sid} was reopened (line {reopened}); a "
            f"reopened stage needs a new sign-off; {fix}"
        )
    return out


def _reopen_line(events: list[tuple[int, dict[str, object]]], sid: str) -> int:
    """Line of the last reopen of stage `sid` (a set to open); 0 if none. The
    stage-open of a planned stage (planned -> open) is no reopen."""
    line: int = 0
    was: object = None
    for n, ev in events:
        f: object = ev.get("f")
        if ev.get("id") != sid or not isinstance(f, dict):
            continue
        if ev.get("ev") == "set" and f.get("status") == "open" and was != "planned":
            line = n
        was = f.get("status", was)
    return line


def _stage_checks(repo: Path, ref: str, local: bool) -> None:
    """The doctor checks of one open stage, before it is closed: prints what
    they find; refuses (LedgerError) on a missing ref or stage folder.
    `local`: pm/ is local only (`_findings`)."""
    raw: bytes = (repo / LEDGER_REL).read_bytes()
    events: list[tuple[int, dict[str, object]]] = _parse(raw)
    state: dict[str, Entry] = fold(events)
    sid: str = resolve(state, ref, stage=True)
    if state[sid].status != "open":
        return  # refused below, with the reason
    found, notes = _findings(repo, raw, events, state, sid, False, local)
    if not found:  # the git and pm notes alone are not worth a line (D-73)
        return
    n_hard: int = _print_findings(found, notes, f"checks {sid}")
    if n_hard:
        raise LedgerError(
            f"stage-close {sid} refused: {n_hard} HARD finding(s) above; a missing "
            "ref: restore the file or set <id> --ref-drop <path>; a missing stage "
            f"folder: restore {_stage_dir(state[sid])}"
        )


def _stamps(ev: dict[str, object] | None) -> str:
    rules: object = ev.get("rules") if ev else None
    if not isinstance(rules, dict) or not rules:
        return "none"
    return ", ".join(f"{k} {v}" for k, v in sorted(rules.items()))


def render_stage_record(
    events: list[tuple[int, dict[str, object]]], sid: str
) -> str:
    """The record of closed stage `sid` as of its close: a function of the ledger
    lines up to the close alone (no clock), so it is the same when made again.
    Stage entries, entries touched in the window (the stage's open spans: add or
    reopen to close), decisions by owner, what is left open, the kit, session
    and rule values seen. A reopened stage's record also carries RECORD_MARK and
    a `Reopened` part; a stage never reopened gets no such line. The one thing
    read after the close (D-43): a later title change adds the line `renamed to
    <title> on <date>` (the last one) below the head, which keeps the title at
    the close."""
    end: int = _close_line(events, sid) or 0
    upto: list[tuple[int, dict[str, object]]] = [(n, v) for n, v in events if n <= end]
    state: dict[str, Entry] = fold(upto)
    st: Entry = state[sid]
    spans: list[tuple[int, int]] = [
        (lo, end if hi is None else hi)
        for lo, hi in _record_spans(upto, sid, st.lines[0])
    ]
    first: int = spans[0][0]  # the add line, or the stage-open of a planned add
    added_closed: bool = spans[0] == (first, first)  # span 0 is the add line only
    window: list[tuple[int, dict[str, object]]] = [
        (n, v) for n, v in upto if any(lo <= n <= hi for lo, hi in spans)
    ]
    by_line: dict[int, dict[str, object]] = dict(upto)
    from_ts: object = (  # created: an imported stage's --date, as in 0.2.4
        st.created if first == st.lines[0] else by_line[first].get("ts")
    )
    window_line: str = (  # one span: the form of 0.2.3, byte for byte
        f"Window: ledger lines {first} to {end}, {from_ts} to {st.updated}."
        if len(spans) == 1
        else "Window: ledger lines " + ", ".join(  # times per span, not across gaps
            f"{lo} to {hi} ({by_line[lo].get('ts')} to {by_line[hi].get('ts')})"
            for lo, hi in spans
        ) + "."
    )
    add_f: object = by_line[st.lines[0]].get("f")
    add_status: object = add_f.get("status") if isinstance(add_f, dict) else None
    reopens: list[str] = []
    for k, ((lo, _), (_, closed)) in enumerate(zip(spans[1:], spans)):
        ev: dict[str, object] = by_line[lo]
        f: object = ev.get("f")
        why: object = f.get("reason") if isinstance(f, dict) else None
        tail: str = f": {_cut(why)}" if isinstance(why, str) and why.strip() else ""
        since: str = (  # span 0 of a stage imported not open was no close
            f"import at line {closed} ({add_status})"
            if k == 0 and added_closed
            else f"close at line {closed}"
        )
        reopens.append(
            f"- line {lo}, {str(ev.get('ts'))[:10]}, {ev.get('who')}, after the "
            f"{since}{tail}"
        )
    touched: set[object] = {v.get("id") for _, v in window} - {sid}
    mine: list[Entry] = [e for e in state.values() if e.stage == sid and e.id != sid]
    other: list[Entry] = [
        e for e in state.values() if e.id in touched and e.stage != sid
    ]
    mine.sort(key=lambda e: e.lines[0])
    other.sort(key=lambda e: e.lines[0])

    def line(e: Entry) -> str:
        why: object = e.extra.get("reason")  # beside a dropped entry: the why
        tail: str = (
            f" -- reason: {_cut(why)}"
            if e.status in ("dropped", "shelved") and isinstance(why, str) and why
            else ""
        )
        return f"- {e.id} {e.type} {e.status} ({e.owner}) {e.title}{tail}"

    def part(title: str, lines: list[str]) -> list[str]:
        return ["", f"## {title}", *(lines or ["none"])]

    decs: list[Entry] = [e for e in [*mine, *other] if e.type == "decision"]
    by_owner: list[str] = []
    for who in sorted({e.owner for e in decs}):
        by_owner += [f"### {who}"] + [
            f"- {e.id} {e.title}" + ("" if e.status == "done" else f" ({e.status})")
            for e in decs
            if e.owner == who
        ]

    def seen(key: str) -> str:
        vals: list[str] = [str(v[key]) for _, v in window if v.get(key)]
        return ", ".join(dict.fromkeys(vals)) or "none"

    close_ev: dict[str, object] = by_line[end]
    renamed: list[str] = []  # D-43: a title change after the close, the last one
    for n, v in events:
        nf: object = v.get("f")
        if n > end and v.get("id") == sid and isinstance(nf, dict) and "title" in nf:
            renamed = [f"renamed to {nf['title']} on {str(v.get('ts'))[:10]}"]
            if nf["title"] == st.title:  # back to the title at the close
                renamed = []
    out: list[str] = [
        _record_head(st),
        *renamed,
        *([RECORD_MARK.format(sid=sid, end=end)] if reopens else []),
        "",
        f"Generated from {LEDGER_REL} by rk.py when the stage was closed; frozen",
        "with the stage. Do not edit: hand edits are blocked.",
        window_line,
        *(part(f"Reopened ({len(reopens)})", reopens) if reopens else []),
        *part(f"Entries of the stage ({len(mine)})", [line(e) for e in mine]),
        *part(
            f"Entries touched in the window, not of the stage ({len(other)})",
            [f"{line(e)} [{_stage_word(e)}]" for e in other],
        ),
        *part("Decisions by owner", by_owner),
        *part(
            "Left open",
            [line(e) for e in [*mine, *other] if _is_open(e)],
        ),
        "",
        "## Seen in the window",
        f"kit: {seen('kit')}",
        f"sid: {seen('sid')}",
        f"rules at open: {_stamps(by_line[first])}",
        f"rules at close: {_stamps(close_ev)}",
    ]
    return "\n".join(out) + "\n"


def _record_head(st: Entry) -> str:
    return f"# Ledger of stage {st.id} {st.title} (generated)"


def _record_current(
    text: str | None, events: list[tuple[int, dict[str, object]]], sid: str
) -> bool:
    """Whether `text` is the record of the last close of stage `sid`: its first
    line (the title at the close) and its RECORD_MARK match the record made now.
    A record without the mark (a stage never reopened, or written by 0.2.3 and
    earlier) matches by its `Window:` line in the 0.2.3 form, frozen here so
    that a later change of the record's wording does not make it stale."""
    if text is None:
        return False
    want: str = render_stage_record(events, sid)
    if text.split("\n", 1)[0] != want.split("\n", 1)[0]:
        return False

    def renamed(t: str) -> str | None:
        """The `renamed to` line below the head (D-43), if there is one."""
        second: list[str] = t.split("\n", 2)[1:2]
        return second[0] if second and second[0].startswith("renamed to ") else None

    if renamed(text) != renamed(want):  # a title change after the close
        return False
    mark: re.Match[str] | None = RECORD_MARK_RE.search(text)
    if mark is not None:
        now: re.Match[str] | None = RECORD_MARK_RE.search(want)
        return now is not None and now.group(0) == mark.group(0)
    end: int = _close_line(events, sid) or 0
    upto: list[tuple[int, dict[str, object]]] = [(n, v) for n, v in events if n <= end]
    st: Entry = fold(upto)[sid]
    lo: int = _record_spans(upto, sid, st.lines[0])[0][0]  # add line, or the open
    from_ts: object = st.created if lo == st.lines[0] else dict(upto)[lo].get("ts")
    old: str = (  # 0.2.3: one span, add to close; never change this literal
        f"Window: ledger lines {lo} to {end}, {from_ts} to {st.updated}."
    )
    return old in text.split("\n")


def _file_text(path: Path) -> str | None:
    """A file's text; None if it is not there or not readable."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _record_folder(repo: Path, st: Entry) -> Path | None:
    """The folder for the record of stage `st`; None when its title is no folder
    name (`.`, `..`, odd characters) or an imported stage has no folder."""
    folder: Path = repo / _stage_dir(st)
    if st.title in (".", "..") or not NAME_RE.match(st.title):
        return None
    return None if _imported(st) and not os.path.isdir(folder) else folder


def _first_line(path: Path) -> str | None:
    """First line of a file; None if it is not there or not readable."""
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            return fh.readline().rstrip("\n")
    except OSError:
        return None


def _write_stage_record(repo: Path, st: Entry) -> str:
    """Write LEDGER.md into the folder of the closed stage `st`; the receipt line.
    Only stage-close calls this; the file is never edited by hand. A file that
    is there without the generated header is not overwritten."""
    rel: str = f"{_stage_dir(st)}{STAGE_RECORD}"
    folder: Path | None = _record_folder(repo, st)
    if folder is None:
        return f"no {STAGE_RECORD}: {st.id} has no folder {_stage_dir(st)}"
    tmp: Path = folder / (STAGE_RECORD + ".tmp")
    again: str = f"; then run rk stage-close {st.id} to write it"
    try:
        text: str = render_stage_record(read_events(repo), st.id)
        have: str | None = _first_line(folder / STAGE_RECORD)
        if have is not None and have != text.split("\n", 1)[0]:
            raise LedgerError(
                f"{st.id} is closed, but {rel} is there and is not a generated "
                f"record: not overwritten; move it away{again}"
            )
        folder.mkdir(parents=True, exist_ok=True)
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, folder / STAGE_RECORD)
    except OSError as err:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise LedgerError(
            f"{st.id} is closed, but {rel} could not be written: {err.strerror}"
            f"; fix that{again}"
        ) from None
    return f"wrote {rel}"


def _cmd_stage_close(a: argparse.Namespace) -> int:
    repo: Path = _repo(a)
    local: bool = read_config(repo)["pm"] == "local"  # broken: refused, no write
    who: str = _name(a.who, "--who")
    a.ref = _check_refs(repo, a.ref)
    state: dict[str, Entry] = load(repo)
    st: Entry = state[resolve(state, a.id, stage=True)]
    folder: Path | None = _record_folder(repo, st)
    if (  # a closed stage without the record of its last close: write it only
        st.status == "done"
        and folder is not None
        and not _record_current(
            _file_text(folder / STAGE_RECORD), read_events(repo), st.id
        )
    ):
        print(f"{st.id} is already closed; no ledger line written")
        print(_write_stage_record(repo, st))
        return 0
    _stage_checks(repo, a.id, local)
    out: list[str] = []
    closed: list[str] = []

    def build(state: dict[str, Entry]) -> list[dict[str, object]]:
        sid: str = resolve(state, a.id, stage=True)
        stage: Entry = state[sid]
        sign: str = a.sign_off or ""
        if sign and sign not in state and _matches(state, sign):
            sign = resolve(state, sign)  # a label; an unknown ref stays as given
        if stage.status != "open":  # the one reason: the rest would not apply
            raise LedgerError(
                f"stage-close {sid} refused: {sid} is {stage.status}, not open"
            )
        problems: list[str] = []
        busy: list[Entry] = sorted(
            (
                e
                for e in state.values()
                if e.type == "task" and e.stage == sid and _is_open(e)
            ),
            key=lambda e: _num(e.id),
        )
        if busy:
            t: str = busy[0].id
            land: str = (
                "land the staged ones once merged (rk land T-<n>...), "
                if any(e.status == "staged" for e in busy) else ""
            )
            problems.append(
                ", ".join(f"{e.id} {e.status}" for e in busy)
                + f": {land}close, drop, shelve, re-stage (set {t} --stage S-<x>) or "
                f"defer them (add deferred ... --link {t}, then drop {t} --note"
                ' "deferred as DF-<k>")'
            )
        reopened: int = _reopen_line(read_events(repo), sid)  # under append's lock
        problems += _sign_off_problems(state, sid, sign, reopened)
        if problems:
            raise LedgerError(f"stage-close {sid} refused: " + "; ".join(problems))
        f: dict[str, object] = {
            "status": "done",
            "note": _note_plus(stage.note, f"closed; sign-off {sign}"),
            "links": _union(stage.links, [sign]),
        }
        if "reason" in stage.extra:  # a reopen's why must not stand beside done
            f["reason"] = f"closed; sign-off {sign}"
        if a.ref:
            f["refs"] = _union(stage.refs, a.ref)
        out.append(f"closed {sid}: sign-off {sign}")
        closed.append(sid)
        ev: dict[str, object] = make_event(who, "set", sid, f)
        ev["rules"] = rule_stamps(repo)
        return [ev]

    state = append(repo, build)
    print(out[0])
    print(_write_stage_record(repo, state[closed[0]]))
    return 0


# ---- doctor -----------------------------------------------------------------

Finding = tuple[bool, str, str]  # (hard, group, one line)
G_PARSE: str = "ledger does not parse"
G_REF: str = "missing ref"
G_FOLDER: str = "missing stage folder"
G_HEAD: str = "ledger not append-only against HEAD"
G_IGNORED: str = (
    "ref in a git-ignored or waste folder (move the file to the stage's "
    "notes/team/ or pm/logs/team/, then rk reref)"
)
G_UNCOMMITTED: str = "done stage not in HEAD (the user commits it)"
G_NOSTAGE: str = (
    "entry without stage, made while a stage was open (set ID --stage S-n)"
)
G_LATE: str = (
    "entry without stage, made after a stage closed, before the next opened "
    "(set ID --stage S-n; an open task only into an open stage)"
)
G_RUNNING: str = (
    f"task running over {RUNNING_MAX_H} h (close, drop or shelve it, or set ID "
    "--note why)"
)
G_IMPORTED: str = (
    "missing refs of imported entries (rk set ID --ref-drop PATH, or rk reref "
    "after a move)"
)
G_WASTE_GONE: str = (
    "ref into the waste folder, file gone (rk set ID --ref-drop PATH)"
)
G_IGNORED_GONE: str = (
    "ref to a git-ignored file that is not here (a clone has none; lost if this "
    "is the main checkout: git keeps no copy; if gone for good: rk set ID "
    "--ref-drop PATH)"
)
G_FOLDER_EMPTY: str = (
    "stage folder not here, and git has no file of it (a clone has no empty "
    "folders; mkdir it when work starts)"
)
G_OUTSIDE: str = (
    "ref outside the repo or absolute (breaks in a clone: rk set ID --ref-drop "
    "PATH --ref <repo-relative path>, or rk reref)"
)
G_STATUS_WORD: str = (
    "imported entry titled with a status word, the old system's state (rk set "
    "ID --title TEXT; the entry's own status is the real one)"
)
G_DONE_OPEN: str = (
    "done entry whose title starts with 'open:' or 'OPEN ' (rk set ID --title TEXT)"
)
STATUS_WORD_RE: re.Pattern[str] = re.compile(r"^(open|done|todo)[:\s]", re.I)
# "open access check" is a title; "OPEN: ..." / "OPEN ..." is a status
DONE_OPEN_RE: re.Pattern[str] = re.compile(r"^(?:(?i:open):|OPEN\s)")
G_STAMPS: str = "rule file behind the kit (run /rk-sync)"
G_DECISIONS: str = "decisions of the stage not owned by user (for the sign-off)"
_CONFIG_REL: str = "pm/config.json"
_G_CONFIG: str = f"{_CONFIG_REL} does not parse"
_LOCAL_NOTICE: str = f"pm: local only ({_CONFIG_REL}): git checks on pm/ skipped"


def read_config(repo: Path) -> dict[str, object]:
    """The object of pm/config.json with `pm` always set ("tracked" without the
    file or key); a linked worktree without the file reads its main checkout's
    (`_main_checkout`). The only reader of the file; no git, no write."""
    try:
        raw: bytes = (repo / _CONFIG_REL).read_bytes()
    except (FileNotFoundError, NotADirectoryError):
        main: Path = _main_checkout(repo)
        if main == repo:
            return {"pm": "tracked"}
        try:
            return read_config(main)
        except LedgerError as e:  # name the file read: the main checkout's (DB-68)
            msg: str = str(e).removeprefix(_CONFIG_REL)
            raise LedgerError(f"{main / _CONFIG_REL}{msg}") from None
    except OSError:  # a folder, no permission: as unreadable JSON
        raw = b""
    try:
        obj: object = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):  # not UTF-8, not JSON, nested too deep
        obj = None
    if not isinstance(obj, dict):
        raise LedgerError(f"{_CONFIG_REL}: not a JSON object")
    cfg: dict[str, object] = obj
    cfg.setdefault("pm", "tracked")
    if cfg["pm"] not in ("local", "tracked"):
        raise LedgerError(f'{_CONFIG_REL}: "pm" must be "local" or "tracked"')
    return cfg


def _under_pm(ref: str) -> bool:
    """`ref` lies under pm/ (design I7)."""
    p: str = os.path.normpath(ref)
    return p == "pm" or p.startswith("pm/")


def _git(
    repo: Path, args: list[str], stdin: bytes = b""
) -> subprocess.CompletedProcess[bytes] | None:
    """A read-only git command run in `repo`; None when git cannot run."""
    if args[0] not in GIT_READ:
        raise ValueError(f"git {args[0]}: not a read-only command")
    exe: str | None = shutil.which("git")
    if exe is None:
        return None
    env: dict[str, str] = {  # no index write; this repo, not an inherited GIT_DIR
        **{k: v for k, v in os.environ.items() if k not in GIT_LOCAL_ENV},
        "GIT_OPTIONAL_LOCKS": "0",
    }
    try:
        return subprocess.run(
            [exe, "-C", str(repo), *args],
            input=stdin, capture_output=True, env=env, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _git_skip(repo: Path) -> str:
    """Why the git checks are skipped; '' when git works in `repo`."""
    if shutil.which("git") is None:
        return "git: no git binary; git checks skipped"
    r: subprocess.CompletedProcess[bytes] | None = _git(
        repo, ["ls-files", "--", LEDGER_REL]
    )
    if r is None or r.returncode != 0:
        return "git: not a git repo; git checks skipped"
    return ""


def git_exclude_file(repo: Path) -> Path | None:
    """Absolute path of git's exclude file for `repo` (a linked worktree: the
    main checkout's); None when git cannot run or `repo` is in no git repo."""
    r: subprocess.CompletedProcess[bytes] | None = _git(
        repo, ["rev-parse", "--git-path", "info/exclude"]
    )
    out: bytes = r.stdout.rstrip(b"\n") if r is not None and r.returncode == 0 else b""
    return (repo / os.fsdecode(out)).resolve() if out else None


def git_prefix(repo: Path) -> str | None:
    """`repo` below the git top level with a trailing slash ("" at the top
    level); None when git cannot run or `repo` is in no git repo."""
    r: subprocess.CompletedProcess[bytes] | None = _git(
        repo, ["rev-parse", "--show-prefix"]
    )
    if r is None or r.returncode != 0:
        return None
    return os.fsdecode(r.stdout.removesuffix(b"\n"))


def git_tracked(repo: Path, rel: str) -> bool:
    """git has a file at or under `rel` in `repo`; False when git cannot run."""
    r: subprocess.CompletedProcess[bytes] | None = _git(repo, ["ls-files", "--", rel])
    return r is not None and r.returncode == 0 and bool(r.stdout)


def _head_lines(repo: Path, raw: bytes) -> tuple[int, int | None]:
    """(ledger lines that are in HEAD, first line that differs from HEAD or None).

    A ledger not in HEAD counts as 0 lines committed."""
    r: subprocess.CompletedProcess[bytes] | None = _git(
        repo, ["show", f"HEAD:./{LEDGER_REL}"]
    )
    head: bytes = r.stdout if r is not None and r.returncode == 0 else b""
    tail: bytes = raw[len(head):len(head) + 1]
    if raw.startswith(head) and (not head or head.endswith(b"\n") or tail in b"\n"):
        return head.count(b"\n") + (0 if head.endswith(b"\n") or not head else 1), None
    hl: list[bytes] = head.split(b"\n")
    cl: list[bytes] = raw.split(b"\n")
    same: int = next(
        (i for i, (x, y) in enumerate(zip(hl, cl)) if x != y), min(len(hl), len(cl))
    )
    return same, same + 1


def _close_line(events: list[tuple[int, dict[str, object]]], sid: str) -> int | None:
    """Line of the event that made stage `sid` done (None while it is not)."""
    line: int | None = None
    for n, ev in events:
        f: object = ev.get("f")
        if ev.get("id") == sid and isinstance(f, dict) and "status" in f:
            line = n if f["status"] == "done" else None
    return line


def _stage_spans(
    events: list[tuple[int, dict[str, object]]], sids: set[str]
) -> dict[str, list[tuple[int, int | None]]]:
    """For each stage in `sids`: (open line, close line or None) of each time it
    was open, from its add or a reopen to the next close."""
    out: dict[str, list[tuple[int, int | None]]] = {s: [] for s in sids}
    for n, ev in events:
        f: object = ev.get("f")
        sp: list[tuple[int, int | None]] | None = out.get(str(ev.get("id")))
        if sp is None or not isinstance(f, dict):
            continue
        if f.get("status") == "open" and (not sp or sp[-1][1] is not None):
            sp.append((n, None))
        elif f.get("status") == "done" and sp and sp[-1][1] is None:
            sp[-1] = (sp[-1][0], n)
    return out


def _with_add_span(
    found: list[tuple[int, int | None]], add: int
) -> list[tuple[int, int | None]]:
    """A stage's spans as its record and doctor count them: `found` (from
    `_stage_spans`), and for a stage added not open (imported done) its add line
    as span 0, closed on that line, so a later reopen counts as one."""
    return found if found and found[0][0] == add else [(add, add), *found]


def _record_spans(
    events: list[tuple[int, dict[str, object]]], sid: str, add: int
) -> list[tuple[int, int | None]]:
    """A stage's spans as its record counts them: a stage added planned starts
    at its stage-open (the planned add is no close, the open no reopen); any
    other stage as `_with_add_span`."""
    found: list[tuple[int, int | None]] = _stage_spans(events, {sid})[sid]
    f: object = dict(events)[add].get("f")
    if isinstance(f, dict) and f.get("status") == "planned":
        return found
    return _with_add_span(found, add)


def _ignored(repo: Path, refs: list[str]) -> set[str]:
    """Those of `refs` git ignores (`check-ignore`; works for missing files too;
    tracked files are never ignored). Empty set when git cannot tell."""
    paths: list[str] = list(dict.fromkeys(refs))
    if not paths:
        return set()
    res: subprocess.CompletedProcess[bytes] | None = _git(
        repo, ["check-ignore", "--stdin", "-z"], "\0".join(paths).encode() + b"\0"
    )
    if res is None or res.returncode not in (0, 1):  # 1: none ignored
        return set()
    return set(res.stdout.decode(errors="replace").split("\0")) - {""}


def _waste(ref: str) -> bool:
    return (os.path.normpath(ref) + "/").startswith(WASTE_DIRS)


def _findings(
    repo: Path,
    raw: bytes,
    events: list[tuple[int, dict[str, object]]],
    state: dict[str, Entry],
    only: str | None,
    ledger_wide: bool,
    local: bool = False,
) -> tuple[list[Finding], list[str]]:
    """(findings, notes) for the whole ledger, or for stage `only` and its entries.

    `ledger_wide`: also the checks that are not about one stage (ledger against
    HEAD, rule stamps). `local`: pm/ is local only (design R5, R6): no git check
    on a path under pm/; a missing ref there or stage folder is HARD; nothing
    against HEAD. Read-only: writes nothing, git read-only commands only."""
    out: list[Finding] = []
    skip: str = _git_skip(repo)
    notes: list[str] = [_LOCAL_NOTICE] * local + ([skip] if skip else [])
    entries: list[Entry] = sorted(
        (e for e in state.values() if only is None or only in (e.id, e.stage)),
        key=lambda e: e.lines[0],
    )
    spans: dict[str, list[tuple[int, int | None]]] = {  # as in the record, all
        sid: _with_add_span(sp, state[sid].lines[0])
        for sid, sp in _stage_spans(
            events, {x.id for x in state.values() if x.type == "stage"}
        ).items()
    }
    # folder and not-in-HEAD checks (scope unchanged): an imported stage only
    # once it was reopened here (a span that does not start at its import line);
    # not a dropped stage: its folder goes to pm/waste
    stages: list[Entry] = [
        e for e in entries
        if e.type == "stage"
        and e.status != "dropped"
        and (not _imported(e) or any(lo != e.lines[0] for lo, _ in spans[e.id]))
    ]
    present: list[tuple[str, str]] = []  # (id, ref) of refs that exist
    imp: list[tuple[str, str]] = []
    gone: list[tuple[str, str]] = []  # missing, not imported, not in waste
    for e in entries:
        own: str = _stage_dir(e) if e.type == "stage" else ""
        for r in e.refs:
            if not _is_path(r) or r == own:  # own folder: the folder check
                continue
            if _outside(r):  # absolute or ../: breaks in a clone, never checked
                out.append((False, G_OUTSIDE, _clip(f"{e.id} {r}", TITLE_MAX)))
            elif _there(repo / r):
                present.append((e.id, r))
            elif _imported(e):
                imp.append((e.id, r))
            elif _waste(r):  # an older kit put reports there; the user empties it
                out.append((False, G_WASTE_GONE, _clip(f"{e.id} {r}", TITLE_MAX)))
            else:
                gone.append((e.id, r))
    # a clone has no git-ignored files: such a missing ref is no damage; a
    # local pm/ is in no clone, so a missing ref there is (D-67)
    def local_pm(r: str) -> bool:
        return local and _under_pm(r)

    ign: set[str] = set() if skip else _ignored(
        repo, [r for _, r in gone if not local_pm(r)]
    )
    for i, r in gone:
        txt: str = _clip(f"{i} {r}", TITLE_MAX)
        if local_pm(r):
            out.append((True, G_REF, txt))
        elif r in ign or KIT_IGNORED_RE.match(os.path.normpath(r)):
            out.append((False, G_IGNORED_GONE, txt))
        else:
            out.append((True, G_REF, txt))
    out += [
        (False, G_IGNORED, _clip(f"{i} {r} (waste)", TITLE_MAX))
        for i, r in present if _waste(r)
    ]
    cand: list[tuple[str, str]] = [  # the kit's own ignored places: by design
        (i, r) for i, r in present
        if not _waste(r) and not KIT_IGNORED_RE.match(os.path.normpath(r))
        and not local_pm(r)
    ]
    if not skip and cand:
        ignored: set[str] = _ignored(repo, [r for _, r in cand])
        out += [(False, G_IGNORED, _clip(f"{i} {r} (ignored)", TITLE_MAX))
                for i, r in cand
                if r in ignored]
    if imp:
        n: int = len({i for i, _ in imp})
        out.append((False, G_IMPORTED, f"{len(imp)} refs of {n} imported entries "
                    f"missing, e.g. {imp[0][0]} {imp[0][1]}"))
    for st in stages:
        folder: str = _stage_dir(st)
        if (repo / folder).is_dir():
            continue
        tracked: subprocess.CompletedProcess[bytes] | None = (
            None if skip or local else _git(repo, ["ls-files", "--", folder])
        )  # local: no clone lacks it, so missing is HARD (D-67)
        if tracked is not None and tracked.returncode == 0 and not tracked.stdout:
            # git keeps no empty folder: a clone of a stage with no files yet
            out.append((False, G_FOLDER_EMPTY, f"{st.id} {folder}"))
        else:
            out.append((True, G_FOLDER, f"{st.id} {folder}"))
    done: list[Entry] = [st for st in stages if st.status == "done"]
    if not skip and not local and (done or ledger_wide):
        committed, differs = _head_lines(repo, raw)
        if ledger_wide and differs is not None:
            out.append((True, G_HEAD, f"{LEDGER_REL}:{differs} differs from HEAD: "
                        "lines were changed or removed, not only appended"))
        for st in done:
            close: int | None = _close_line(events, st.id)
            lines: int = sum(1 for k, _ in events if committed < k <= (close or 0))
            st_r: subprocess.CompletedProcess[bytes] | None = _git(
                repo,
                ["status", "--porcelain", "--untracked-files=all", "--",
                 _stage_dir(st)],
            )
            files: int = (
                len(st_r.stdout.splitlines()) if st_r and st_r.returncode == 0 else 0
            )
            if lines or files:
                out.append((False, G_UNCOMMITTED, f"{st.id} {st.title}: {lines} "
                            f"ledger lines and {files} folder files not in HEAD"))
    # "late" = made after a close made in this ledger (a set to done) and before
    # the next open made in it (an add as open, or a reopen); this holds for
    # every stage. The import line of a stage imported closed (its span 0,
    # (add, add), kept for the record) is neither: it starts and ends no gap.
    opens: list[int] = sorted(
        lo for sp in spans.values() for lo, hi in sp if hi is None or lo < hi
    )
    loose: list[Entry] = [  # not from `entries`: these carry no stage
        e for e in state.values()
        if e.type != "stage" and not e.stage and not _imported(e)
    ]
    # every stage of the ledger, also under `only` (stage-close pre-check,
    # doctor --stage): each entry gets one hint, the same line either way, and
    # `only` keeps just the hints that name it
    mine: list[tuple[int, int | None, Entry]] = sorted(
        (
            (lo, hi, st)
            for st in state.values() if st.type == "stage"  # imported too: the
            for lo, hi in spans[st.id]  # record's spans, no exception
        ),
        key=lambda x: -x[0],  # opened most recently first
    )
    seen: set[str] = set()
    for e in loose:  # made while stages were open: every one of them is named
        first: int = e.lines[0]
        open_at: list[str] = list(dict.fromkeys(
            st.id for lo, hi, st in mine if lo < first and (hi is None or first < hi)
        ))
        if not open_at:
            continue
        seen.add(e.id)
        if only is None or only in open_at:
            out.append((False, G_NOSTAGE,
                        _clip(f"{e.id} ({', '.join(open_at)}) {e.title}")))
    by_close: list[tuple[int, int | None, Entry]] = sorted(  # gaps: the stage
        (x for x in mine if x[1] is not None and x[0] < x[1]),  # closed last
        key=lambda x: -(x[1] or 0),  # before an entry, by a real close (above)
    )
    for _, end, st in by_close:  # then the gaps
        after: int | None = next((k for k in opens if k > (end or 0)), None)
        for e in loose:
            first = e.lines[0]
            if e.id in seen or first <= (end or 0) or (
                after is not None and first >= after
            ):
                continue
            seen.add(e.id)
            if only is None or st.id == only:
                out.append((False, G_LATE, _clip(f"{e.id} (after {st.id}) {e.title}")))
    now: datetime = datetime.now().astimezone()
    for e in entries:
        if e.type != "task" or e.status != "running" or not e.started:
            continue
        try:
            then: datetime = datetime.fromisoformat(e.started).astimezone()
        except ValueError:
            continue
        if (now - then).total_seconds() > RUNNING_MAX_H * 3600:
            line: str = f"{e.id} ({e.owner}, {age(e.started, now)}) {e.title}"
            out.append((False, G_RUNNING, _clip(line)))
    for e in entries:  # a title that still carries the old system's state
        if e.status in ("dropped", "superseded"):
            continue
        if _imported(e) and STATUS_WORD_RE.match(e.title):
            out.append((False, G_STATUS_WORD, _clip(f"{e.id} ({e.status}) {e.title}")))
        elif e.status == "done" and DONE_OPEN_RE.match(e.title):
            out.append((False, G_DONE_OPEN, _clip(f"{e.id} {e.title}")))
    if ledger_wide:
        out += [(False, G_STAMPS, f"{rel} {have}, kit {want}")
                for rel, have, want in stamps_behind(repo)]
    if only is not None:
        for e in entries:
            if not (e.type == "decision" and e.stage == only and e.status == "done"
                    and e.owner != "user"):
                continue
            users: list[str] = [  # the user decisions it links (narrowed?)
                x for x in e.links
                if (d := state.get(x)) is not None and d.type == "decision"
                and d.owner == "user"
            ]
            by: str = f"{e.owner}; links {', '.join(users)}" if users else e.owner
            out.append((False, G_DECISIONS, _clip(f"{e.id} ({by}) {e.title}")))
    return out, notes


def _print_findings(
    found: list[Finding], notes: list[str], what: str, cap: int = GROUP_CAP
) -> int:
    """Notes, then HARD groups, then SOFT groups, one line per finding (at most
    `cap` per group, 0 = all), then a count line. Returns the number of hard ones."""
    for note in notes:
        print(note)
    for hard in (True, False):
        groups: dict[str, list[str]] = {}
        for h, g, line in found:
            if h == hard:
                groups.setdefault(g, []).append(line)
        for g, lines in groups.items():
            print(f"{'HARD' if hard else 'SOFT'} {g} ({len(lines)})")
            shown: list[str] = lines[:cap] if cap else lines
            for line in shown:
                print(f"  {line}")
            if len(shown) < len(lines):
                print(f"  +{len(lines) - len(shown)} more (all: --limit 0)")
    n_hard: int = sum(1 for h, _, _ in found if h)
    print(f"{what}: {n_hard} hard, {len(found) - n_hard} soft" if found
          else f"{what}: no findings")
    return n_hard


def _doctor_start(a: argparse.Namespace) -> int:
    """Session start. The kit part, at most 3 lines (the hook cuts it at 3): kit
    line, then up to two rule files behind the kit; with more than two, one and
    '+N more'. A local or broken pm/config.json takes line 2, leaving one line
    (D-71). Then the `spec: ` lines (`_spec_lines`)."""
    print(f"kit {kit_version()}")
    try:
        repo: Path = _repo(a)
        behind: list[tuple[str, str, str]] = stamps_behind(repo)
    except (LedgerError, OSError):
        return 0
    room: int = 2
    try:
        if read_config(repo)["pm"] == "local":
            print("pm: local only")
            room = 1
    except LedgerError:
        print(_G_CONFIG)
        room = 1
    shown: list[tuple[str, str, str]] = (
        behind[:room] if len(behind) <= room else behind[:room - 1]
    )
    for rel, have, want in shown:
        print(f"{rel} {have}, kit {want}: run /rk-sync")
    if len(shown) < len(behind):
        print(f"+{len(behind) - len(shown)} more: rk doctor")
    try:  # after the kit part; the hook passes every `spec: ` line (D1)
        state: dict[str, Entry] = load(repo)
    except (LedgerError, OSError):
        return 0
    for line in _spec_lines(state):
        print(line)
    return 0


def _spec_lines(state: dict[str, Entry]) -> list[str]:
    """One line per open stage with an NN title and no done user decision
    labelled `<stage code>/SPEC` (design-debt-batch I1, I2), in ledger order.
    A superseded holder counts when its chain of replacements ends in a done
    user decision (DB-67); its own owner does not matter."""

    def held(e: Entry) -> bool:
        seen: set[str] = set()
        while e.status == "superseded" and e.id not in seen:  # a cycle: False
            seen.add(e.id)
            nxt: Entry | None = state.get(str(e.extra.get("superseded_by")))
            if nxt is None:
                return False
            e = nxt
        return e.status == "done" and e.owner == "user"

    labels: set[object] = {
        e.extra.get("legacy_id")
        for e in state.values()
        if e.type == "decision" and held(e)
    }
    out: list[str] = []
    for st in sorted(state.values(), key=lambda x: x.lines[0]):
        if st.type != "stage" or st.status != "open" or not STAGE_RE.match(st.title):
            continue
        code: str = st.title.split("-", 1)[0]
        if f"{code}/SPEC" not in labels:
            out.append(
                f"spec: {st.id} {st.title} has no user decision labelled "
                f"{code}/SPEC (AGENTS.md 3.3)"
            )
    return out


def _cmd_doctor(a: argparse.Namespace) -> int:
    if a.start:
        return _doctor_start(a)
    repo: Path = _repo(a)
    raw: bytes = (repo / LEDGER_REL).read_bytes()
    cfg: list[Finding] = []  # broken config: listed first, checked as tracked
    local: bool = False
    try:
        local = read_config(repo)["pm"] == "local"
    except LedgerError as e:
        cfg = [(True, _G_CONFIG, str(e).removeprefix(f"{_CONFIG_REL}: "))]
    try:
        events: list[tuple[int, dict[str, object]]] = _parse(raw)
        state: dict[str, Entry] = fold(events)
    except LedgerError as e:
        found: list[Finding] = [*cfg, (True, G_PARSE, str(e))]
        return 1 if _print_findings(found, [_LOCAL_NOTICE] * local, "doctor") else 0
    only: str | None = resolve(state, a.stage, stage=True) if a.stage else None
    found, notes = _findings(repo, raw, events, state, only, True, local)
    what: str = f"doctor {only or ''}".strip()
    return (
        1 if _print_findings(cfg + found, notes, what, _nonneg(a.limit, "--limit"))
        else 0
    )


def _cmd_brief_check(a: argparse.Namespace) -> int:
    """Hook gate: rc 0 pass (open tasks named on TASK: lines -> running), 2 refuse.

    Only a brief (a line starting with DELIVERABLE:) is checked; no ledger = pass.
    """
    text: str = sys.stdin.read()
    if not BRIEF_RE.search(text):
        return 0
    try:
        repo: Path = _repo(a)
    except LedgerError:
        return 0
    who: str = _name(a.who, "--who")
    lines: list[str] = [m.group(1) for m in TASK_LINE_RE.finditer(text)]
    ids: list[str] = []
    problems: list[str] = []
    out: list[str] = []

    def build(state: dict[str, Entry]) -> list[dict[str, object]]:
        labels: dict[str, list[Entry]] = {}  # --label labels; legacy ids never
        for x in state.values():
            lab: str | bool | None = x.extra.get("legacy_id")
            if isinstance(lab, str) and not _imported(x):
                labels.setdefault(lab, []).append(x)
        for line in lines:
            ids.extend(ANY_ID_RE.findall(line))  # ids by form anywhere, as before
            for w in TOKEN_SEP_RE.split(line.strip()):  # leading refs only: the
                w = w.strip("(),:;.")  # first token neither id nor label ends
                if ANY_ID_RE.fullmatch(w):
                    continue
                hits: list[Entry] = labels.get(w, [])
                if not hits:
                    break
                if len(hits) > 1:  # only via hand edits: --label is unique
                    problems.append(str(_ambiguous(w, hits)))
                else:
                    ids.append(hits[0].id)
        ids[:] = dict.fromkeys(ids)
        if not ids and not problems:
            problems.append("no TASK: line naming a task")
        for eid in ids:
            e: Entry | None = state.get(eid)
            if e is None:
                problems.append(f"{eid} unknown")
            elif e.type != "task":
                problems.append(f"{eid} is not a task")
            elif not _is_open(e):
                problems.append(f"{eid} is {e.status}")
            elif e.status in ("open", "staged"):  # the one this call would start
                try:
                    _check_stage_startable(state, e)
                except LedgerError as err:
                    problems.append(f"{eid}: {err}")
        if problems:
            return []
        started: list[Entry] = [
            state[i] for i in ids if state[i].status in ("open", "staged")
        ]
        out.extend(f"started {e.id}: {e.title}" for e in started)
        return [make_event(who, "set", e.id, {"status": "running"}) for e in started]

    try:
        append(repo, build)
    except LedgerError as e:
        print(f"refused: {e}")
        return 2
    if problems:
        rk_py: Path = Path(__file__).resolve().with_name("rk.py")
        print(
            f"refused: {'; '.join(problems)}. A brief (a message with a "
            "DELIVERABLE: line) needs a TASK: line naming an open task by its id "
            "or by its label, first on the line (TASK: T-<n> or TASK: 03b/W2). "
            "A work item that already has a task is reused, not added again: "
            f"python3 -I {rk_py} set <label> --owner <teammate>. Else open one: "
            f'python3 -I {rk_py} add task "<work item>" --owner <teammate> '
            '--note "<deliverable and scope, 1-3 lines>" --label '
            "<stage code>/<item> [--stage S-n]. Messages without a DELIVERABLE: "
            "line are not checked."
        )
        return 2
    for line in out:
        print(line)
    return 0


def _parser() -> argparse.ArgumentParser:
    common: argparse.ArgumentParser = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", type=Path, default=None)
    common.add_argument("--who", default="lead")
    p: argparse.ArgumentParser = argparse.ArgumentParser(prog="rk.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    pa: argparse.ArgumentParser = sub.add_parser("add", parents=[common])
    pa.add_argument("type")
    pa.add_argument("title")
    pa.add_argument("--owner", default=None)
    pa.add_argument("--stage", default=None)
    pa.add_argument("--note", default="")
    pa.add_argument("--link", action="append", default=[])
    pa.add_argument("--ref", action="append", default=[])
    pa.add_argument("--status", choices=STATUSES, default=None)
    pa.add_argument("--imported", action="store_true")
    pa.add_argument("--source", default=None)
    lab = pa.add_mutually_exclusive_group()
    lab.add_argument("--legacy-id", default=None)
    lab.add_argument("--label", default=None, help="unique; e.g. 03b/W4")
    pa.add_argument("--date", default=None)
    pa.add_argument("--open", action="store_true")
    pa.add_argument("--follows", default=None)
    place = pa.add_mutually_exclusive_group()
    place.add_argument("--before", default=None, metavar="S")
    place.add_argument("--after", default=None, metavar="S")
    ps: argparse.ArgumentParser = sub.add_parser("start", parents=[common])
    ps.add_argument("id")
    ps.add_argument("--owner", default=None)
    for name in ("close", "drop", "shelve", "reopen"):
        pc: argparse.ArgumentParser = sub.add_parser(name, parents=[common])
        pc.add_argument("id")
        pc.add_argument(
            "--note", default=None,
            help="required: added as a new line of the note and stored as the "
            "entry's `reason` (why it has this status now)",
        )
        pc.add_argument("--ref", action="append", default=[])
        if name != "reopen":
            pc.add_argument("--link", action="append", default=[])
    for name in ("staged", "land"):  # D-50, D-51
        pg: argparse.ArgumentParser = sub.add_parser(name, parents=[common])
        pg.add_argument("ids", nargs="+" if name == "staged" else "*", metavar="ID")
        pg.add_argument(
            "--note", default=None,
            help="required: where the work sits (staged) or landed (land); "
            "added to the note and stored as `reason`",
        )
        pg.add_argument("--ref", action="append", default=[])
        if name == "land":
            pg.add_argument("--stage", default=None, help="only this stage's")
        else:
            pg.set_defaults(stage=None)
    pt: argparse.ArgumentParser = sub.add_parser("set", parents=[common])
    pt.add_argument("id")
    pt.add_argument("--title", default=None)
    pt.add_argument("--owner", default=None)
    pt.add_argument("--label", default=None, help="unique; e.g. 03b/W4")
    pt.add_argument("--stage", default=None)
    pt.add_argument("--status", choices=STATUSES, default=None)
    notes = pt.add_mutually_exclusive_group()
    notes.add_argument("--note", default=None, help="added as a new line of the note")
    notes.add_argument(
        "--note-replace", default=None, help="replaces the whole note ('' clears it)"
    )
    pt.add_argument("--link", action="append", default=[])
    pt.add_argument("--ref", action="append", default=[])
    pt.add_argument(
        "--ref-drop", action="append", default=[], metavar="PATH",
        help="removes this ref (exactly as shown by show); the history keeps it",
    )
    moveto = pt.add_mutually_exclusive_group()
    moveto.add_argument("--before", default=None, metavar="S")
    moveto.add_argument("--after", default=None, metavar="S")
    pu: argparse.ArgumentParser = sub.add_parser("supersede", parents=[common])
    pu.add_argument("id")
    pu.add_argument("title")
    pu.add_argument("--owner", default=None)
    pu.add_argument("--note", default="")
    pu.add_argument("--link", action="append", default=[])
    pu.add_argument("--ref", action="append", default=[])
    pl: argparse.ArgumentParser = sub.add_parser("list", parents=[common])
    pl.add_argument("--type", default=None)
    pl.add_argument("--owner", default=None)
    pl.add_argument("--stage", default=None)
    pl.add_argument("--status", choices=STATUSES, default=None)
    pl.add_argument("--limit", type=int, default=LIST_LIMIT)
    pl.add_argument("--all", action="store_true")
    ph: argparse.ArgumentParser = sub.add_parser("show", parents=[common])
    ph.add_argument("id", nargs="+")
    pq: argparse.ArgumentParser = sub.add_parser("search", parents=[common])
    pq.add_argument("text", nargs="?", default=None)
    pq.add_argument("--source", default=None, help="exact source of an imported entry")
    pq.add_argument(
        "--label", "--legacy-id", dest="legacy_id", default=None, metavar="LABEL",
        help="exact label (= legacy id)",
    )
    pq.add_argument("--type", default=None)
    pq.add_argument("--limit", type=int, default=SEARCH_LIMIT)
    pr: argparse.ArgumentParser = sub.add_parser("recent", parents=[common])
    pr.add_argument("-n", type=int, default=10)
    sub.add_parser("render", parents=[common])
    pz: argparse.ArgumentParser = sub.add_parser("stage-close", parents=[common])
    pz.add_argument("id")
    pz.add_argument("--sign-off", default=None)
    pz.add_argument("--ref", action="append", default=[])
    po: argparse.ArgumentParser = sub.add_parser("stage-open", parents=[common])
    po.add_argument("id")
    po.add_argument("--follows", default=None)
    po.set_defaults(imported=False, legacy_id=None)  # for _check_names
    pr: argparse.ArgumentParser = sub.add_parser("stage-rename", parents=[common])
    pr.add_argument("id")
    pr.add_argument("topic")
    pr.add_argument("--note", default=None)
    pr.set_defaults(imported=False, legacy_id=None)  # for _check_names
    pv: argparse.ArgumentParser = sub.add_parser(
        "reref",
        parents=[common],
        description="Replace the leading OLD of every ref that starts with OLD by "
        "NEW, on all entries (imported, done and those of a done stage too), "
        "after the files were moved. All or nothing: refused, nothing written, "
        "when a new path does not exist. One set event (refs) per changed entry.",
    )
    pv.add_argument("old", metavar="OLD", help="path prefix, e.g. pm/waste/team/03b/")
    pv.add_argument("new", metavar="NEW", help="replacement prefix")
    pv.add_argument("--dry-run", action="store_true")
    pd: argparse.ArgumentParser = sub.add_parser(
        "doctor",
        parents=[common],
        description="Read-only check of the ledger against folders and git; "
        "writes nothing. Exit 1 on a HARD finding, else 0.",
    )
    pd.add_argument(
        "--stage", default=None, help="only this stage: S-n, its code or title"
    )
    pd.add_argument(
        "--limit", type=int, default=GROUP_CAP,
        help=f"lines per group (default {GROUP_CAP}; 0 = all)",
    )
    pd.add_argument(
        "--start", action="store_true",
        help="session start: kit version and rule files behind the kit; exit 0",
    )
    sub.add_parser("brief-check", parents=[common])
    pi: argparse.ArgumentParser = sub.add_parser(
        "import",
        parents=[common],
        description=IMPORT_DESCRIPTION,
        epilog=IMPORT_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    pi.add_argument("files", nargs="+", metavar="FILE", help="JSON Lines file")
    pi.add_argument("--dry-run", action="store_true")
    return p


HANDLERS: dict[str, Callable[[argparse.Namespace], int]] = {
    "add": _cmd_add,
    "start": _cmd_start,
    "close": _close_drop_reopen,
    "drop": _close_drop_reopen,
    "shelve": _close_drop_reopen,
    "reopen": _close_drop_reopen,
    "staged": _cmd_staged_land,
    "land": _cmd_staged_land,
    "set": _cmd_set,
    "supersede": _cmd_supersede,
    "list": _cmd_list,
    "show": _cmd_show,
    "search": _cmd_search,
    "recent": _cmd_recent,
    "render": _cmd_render,
    "stage-close": _cmd_stage_close,
    "brief-check": _cmd_brief_check,
    "import": _cmd_import,
    "doctor": _cmd_doctor,
    "reref": _cmd_reref,
    "stage-open": _cmd_stage_open,
    "stage-rename": _cmd_stage_rename,
}


def main(argv: list[str]) -> int:
    a: argparse.Namespace = _parser().parse_args(argv)
    try:
        return HANDLERS[a.cmd](a)
    except LedgerError as e:
        print(f"error: {e}")
        return 1
