"""Ledger store for research-kit: pm/ledger.jsonl, an append-only event log.

Each line is one event on one entry: {"ts", "who", "ev": "add"|"set", "id", "f"}.
Current state of an entry = its events folded in file order. Nothing is ever
rewritten. Reached through rk.py (store subcommands); never runs git.
"""

from __future__ import annotations

import argparse
import difflib
import fcntl
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

LEDGER_REL: str = "pm/ledger.jsonl"
STATUS_REL: str = "pm/STATUS.md"
STATUSES: tuple[str, ...] = ("open", "running", "done", "dropped", "superseded")
OPEN_STATUSES: tuple[str, ...] = ("open", "running")
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
COMMANDS: frozenset[str] = frozenset(
    {"add", "start", "close", "drop", "reopen", "set", "supersede"}
)
HINT: str = (
    "fix the line by hand outside Claude (agents' edits of the ledger are blocked)"
)
STR_FIELDS: tuple[str, ...] = ("type", "title", "status", "owner", "stage", "note")
LIST_FIELDS: tuple[str, ...] = ("links", "refs")


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


# ---- reading and folding ----------------------------------------------------


def _bad(n: int, what: str) -> LedgerError:
    return LedgerError(f"{LEDGER_REL}:{n}: {what}; {HINT}")


def find_repo(start: Path, explicit: bool = False) -> Path:
    """Dir holding pm/ledger.jsonl: `start` itself, or (not explicit) a parent."""
    start = start.resolve()
    for d in [start] if explicit else [start, *start.parents]:
        if (d / LEDGER_REL).is_file():
            return d
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


def fold(events: list[tuple[int, dict[str, object]]]) -> dict[str, Entry]:
    state: dict[str, Entry] = {}
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


def make_event(
    who: str, ev: str, eid: str, fields: dict[str, object]
) -> dict[str, object]:
    ts: str = datetime.now().astimezone().isoformat(timespec="seconds")
    return {"ts": ts, "who": who, "ev": ev, "id": eid, "f": fields}


