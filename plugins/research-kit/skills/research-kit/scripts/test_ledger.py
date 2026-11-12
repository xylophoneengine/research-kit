#!/usr/bin/env python3
"""Tests for ledger.py. Run: python3 -I test_ledger.py (test_rk.py runs them too)."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import traceback
from collections.abc import Callable
from datetime import datetime, timedelta
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType
from typing import Any

# -I drops the script dir from sys.path, so load rk.py by path.
RK_PY: Path = Path(__file__).with_name("rk.py")
_spec: ModuleSpec | None = importlib.util.spec_from_file_location("rk", RK_PY)
assert _spec is not None and _spec.loader is not None
rk: ModuleType = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rk)
L: ModuleType = rk.ledger


def new_repo(root: Path) -> Path:
    """Repo dir with an empty pm/ledger.jsonl and pm/kinds/."""
    repo: Path = root / "repo"
    (repo / "pm" / "kinds").mkdir(parents=True)
    (repo / L.LEDGER_REL).write_text("")
    return repo


def lrun(repo: Path, *argv: str) -> tuple[int, str]:
    buf: io.StringIO = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code: int = L.main([*argv, "--repo", str(repo)])
    return code, buf.getvalue()


def jl(repo: Path) -> list[dict[str, Any]]:
    text: str = (repo / L.LEDGER_REL).read_text()
    return [json.loads(ln) for ln in text.splitlines() if ln.strip()]


def snapshot(root: Path) -> dict[str, bytes | None]:
    return {
        str(p.relative_to(root)): (p.read_bytes() if p.is_file() else None)
        for p in sorted(root.rglob("*"))
    }


def ev_line(
    eid: str, title: str, typ: str = "task", status: str = "open", owner: str = "lead"
) -> str:
    f: dict[str, object] = {
        "type": typ, "title": title, "status": status, "owner": owner,
        "stage": "", "note": "", "links": [], "refs": [],
    }
    return json.dumps(L.make_event("lead", "add", eid, f)) + "\n"


def test_add_and_fold() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        code, out = lrun(repo, "add", "task", "Write loader")
        assert code == 0 and out == "logged T-1: Write loader\n", out
        ev: dict[str, Any] = jl(repo)[0]
        assert list(ev) == ["ts", "who", "ev", "id", "f"] and ev["ev"] == "add", ev
        assert ev["f"]["status"] == "open" and ev["f"]["owner"] == "lead", ev
        assert lrun(repo, "add", "task", "B")[1] == "logged T-2: B\n"
        out = lrun(repo, "add", "decision", "dE00", "--owner", "user")[1]
        assert out.startswith("logged D-1"), out
        assert L.load(repo)["D-1"].status == "done"
        n: int = len(jl(repo))
        code, out = lrun(repo, "add", "decision", "x")
        assert code == 1 and "--owner" in out, out
        assert len(jl(repo)) == n


def test_unknown_type_fails() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        code, out = lrun(repo, "add", "tsak", "x")
        assert code == 1 and "did you mean 'task'" in out, out
        kind: Path = repo / "pm/kinds/k.md"
        kind.write_text("# Kind k\n<!-- rk:type sample SM -->\n")
        assert lrun(repo, "add", "sample", "x")[1] == "logged SM-1: x\n"
        kind.write_text("<!-- rk:type Bad -->\n")
        code, out = lrun(repo, "add", "task", "x")
        assert code == 1 and "k.md:1" in out, out
        kind.write_text("<!-- rk:type foo T -->\n")
        code, out = lrun(repo, "add", "task", "x")
        assert code == 1 and "k.md:1" in out, out
        assert len(jl(repo)) == 1


def test_duplicate_id_detected() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        (repo / L.LEDGER_REL).write_text(
            ev_line("T-1", "a") + ev_line("T-2", "b") + ev_line("T-1", "c")
        )
        before: bytes = (repo / L.LEDGER_REL).read_bytes()
        code, out = lrun(repo, "add", "task", "x")
        assert code == 1 and "duplicate id T-1: lines 1 and 3" in out, out
        assert (repo / L.LEDGER_REL).read_bytes() == before


def test_bad_line_fails_loudly() -> None:
    for bad in ("{not json", "<<<<<<< HEAD"):
        with tempfile.TemporaryDirectory() as d:
            repo: Path = new_repo(Path(d))
            (repo / L.LEDGER_REL).write_text(ev_line("T-1", "a") + bad + "\n")
            before: bytes = (repo / L.LEDGER_REL).read_bytes()
            code, out = lrun(repo, "add", "task", "x")
            assert code == 1 and "pm/ledger.jsonl:2" in out and "by hand" in out, out
            assert (repo / L.LEDGER_REL).read_bytes() == before


def test_concurrent_appends() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        procs: list[subprocess.Popen[bytes]] = [
            subprocess.Popen(
                [sys.executable, "-I", str(RK_PY), "add", "task", f"p{i}",
                 "--repo", str(repo)],
                stdout=subprocess.DEVNULL,
            )
            for i in range(20)
        ]
        rcs: list[int] = [p.wait() for p in procs]
        assert all(rc == 0 for rc in rcs), rcs
        ids: list[str] = sorted(e["id"] for e in jl(repo))
        assert ids == sorted(f"T-{i}" for i in range(1, 21)), ids


def test_no_git_call() -> None:
    for src in (RK_PY, RK_PY.with_name("ledger.py")):
        text: str = src.read_text()
        bad: tuple[str, ...] = (
            "subprocess", "os.system", "os.exec", "os.popen", "import pty"
        )
        assert not any(w in text for w in bad), src
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        fakebin: Path = Path(d) / "bin"
        fakebin.mkdir()
        marker: Path = Path(d) / "git-was-called"
        git: Path = fakebin / "git"
        git.write_text(f'#!/bin/sh\ntouch "{marker}"\n')
        git.chmod(0o755)
        env: dict[str, str] = {
            **os.environ, "PATH": f"{fakebin}{os.pathsep}{os.environ['PATH']}"
        }
        r: subprocess.CompletedProcess[bytes] = subprocess.run(
            [sys.executable, "-I", str(RK_PY), "add", "task", "x",
             "--repo", str(repo)],
            env=env, capture_output=True,
        )
        assert r.returncode == 0, r
        assert not marker.exists(), "rk.py called git"


def test_repo_lookup() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        assert L.find_repo(repo / "pm" / "kinds") == repo.resolve()
        bare: Path = Path(d) / "bare"
        bare.mkdir()
        snap: dict[str, bytes | None] = snapshot(bare)
        code, out = lrun(bare, "add", "task", "x")
        assert code == 1 and "pm/ledger.jsonl" in out, out
        assert snapshot(bare) == snap


def test_worktree_uses_main_ledger() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d).resolve()
        main: Path = new_repo(root)
        (main / ".git" / "worktrees" / "wt").mkdir(parents=True)
        wt: Path = new_repo(root / "wt")
        (wt / ".git").write_text(f"gitdir: {main}/.git/worktrees/wt\n")
        assert L.find_repo(wt / "pm" / "kinds") == main
        assert L.find_repo(wt, explicit=True) == wt  # --repo is taken as given
        rel: Path = new_repo(root / "rel")  # relative gitdir
        (rel / ".git").write_text("gitdir: ../../repo/.git/worktrees/wt\n")
        assert L.find_repo(rel) == main
        sub: Path = new_repo(root / "sub")  # submodule: .git file, not a worktree
        (sub / ".git").write_text(f"gitdir: {main}/.git/modules/sub\n")
        decoy: Path = main / ".git" / "modules" / "sub" / "pm"  # ledger at the gitdir
        decoy.mkdir(parents=True)
        (decoy / "ledger.jsonl").write_text("")
        assert L.find_repo(sub) == sub  # pins the /.git/worktrees/ check
        wsub: Path = new_repo(wt / "wsub")  # submodule inside a worktree
        (main / ".git" / "worktrees" / "wt" / "modules" / "wsub").mkdir(parents=True)
        (wsub / ".git").write_text(f"gitdir: {main}/.git/worktrees/wt/modules/wsub\n")
        assert L.find_repo(wsub) == wsub
        lone: Path = root / "lone"  # main checkout without a ledger
        (lone / ".git" / "worktrees" / "w").mkdir(parents=True)
        w: Path = new_repo(lone / "w")
        (w / ".git").write_text(f"gitdir: {lone}/.git/worktrees/w\n")
        assert L.find_repo(w) == w
        r: subprocess.CompletedProcess[str] = subprocess.run(
            [sys.executable, "-I", str(RK_PY), "add", "task", "from wt"],
            cwd=wt / "pm", capture_output=True, text=True,
        )
        assert r.returncode == 0 and r.stdout == "logged T-1: from wt\n", r
        assert len(jl(main)) == 1 and jl(wt) == [], (jl(main), jl(wt))


def test_unterminated_last_line_kept() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        (repo / L.LEDGER_REL).write_text(ev_line("T-1", "a").rstrip("\n"))
        code, out = lrun(repo, "add", "task", "b")
        assert code == 0 and out == "logged T-2: b\n", out
        raw: str = (repo / L.LEDGER_REL).read_text()
        assert raw.endswith("\n") and len(raw.splitlines()) == 2, raw
        assert [e["id"] for e in jl(repo)] == ["T-1", "T-2"]


def test_import_fields() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        code, out = lrun(
            repo, "add", "task", "old", "--status", "done", "--imported",
            "--source", "pm/living/TASKS.md:44", "--legacy-id", "07-12",
            "--date", "2025-03-04",
        )
        assert code == 0, out
        e: Any = L.load(repo)["T-1"]
        assert e.status == "done" and e.created == "2025-03-04", e
        assert e.extra == {
            "imported": True, "legacy_id": "07-12",
            "source": "pm/living/TASKS.md:44", "date": "2025-03-04",
        }, e.extra
        assert lrun(repo, "add", "task", "x", "--date", "2025-01-01")[0] == 1
        assert lrun(repo, "add", "task", "x", "--imported")[0] == 1
        assert lrun(repo, "add", "task", "x", "--status", "superseded")[0] == 1
        assert lrun(
            repo, "add", "task", "x", "--imported", "--source", "a:1",
            "--date", "2025-13-01",
        )[0] == 1
        assert len(jl(repo)) == 1


def test_title_one_line_and_ascii() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        assert lrun(repo, "add", "task", "a\nb")[0] == 1
        assert lrun(repo, "add", "task", "   ")[0] == 1
        assert lrun(repo, "add", "task", "Δ métrique")[0] == 0
        raw: str = (repo / L.LEDGER_REL).read_text()
        assert raw.isascii(), raw
        assert L.load(repo)["T-1"].title == "Δ métrique"


def test_link_and_stage_validation() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        assert lrun(repo, "add", "task", "x", "--link", "X-9")[0] == 1
        assert lrun(repo, "add", "stage", "03-software-x")[1] == (
            "logged S-1: 03-software-x\n"
        )
        lrun(repo, "add", "task", "a")
        assert L.load(repo)["T-1"].stage == "S-1"
        lrun(repo, "add", "stage", "04-paper-y")
        lrun(repo, "add", "task", "b")
        assert L.load(repo)["T-2"].stage == ""
        lrun(repo, "add", "task", "c", "--stage", "04-paper-y", "--link", "T-1")
        e: Any = L.load(repo)["T-3"]
        assert e.stage == "S-2" and e.links == ["T-1"], e
        assert lrun(repo, "add", "task", "d", "--stage", "S-9")[0] == 1
        assert lrun(repo, "add", "task", "d", "--stage", "T-1")[0] == 1


def test_title_length_cap() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        long: str = "w" * L.TITLE_MAX
        assert lrun(repo, "add", "task", long)[0] == 0
        code, out = lrun(repo, "add", "task", long + "w")
        assert code == 1 and "--note" in out, out
        code, out = lrun(repo, "set", "T-1", "--title", long + "w")
        assert code == 1 and "--note" in out, out
        lrun(repo, "add", "decision", "d" * L.TITLE_MAX, "--owner", "user")
        lrun(repo, "add", "stage", "s" * L.TITLE_MAX)
        lrun(repo, "add", "task", "u" * L.TITLE_MAX, "--owner", "user")
        lrun(repo, "start", "T-2")
        st: str = (repo / L.STATUS_REL).read_text()
        for ln in st.splitlines():
            if ln.startswith("- "):
                assert len(ln) <= L.LINE_MAX and ln.endswith("..."), ln
        assert len(jl(repo)) == 5


def test_status_cycle() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "task", "Loader", "--owner", "sr1")
        assert lrun(repo, "start", "T-1")[1] == "started T-1: Loader\n"
        n: int = len(jl(repo))
        code, out = lrun(repo, "start", "T-1")
        assert code == 0 and "already running" in out, out
        assert len(jl(repo)) == n
        assert lrun(repo, "close", "T-1")[0] == 1  # needs --note
        code, out = lrun(
            repo, "close", "T-1", "--note", "loader works",
            "--ref", "a.md", "--ref", "b.md",
        )
        e: Any = L.load(repo)["T-1"]
        assert out == "closed T-1: loader works\n", out
        assert e.status == "done" and e.refs == ["a.md", "b.md"], e
        assert lrun(repo, "close", "T-1", "--note", "again")[0] == 1
        assert lrun(repo, "start", "T-1")[0] == 1  # use reopen
        lrun(repo, "add", "task", "B")
        lrun(repo, "drop", "T-2", "--note", "not needed")
        assert L.load(repo)["T-2"].status == "dropped"
        lrun(repo, "reopen", "T-2", "--note", "needed after all")
        e = L.load(repo)["T-2"]
        assert e.status == "open" and e.note == "needed after all", e
        assert lrun(repo, "reopen", "T-2", "--note", "x")[0] == 1  # already open
        code, out = lrun(repo, "start", "T-2", "--owner", "sr2")
        assert code == 0 and L.load(repo)["T-2"].owner == "sr2", out
        long: str = "x" * 70 + "\nsecond line"
        out = lrun(repo, "close", "T-2", "--note", long)[1]
        assert out == f"closed T-2: {'x' * 60}\n", out
        assert lrun(repo, "close", "T-9", "--note", "x")[0] == 1  # unknown id


def test_close_refuses_stage_and_decision() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "stage", "03-software-x")
        code, out = lrun(repo, "close", "S-1", "--note", "x")
        assert code == 1 and "stage-close" in out, out
        assert lrun(repo, "drop", "S-1", "--note", "x")[0] == 1
        assert lrun(repo, "reopen", "S-1", "--note", "x")[0] == 1
        lrun(repo, "add", "decision", "use dE00", "--owner", "user")
        code, out = lrun(repo, "close", "D-1", "--note", "x")
        assert code == 1 and "supersede" in out, out
        assert lrun(repo, "drop", "D-1", "--note", "revoked")[0] == 0
        assert L.load(repo)["D-1"].status == "dropped"
        code, out = lrun(repo, "reopen", "D-1", "--note", "x")
        assert code == 1 and "supersede or drop" in out, out
        n: int = len(jl(repo))
        code, out = lrun(repo, "start", "S-1")
        assert code == 1 and "stage-close" in out, out
        assert L.load(repo)["S-1"].status == "open"
        code, out = lrun(repo, "add", "decision", "q?", "--owner", "user",
                         "--status", "open")
        assert code == 1 and "deferred" in out, out
        assert lrun(repo, "add", "stage", "s", "--status", "done")[0] == 1
        assert len(jl(repo)) == n
        assert lrun(
            repo, "add", "stage", "old", "--status", "done", "--imported",
            "--source", "a:1",
        )[0] == 0


def test_closed_stage_takes_no_open_entry() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "stage", "01-a")
        lrun(repo, "add", "task", "t")
        lrun(repo, "add", "deferred", "later")
        lrun(repo, "close", "T-1", "--note", "ok")
        lrun(repo, "add", "decision", "ok", "--owner", "user", "--link", "S-1")
        assert lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")[0] == 0
        lrun(repo, "add", "stage", "02-b")
        lrun(repo, "add", "task", "u")  # T-2, stage S-2
        n: int = len(jl(repo))
        code, out = lrun(repo, "add", "task", "late", "--stage", "S-1")
        assert code == 1 and "S-1 is closed" in out, out
        assert lrun(repo, "set", "T-2", "--stage", "S-1")[0] == 1
        code, out = lrun(repo, "reopen", "T-1", "--note", "again")
        assert code == 1 and "set T-1 --stage" in out, out
        assert lrun(repo, "start", "DF-1")[0] == 1
        assert len(jl(repo)) == n
        code, out = lrun(
            repo, "add", "task", "x", "--stage", "S-1", "--status", "done"
        )
        assert code == 0, out  # created closed: allowed
        assert lrun(repo, "set", "T-1", "--stage", "S-2")[0] == 0  # T-1 is done
        assert lrun(repo, "reopen", "T-1", "--note", "again")[0] == 0
        assert lrun(repo, "list", "--stage", "S-1")[1].startswith("open 1 ")


def test_supersede() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "decision", "metric dE76", "--owner", "user")
        n: int = len(jl(repo))
        code, out = lrun(repo, "supersede", "D-1", "metric dE00", "--owner", "user")
        s: dict[str, Any] = L.load(repo)
        assert out == "logged D-2: metric dE00 (supersedes D-1)\n", out
        assert len(jl(repo)) == n + 2
        assert s["D-1"].status == "superseded"
        assert s["D-1"].extra["superseded_by"] == "D-2"
        assert s["D-2"].extra["supersedes"] == "D-1" and "D-1" in s["D-2"].links
        assert s["D-2"].status == "done"
        assert lrun(repo, "reopen", "D-1", "--note", "x")[0] == 1  # superseded
        assert lrun(repo, "supersede", "D-1", "again", "--owner", "user")[0] == 1
        lrun(repo, "add", "task", "t")
        assert lrun(repo, "supersede", "T-1", "x", "--owner", "user")[0] == 1
        assert lrun(repo, "supersede", "D-2", "x")[0] == 1  # --owner required
        assert len(jl(repo)) == n + 3


def test_set_appends_lists() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "task", "t", "--ref", "a.md", "--ref", "b.md")
        code, out = lrun(
            repo, "set", "T-1", "--ref", "a.md", "--ref", "c.md", "--owner", "sr2"
        )
        e: Any = L.load(repo)["T-1"]
        assert code == 0 and out == "updated T-1: owner, refs\n", out
        assert e.refs == ["a.md", "b.md", "c.md"] and e.owner == "sr2", e
        assert e.status == "open"
        lrun(repo, "add", "task", "u")
        lrun(repo, "set", "T-2", "--link", "T-1", "--link", "T-1", "--title", "v")
        e = L.load(repo)["T-2"]
        assert e.links == ["T-1"] and e.title == "v", e
        n: int = len(jl(repo))
        code, out = lrun(repo, "set", "T-1")
        assert code == 1 and "nothing to set" in out, out
        assert lrun(repo, "set", "T-1", "--stage", "S-9")[0] == 1
        assert lrun(repo, "set", "T-1", "--link", "X-9")[0] == 1
        assert lrun(repo, "set", "T-1", "--title", "a\nb")[0] == 1
        assert len(jl(repo)) == n


def test_append_only() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        steps: list[tuple[str, ...]] = [
            ("add", "task", "a"),
            ("start", "T-1"),
            ("set", "T-1", "--note", "n"),
            ("close", "T-1", "--note", "done"),
            ("reopen", "T-1", "--note", "again"),
            ("drop", "T-1", "--note", "no"),
            ("add", "decision", "x", "--owner", "user"),
            ("supersede", "D-1", "y", "--owner", "user"),
        ]
        for cmd in steps:
            old: bytes = (repo / L.LEDGER_REL).read_bytes()
            code, out = lrun(repo, *cmd)
            assert code == 0, (cmd, out)
            assert (repo / L.LEDGER_REL).read_bytes().startswith(old), cmd


def seed_views(repo: Path) -> None:
    """Stage S-1, tasks T-1..T-4, D-1 superseded by D-2, F-1, DB-1, H-1, DF-1."""
    lrun(repo, "add", "stage", "03-software-x")
    lrun(repo, "add", "task", "Loader", "--owner", "sr1")
    lrun(repo, "start", "T-1")
    lrun(repo, "add", "task", "Parser")
    lrun(repo, "add", "task", "Ask the user", "--owner", "user")
    lrun(repo, "add", "task", "Old")
    lrun(repo, "close", "T-4", "--note", "done long ago")
    lrun(repo, "add", "decision", "metric dE76", "--owner", "user")
    lrun(repo, "supersede", "D-1", "metric dE00", "--owner", "user")
    lrun(repo, "add", "fetch", "smith2020: A paper")
    lrun(repo, "add", "debt", "hardcoded path")
    lrun(repo, "add", "handoff", "continue in a new session")
    lrun(repo, "add", "deferred", "plot later")


def sections(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    head: str | None = None
    for ln in text.splitlines():
        if ln.startswith("## "):
            head = ln
            out[head] = ""
        elif head is not None:
            out[head] += ln + "\n"
    return out


def test_status_md_sections() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        seed_views(repo)
        st: str = (repo / L.STATUS_REL).read_text()  # no render call: automatic
        assert st.startswith("# Status (generated)\n"), st
        assert "Generated from pm/ledger.jsonl by rk.py at" in st.splitlines()[2]
        sec: dict[str, str] = sections(st)
        assert "T-1" in sec["## Running"] and "sr1" in sec["## Running"]
        assert "T-3" in sec["## Needs you"]
        assert "T-3" not in sec["## Open tasks"] and "T-2" in sec["## Open tasks"]
        assert "T-4" not in st and "D-1" not in st
        assert "D-2" in sec["## Recent decisions"]
        assert "F-1" in sec["## Open fetches"] and "DB-1" in sec["## Open debt"]
        assert "H-1" in sec["## Open handoffs"] and "DF-1" in sec["## Deferred"]
        assert "tasks: 1 running, 2 open" in sec["## Stages"], sec["## Stages"]
        lrun(repo, "close", "T-1", "--note", "ok")
        assert "## Running" not in (repo / L.STATUS_REL).read_text()


def test_status_declared_type_and_recent_decisions() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        (repo / "pm/kinds/k.md").write_text("<!-- rk:type sample SM -->\n")
        lrun(repo, "add", "sample", "a sample")
        lrun(repo, "add", "decision", "early", "--owner", "user")  # no stage
        sec: dict[str, str] = sections((repo / L.STATUS_REL).read_text())
        assert "SM-1" in sec["## Open sample"]
        assert "D-1" in sec["## Recent decisions"]  # no stage is open: all count
        lrun(repo, "add", "stage", "03-x")
        for i in range(7):
            lrun(repo, "add", "decision", f"dec {i}", "--owner", "user")
        lrun(repo, "add", "stage", "04-y")
        lrun(repo, "add", "decision", "last", "--owner", "user", "--stage", "04-y")
        sec = sections((repo / L.STATUS_REL).read_text())
        rec: str = sec["## Recent decisions"]
        assert len(rec.splitlines()) == 5 and "D-9" in rec and "D-5" in rec, rec
        assert "D-4" not in rec and "D-1 " not in rec
        lrun(repo, "add", "decision", "big call", "--owner", "user")  # two open stages
        assert L.load(repo)["D-10"].stage == ""
        rec = sections((repo / L.STATUS_REL).read_text())["## Recent decisions"]
        assert "D-10" in rec and len(rec.splitlines()) == 5, rec


def test_render_command() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        (repo / L.LEDGER_REL).write_text(ev_line("T-1", "by hand"))
        assert not (repo / L.STATUS_REL).exists()
        code, out = lrun(repo, "render")
        assert code == 0 and out == "wrote pm/STATUS.md (1 open)\n", out
        assert "T-1" in (repo / L.STATUS_REL).read_text()


def test_list_default_and_filters() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        seed_views(repo)
        out: str = lrun(repo, "list")[1]
        assert out.splitlines()[0].startswith("open "), out
        assert "D-2" not in out and "T-4" not in out
        lines: list[str] = lrun(repo, "list", "--type", "task")[1].splitlines()
        assert all(ln.startswith("T-") for ln in lines[1:]), lines
        assert lines[1].startswith("T-3"), lines  # owner user first
        assert lines[2].startswith("T-1"), lines  # then running first
        assert "T-3" in lrun(repo, "list", "--owner", "user")[1]
        assert "T-1" in lrun(repo, "list", "--stage", "03-software-x")[1]
        assert lrun(repo, "list", "--type", "tsak")[0] == 1
        assert "T-4" in lrun(repo, "list", "--all")[1]
        head: str = out.splitlines()[0]
        assert head.startswith("open 8 (running 1): task 3"), head
        ids: list[str] = [ln.split()[0] for ln in out.splitlines()[1:]]
        assert ids[:4] == ["S-1", "H-1", "T-3", "T-1"], ids  # stage, handoff, user


def test_list_columns_separate() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        (repo / L.LEDGER_REL).write_text(ev_line("DF-1000", "wide", "deferred"))
        lrun(repo, "add", "decision", "a", "--owner", "averyverylongname")
        lrun(repo, "supersede", "D-1", "b", "--owner", "user")
        out: list[str] = lrun(repo, "list", "--all")[1].splitlines()[1:]
        cols: list[list[str]] = [ln.split()[:3] for ln in out]
        assert ["DF-1000", "open", "lead"] in cols, out
        assert ["D-1", "superseded", "averyver"] in cols, out
        assert all(len(ln) <= L.LINE_MAX for ln in out), out


def test_list_size_bound() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        title: str = "t" * 120
        rows: list[str] = []
        for i in range(1, 51):
            status: str = "running" if i <= 10 else "open"
            rows.append(ev_line(f"T-{i}", title, "task", status))
        for i in range(51, 151):
            rows.append(ev_line(f"T-{i}", title, "task", "done"))
        for i in range(1, 11):
            rows.append(ev_line(f"DB-{i}", title, "debt"))
        for i in range(1, 41):
            rows.append(ev_line(f"D-{i}", title, "decision", "done"))
        (repo / L.LEDGER_REL).write_text("".join(rows))
        out: str = lrun(repo, "list")[1]
        assert len(out.encode()) <= L.LIST_MAX_BYTES, len(out.encode())
        assert all(len(ln) <= L.LINE_MAX for ln in out.splitlines())
        assert out.splitlines()[-1].startswith("+30 more"), out.splitlines()[-1]
        full: list[str] = lrun(repo, "list", "--limit", "0")[1].splitlines()
        assert len(full) == 61, len(full)
    with tempfile.TemporaryDirectory() as d:  # many long type and owner names
        repo = new_repo(Path(d))
        types: list[str] = [f"{c * 30}-{i}" for i, c in enumerate("abcdefgh")]
        rows = [
            ev_line(f"X-{i}", "t" * 160, typ, "running" if i % 3 else "open",
                    "o" * 60)
            for i, typ in enumerate(types * 25, 1)
        ]  # fmt: skip
        (repo / L.LEDGER_REL).write_text("".join(rows))
        out = lrun(repo, "list")[1]
        assert len(out.encode()) <= L.LIST_MAX_BYTES, len(out.encode())
        assert all(len(ln) <= L.LINE_MAX for ln in out.splitlines()), out
        head: str = out.splitlines()[0]
        assert head.startswith("open 200 (running 134): "), head
        shown: list[str] = head.split(": ", 1)[1].removesuffix(", ...").split(", ")
        assert shown and all(x == f"{t} 25" for x, t in zip(shown, types)), head
        assert head.endswith(", ...") and len(shown) < len(types), head


def test_show_history() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "task", "Loader", "--note", "line1\nline2")
        lrun(repo, "start", "T-1")
        out: str = lrun(repo, "show", "T-1")[1]
        assert "title: Loader" in out and "history:" in out, out
        assert " add " in out and " set " in out and "status=running" in out, out
        hist: list[str] = out.split("history:\n")[1].splitlines()
        assert len(hist) == 2 and all(h.startswith("  ") for h in hist), hist
        assert lrun(repo, "show", "T-99")[0] == 1
        lrun(repo, "add", "decision", "use dE00", "--owner", "user", "--link", "T-1")
        lrun(repo, "add", "fetch", "smith2020")
        lrun(repo, "set", "T-1", "--link", "F-1")
        out = lrun(repo, "show", "T-1")[1]
        linked: list[str] = out.split("linked:\n")[1].split("history:")[0].splitlines()
        assert linked == ["  F-1 open: smith2020", "  D-1 done: use dE00"], linked


def test_search() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "task", "Fix Loader")
        lrun(repo, "close", "T-1", "--note", "ok")
        lrun(
            repo, "add", "task", "Old row", "--imported", "--legacy-id", "07-12",
            "--source", "pm/living/TASKS.md:44",
        )
        assert "T-1 done" in lrun(repo, "search", "loader")[1]
        assert "[src pm/living/TASKS.md:44]" in lrun(repo, "search", "07-12")[1]
        assert lrun(repo, "search", "loader", "--type", "decision")[1] == ""
        assert lrun(repo, "search", "zzz")[1] == ""
        assert lrun(repo, "search", "x", "--type", "tsak")[0] == 1


def test_recent() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "task", "a")
        lrun(repo, "add", "task", "b")
        lrun(repo, "add", "task", "c")
        lrun(repo, "start", "T-1")
        out: list[str] = lrun(repo, "recent", "-n", "3")[1].splitlines()
        assert len(out) == 3 and " T-1 " in out[0] and " set " in out[0], out
        assert " T-3 " in out[1] and " T-2 " in out[2], out


def bcheck(repo: Path, text: str) -> tuple[int, str]:
    """brief-check with `text` on stdin, as the hook runs it."""
    old: Any = sys.stdin
    sys.stdin = io.StringIO(text)
    buf: io.StringIO = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            code: int = L.main(["brief-check", "--repo", str(repo), "--who", "hook"])
    finally:
        sys.stdin = old
    return code, buf.getvalue()


def test_stage_close_refusals() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "stage", "03-software-x")
        lrun(repo, "add", "task", "a", "--owner", "sr1")
        lrun(repo, "start", "T-1")
        lrun(repo, "add", "task", "b")
        lrun(repo, "add", "decision", "sign-off", "--owner", "user", "--link", "S-1")
        n: int = len(jl(repo))
        code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")
        assert code == 1 and "T-1 running" in out and "T-2 open" in out, out
        assert len(jl(repo)) == n
        lrun(repo, "close", "T-1", "--note", "ok")
        lrun(repo, "add", "stage", "04-x")
        lrun(repo, "set", "T-2", "--stage", "S-2")
        lrun(repo, "add", "decision", "lead ok", "--owner", "lead", "--link", "S-1")
        code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-2")
        assert code == 1 and "owner user" in out, out
        lrun(repo, "add", "decision", "unlinked", "--owner", "user")
        code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-3")
        assert code == 1 and "--link S-1" in out, out
        assert "ask the user" in out and "only after" in out, out
        code, out = lrun(repo, "stage-close", "S-1")
        assert code == 1 and "--sign-off" in out, out
        lrun(repo, "add", "decision", "old ok", "--owner", "user", "--link", "S-1")
        lrun(repo, "supersede", "D-4", "new ok", "--owner", "user")
        code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-4")
        assert code == 1 and "superseded" in out, out
        code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")
        assert code == 0 and out == "closed S-1: sign-off D-1\n", out
        s: Any = L.load(repo)["S-1"]
        assert s.status == "done" and "D-1" in s.links, s
        assert lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")[0] == 1
        assert lrun(repo, "stage-close", "T-1", "--sign-off", "D-1")[0] == 1


def test_stage_close_sign_off_needs_link() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "stage", "01-a")
        lrun(repo, "add", "decision", "use dE00", "--owner", "user")  # stage S-1
        assert L.load(repo)["D-1"].stage == "S-1"
        n: int = len(jl(repo))
        code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")
        assert code == 1 and "does not link S-1" in out, out
        assert "ask the user" in out and "--link S-1" in out, out
        assert len(jl(repo)) == n and L.load(repo)["S-1"].status == "open"
        lrun(repo, "add", "decision", "01 done", "--owner", "user", "--link", "S-1")
        code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-2")
        assert code == 0 and out == "closed S-1: sign-off D-2\n", out


def test_brief_check() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "task", "old")
        lrun(repo, "close", "T-1", "--note", "done")
        lrun(repo, "add", "task", "work")
        lrun(repo, "add", "decision", "x", "--owner", "user")
        n: int = len(jl(repo))
        assert bcheck(repo, "hi lead, DONE, report at x") == (0, "")
        assert bcheck(repo, "quoting: the DELIVERABLE: line was clear")[0] == 0
        assert len(jl(repo)) == n
        code, out = bcheck(repo, "You are sr1\nDELIVERABLE: x at y\n")
        assert code == 2 and out.startswith("refused:"), out
        assert str(RK_PY.resolve()) in out, out
        code, out = bcheck(repo, "  DELIVERABLE: x\nTASK: T-9\n")
        assert code == 2 and "T-9 unknown" in out, out
        code, out = bcheck(repo, "DELIVERABLE: x\nTASK: T-1\n")
        assert code == 2 and "T-1 is done" in out, out
        code, out = bcheck(repo, "DELIVERABLE: x\nTASK: D-1\n")
        assert code == 2 and "D-1 is not a task" in out, out
        assert bcheck(repo, "DELIVERABLE: x\nTASK: T-2, T-9\n")[0] == 2
        assert len(jl(repo)) == n
        code, out = bcheck(repo, "DELIVERABLE: x\nTASK: T-2\n")
        assert code == 0 and out == "started T-2: work\n", out
        e: Any = L.load(repo)["T-2"]
        assert e.status == "running" and jl(repo)[-1]["who"] == "hook", e
        m: int = len(jl(repo))
        assert bcheck(repo, "DELIVERABLE: x\nTASK: T-2\n")[0] == 0
        assert len(jl(repo)) == m
        bare: Path = Path(d) / "bare"
        bare.mkdir()
        assert bcheck(bare, "DELIVERABLE: x\n") == (0, "")
        with (repo / L.LEDGER_REL).open("a") as fh:
            fh.write("{bad\n")
        code, out = bcheck(repo, "DELIVERABLE: x\nTASK: T-2\n")
        assert code == 2 and f"{L.LEDGER_REL}:{m + 1}" in out, out


def test_running_age_counts_from_start() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        now: datetime = datetime.now().astimezone()

        def row(ev: str, eid: str, days: int, hours: int, f: dict[str, Any]) -> str:
            ts: str = (now - timedelta(days=days, hours=hours)).isoformat(
                timespec="seconds"
            )
            return json.dumps(
                {"ts": ts, "who": "lead", "ev": ev, "id": eid, "f": f}
            ) + "\n"

        base: dict[str, Any] = {
            "type": "task", "title": "Slow", "status": "open", "owner": "sr1",
            "stage": "", "note": "", "links": [], "refs": [],
        }
        (repo / L.LEDGER_REL).write_text(
            row("add", "T-1", 10, 0, base)  # created 10d ago
            + row("set", "T-1", 0, 2, {"status": "running"})  # started 2h ago
            + row("add", "T-2", 10, 0, {**base, "title": "Waiting"})
        )
        st: dict[str, Any] = L.load(repo)
        assert L.age(st["T-1"].started, now) == "2h", st["T-1"].started
        lrun(repo, "render")
        sec: dict[str, str] = sections((repo / L.STATUS_REL).read_text())
        assert "(sr1, 2h) Slow" in sec["## Running"], sec["## Running"]
        assert "(sr1, 10d) Waiting" in sec["## Open tasks"]  # open: from created
        row1: str = [ln for ln in lrun(repo, "list")[1].splitlines() if "Slow" in ln][0]
        assert "  2h  Slow" in row1, row1
        # reopened and started again: counts from the latest start
        lrun(repo, "close", "T-1", "--note", "x")
        lrun(repo, "reopen", "T-1", "--note", "y")
        lrun(repo, "start", "T-1")
        assert L.age(L.load(repo)["T-1"].started, now) == "0m"
        sec = sections((repo / L.STATUS_REL).read_text())
        assert "(sr1, 0m) Slow" in sec["## Running"], sec["## Running"]


def main() -> int:
    tests: list[tuple[str, Callable[[], None]]] = [
        (n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)
    ]
    failed: list[str] = []
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except KeyboardInterrupt:
            raise
        except BaseException as e:
            failed.append(name)
            print(f"FAIL {name}: {type(e).__name__}: {e}")
            if not isinstance(e, AssertionError):
                traceback.print_exc(limit=3, file=sys.stdout)
    if failed:
        print(f"{len(failed)} of {len(tests)} failed: {', '.join(failed)}")
        return 1
    print("all ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