def append(
    repo: Path, build: Callable[[dict[str, Entry]], list[dict[str, object]]]
) -> dict[str, Entry]:
    """Lock, fold, build events from the current state, append them.

    A LedgerError from `build` (or from validating its events) writes nothing.
    """
    path: Path = repo / LEDGER_REL
    if not path.is_file():
        raise LedgerError(f"no {LEDGER_REL} in {repo}; run rk.py init")
    with path.open("ab+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            fh.seek(0)
            raw: bytes = fh.read()
            state: dict[str, Entry] = fold(_parse(raw))
            new: list[dict[str, object]] = build(state)
            if not new:
                return state
            data: bytes = "".join(json.dumps(e) + "\n" for e in new).encode("ascii")
            if raw and not raw.endswith(b"\n"):
                data = b"\n" + data
            new_state: dict[str, Entry] = fold(_parse(raw + data))
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
    return new_state


def resolve_stage(state: dict[str, Entry], ref: str) -> str:
    """Stage entry id for `ref` = a stage id or the exact title of one stage."""
    e: Entry | None = state.get(ref)
    if e is not None:
        if e.type != "stage":
            raise LedgerError(f"{ref} is a {e.type}, not a stage")
        return ref
    hits: list[str] = [
        x.id for x in state.values() if x.type == "stage" and x.title == ref
    ]
    if len(hits) != 1:
        what: str = "no" if not hits else "more than one"
        raise LedgerError(f"{what} stage '{ref}'")
    return hits[0]


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
    return title


def _repo(a: argparse.Namespace) -> Path:
    return find_repo(a.repo, explicit=True) if a.repo else find_repo(Path.cwd())


# ---- commands ---------------------------------------------------------------


def _cmd_add(a: argparse.Namespace) -> int:
    repo: Path = _repo(a)
    who: str = _name(a.who, "--who")
    types: dict[str, str] = known_types(repo)
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
    if a.status == "superseded":
        import_only.append("--status superseded")
    if import_only and not a.imported:
        raise LedgerError(f"{', '.join(import_only)}: only with --imported")
    if a.imported and not a.source:
        raise LedgerError("--imported needs --source FILE:LINE")
    if a.date is not None:
        try:
            date.fromisoformat(a.date)
        except ValueError:
            raise LedgerError(f"--date '{a.date}': want YYYY-MM-DD") from None
    status: str = a.status or ("done" if typ == "decision" else "open")
    made: list[str] = []

    def build(state: dict[str, Entry]) -> list[dict[str, object]]:
        for link in a.link:
            if link not in state:
                raise LedgerError(f"--link {link}: no such entry")
        stage: str = (
            resolve_stage(state, a.stage)
            if a.stage
            else _default_stage(state, typ, a.imported)
        )
        eid: str = next_id(state, types[typ])
        f: dict[str, object] = {
            "type": typ,
            "title": title,
            "status": status,
            "owner": owner,
            "stage": stage,
            "note": a.note,
            "links": list(dict.fromkeys(a.link)),
            "refs": list(dict.fromkeys(a.ref)),
        }
        if a.imported:
            f["imported"] = True
            f["source"] = a.source
            if a.legacy_id is not None:
                f["legacy_id"] = a.legacy_id
            if a.date is not None:
                f["date"] = a.date
        made.append(eid)
        return [make_event(who, "add", eid, f)]

    append(repo, build)
    print(f"logged {made[0]}: {title}")
    return 0


def _entry(state: dict[str, Entry], eid: str) -> Entry:
    e: Entry | None = state.get(eid)
    if e is None:
        raise LedgerError(f"no such entry {eid}")
    return e


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
        if e.status == "running":
            out.append(f"{e.id} already running")
            return []
        if e.status != "open":
            raise LedgerError(f"{e.id} is {e.status}: use reopen first")
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
    cmd: str = a.cmd
    new: str = {"close": "done", "drop": "dropped", "reopen": "open"}[cmd]

    def build(state: dict[str, Entry]) -> list[dict[str, object]]:
        e: Entry = _entry(state, a.id)
        if e.type == "stage":
            raise LedgerError(f"{e.id} is a stage: use stage-close")
        if cmd == "close" and e.type == "decision":
            raise LedgerError(
                f"{e.id} is a decision; decisions are in force when logged: "
                "supersede or drop"
            )
        allowed: tuple[str, ...] = {
            "close": OPEN_STATUSES,
            "drop": OPEN_STATUSES + (("done",) if e.type == "decision" else ()),
            "reopen": ("done", "dropped"),
        }[cmd]
        if e.status not in allowed:
            raise LedgerError(f"cannot {cmd} {e.id}: it is {e.status}")
        f: dict[str, object] = {"status": new, "note": note}
        if cmd == "close" and a.ref:
            f["refs"] = _union(e.refs, a.ref)
        return [make_event(who, "set", e.id, f)]

    append(repo, build)
    verb: str = {"close": "closed", "drop": "dropped", "reopen": "reopened"}[cmd]
    print(f"{verb} {a.id}: {_cut(note)}")
    return 0


def _cmd_set(a: argparse.Namespace) -> int:
    repo: Path = _repo(a)
    who: str = _name(a.who, "--who")
    title: str | None = _title(a.title) if a.title is not None else None
    owner: str | None = _name(a.owner, "--owner") if a.owner is not None else None
    if not (
        title is not None
        or owner is not None
        or a.stage is not None
        or a.note is not None
        or a.link
        or a.ref
    ):
        raise LedgerError(
            "nothing to set (give --title, --owner, --stage, --note, --link or --ref)"
        )
    keys: list[str] = []

    def build(state: dict[str, Entry]) -> list[dict[str, object]]:
        e: Entry = _entry(state, a.id)
        f: dict[str, object] = {}
        if title is not None:
            f["title"] = title
        if owner is not None:
            f["owner"] = owner
        if a.stage is not None:
            f["stage"] = resolve_stage(state, a.stage)
        if a.note is not None:
            f["note"] = a.note
        for link in a.link:
            if link not in state:
                raise LedgerError(f"--link {link}: no such entry")
        if a.link:
            f["links"] = _union(e.links, a.link)
        if a.ref:
            f["refs"] = _union(e.refs, a.ref)
        keys.extend(f)
        return [make_event(who, "set", e.id, f)]

    append(repo, build)
    print(f"updated {a.id}: {', '.join(keys)}")
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
    made: list[str] = []

    def build(state: dict[str, Entry]) -> list[dict[str, object]]:
        old: Entry = _entry(state, a.id)
        if old.type != "decision":
            raise LedgerError(f"{old.id} is a {old.type}, not a decision")
        if old.status != "done":
            raise LedgerError(f"{old.id} is {old.status}, not in force")
        for link in a.link:
            if link not in state:
                raise LedgerError(f"--link {link}: no such entry")
        eid: str = next_id(state, BUILTIN_TYPES["decision"])
        f: dict[str, object] = {
            "type": "decision",
            "title": title,
            "status": "done",
            "owner": owner,
            "stage": _default_stage(state, "decision", False),
            "note": a.note or "",
            "links": _union([old.id], a.link),
            "refs": _union([], a.ref),
            "supersedes": old.id,
        }
        made.append(eid)
        return [
            make_event(who, "add", eid, f),
            make_event(
                who, "set", old.id, {"status": "superseded", "superseded_by": eid}
            ),
        ]

    append(repo, build)
    print(f"logged {made[0]}: {title} (supersedes {a.id})")
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
    pa.add_argument("--legacy-id", default=None)
    pa.add_argument("--date", default=None)
    ps: argparse.ArgumentParser = sub.add_parser("start", parents=[common])
    ps.add_argument("id")
    ps.add_argument("--owner", default=None)
    for name in ("close", "drop", "reopen"):
        pc: argparse.ArgumentParser = sub.add_parser(name, parents=[common])
        pc.add_argument("id")
        pc.add_argument("--note", default=None)
        if name == "close":
            pc.add_argument("--ref", action="append", default=[])
    pt: argparse.ArgumentParser = sub.add_parser("set", parents=[common])
    pt.add_argument("id")
    pt.add_argument("--title", default=None)
    pt.add_argument("--owner", default=None)
    pt.add_argument("--stage", default=None)
    pt.add_argument("--note", default=None)
    pt.add_argument("--link", action="append", default=[])
    pt.add_argument("--ref", action="append", default=[])
    pu: argparse.ArgumentParser = sub.add_parser("supersede", parents=[common])
    pu.add_argument("id")
    pu.add_argument("title")
    pu.add_argument("--owner", default=None)
    pu.add_argument("--note", default="")
    pu.add_argument("--link", action="append", default=[])
    pu.add_argument("--ref", action="append", default=[])
    return p


HANDLERS: dict[str, Callable[[argparse.Namespace], int]] = {
    "add": _cmd_add,
    "start": _cmd_start,
    "close": _close_drop_reopen,
    "drop": _close_drop_reopen,
    "reopen": _close_drop_reopen,
    "set": _cmd_set,
    "supersede": _cmd_supersede,
}


def main(argv: list[str]) -> int:
    a: argparse.Namespace = _parser().parse_args(argv)
    try:
        return HANDLERS[a.cmd](a)
    except LedgerError as e:
        print(f"error: {e}")
        return 1
