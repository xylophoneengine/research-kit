#!/usr/bin/env python3
"""Tests for ledger.py. Run: python3 -I test_ledger.py (test_rk.py runs them too)."""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from collections.abc import Callable, Iterator
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
CLOSED_D1: str = "closed S-1: sign-off D-1\nwrote pm/stages/"  # stage-close receipt


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
        code, out = lrun(repo, "add", "task", "Write loader", "--note", "n")
        assert code == 0 and out == "logged T-1: Write loader (no stage)\n", out
        ev: dict[str, Any] = jl(repo)[0]
        assert list(ev)[:5] == ["ts", "who", "ev", "id", "f"] and ev["ev"] == "add"
        assert ev["kit"] == L.kit_version() != "unknown", ev
        assert ev["f"]["status"] == "open" and ev["f"]["owner"] == "lead", ev
        out = lrun(repo, "add", "task", "B", "--note", "n")[1]
        assert out == "logged T-2: B (no stage)\n", out
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
        assert lrun(repo, "add", "sample", "x")[1] == "logged SM-1: x (no stage)\n"
        kind.write_text("<!-- rk:type Bad -->\n")
        code, out = lrun(repo, "add", "task", "x", "--note", "n")
        assert code == 1 and "k.md:1" in out, out
        kind.write_text("<!-- rk:type foo T -->\n")
        code, out = lrun(repo, "add", "task", "x", "--note", "n")
        assert code == 1 and "k.md:1" in out, out
        assert len(jl(repo)) == 1


def test_duplicate_id_detected() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        (repo / L.LEDGER_REL).write_text(
            ev_line("T-1", "a") + ev_line("T-2", "b") + ev_line("T-1", "c")
        )
        before: bytes = (repo / L.LEDGER_REL).read_bytes()
        code, out = lrun(repo, "add", "task", "x", "--note", "n")
        assert code == 1 and "duplicate id T-1: lines 1 and 3" in out, out
        assert (repo / L.LEDGER_REL).read_bytes() == before


def test_bad_line_fails_loudly() -> None:
    for bad in ("{not json", "<<<<<<< HEAD"):
        with tempfile.TemporaryDirectory() as d:
            repo: Path = new_repo(Path(d))
            (repo / L.LEDGER_REL).write_text(ev_line("T-1", "a") + bad + "\n")
            before: bytes = (repo / L.LEDGER_REL).read_bytes()
            code, out = lrun(repo, "add", "task", "x", "--note", "n")
            assert code == 1 and "pm/ledger.jsonl:2" in out and "by hand" in out, out
            assert (repo / L.LEDGER_REL).read_bytes() == before


def test_concurrent_appends() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        procs: list[subprocess.Popen[bytes]] = [
            subprocess.Popen(
                [sys.executable, "-I", str(RK_PY), "add", "task", f"p{i}",
                 "--note", "n", "--repo", str(repo)],
                stdout=subprocess.DEVNULL,
            )
            for i in range(20)
        ]
        rcs: list[int] = [p.wait() for p in procs]
        assert all(rc == 0 for rc in rcs), rcs
        ids: list[str] = sorted(e["id"] for e in jl(repo))
        assert ids == sorted(f"T-{i}" for i in range(1, 21)), ids


def test_no_git_call() -> None:
    """Only doctor and stage-close run git, only read-only subcommands, all
    through ledger._git; every other command never runs git."""
    for src in (RK_PY, RK_PY.with_name("ledger.py")):
        text: str = src.read_text()
        bad: tuple[str, ...] = ("os.system", "os.exec", "os.popen", "import pty")
        assert not any(w in text for w in bad), src
    assert "subprocess" not in RK_PY.read_text()
    text = RK_PY.with_name("ledger.py").read_text()
    assert text.count("subprocess.run(") == 1, "git only through _git"
    doc_start: int = text.index("# ---- doctor ---")
    doc_end: int = text.index("def _cmd_brief_check(")
    calls: list[int] = [i for i in range(len(text)) if text.startswith("_git(", i)]
    assert calls and all(doc_start < i < doc_end for i in calls), "git outside doctor"
    run_at: int = text.index("subprocess.run(")
    assert doc_start < run_at < doc_end and text.index("def _git(") < run_at
    assert L.GIT_READ == {
        "status", "diff", "ls-files", "check-ignore", "show", "rev-parse"
    }  # design D2: rev-parse joins (git_exclude_file)
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        fakebin: Path = Path(d) / "bin"
        fakebin.mkdir()
        log: Path = Path(d) / "git-calls"
        git: Path = fakebin / "git"
        envlog: Path = Path(d) / "git-env"
        git.write_text(
            f'#!/bin/sh\necho "$3" >> "{log}"\n'
            f'echo "${{GIT_OPTIONAL_LOCKS:-unset}} ${{GIT_DIR:-nodir}}" >> "{envlog}"\n'
            "exit 0\n"
        )
        git.chmod(0o755)
        env: dict[str, str] = {
            **os.environ, "PATH": f"{fakebin}{os.pathsep}{os.environ['PATH']}"
        }

        def tool(*argv: str) -> list[str]:
            """git subcommands (after -C DIR) that one tool call ran."""
            log.write_text("")
            r: subprocess.CompletedProcess[bytes] = subprocess.run(
                [sys.executable, "-I", str(RK_PY), *argv, "--repo", str(repo)],
                env=env, capture_output=True,
            )
            assert r.returncode == 0, (argv, r)
            return log.read_text().split()

        for argv in (
            ("add", "stage", "software-x", "--open"),
            ("add", "task", "x", "--note", "n"),
            ("start", "T-1"),
            ("close", "T-1", "--note", "ok"),
            ("set", "T-1", "--owner", "sr1"),
            ("list", "--all"),
            ("show", "T-1"),
            ("doctor", "--start"),
            ("add", "decision", "ok", "--owner", "user", "--link", "S-1"),
        ):
            assert tool(*argv) == [], argv
        for argv in (("doctor",), ("stage-close", "S-1", "--sign-off", "D-1")):
            envlog.write_text("")
            env["GIT_DIR"] = str(Path(d) / "other.git")  # must not reach git
            calls: list[str] = tool(*argv)
            assert calls and set(calls) <= L.GIT_READ, (argv, calls)
            seen: set[str] = set(envlog.read_text().splitlines())
            assert seen == {"0 nodir"}, seen  # no index write; no inherited GIT_DIR
        try:
            L._git(repo, ["commit", "-m", "x"])
        except ValueError:
            pass
        else:
            raise AssertionError("_git ran a write command")


def test_repo_lookup() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        assert L.find_repo(repo / "pm" / "kinds") == repo.resolve()
        bare: Path = Path(d) / "bare"
        bare.mkdir()
        snap: dict[str, bytes | None] = snapshot(bare)
        code, out = lrun(bare, "add", "task", "x", "--note", "n")
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
            [sys.executable, "-I", str(RK_PY), "add", "task", "from wt", "--note", "n"],
            cwd=wt / "pm", capture_output=True, text=True,
        )
        assert r.returncode == 0 and r.stdout == "logged T-1: from wt (no stage)\n", r
        assert len(jl(main)) == 1 and jl(wt) == [], (jl(main), jl(wt))


def test_unterminated_last_line_kept() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        (repo / L.LEDGER_REL).write_text(ev_line("T-1", "a").rstrip("\n"))
        code, out = lrun(repo, "add", "task", "b", "--note", "n")
        assert code == 0 and out == "logged T-2: b (no stage)\n", out
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
        x: tuple[str, ...] = ("add", "task", "x", "--note", "n")
        assert lrun(repo, *x, "--date", "2025-01-01")[0] == 1
        assert lrun(repo, "add", "task", "x", "--imported")[0] == 1
        assert lrun(repo, *x, "--status", "superseded")[0] == 1
        assert lrun(
            repo, "add", "task", "x", "--imported", "--source", "a:1",
            "--date", "2025-13-01",
        )[0] == 1
        assert len(jl(repo)) == 1


def test_title_one_line_and_ascii() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        assert lrun(repo, "add", "task", "a\nb", "--note", "n")[0] == 1
        assert lrun(repo, "add", "task", "   ", "--note", "n")[0] == 1
        assert lrun(repo, "add", "task", "Δ métrique", "--note", "n")[0] == 0
        raw: str = (repo / L.LEDGER_REL).read_text()
        assert raw.isascii(), raw
        assert L.load(repo)["T-1"].title == "Δ métrique"


def test_link_and_stage_validation() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        assert lrun(repo, "add", "task", "x", "--note", "n", "--link", "X-9")[0] == 1
        assert lrun(repo, "add", "stage", "software-x", "--open")[1] == (
            "logged S-1: 01-software-x\n"
            "folder pm/stages/01-software-x/ (deliverables/ notes/ code/ chat/)\n"
        )
        lrun(repo, "add", "task", "a", "--note", "n")
        assert L.load(repo)["T-1"].stage == "S-1"
        lrun(repo, "add", "stage", "paper-y", "--open")
        lrun(repo, "add", "task", "b", "--note", "n")
        assert L.load(repo)["T-2"].stage == ""
        lrun(
            repo, "add", "task", "c", "--note", "n", "--stage", "02-paper-y",
            "--link", "T-1",
        )
        e: Any = L.load(repo)["T-3"]
        assert e.stage == "S-2" and e.links == ["T-1"], e
        assert lrun(repo, "add", "task", "d", "--note", "n", "--stage", "S-9")[0] == 1
        assert lrun(repo, "add", "task", "d", "--note", "n", "--stage", "T-1")[0] == 1


def test_title_length_cap() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        long: str = "w" * L.TITLE_MAX
        assert lrun(repo, "add", "task", long, "--note", "n")[0] == 0
        code, out = lrun(repo, "add", "task", long + "w", "--note", "n")
        assert code == 1 and "--note" in out, out
        code, out = lrun(repo, "set", "T-1", "--title", long + "w")
        assert code == 1 and "--note" in out, out
        lrun(repo, "add", "decision", "d" * L.TITLE_MAX, "--owner", "user")
        lrun(repo, "add", "stage", "software-" + "s" * (L.TITLE_MAX - 12), "--open")
        lrun(repo, "add", "task", "u" * L.TITLE_MAX, "--note", "n", "--owner", "user")
        lrun(repo, "start", "T-2")
        st: str = (repo / L.STATUS_REL).read_text()
        for ln in st.splitlines():
            if ln.startswith("- "):
                assert len(ln) <= L.LINE_MAX and ln.endswith("..."), ln
        assert len(jl(repo)) == 5


def test_status_cycle() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "task", "Loader", "--note", "n", "--owner", "sr1")
        assert lrun(repo, "start", "T-1")[1] == "started T-1: Loader\n"
        n: int = len(jl(repo))
        code, out = lrun(repo, "start", "T-1")
        assert code == 0 and "already running" in out, out
        assert len(jl(repo)) == n
        assert lrun(repo, "close", "T-1")[0] == 1  # needs --note
        (repo / "a.md").write_text("a")
        (repo / "b.md").write_text("b")
        code, out = lrun(
            repo, "close", "T-1", "--note", "loader works",
            "--ref", "a.md", "--ref", "b.md",
        )
        e: Any = L.load(repo)["T-1"]
        assert out == "closed T-1: loader works (no stage)\n", out
        assert e.status == "done" and e.refs == ["a.md", "b.md"], e
        assert lrun(repo, "close", "T-1", "--note", "again")[0] == 1
        assert lrun(repo, "start", "T-1")[0] == 1  # use reopen
        lrun(repo, "add", "task", "B", "--note", "n")
        lrun(repo, "drop", "T-2", "--note", "not needed")
        assert L.load(repo)["T-2"].status == "dropped"
        lrun(repo, "reopen", "T-2", "--note", "needed after all")
        e = L.load(repo)["T-2"]
        assert e.status == "open" and e.note == "n\nnot needed\nneeded after all", e
        assert lrun(repo, "reopen", "T-2", "--note", "x")[0] == 1  # already open
        code, out = lrun(repo, "start", "T-2", "--owner", "sr2")
        assert code == 0 and L.load(repo)["T-2"].owner == "sr2", out
        long: str = "x" * 70 + "\nsecond line"
        out = lrun(repo, "close", "T-2", "--note", long)[1]
        assert out == f"closed T-2: {'x' * 60} (no stage)\n", out
        assert lrun(repo, "close", "T-9", "--note", "x")[0] == 1  # unknown id


def test_close_refuses_stage_and_decision() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "stage", "software-x", "--open")
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
        assert lrun(
            repo, "add", "stage", "software-s", "--open", "--status", "done"
        )[0] == 1
        assert len(jl(repo)) == n
        assert lrun(
            repo, "add", "stage", "old", "--status", "done", "--imported",
            "--source", "a:1",
        )[0] == 0


def test_closed_stage_takes_no_open_entry() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "stage", "software-a", "--open")
        lrun(repo, "add", "task", "t", "--note", "n")
        lrun(repo, "add", "deferred", "later")
        lrun(repo, "close", "T-1", "--note", "ok")
        lrun(repo, "add", "decision", "ok", "--owner", "user", "--link", "S-1")
        assert lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")[0] == 0
        lrun(repo, "add", "stage", "software-b", "--open")
        lrun(repo, "add", "task", "u", "--note", "n")  # T-2, stage S-2
        n: int = len(jl(repo))
        code, out = lrun(repo, "add", "task", "late", "--note", "n", "--stage", "S-1")
        assert code == 1 and "S-1 is closed" in out, out
        assert lrun(repo, "set", "T-2", "--stage", "S-1")[0] == 1
        code, out = lrun(repo, "reopen", "T-1", "--note", "again")
        assert code == 1 and "set T-1 --stage" in out, out
        assert len(jl(repo)) == n
        code, out = lrun(
            repo, "add", "task", "x", "--note", "n", "--stage", "S-1",
            "--status", "done",
        )
        assert code == 0, out  # created closed: allowed
        assert lrun(repo, "set", "T-1", "--stage", "S-2")[0] == 0  # T-1 is done
        assert lrun(repo, "reopen", "T-1", "--note", "again")[0] == 0
        assert lrun(repo, "list", "--stage", "S-1")[1].startswith("open 1 ")


def test_non_task_open_entry_into_closed_stage() -> None:  # 0.2.2 R1-R5
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "stage", "paper-x", "--open")  # S-1
        lrun(repo, "add", "decision", "ok", "--owner", "user", "--link", "S-1")
        assert lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")[0] == 0
        rec: Path = repo / "pm/stages/01-paper-x/LEDGER.md"
        frozen: str = rec.read_text()
        lrun(repo, "add", "stage", "paper-y", "--open")  # S-2, the default stage now
        for typ in ("debt", "deferred", "fetch", "handoff"):
            lrun(repo, "add", typ, f"a {typ}")  # DB-1, DF-1, F-1, H-1 in S-2
        # R1: open non-task entries can be set into the done stage; the receipt names it
        for eid in ("DB-1", "DF-1", "F-1", "H-1"):
            code, out = lrun(repo, "set", eid, "--stage", "S-1")
            assert code == 0 and out == f"updated {eid}: stage (stage S-1)\n", out
            e: Any = L.load(repo)[eid]
            assert e.stage == "S-1" and e.status == "open", e
        code, out = lrun(repo, "add", "debt", "found later", "--stage", "S-1")
        assert code == 0 and out == "logged DB-2: found later (stage S-1)\n", out
        rows: Path = write_rows(
            Path(d),
            [{"type": "fetch", "title": "old", "source": "B:1", "stage": "S-1"}],
        )
        assert lrun(repo, "import", str(rows))[0] == 0  # the backfill case
        assert L.load(repo)["F-2"].stage == "S-1"
        # R2: an open or running task still cannot, same text
        lrun(repo, "add", "task", "t", "--note", "n")  # T-1 in S-2
        want: str = "error: S-1 is closed (done); an open task cannot go into it: "
        code, out = lrun(repo, "set", "T-1", "--stage", "S-1")
        assert code == 1 and out == want + "pick an open stage\n", out
        code, out = lrun(repo, "add", "task", "u", "--note", "n", "--stage", "S-1")
        assert code == 1 and out == want + "pass --stage with an open stage\n", out
        # type stage keeps the old rule: no open stage inside a done one
        code, out = lrun(repo, "add", "stage", "paper-z", "--open", "--stage", "S-1")
        assert code == 1 and "an open stage cannot go into it" in out, out
        lrun(repo, "start", "T-1")
        code, out = lrun(repo, "set", "T-1", "--stage", "S-1")
        assert code == 1 and out == (
            "error: S-1 is closed (done); a running task cannot go into it: "
            "pick an open stage\n"
        ), out
        assert L.load(repo)["T-1"].stage == "S-2"
        # R3: a done or shelved non-task reopens in the done stage; a task does not
        lrun(repo, "close", "DB-1", "--note", "fixed")
        code, out = lrun(repo, "reopen", "DB-1", "--note", "back")
        assert code == 0 and out == "reopened DB-1: back (stage S-1)\n", out
        lrun(repo, "shelve", "F-1", "--note", "later")
        code, out = lrun(repo, "reopen", "F-1", "--note", "now")
        assert code == 0 and out == "reopened F-1: now (stage S-1)\n", out
        lrun(repo, "close", "T-1", "--note", "ok")
        assert lrun(repo, "set", "T-1", "--stage", "S-1")[0] == 0  # done: allowed
        code, out = lrun(repo, "reopen", "T-1", "--note", "again")
        assert code == 1 and "re-stage it first: set T-1 --stage S-<x>" in out, out
        lrun(repo, "add", "task", "v", "--note", "n")  # T-2 in S-2
        lrun(repo, "shelve", "T-2", "--note", "later")
        assert lrun(repo, "set", "T-2", "--stage", "S-1")[0] == 0  # shelved: allowed
        assert lrun(repo, "reopen", "T-2", "--note", "again")[0] == 1
        # start: the same check, so an open non-task in the done stage can start
        assert lrun(repo, "start", "DF-1")[1] == "started DF-1: a deferred\n"
        # R4, R5: the views; the frozen record is not rewritten
        out = lrun(repo, "list", "--stage", "S-1")[1]
        for eid in ("DB-1", "DB-2", "DF-1", "F-1", "F-2", "H-1"):
            assert eid in out, out
        assert "DB-1" in lrun(repo, "list", "--stage", "S-1", "--all")[1]
        assert "DB-1" in sections((repo / L.STATUS_REL).read_text())["## Open debt"]
        assert rec.read_text() == frozen and "DB-1" not in frozen
        assert lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")[0] == 1  # done


def test_closed_stage_declared_type_and_import_rows() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        repo: Path = new_repo(root)
        (repo / "pm/kinds/k.md").write_text("<!-- rk:type sample SM -->\n")
        lrun(repo, "add", "stage", "paper-x", "--open")  # S-1
        lrun(repo, "add", "decision", "ok", "--owner", "user", "--link", "S-1")
        assert lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")[0] == 0
        lrun(repo, "add", "stage", "paper-y", "--open")  # S-2
        # a declared type is a non-task: open entries go into the done stage
        code, out = lrun(repo, "add", "sample", "a", "--stage", "S-1")
        assert code == 0 and out == "logged SM-1: a (stage S-1)\n", out
        lrun(repo, "add", "sample", "b")  # SM-2, default stage S-2
        code, out = lrun(repo, "set", "SM-2", "--stage", "S-1")
        assert code == 0 and out == "updated SM-2: stage (stage S-1)\n", out
        assert lrun(repo, "start", "SM-1")[0] == 0
        assert lrun(repo, "drop", "SM-2", "--note", "x")[0] == 0
        code, out = lrun(repo, "reopen", "SM-2", "--note", "back")  # from dropped
        assert code == 0 and out == "reopened SM-2: back (stage S-1)\n", out
        # import rows: a running non-task passes, an open or running task does not
        rows: Path = write_rows(root, [
            {"type": "debt", "title": "d", "source": "A:1", "stage": "S-1",
             "status": "running"},
            {"type": "sample", "title": "s", "source": "A:2", "stage": "S-1"},
            {"type": "task", "title": "t", "source": "A:3", "stage": "S-1",
             "status": "running"},
            {"type": "task", "title": "u", "source": "A:4", "stage": "S-1"},
        ])
        code, out = lrun(repo, "import", str(rows), "--dry-run")
        out = out.replace(f"{root}/", "")  # the errors start with the file path
        assert code == 1 and out == (
            "rows.jsonl:3: S-1 is closed (done); a running task cannot go into it: "
            "pass --stage with an open stage\n"
            "rows.jsonl:4: S-1 is closed (done); an open task cannot go into it: "
            "pass --stage with an open stage\n"
        ), out
        out = lrun(repo, "list", "--stage", "S-1", "--all")[1]
        assert len(out.splitlines()) == 4, out  # head, D-1, SM-1, SM-2: no import


def test_supersede() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "decision", "metric dE76", "--owner", "user")
        n: int = len(jl(repo))
        code, out = lrun(repo, "supersede", "D-1", "metric dE00", "--owner", "user")
        s: dict[str, Any] = L.load(repo)
        assert out == "logged D-2: metric dE00 (supersedes D-1; no stage)\n", out
        assert len(jl(repo)) == n + 2
        assert s["D-1"].status == "superseded"
        assert s["D-1"].extra["superseded_by"] == "D-2"
        assert s["D-2"].extra["supersedes"] == "D-1" and "D-1" in s["D-2"].links
        assert s["D-2"].status == "done"
        assert lrun(repo, "reopen", "D-1", "--note", "x")[0] == 1  # superseded
        assert lrun(repo, "supersede", "D-1", "again", "--owner", "user")[0] == 1
        lrun(repo, "add", "task", "t", "--note", "n")
        assert lrun(repo, "supersede", "T-1", "x", "--owner", "user")[0] == 1
        assert lrun(repo, "supersede", "D-2", "x")[0] == 1  # --owner required
        assert len(jl(repo)) == n + 3


def test_set_appends_lists() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        for name in ("a.md", "b.md", "c.md"):
            (repo / name).write_text(name)
        lrun(repo, "add", "task", "t", "--note", "n", "--ref", "a.md", "--ref", "b.md")
        code, out = lrun(
            repo, "set", "T-1", "--ref", "a.md", "--ref", "c.md", "--owner", "sr2"
        )
        e: Any = L.load(repo)["T-1"]
        assert code == 0 and out == "updated T-1: owner, refs (no stage)\n", out
        assert e.refs == ["a.md", "b.md", "c.md"] and e.owner == "sr2", e
        assert e.status == "open"
        lrun(repo, "add", "task", "u", "--note", "n")
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
            ("add", "task", "a", "--note", "n"),
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
    lrun(repo, "add", "stage", "software-x", "--open")
    lrun(repo, "add", "task", "Loader", "--note", "n", "--owner", "sr1")
    lrun(repo, "start", "T-1")
    lrun(repo, "add", "task", "Parser", "--note", "n")
    lrun(repo, "add", "task", "Ask the user", "--note", "n", "--owner", "user")
    lrun(repo, "add", "task", "Old", "--note", "n")
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
        lrun(repo, "add", "stage", "paper-x", "--open")
        for i in range(7):
            lrun(repo, "add", "decision", f"dec {i}", "--owner", "user")
        lrun(repo, "add", "stage", "software-y", "--open")  # another kind: both open
        lrun(
            repo, "add", "decision", "last", "--owner", "user", "--stage",
            "02-software-y",
        )
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
        assert "T-1" in lrun(repo, "list", "--stage", "01-software-x")[1]
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
        hist: list[str] = [  # event lines; the kit/sid line under each is indented
            h for h in out.split("history:\n")[1].splitlines() if h[:4] != "    "
        ]
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
        lrun(repo, "add", "task", "Fix Loader", "--note", "n")
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
        lrun(repo, "add", "task", "a", "--note", "n")
        lrun(repo, "add", "task", "b", "--note", "n")
        lrun(repo, "add", "task", "c", "--note", "n")
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
        lrun(repo, "add", "stage", "software-x", "--open")
        lrun(repo, "add", "task", "a", "--note", "n", "--owner", "sr1")
        lrun(repo, "start", "T-1")
        lrun(repo, "add", "task", "b", "--note", "n")
        lrun(repo, "add", "decision", "sign-off", "--owner", "user", "--link", "S-1")
        n: int = len(jl(repo))
        code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")
        assert code == 1 and "T-1 running" in out and "T-2 open" in out, out
        assert len(jl(repo)) == n
        lrun(repo, "close", "T-1", "--note", "ok")
        lrun(repo, "add", "stage", "paper-x", "--open")
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
        assert code == 0 and CLOSED_D1 in out, out
        # D-2 was made while S-1 and S-2 were open: one hint names both (opened
        # last first), at S-1's close as in 0.2.3, and the same line in doctor
        assert "SOFT entry without stage" in out and "D-2 (S-2, S-1) lead ok" in out
        assert "D-2 (S-2, S-1) lead ok" in doctor(repo, "--stage", "S-2")[1]
        s: Any = L.load(repo)["S-1"]
        assert s.status == "done" and "D-1" in s.links, s
        assert lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")[0] == 1
        assert lrun(repo, "stage-close", "T-1", "--sign-off", "D-1")[0] == 1


def test_stage_close_sign_off_needs_link() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "stage", "software-a", "--open")
        lrun(repo, "add", "decision", "use dE00", "--owner", "user")  # stage S-1
        assert L.load(repo)["D-1"].stage == "S-1"
        n: int = len(jl(repo))
        code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")
        assert code == 1 and "does not link S-1" in out, out
        assert "ask the user" in out and "--link S-1" in out, out
        assert len(jl(repo)) == n and L.load(repo)["S-1"].status == "open"
        lrun(repo, "add", "decision", "01 done", "--owner", "user", "--link", "S-1")
        code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-2")
        assert code == 0 and out == (
            "closed S-1: sign-off D-2\nwrote pm/stages/01-software-a/LEDGER.md\n"
        ), out


def test_brief_check() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "task", "old", "--note", "n")
        lrun(repo, "close", "T-1", "--note", "done")
        lrun(repo, "add", "task", "work", "--note", "n")
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


def write_rows(root: Path, rows: list[dict[str, object] | str]) -> Path:
    path: Path = root / "rows.jsonl"
    path.write_text(
        "".join((r if isinstance(r, str) else json.dumps(r)) + "\n" for r in rows)
    )
    return path


def no_ts(repo: Path) -> list[dict[str, Any]]:
    return [{k: v for k, v in e.items() if k != "ts"} for e in jl(repo)]


IMPORT_ROWS: list[dict[str, object] | str] = [
    {"type": "stage", "title": "Old stage", "source": "P.md:1", "status": "done"},
    "",
    {"type": "task", "title": "t1", "source": "P.md:2", "stage": "S-1",
     "status": "done", "legacy_id": "07-1", "date": "2025-03-04", "note": "n",
     "link": ["S-1"], "ref": ["a.md"], "owner": "ann"},
    {"type": "task", "title": "t2", "source": "P.md:3", "stage": "Old stage",
     "status": "dropped"},
    {"type": "decision", "title": "d1", "source": "P.md:4", "owner": "user"},
]


def test_import_happy_and_equals_add() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        repo: Path = new_repo(root)
        rows: Path = write_rows(root, IMPORT_ROWS)
        code, out = lrun(repo, "import", str(rows))
        assert code == 0, out
        assert out.splitlines() == [
            "stage: 1 (done 1) S-1..S-1",
            "task: 2 (done 1, dropped 1) T-1..T-2",
            "decision: 1 (done 1) D-1..D-1",
            "total 4 imported",
        ], out
        st: dict[str, Any] = L.load(repo)
        assert st["T-1"].stage == "S-1" and st["T-2"].stage == "S-1"
        assert st["D-1"].extra["imported"] is True and "S-1" in st["T-1"].links
        assert (repo / L.STATUS_REL).is_file()
        other: Path = new_repo(root / "o")
        for argv in (
            ("stage", "Old stage", "--status", "done", "--source", "P.md:1"),
            ("task", "t1", "--stage", "S-1", "--status", "done", "--legacy-id",
             "07-1", "--date", "2025-03-04", "--note", "n", "--link", "S-1",
             "--ref", "a.md", "--owner", "ann", "--source", "P.md:2"),
            ("task", "t2", "--stage", "Old stage", "--status", "dropped",
             "--source", "P.md:3"),
            ("decision", "d1", "--owner", "user", "--source", "P.md:4"),
        ):
            assert lrun(other, "add", *argv, "--imported")[0] == 0
        assert no_ts(repo) == no_ts(other)


def test_import_failure_writes_nothing() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        repo: Path = new_repo(root)
        lrun(repo, "add", "task", "pre", "--note", "n")
        rows: Path = write_rows(root, [
            {"type": "task", "title": "ok", "source": "P.md:1"},
            {"type": "task", "title": "x" * 161, "source": "P.md:2"},
            "{not json",
            {"type": "task", "title": "k", "source": "P.md:3", "bogus": 1},
            {"type": "task", "title": "m", "source": "P.md:3", "link": ["T-9"]},
            {"type": "task", "title": "s", "source": "P.md:3", "status": "bad"},
            {"type": "task", "title": "ok2", "source": "P.md:4"},
        ])
        before: dict[str, bytes | None] = snapshot(root)
        code, out = lrun(repo, "import", str(rows))
        lines: list[str] = out.splitlines()
        assert code == 1 and len(lines) == 5, out
        assert [ln.split(":")[1] for ln in lines] == ["2", "3", "4", "5", "6"], out
        assert "at most 160" in lines[0] and "not a JSON line" in lines[1], out
        assert "unknown key 'bogus'" in lines[2] and "T-9" in lines[3], out
        assert snapshot(root) == before


def test_import_dry_run() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        repo: Path = new_repo(root)
        rows: Path = write_rows(root, IMPORT_ROWS)
        before: dict[str, bytes | None] = snapshot(root)
        code, out = lrun(repo, "import", str(rows), "--dry-run")
        assert code == 0 and "dry run, nothing written" in out, out
        assert "task: 2 (done 1, dropped 1) T-1..T-2" in out, out
        assert snapshot(root) == before


def test_import_rerun_guard() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        repo: Path = new_repo(root)
        rows: Path = write_rows(root, IMPORT_ROWS)
        assert lrun(repo, "import", str(rows))[0] == 0
        before: bytes = (repo / L.LEDGER_REL).read_bytes()
        code, out = lrun(repo, "import", str(rows))
        lines: list[str] = out.splitlines()
        assert code == 1 and len(lines) == 4, out
        assert lines[0].endswith(":1: already imported as S-1"), out
        assert (repo / L.LEDGER_REL).read_bytes() == before
        # same source: legacy id decides when given, else the title
        one: Path = write_rows(root, [
            {"type": "task", "title": "o", "source": "P.md:2", "legacy_id": "07-1"},
            {"type": "task", "title": "o", "source": "P.md:2", "legacy_id": "07-2"},
            {"type": "task", "title": "o", "source": "P.md:2", "legacy_id": "07-2"},
            {"type": "task", "title": "t", "source": "P.md:9"},
            {"type": "task", "title": "t", "source": "P.md:9"},
        ])
        code, out = lrun(repo, "import", str(one))
        lines = out.splitlines()
        assert code == 1 and [ln.split(":")[1] for ln in lines] == ["1", "3", "5"], out
        assert "already imported as T-1" in lines[0], out
        assert "already imported as T-3" in lines[1], out


def test_import_closed_stage_refused() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        repo: Path = new_repo(root)
        rows: Path = write_rows(root, [
            {"type": "stage", "title": "S", "source": "P.md:1", "status": "done"},
            {"type": "task", "title": "a", "source": "P.md:2", "stage": "S-1",
             "status": "done"},
            {"type": "task", "title": "b", "source": "P.md:3", "stage": "S-1"},
        ])
        code, out = lrun(repo, "import", str(rows))
        assert code == 1 and out.count("\n") == 1, out
        assert "rows.jsonl:3: S-1 is closed" in out, out
        assert jl(repo) == []


def test_import_title_over_160_refused() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        repo: Path = new_repo(root)
        rows: Path = write_rows(
            root, [{"type": "task", "title": "x" * 161, "source": "P.md:1"}]
        )
        code, out = lrun(repo, "import", str(rows))
        assert code == 1 and "rows.jsonl:1:" in out and "161 characters" in out, out
        assert jl(repo) == []


def test_notes_append() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "task", "a", "--note", "orig\ntext")
        for cmd in (("close", "T-1"), ("reopen", "T-1"), ("drop", "T-1")):
            assert lrun(repo, *cmd, "--note", cmd[0])[0] == 0
        assert lrun(repo, "set", "T-1", "--note", "set")[0] == 0
        note: str = L.load(repo)["T-1"].note
        assert note == "orig\ntext\nclose\nreopen\ndrop\nset", note
        lrun(repo, "add", "debt", "b")  # empty note: just the text
        lrun(repo, "set", "DB-1", "--note", "first")
        assert L.load(repo)["DB-1"].note == "first"
        n: int = len(jl(repo))
        code, out = lrun(repo, "set", "T-1", "--note", "  ")
        assert code == 1 and "--note-replace" in out, out
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                lrun(repo, "set", "T-1", "--note", "x", "--note-replace", "y")
            raise AssertionError("--note with --note-replace accepted")
        except SystemExit:
            pass
        assert len(jl(repo)) == n
        code, out = lrun(repo, "set", "T-1", "--note-replace", "new")
        assert code == 0 and out == "updated T-1: note (no stage)\n", out
        assert L.load(repo)["T-1"].note == "new"
        assert lrun(repo, "set", "T-1", "--note-replace", "")[0] == 0
        assert L.load(repo)["T-1"].note == ""


def test_stage_close_keeps_note() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "stage", "software-a", "--open", "--note", "scope: x")
        lrun(repo, "add", "decision", "ok", "--owner", "user", "--link", "S-1")
        assert lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")[0] == 0
        note: str = L.load(repo)["S-1"].note
        assert note == "scope: x\nclosed; sign-off D-1", note


def test_close_drop_link() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        for t in ("a", "b", "c"):
            lrun(repo, "add", "task", t, "--note", "n")
        lrun(repo, "set", "T-1", "--link", "T-2")
        code, out = lrun(
            repo, "close", "T-1", "--note", "ok", "--link", "T-3", "--link", "T-2"
        )
        assert code == 0, out
        assert L.load(repo)["T-1"].links == ["T-2", "T-3"]
        assert lrun(repo, "drop", "T-2", "--note", "no", "--link", "T-1")[0] == 0
        assert L.load(repo)["T-2"].links == ["T-1"]
        n: int = len(jl(repo))
        code, out = lrun(repo, "drop", "T-3", "--note", "no", "--link", "X-9")
        assert code == 1 and "X-9" in out, out
        assert len(jl(repo)) == n


def test_import_multi_file() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        repo: Path = new_repo(root)
        (root / "a").mkdir()
        (root / "b").mkdir()
        one: Path = write_rows(root / "a", [
            {"type": "stage", "title": "Old", "source": "P.md:1", "status": "done"},
        ])
        two: Path = write_rows(root / "b", [
            {"type": "task", "title": "t", "source": "Q.md:1", "stage": "Old",
             "status": "done"},
        ])
        code, out = lrun(repo, "import", str(two), str(one), "--dry-run")
        assert code == 1 and f"{two}:1: no stage 'Old'" in out, out  # order counts
        code, out = lrun(repo, "import", str(one), str(two), "--dry-run")
        assert code == 0 and "total 2 would be imported" in out, out
        assert jl(repo) == []
        code, out = lrun(repo, "import", str(one), str(two))
        assert code == 0 and out.endswith("total 2 imported\n"), out
        assert L.load(repo)["T-1"].stage == "S-1"
        before: bytes = (repo / L.LEDGER_REL).read_bytes()
        empty: Path = root / "empty.jsonl"
        empty.write_text("\n")
        bad: Path = write_rows(root, [
            {"type": "task", "title": "u", "source": "R.md:1"},
            {"type": "task", "title": "v"},
        ])
        code, out = lrun(repo, "import", str(empty), str(bad))
        assert code == 1 and out.splitlines() == [
            f"{empty}: no rows", f"{bad}:2: missing key 'source'"
        ], out
        assert (repo / L.LEDGER_REL).read_bytes() == before


def test_import_key_links() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        repo: Path = new_repo(root)
        lrun(repo, "add", "task", "pre", "--note", "n")
        rows: Path = write_rows(root, [
            {"type": "task", "title": "a", "source": "P.md:1",
             "link": ["@later", "T-1", "@b"], "key": "a"},
            {"type": "decision", "title": "b", "source": "P.md:2", "owner": "user",
             "key": "b", "link": ["@a"]},
            {"type": "task", "title": "c", "source": "P.md:3", "key": "later"},
        ])
        code, out = lrun(repo, "import", str(rows))
        assert code == 0, out
        st: dict[str, Any] = L.load(repo)
        assert st["T-2"].links == ["T-3", "T-1", "D-1"], st["T-2"]
        assert st["D-1"].links == ["T-2"], st["D-1"]
        assert all("key" not in e["f"] for e in jl(repo)), jl(repo)
        before: bytes = (repo / L.LEDGER_REL).read_bytes()
        bad: Path = write_rows(root, [
            {"type": "task", "title": "x", "source": "Z.md:1", "key": "k"},
            {"type": "task", "title": "y", "source": "Z.md:2", "key": "k"},
            {"type": "task", "title": "z", "source": "Z.md:3", "link": ["@nope"]},
            {"type": "task", "title": "w", "source": "Z.md:4", "key": "a b"},
        ])
        code, out = lrun(repo, "import", str(bad))
        lines: list[str] = out.splitlines()
        assert code == 1 and len(lines) == 3, out
        assert lines[0] == f"{bad}:2: duplicate key 'k' (first at {bad}:1)", out
        assert lines[1] == f"{bad}:3: link @nope: no row with that key", out
        assert lines[2].startswith(f"{bad}:4: key 'a b'"), out
        assert (repo / L.LEDGER_REL).read_bytes() == before


def test_import_help_documents_rows() -> None:
    buf: io.StringIO = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            L.main(["import", "--help"])
        except SystemExit:
            pass
    text: str = buf.getvalue()
    for key in (*L.IMPORT_STR_KEYS, *L.IMPORT_LIST_KEYS, "@KEY", "FILE [FILE ...]"):
        assert key in text, key
    assert "required: type, title, source" in text and "order given" in text, text
    assert "never @KEY" in text and "must come\nbefore" in text, text
    flat: str = " ".join(text.split())  # closed stages: what the rows may do
    assert (
        "A done (closed) stage refuses only a task or stage row that is open or "
        "running (such a row fails the whole batch)" in flat
    ), flat
    assert "every other row may name it (backfill)" in flat, flat
    with tempfile.TemporaryDirectory() as d:  # the example rows import as shown
        root: Path = Path(d)
        repo: Path = new_repo(root)
        rows: list[str] = [
            ln.strip() for ln in text.splitlines() if ln.startswith("  {")
        ]
        assert len(rows) == 3, rows
        (root / "ex.jsonl").write_text("\n".join(rows) + "\n")
        code, out = lrun(repo, "import", str(root / "ex.jsonl"))
        assert code == 0, out
        assert L.load(repo)["T-1"].links == ["F-1"]


def test_search_exact() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        long: str = "Long imported title " + "x" * 80
        for src, legacy in (("P.md:1", "07-1"), ("P.md:10", "07-10")):
            lrun(
                repo, "add", "task", long, "--imported", "--source", src,
                "--legacy-id", legacy,
            )
        lrun(repo, "add", "task", "plain P.md:1", "--note", "n")
        out: str = lrun(repo, "search", "--source", "P.md:1")[1]
        assert out == f"T-1 open: {long} [src P.md:1]\n", out
        out = lrun(repo, "search", "--legacy-id", "07-10")[1]
        assert out.startswith("T-2 open: ") and long in out, out
        assert lrun(repo, "search", "--legacy-id", "07")[1] == ""
        out = lrun(repo, "search", "P.md:1")[1]  # substring: all three, full titles
        assert len(out.splitlines()) == 3 and out.count(long) == 2, out
        assert lrun(repo, "search", "Long", "--source", "P.md:10")[1].startswith(
            "T-2 "
        )
        code, out = lrun(repo, "search")
        assert code == 1 and "--source" in out, out


def test_label_add_set_unique() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        code, out = lrun(repo, "add", "task", "a", "--note", "n", "--label", "03b/W4")
        assert code == 0 and out == "logged T-1: a (no stage)\n", out
        assert L.load(repo)["T-1"].extra == {"legacy_id": "03b/W4"}
        show: list[str] = lrun(repo, "show", "T-1")[1].splitlines()
        assert show[:2] == ["id: T-1", "label: 03b/W4"], show
        assert not any(ln.startswith("legacy_id:") for ln in show), show
        n: int = len(jl(repo))
        code, out = lrun(repo, "add", "task", "b", "--note", "n", "--label", "03b/W4")
        assert code == 1 and "already names T-1 (a)" in out, out
        for bad in ("a b", "x/" + "x" * 39, "T-3", "", "W4", "the"):
            code, out = lrun(repo, "add", "task", "b", "--note", "n", "--label", bad)
            assert code == 1 and "--label" in out, (bad, out)
        code, out = lrun(repo, "set", "T-1", "--label", "fix")
        assert code == 1 and "a / is required" in out, out
        assert len(jl(repo)) == n
        x40: str = "x/" + "x" * 38
        code, out = lrun(repo, "add", "task", "b", "--note", "n", "--label", x40)
        assert code == 0, out
        code, out = lrun(repo, "set", "T-2", "--label", "03b/W4")
        assert code == 1 and "T-1" in out, out
        code, out = lrun(repo, "set", "T-2", "--label", "03b/W7")
        assert code == 0 and out == "updated T-2: label (no stage)\n", out
        assert lrun(repo, "set", "T-1", "--label", "03b/W4")[0] == 0  # its own
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                lrun(repo, "add", "task", "c", "--note", "n", "--label", "a",
                     "--legacy-id", "b", "--imported", "--source", "s:1")
            raise AssertionError("--label with --legacy-id accepted")
        except SystemExit:
            pass
        # imported duplicates are tolerated; a label never moves off an import key
        for i in (1, 2):
            assert lrun(
                repo, "add", "task", f"old{i}", "--imported", "--source", f"P.md:{i}",
                "--legacy-id", "07/1",  # legacy ids: any form
            )[0] == 0
        code, out = lrun(repo, "set", "T-3", "--label", "03b/W9")
        assert code == 1 and "legacy id '07/1'" in out, out
        code, out = lrun(repo, "add", "task", "c", "--note", "n", "--label", "07/1")
        assert code == 1 and "already names T-3" in out, out
        code, out = lrun(repo, "show", "07/1")
        assert code == 1 and "T-3 old1" in out and "T-4 old2" in out, out
        assert lrun(repo, "search", "W4")[1] == "T-1 open: a\n"
        assert lrun(repo, "search", "--label", "03b/W4")[1] == "T-1 open: a\n"
        assert lrun(repo, "search", "--label", "03b")[1] == ""  # exact
        assert lrun(repo, "search", "--legacy-id", "03b/W7")[1] == "T-2 open: b\n"


def test_resolver_labels_and_stage_codes() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "stage", "03-paper-old", "--imported", "--source", "a:0",
             "--status", "done")  # S-1: gives the NN 03 for --follows
        lrun(repo, "add", "stage", "paper-scan", "--open", "--follows", "S-1")  # S-2
        lrun(repo, "add", "task", "a", "--note", "n", "--label", "03b/W4")
        assert lrun(repo, "show", "03b")[1].startswith("id: S-2\n")
        assert lrun(repo, "show", "03b-paper-scan")[1].startswith("id: S-2\n")
        assert lrun(repo, "start", "03b/W4")[1] == "started T-1: a\n"
        code, out = lrun(
            repo, "add", "task", "b", "--note", "n", "--stage", "03b",
            "--link", "03b/W4", "--label", "03b/W7",
        )
        assert code == 0, out
        e: Any = L.load(repo)["T-2"]
        assert e.stage == "S-2" and e.links == ["T-1"], e
        assert lrun(repo, "set", "03b/W7", "--link", "03b/W4", "--stage", "03b")[
            1
        ] == "updated T-2: links (stage S-2)\n"  # same stage again: not an event
        assert lrun(repo, "close", "03b/W4", "--note", "ok")[1] == (
            "closed T-1: ok (stage S-2)\n"
        )
        assert lrun(repo, "reopen", "03b/W4", "--note", "x")[1] == (
            "reopened T-1: x (stage S-2)\n"
        )
        out = lrun(repo, "drop", "03b/W4", "--note", "y", "--link", "03b/W7")[1]
        assert out == "dropped T-1: y (stage S-2)\n"
        assert L.load(repo)["T-1"].links == ["T-2"]
        assert "T-2" in lrun(repo, "list", "--stage", "03b")[1]
        lrun(repo, "close", "T-2", "--note", "ok")
        lrun(repo, "add", "decision", "m", "--owner", "user", "--label", "03b/D1")
        out = lrun(repo, "supersede", "03b/D1", "m2", "--owner", "user")[1]
        assert out == "logged D-2: m2 (supersedes D-1; stage S-2)\n", out
        lrun(repo, "add", "decision", "ok", "--owner", "user", "--link", "03b",
             "--label", "03b/signoff")
        assert L.load(repo)["D-3"].links == ["S-2"]
        code, out = lrun(repo, "stage-close", "03b", "--sign-off", "03b/signoff")
        assert code == 0 and out.startswith("closed S-2: sign-off D-3\n"), out
        assert "D-3" in L.load(repo)["S-2"].links
        # real ids win; a non-stage is no stage; more than one match is refused
        lrun(repo, "add", "task", "z", "--imported", "--source", "a:1",
             "--legacy-id", "T-2")
        assert lrun(repo, "show", "T-2")[1].startswith("id: T-2\n")
        code, out = lrun(repo, "add", "task", "c", "--note", "n", "--stage", "03b/W7")
        assert code == 1 and "03b/W7 (T-2) is a task, not a stage" in out, out
        lrun(repo, "add", "stage", "03b-old", "--imported", "--source", "a:2")
        n: int = len(jl(repo))
        code, out = lrun(repo, "show", "03b")
        assert code == 1 and "S-2 03b-paper-scan" in out and "S-3 03b-old" in out
        assert "pass the id" in out, out
        code, out = lrun(repo, "add", "task", "c", "--note", "n", "--link", "03b")
        assert code == 1 and "--link 03b:" in out, out
        code, out = lrun(repo, "show", "W4")
        assert code == 1 and "no such entry W4" in out, out
        assert len(jl(repo)) == n


def test_brief_check_labels() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "task", "a", "--note", "n", "--label", "03b/W4")
        lrun(repo, "add", "task", "b", "--note", "n")
        code, out = bcheck(repo, "DELIVERABLE: x\nTASK: 03b/W4. (the loader)\n")
        assert code == 0 and out == "started T-1: a\n", out
        code, out = bcheck(repo, "DELIVERABLE: x\nTASK: the W6c item\n")
        assert code == 2 and "no TASK: line naming a task" in out, out
        assert "--note" in out and "--label" in out, out
        # prose is inert: legacy ids never count, labels only lead the line
        for i in (1, 2):
            lrun(repo, "add", "task", f"o{i}", "--imported", "--source", f"P:{i}",
                 "--legacy-id", "W4")  # T-3, T-4
        lrun(repo, "add", "task", "o3", "--imported", "--source", "P:3",
             "--legacy-id", "1")  # T-5
        lrun(repo, "add", "task", "c", "--note", "n", "--label", "03b/W2")  # T-6
        code, out = bcheck(repo, "DELIVERABLE: x\nTASK: T-2 (step 1; old W4 rows)\n")
        assert code == 0 and out == "started T-2: b\n", out
        code, out = bcheck(repo, "DELIVERABLE: x\nTASK: 1\n")
        assert code == 2 and "no TASK: line" in out, out
        code, out = bcheck(repo, "DELIVERABLE: x\nTASK: T-2 and then 03b/W2\n")
        assert code == 0 and out == "", out  # 03b/W2 follows prose: inert
        st: dict[str, Any] = L.load(repo)
        assert [st[i].status for i in ("T-3", "T-4", "T-5", "T-6")] == ["open"] * 4
        code, out = bcheck(repo, "DELIVERABLE: x\nTASK: T-2, 03b/W2 loader\n")
        assert code == 0 and out == "started T-6: c\n", out
        # two non-imported entries with one label: only by hand edits; refused
        f: dict[str, object] = {
            "type": "task", "title": "h", "status": "open", "owner": "lead",
            "stage": "", "note": "", "links": [], "refs": [], "legacy_id": "03b/W2",
        }
        with (repo / L.LEDGER_REL).open("a") as fh:
            fh.write(json.dumps(L.make_event("lead", "add", "T-9", f)) + "\n")
        code, out = bcheck(repo, "DELIVERABLE: x\nTASK: 03b/W2\n")
        assert code == 2 and "'03b/W2' names more than one entry" in out, out


def test_import_label_key() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        repo: Path = new_repo(root)
        rows: Path = write_rows(root, [
            {"type": "task", "title": "a", "source": "P.md:1", "label": "03b/W4"},
            {"type": "task", "title": "b", "source": "P.md:2", "label": "03b/W4"},
        ])
        assert lrun(repo, "import", str(rows))[0] == 0
        st: dict[str, Any] = L.load(repo)
        assert st["T-1"].extra["legacy_id"] == "03b/W4" == st["T-2"].extra["legacy_id"]
        assert lrun(repo, "import", str(rows))[0] == 1  # re-run guard: label = key
        before: bytes = (repo / L.LEDGER_REL).read_bytes()
        bad: Path = write_rows(root, [
            {"type": "task", "title": "c", "source": "Q:1", "label": "a",
             "legacy_id": "a"},
            {"type": "task", "title": "d", "source": "Q:2", "label": "a b"},
        ])
        code, out = lrun(repo, "import", str(bad))
        lines: list[str] = out.splitlines()
        assert code == 1 and "label or legacy_id, not both" in lines[0], out
        assert "label 'a b'" in lines[1], out
        assert (repo / L.LEDGER_REL).read_bytes() == before


def test_task_needs_note() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        repo: Path = new_repo(root)
        for extra in ((), ("--note", "  \n ")):
            code, out = lrun(repo, "add", "task", "work", *extra)
            assert code == 1 and "add task needs --note" in out, out
            assert "deliverable and its scope, one to three lines" in out, out
        assert jl(repo) == []
        assert lrun(repo, "add", "task", "w", "--note", "deliverable: x")[0] == 0
        assert lrun(repo, "add", "task", "o", "--imported", "--source", "a:1")[0] == 0
        assert lrun(repo, "add", "debt", "d")[0] == 0  # other types: unchanged
        rows: Path = write_rows(root, [{"type": "task", "title": "r", "source": "b:1"}])
        assert lrun(repo, "import", str(rows))[0] == 0


def test_stage_folder() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        code, out = lrun(repo, "add", "stage", "paper-scan", "--open")
        assert code == 0, out
        folder: Path = repo / "pm/stages/01-paper-scan"
        assert sorted(p.name for p in folder.iterdir()) == sorted(L.STAGE_DIRS)
        assert L.load(repo)["S-1"].refs == ["pm/stages/01-paper-scan/"]
        kept: Path = repo / "pm/stages/01b-software-x/notes/old.md"
        kept.parent.mkdir(parents=True)
        kept.write_text("keep")
        (repo / "a.md").write_text("a")
        code, out = lrun(repo, "add", "stage", "software-x", "--open", "--follows",
                         "S-1", "--ref", "a.md")  # a letter code: 01b
        assert code == 0 and kept.read_text() == "keep", out
        assert (kept.parents[1] / "deliverables").is_dir()
        assert L.load(repo)["S-2"].refs == ["pm/stages/01b-software-x/", "a.md"]
        n: int = len(jl(repo))
        for bad in ("01-a", "1-paper-x", "03-Paper-x", "03b paper x", "paper"):
            code, out = lrun(repo, "add", "stage", bad)
            assert code == 1 and "<kind>-<topic>" in out, (bad, out)
            assert "NN[letter]" not in out, (bad, out)
        assert len(jl(repo)) == n
        assert sorted(p.name for p in (repo / "pm/stages").iterdir()) == [
            "01-paper-scan", "01b-software-x"
        ]
        code, out = lrun(repo, "add", "stage", "old", "--imported", "--source", "a:1")
        assert code == 0 and out == "logged S-3: old\n", out
        assert not (repo / "pm/stages/old").exists() and L.load(repo)["S-3"].refs == []


def test_names_unique_both_ways() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        repo: Path = new_repo(root)
        for bad in ("03b/T-1", "AB-12/x", "x/S-3"):  # an id inside: refused
            code, out = lrun(repo, "add", "task", "a", "--note", "n", "--label", bad)
            assert code == 1 and "contains one" in out, (bad, out)
        for i, legacy in ((1, "08"), (2, "09-paper-q")):  # T-1, T-2: legacy ids
            lrun(repo, "add", "task", f"o{i}", "--imported", "--source", f"a:{i}",
                 "--legacy-id", legacy)
        lrun(repo, "add", "task", "c", "--note", "n", "--label", "03b/W1")  # T-3
        lrun(repo, "add", "stage", "03-paper-old", "--imported", "--source", "a:0",
             "--status", "done")  # S-1: gives the NN 03 for --follows
        lrun(repo, "add", "stage", "paper-scan", "--open", "--follows", "S-1")  # S-2
        lrun(repo, "add", "stage", "old", "--imported", "--source", "a:9")  # S-3
        n: int = len(jl(repo))
        # the CLI cannot reach these (the NN is computed, Q12 skips a taken code);
        # the guard itself stays (stage-rename uses it): called directly
        new: argparse.Namespace = argparse.Namespace(imported=False, legacy_id=None)
        for title, name, owner in (
            ("08-paper-z", "08", "T-1"),
            ("09-paper-q", "09-paper-q", "T-2"),
            ("03b-paper-other", "03b", "S-2"),
        ):
            try:
                L._check_names(L.load(repo), "stage", title, new)
                raise AssertionError(f"{title}: no clash")
            except L.LedgerError as err:
                assert f"'{name}' already names {owner}" in str(err), err
        assert len(jl(repo)) == n and not (repo / "pm/stages/08-paper-z").exists()
        rows: Path = write_rows(root, [
            {"type": "task", "title": "x", "source": "P:1", "label": "03b/W1"},
            {"type": "task", "title": "y", "source": "P:2", "legacy_id": "03b"},
        ])
        code, out = lrun(repo, "import", str(rows))
        lines: list[str] = out.splitlines()
        assert code == 1 and len(lines) == 2, out
        assert "legacy id '03b/W1': '03b/W1' already names T-3" in lines[0], out
        assert "already names S-2" in lines[1], out
        code, out = lrun(repo, "add", "task", "z", "--imported", "--source", "P:3",
                         "--legacy-id", "03b/W1")
        assert code == 1 and "already names T-3" in out, out
        code, out = lrun(repo, "add", "stage", "03b/W1-old", "--imported",
                         "--source", "a:8")  # imported stage code = a --label
        assert code == 1 and "'03b/W1' already names T-3" in out, out
        # a stage keeps its title: it is the folder name and gives the code
        for ref in ("S-2", "03b"):
            code, out = lrun(repo, "set", ref, "--title", "13-paper-x")
            assert code == 1 and "S-2 is a stage" in out, out
            assert "pm/stages/03b-paper-scan/" in out, out
        assert len(jl(repo)) == n
        assert lrun(repo, "set", "S-3", "--title", "older")[0] == 0  # imported
        ok: Path = write_rows(root, [  # imported duplicates: still tolerated
            {"type": "task", "title": "x", "source": "Q:1", "label": "08"},
            {"type": "task", "title": "y", "source": "Q:2", "legacy_id": "old-1"},
            {"type": "task", "title": "w", "source": "Q:3", "legacy_id": "old-1"},
        ])
        assert lrun(repo, "import", str(ok))[0] == 0  # T-4 to T-6
        # through the CLI: a planned title that names a legacy id is refused
        lrun(repo, "add", "task", "o3", "--imported", "--source", "a:3",
             "--legacy-id", "paper-q")  # T-7
        n = len(jl(repo))
        code, out = lrun(repo, "add", "stage", "paper-q")
        assert code == 1 and "'paper-q' already names T-7" in out, out
        assert len(jl(repo)) == n and not (repo / "pm/stages/P-4-paper-q").exists()
        # ... and a computed NN skips the code `08` that T-1 names (Q12)
        lrun(repo, "add", "stage", "07-paper-old", "--imported", "--source", "a:7",
             "--status", "done")  # S-4, NN 7
        out = lrun(repo, "add", "stage", "software-z", "--open")[1]
        assert out.startswith("logged S-5: 09-software-z\n"), out


def test_brief_check_label_punctuation() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        for i in (1, 2, 3):
            lrun(repo, "add", "task", f"t{i}", "--note", "n", "--label", f"03b/W{i}")
        for i, line in ((1, "03b/W1: the loader"), (2, "(03b/W2)"), (3, "03b/W3;")):
            code, out = bcheck(repo, f"DELIVERABLE: x\nTASK: {line}\n")
            assert code == 0 and out == f"started T-{i}: t{i}\n", (line, out)
        code, out = bcheck(repo, "DELIVERABLE: x\nTASK: see 03b/W3\n")
        assert code == 2 and "first on the line" in out, out
        assert "set <label> --owner <teammate>" in out and "not added again" in out
        assert len(out) < 1000, len(out)  # the hook cuts its deny text at 1000


def test_search_help_metavar() -> None:
    buf: io.StringIO = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            L.main(["search", "--help"])
        except SystemExit:
            pass
    text: str = buf.getvalue()
    assert "[--label LABEL]" in text and "LEGACY_ID" not in text, text


def test_stage_dirs_match_agents() -> None:
    text: str = (RK_PY.parent.parent / "template" / "AGENTS.md").read_text()
    block: str = text.split("### 3.2 Stage folder", 1)[1].split("```", 2)[1]
    dirs: list[str] = [
        ln.split()[0].rstrip("/")
        for ln in block.splitlines()[2:]
        if ln.strip() and ln.split()[0].endswith("/")
    ]
    assert tuple(dirs) == L.STAGE_DIRS, dirs


# ---- kit / sid / rules on events (P2) ---------------------------------------


@contextlib.contextmanager
def env(**kv: str | None) -> Iterator[None]:
    """os.environ with `kv` set (None = unset), restored afterwards."""
    old: dict[str, str | None] = {k: os.environ.get(k) for k in kv}
    try:
        for k, v in kv.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_kit_and_sid_on_events() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        repo: Path = new_repo(root)
        with env(CLAUDE_CODE_SESSION_ID="sess-1"):
            lrun(repo, "add", "task", "a", "--note", "n")
            rows: Path = write_rows(
                root, [{"type": "task", "title": "i", "source": "x:1"}]
            )
            assert lrun(repo, "import", str(rows))[0] == 0
        with env(CLAUDE_CODE_SESSION_ID=None):
            lrun(repo, "start", "T-1")
        with env(CLAUDE_CODE_SESSION_ID=""):
            lrun(repo, "close", "T-1", "--note", "ok")
        evs: list[dict[str, Any]] = jl(repo)
        version: str = json.loads(L.KIT_JSON.read_text())["version"]
        assert all(e["kit"] == version for e in evs), evs
        assert [e.get("sid") for e in evs] == ["sess-1", "sess-1", None, None], evs
        assert "sid" not in evs[2] and "sid" not in evs[3], evs
        out: str = lrun(repo, "show", "T-1")[1]
        assert f"    kit={version} sid=sess-1\n" in out, out
        assert out.count(f"    kit={version}\n") == 2, out


def test_old_ledger_without_new_keys() -> None:
    """Events written before kit/sid/rules fold and print exactly as before."""
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        old: list[dict[str, object]] = [
            {"ts": "2026-01-01T10:00:00+01:00", "who": "lead", "ev": "add",
             "id": "S-1", "f": {"type": "stage", "title": "01-paper-x",
                                "status": "open", "owner": "lead", "stage": "",
                                "note": "", "links": [], "refs": []}},
            {"ts": "2026-01-01T10:01:00+01:00", "who": "lead", "ev": "add",
             "id": "T-1", "f": {"type": "task", "title": "imp", "status": "done",
                                "owner": "lead", "stage": "", "note": "",
                                "links": [], "refs": ["gone.md"], "imported": True,
                                "source": "A.md:1"}},
        ]  # fmt: skip
        (repo / L.LEDGER_REL).write_text("".join(json.dumps(e) + "\n" for e in old))
        st: dict[str, Any] = L.load(repo)
        assert st["T-1"].extra == {"imported": True, "source": "A.md:1"}, st
        for eid in ("S-1", "T-1"):
            out: str = lrun(repo, "show", eid)[1]
            hist: list[str] = out.split("history:\n")[1].splitlines()
            assert len(hist) == 1 and "kit=" not in out and "sid=" not in out, out
        with env(CLAUDE_CODE_SESSION_ID=None):  # mixed: old lines, then new ones
            assert lrun(repo, "add", "task", "new", "--note", "n")[0] == 0
        assert L.load(repo)["T-2"].stage == "S-1"
        assert "kit" in jl(repo)[-1] and "kit" not in jl(repo)[0]


def test_rules_on_stage_add_and_close() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        (repo / "AGENTS.md").write_text("<!-- research-kit: 2026-01-01a -->\n# x\n")
        (repo / "pm/kinds/paper.md").write_text(
            "<!-- research-kit-kind paper: 2026-01-02b -->\n"
        )
        (repo / "pm/kinds/own.md").write_text("# no stamp\n")
        want: dict[str, str] = {
            "AGENTS.md": "2026-01-01a", "pm/kinds/paper.md": "2026-01-02b"
        }
        lrun(repo, "add", "stage", "paper-x", "--open")
        lrun(repo, "add", "task", "t", "--note", "n")
        lrun(repo, "add", "decision", "ok", "--owner", "user", "--link", "S-1")
        (repo / "AGENTS.md").write_text("<!-- research-kit: 2026-01-05c -->\n")
        lrun(repo, "close", "T-1", "--note", "ok")
        code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")
        assert code == 0, out
        evs: list[dict[str, Any]] = jl(repo)
        assert evs[0]["rules"] == want, evs[0]
        assert evs[-1]["rules"] == {**want, "AGENTS.md": "2026-01-05c"}, evs[-1]
        assert all("rules" not in e for e in evs[1:-1]), evs
        out = lrun(repo, "show", "S-1")[1]
        assert "rules=AGENTS.md:2026-01-01a,pm/kinds/paper.md:2026-01-02b" in out, out
        assert "rules=AGENTS.md:2026-01-05c," in out, out


# ---- refs that hold (P3) ----------------------------------------------------


def test_ref_must_exist() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        repo: Path = new_repo(root)
        (repo / "ok.md").write_text("x")
        absf: Path = root / "abs.md"
        absf.write_text("x")
        lrun(repo, "add", "stage", "paper-x", "--open")
        lrun(repo, "add", "task", "a", "--note", "n")
        lrun(repo, "add", "decision", "d", "--owner", "user", "--link", "S-1")
        n: int = len(jl(repo))
        for argv in (
            ("add", "task", "b", "--note", "n", "--ref", "ok.md", "--ref", "no.md"),
            ("set", "T-1", "--ref", "no.md"),
            ("close", "T-1", "--note", "x", "--ref", "no.md"),
            ("drop", "T-1", "--note", "x", "--ref", "no.md"),
            ("supersede", "D-1", "d2", "--owner", "user", "--ref", "no.md"),
            ("stage-close", "S-1", "--sign-off", "D-1", "--ref", "no.md"),
        ):
            code, out = lrun(repo, *argv)
            assert code == 1 and "--ref no.md: no such file" in out, (argv, out)
        assert len(jl(repo)) == n
        for ref in ("https://x.org/a", "doi:10.1000/xyz", "ok.md",
                    "pm/stages/01-paper-x/notes"):
            assert lrun(repo, "set", "T-1", "--ref", ref)[0] == 0, ref
        code, out = lrun(repo, "set", "T-1", "--ref", str(absf))  # outside the repo
        assert code == 1 and "outside the repo" in out, out
        inside: Path = (repo / "pm/stages/01-paper-x/notes/r.md").resolve()
        inside.write_text("x")
        assert lrun(repo, "set", "T-1", "--ref", str(inside))[0] == 0
        assert L.load(repo)["T-1"].refs[-1] == "pm/stages/01-paper-x/notes/r.md"
        code, out = lrun(repo, "set", "T-1", "--ref-drop", str(inside))
        assert code == 0 and "pm/stages/01-paper-x/notes/r.md" not in (
            L.load(repo)["T-1"].refs
        ), out
        refs: list[str] = [r for e in jl(repo) for r in e["f"].get("refs", [])]
        assert not any(r.startswith("/") for r in refs), refs
        lrun(repo, "drop", "T-1", "--note", "x")
        code, out = lrun(repo, "reopen", "T-1", "--note", "y", "--ref", "no.md")
        assert code == 1 and "no such file" in out, out
        code, out = lrun(repo, "reopen", "T-1", "--note", "y", "--ref", "ok.md")
        assert code == 0, out
        code, out = lrun(repo, "add", "task", "old", "--imported", "--source",
                         "A:1", "--ref", "gone.md")  # imported: exempt
        assert code == 0, out
        rows: Path = write_rows(root, [{"type": "task", "title": "i",
                                        "source": "B:1", "ref": ["gone2.md"]}])
        assert lrun(repo, "import", str(rows))[0] == 0


def test_ref_drop() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        for name in ("a.md", "b.md", "c.md"):
            (repo / name).write_text(name)
        lrun(repo, "add", "task", "t", "--note", "n", "--ref", "a.md", "--ref", "b.md")
        (repo / "a.md").rename(Path(d) / "moved.md")  # moved away: the ref is stale
        code, out = lrun(repo, "set", "T-1", "--ref-drop", "a.md", "--ref", "c.md")
        assert code == 0 and out == "updated T-1: refs (no stage)\n", out
        assert L.load(repo)["T-1"].refs == ["b.md", "c.md"]
        show: str = lrun(repo, "show", "T-1")[1]
        assert '"a.md"' in show.split("history:")[1], show  # history keeps it
        n: int = len(jl(repo))
        code, out = lrun(repo, "set", "T-1", "--ref-drop", "x.md")
        assert code == 1 and "--ref-drop x.md: not a ref of T-1" in out, out
        assert "b.md, c.md" in out and len(jl(repo)) == n, out
        assert lrun(repo, "set", "T-1", "--ref-drop", "b.md")[0] == 0
        assert L.load(repo)["T-1"].refs == ["c.md"]


def test_show_several_ids() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "task", "a", "--note", "n")
        lrun(repo, "add", "task", "b", "--note", "n", "--label", "01/W2")
        code, out = lrun(repo, "show", "T-1", "01/W2")
        assert code == 0 and out.startswith("id: T-1\n"), out
        assert "\n\nid: T-2\n" in out and out.count("history:") == 2, out
        code, out = lrun(repo, "show", "T-1", "T-9")
        assert code == 1 and out == "error: no such entry T-9\n", out


def test_add_receipt_names_stage() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        out: str = lrun(repo, "add", "task", "a", "--note", "n")[1]
        assert out == "logged T-1: a (no stage)\n", out
        out = lrun(repo, "add", "stage", "paper-x", "--open")[1]
        assert out.startswith("logged S-1: 01-paper-x\n"), out
        out = lrun(repo, "add", "fetch", "smith")[1]
        assert out == "logged F-1: smith (stage S-1)\n", out


# ---- doctor (P1) and doctor --start (P5) ------------------------------------

GIT_ENV: dict[str, str | None] = {
    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"
}


def git(repo: Path, *args: str) -> None:
    """A real git command in `repo`, without the user's config."""
    exe: str | None = shutil.which("git")
    assert exe is not None, "git not found"
    r: subprocess.CompletedProcess[str] = subprocess.run(
        [exe, "-C", str(repo), "-c", "user.name=t",
         "-c", "user.email=t@example.invalid",
         "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *args],
        env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1",
             "GIT_CONFIG_GLOBAL": "/dev/null"},
        capture_output=True, text=True,
    )  # fmt: skip
    assert r.returncode == 0, r.stderr


def commit_all(repo: Path) -> None:
    if not (repo / ".git").exists():
        git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "c", "--allow-empty")


def doctor(repo: Path, *argv: str) -> tuple[int, str]:
    with env(**GIT_ENV):
        return lrun(repo, "doctor", *argv)


def group(out: str, name: str) -> list[str]:
    """The finding lines under the HARD or SOFT header of group `name`."""
    lines: list[str] = out.splitlines()
    for i, ln in enumerate(lines):
        if ln.rsplit(" (", 1)[0] in (f"HARD {name}", f"SOFT {name}"):
            rest: list[str] = lines[i + 1:]
            k: int = next(
                (j for j, x in enumerate(rest) if not x.startswith("  ")), len(rest)
            )
            return [x.strip() for x in rest[:k]]
    return []


def staged_repo(root: Path) -> Path:
    """Stage S-1 with task T-1 and a user sign-off D-1."""
    repo: Path = new_repo(root)
    lrun(repo, "add", "stage", "paper-x", "--open")
    lrun(repo, "add", "task", "t", "--note", "n")
    lrun(repo, "add", "decision", "ok", "--owner", "user", "--link", "S-1")
    return repo


def test_doctor_clean_and_read_only() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = staged_repo(Path(d))
        commit_all(repo)
        before: dict[str, bytes | None] = snapshot(Path(d))
        stamps: list[tuple[int, int]] = [  # a rewrite in the same second: new inode
            ((repo / f).stat().st_ino, (repo / f).stat().st_mtime_ns)
            for f in (L.LEDGER_REL, L.STATUS_REL)
        ]
        code, out = doctor(repo)
        assert code == 0 and out == "doctor: no findings\n", out
        code, out = doctor(repo, "--stage", "S-1")
        assert code == 0 and out == "doctor S-1: no findings\n", out
        assert snapshot(Path(d)) == before
        assert stamps == [
            ((repo / f).stat().st_ino, (repo / f).stat().st_mtime_ns)
            for f in (L.LEDGER_REL, L.STATUS_REL)
        ]


def test_doctor_parse_error() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = staged_repo(Path(d))
        with (repo / L.LEDGER_REL).open("a") as fh:
            fh.write("{torn\n")
        code, out = doctor(repo)
        assert code == 1 and out.startswith("HARD ledger does not parse (1)\n"), out
        assert "pm/ledger.jsonl:4: not a JSON line" in out, out


def test_doctor_missing_ref() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = staged_repo(Path(d))
        (repo / "r.md").write_text("x")
        lrun(repo, "set", "T-1", "--ref", "r.md", "--ref", "https://x.org")
        (repo / "r.md").rename(Path(d) / "moved.md")
        code, out = doctor(repo)
        assert code == 1 and group(out, "missing ref") == ["T-1 r.md"], out
        assert out.endswith("doctor: 1 hard, 0 soft\n"), out
        code, out = doctor(repo, "--stage", "01")
        assert code == 1 and group(out, "missing ref") == ["T-1 r.md"], out


def test_doctor_missing_stage_folder() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = staged_repo(Path(d))
        lrun(repo, "add", "stage", "02-paper-y", "--imported", "--source", "A:1")
        (repo / "pm/stages/01-paper-x").rename(Path(d) / "moved")
        code, out = doctor(repo)
        assert code == 1, out  # the imported stage has no folder: not a finding
        assert group(out, "missing stage folder") == ["S-1 pm/stages/01-paper-x/"]
        assert group(out, "missing ref") == [], out  # its own folder ref: once


def test_doctor_ledger_against_head() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = staged_repo(Path(d))
        commit_all(repo)
        lrun(repo, "add", "task", "u", "--note", "n")  # appended: fine
        assert doctor(repo)[0] == 0
        path: Path = repo / L.LEDGER_REL
        lines: list[str] = path.read_text().splitlines(keepends=True)
        path.write_text(lines[0] + lines[2] + lines[1] + "".join(lines[3:]))
        code, out = doctor(repo)
        assert code == 1, out
        assert group(out, "ledger not append-only against HEAD") == [
            "pm/ledger.jsonl:2 differs from HEAD: lines were changed or removed, "
            "not only appended"
        ], out


def test_doctor_ref_in_waste_or_ignored() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = staged_repo(Path(d))
        for rel in ("pm/waste/team/r1.md", "build/out.md", "notes.md"):
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo / rel).write_text("x")
        (repo / ".gitignore").write_text("build/\npm/waste/\n")
        commit_all(repo)
        lrun(repo, "set", "T-1", "--ref", "pm/waste/team/r1.md", "--ref",
             "build/out.md", "--ref", "notes.md")
        code, out = doctor(repo)
        assert code == 0, out
        assert group(out, L.G_IGNORED) == [
            "T-1 pm/waste/team/r1.md (waste)", "T-1 build/out.md (ignored)"
        ], out


def test_doctor_heading_names_fix() -> None:
    """Plan G3: the waste/ignored heading says how to fix it."""
    with tempfile.TemporaryDirectory() as d:
        repo: Path = staged_repo(Path(d))
        (repo / "pm/waste/team").mkdir(parents=True)
        (repo / "pm/waste/team/r.md").write_text("x")
        lrun(repo, "set", "T-1", "--ref", "pm/waste/team/r.md")
        head: str = next(
            ln for ln in doctor(repo)[1].splitlines() if ln.startswith("SOFT ref in")
        )
        assert head == (
            "SOFT ref in a git-ignored or waste folder (move the file to the stage's "
            "notes/team/ or pm/logs/team/, then rk reref) (1)"
        ), head


def test_doctor_kit_ignored_places_not_flagged() -> None:
    """A ref the kit prescribes into a folder its own .gitignore ignores (the
    stage chat/ archive) is no finding; other ignored places are, pm/reviews/
    of older repos among them (new team reviews go to a tracked folder)."""
    with tempfile.TemporaryDirectory() as d:
        repo: Path = staged_repo(Path(d))
        rels: tuple[str, ...] = (
            "pm/stages/01-paper-x/chat/INDEX.md", "pm/reviews/critic_x.md",
            "pm/scratch/x.md",
        )
        for rel in rels:
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo / rel).write_text("x")
        (repo / ".gitignore").write_text(
            "pm/stages/*/chat/\npm/reviews/\npm/scratch/\n"
        )
        commit_all(repo)
        lrun(repo, "set", "T-1", *(x for rel in rels for x in ("--ref", rel)))
        assert group(doctor(repo)[1], L.G_IGNORED) == [  # reviews: a finding
            "T-1 pm/reviews/critic_x.md (ignored)", "T-1 pm/scratch/x.md (ignored)"
        ]


def test_doctor_done_stage_not_in_head() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = staged_repo(Path(d))
        commit_all(repo)
        (repo / "pm/stages/01-paper-x/notes/n.md").write_text("x")
        lrun(repo, "close", "T-1", "--note", "ok")
        lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")
        lrun(repo, "add", "task", "later", "--note", "n")  # after the close
        code, out = doctor(repo)
        assert code == 0, out
        assert group(out, L.G_UNCOMMITTED) == [
            # the note and the LEDGER.md that stage-close wrote
            "S-1 01-paper-x: 2 ledger lines and 2 folder files not in HEAD"
        ], out
        commit_all(repo)
        assert group(doctor(repo)[1], L.G_UNCOMMITTED) == []


def test_reopen_stage() -> None:  # a stage closed too early
    with tempfile.TemporaryDirectory() as d:
        repo: Path = staged_repo(Path(d))  # S-1 01-paper-x, T-1, D-1
        rec: Path = repo / "pm/stages/01-paper-x/LEDGER.md"
        code, out = lrun(repo, "reopen", "S-1", "--note", "x")
        assert code == 1 and "cannot reopen S-1: it is open" in out, out
        lrun(repo, "close", "T-1", "--note", "ok")
        assert lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")[0] == 0
        first: str = rec.read_text()
        lrun(repo, "add", "stage", "paper-y", "--open")  # S-2, same kind
        n: int = len(jl(repo))
        code, out = lrun(repo, "reopen", "S-1", "--note", "x")
        assert code == 1 and "cannot reopen S-1: S-2 (02-paper-y) is open" in out, out
        assert "stage-close S-2 first" in out and len(jl(repo)) == n, out
        lrun(repo, "add", "decision", "ok2", "--owner", "user", "--link", "S-2")
        assert lrun(repo, "stage-close", "S-2", "--sign-off", "D-2")[0] == 0
        lrun(repo, "add", "stage", "software-z", "--open")  # S-3, other kind: no block
        commit_all(repo)
        code, out = lrun(repo, "reopen", "S-1", "--note", "closed too early")
        assert code == 0 and out == "reopened S-1: closed too early\n", out
        ev: dict[str, Any] = jl(repo)[-1]
        assert ev["who"] == "lead" and ev["f"]["reason"] == "closed too early", ev
        assert L.load(repo)["S-1"].status == "open"
        assert rec.read_text() == first  # left as it is until the next close
        assert lrun(repo, "reopen", "T-1", "--note", "more")[0] == 0  # check passes
        assert lrun(repo, "start", "T-1")[0] == 0
        assert lrun(repo, "add", "task", "u", "--note", "n", "--stage", "S-1")[0] == 0
        assert doctor(repo) == (0, "doctor: no findings\n")
        assert doctor(repo, "--stage", "S-1") == (0, "doctor S-1: no findings\n")
        lrun(repo, "close", "T-1", "--note", "ok")
        lrun(repo, "close", "T-2", "--note", "ok")
        code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")
        assert code == 1 and "D-1 was logged before S-1 was reopened" in out, out
        lrun(repo, "add", "decision", "ok3", "--owner", "user", "--link", "S-1",
             "--stage", "S-1")  # D-3
        code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-3")
        assert code == 0 and out == (
            "closed S-1: sign-off D-3\nwrote pm/stages/01-paper-x/LEDGER.md\n"
        ), out
        text: str = rec.read_text()
        assert text != first, text
        assert text == L.render_stage_record(L.read_events(repo), "S-1")
        assert "- T-2 task done (lead) u\n" in text and "- D-3 ok3" in text, text
        st: Any = L.load(repo)["S-1"]
        assert st.status == "done" and st.extra["reason"] == "closed; sign-off D-3"
        assert st.links == ["D-1", "D-3"], st.links
        commit_all(repo)
        assert doctor(repo) == (0, "doctor: no findings\n")
        assert doctor(repo, "--stage", "S-1") == (0, "doctor S-1: no findings\n")


def reopened_repo(root: Path) -> Path:
    """S-1 (01-paper-x) closed with D-1, DB-1 logged stage-less while it was
    closed, S-1 reopened, a new sign-off D-2 logged, not yet closed again."""
    repo: Path = staged_repo(root)
    lrun(repo, "close", "T-1", "--note", "ok")
    lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")
    lrun(repo, "add", "debt", "gap")  # DB-1: no stage open, so none
    lrun(repo, "reopen", "S-1", "--note", "closed too early")
    lrun(repo, "add", "decision", "ok2", "--owner", "user", "--link", "S-1")
    return repo


def test_reopened_stage_record_write_failure() -> None:  # blind11 F1
    with tempfile.TemporaryDirectory() as d:
        repo: Path = reopened_repo(Path(d))
        rec: Path = repo / "pm/stages/01-paper-x/LEDGER.md"
        first: str = rec.read_text()
        real: Callable[..., None] = os.replace

        def deny(src: Any, dst: Any) -> None:
            if str(dst).endswith("LEDGER.md"):
                raise OSError(13, "denied")
            real(src, dst)

        L.os.replace = deny
        try:
            code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-2")
        finally:
            L.os.replace = real
        assert code == 1 and "could not be written" in out, out
        assert L.load(repo)["S-1"].status == "done" and rec.read_text() == first
        code, out = lrun(repo, "stage-close", "S-1")  # the documented rerun
        assert code == 0 and out.startswith("S-1 is already closed"), out
        text: str = rec.read_text()
        assert text == L.render_stage_record(L.read_events(repo), "S-1"), text
        assert "Window: ledger lines 1 to 5 (" in text, text
        assert f"), 7 to {len(jl(repo))} (" in text, text
        code, out = lrun(repo, "stage-close", "S-1")  # current now: plain refusal
        assert code == 1 and "S-1 is done, not open" in out, out


def test_doctor_gap_of_reopened_stage() -> None:  # blind11 F2, crit8 m1
    with tempfile.TemporaryDirectory() as d:
        repo: Path = reopened_repo(Path(d))
        late: list[str] = ["DB-1 (after S-1) gap"]
        out: str = doctor(repo)[1]
        assert group(out, L.G_LATE) == late and group(out, L.G_NOSTAGE) == [], out
        lrun(repo, "stage-close", "S-1", "--sign-off", "D-2")
        out = doctor(repo)[1]
        assert group(out, L.G_LATE) == late and group(out, L.G_NOSTAGE) == [], out
        lrun(repo, "add", "debt", "after")  # DB-2, after the second close
        out = doctor(repo)[1]
        assert group(out, L.G_LATE) == ["DB-2 (after S-1) after", *late], out


def test_doctor_reopened_imported_stage() -> None:  # blind14 F1, crit8-r12 m1
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "stage", "01-paper-old", "--imported", "--source",
             "old.md:1", "--status", "done")  # line 1
        (repo / "pm/stages/01-paper-old").mkdir(parents=True)
        lrun(repo, "add", "stage", "software-x", "--open")  # line 2
        lrun(repo, "add", "decision", "ok", "--owner", "user", "--link", "S-2")
        lrun(repo, "stage-close", "S-2", "--sign-off", "D-1")  # line 4
        commit_all(repo)
        assert doctor(repo) == (0, "doctor: no findings\n")  # S-1 still skipped
        lrun(repo, "reopen", "S-1", "--note", "redo")  # line 5
        lrun(repo, "add", "decision", "ok2", "--owner", "user", "--link", "S-1")
        lrun(repo, "stage-close", "S-1", "--sign-off", "D-2")  # line 7
        lrun(repo, "add", "debt", "made after")  # DB-1, no stage open
        out: str = doctor(repo)[1]
        assert group(out, L.G_LATE) == ["DB-1 (after S-1) made after"], out
        assert group(out, L.G_UNCOMMITTED) == [
            "S-1 01-paper-old: 3 ledger lines and 1 folder files not in HEAD"
        ], out


def closed_s1_repo(root: Path) -> Path:
    """S-1 (01-software-a) added and closed with D-1 (lines 1 to 3)."""
    repo: Path = new_repo(root)
    lrun(repo, "add", "stage", "software-a", "--open")
    lrun(repo, "add", "decision", "ok", "--owner", "user", "--link", "S-1")
    lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")
    return repo


def test_doctor_imported_open_stage_reopened() -> None:  # blind15 F1
    with tempfile.TemporaryDirectory() as d:
        repo: Path = closed_s1_repo(Path(d))
        for i, title in ((1, "02-paper-x"), (2, "03-experiment-y")):  # open
            lrun(repo, "add", "stage", title, "--imported", "--source", f"a:{i}")
        lrun(repo, "add", "task", "loose", "--note", "n")  # T-1: two open, none
        (repo / "pm/stages/02-paper-x").mkdir(parents=True)
        for k in (2, 3):  # close S-2, reopen it, close it again
            lrun(repo, "add", "decision", f"ok{k}", "--owner", "user", "--link",
                 "S-2", "--stage", "S-2")
            assert lrun(repo, "stage-close", "S-2", "--sign-off", f"D-{k}")[0] == 0
            if k == 2:
                lrun(repo, "reopen", "S-2", "--note", "again")
        rec: str = (repo / "pm/stages/02-paper-x/LEDGER.md").read_text()
        assert "- T-1 task open (lead) loose [no stage]" in rec, rec  # in span 0
        out: str = doctor(repo)[1]
        # made while S-2 and S-3 were open: both, S-3 (opened last) first
        assert group(out, L.G_NOSTAGE) == ["T-1 (S-3, S-2) loose"], out
        assert group(out, L.G_LATE) == [], out


def test_doctor_import_line_is_no_close() -> None:  # exp6-r4 Lead's call 1
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        for i, title in ((1, "01-paper-old"), (2, "02-software-old")):
            lrun(repo, "add", "stage", title, "--imported", "--source", f"o:{i}",
                 "--status", "done")
        lrun(repo, "add", "task", "t1", "--note", "n")
        lrun(repo, "add", "debt", "d1")
        out: str = doctor(repo)[1]
        assert group(out, L.G_LATE) == [] and group(out, L.G_NOSTAGE) == [], out
        lrun(repo, "add", "stage", "paper-new", "--open")  # S-3, a real open and close
        lrun(repo, "add", "decision", "ok", "--owner", "user", "--link", "S-3")
        lrun(repo, "stage-close", "S-3", "--sign-off", "D-1")
        lrun(repo, "add", "stage", "04-paper-x", "--imported", "--source", "o:3",
             "--status", "done")  # an import line ends no gap either
        lrun(repo, "add", "debt", "d2")  # DB-2: late after S-3
        out = doctor(repo)[1]
        assert group(out, L.G_LATE) == ["DB-2 (after S-3) d2"], out


def test_doctor_and_pre_check_name_one_stage() -> None:  # crit8-r14 B1
    with tempfile.TemporaryDirectory() as d:
        repo: Path = closed_s1_repo(Path(d))  # lines 1 to 3
        lrun(repo, "add", "stage", "02-paper-x", "--imported", "--source", "a:1")
        lrun(repo, "add", "stage", "03-experiment-y", "--imported", "--source",
             "a:2")  # S-3: imported open before S-2's reopen, never closed
        (repo / "pm/stages/02-paper-x").mkdir(parents=True)
        lrun(repo, "add", "decision", "ok2", "--owner", "user", "--link", "S-2",
             "--stage", "S-2")
        lrun(repo, "stage-close", "S-2", "--sign-off", "D-2")
        lrun(repo, "reopen", "S-2", "--note", "again")
        lrun(repo, "add", "decision", "ok3", "--owner", "user", "--link", "S-2")
        hint: str = "D-3 (S-2, S-3) ok3"  # both open: S-2 (reopened) opened last
        assert group(doctor(repo)[1], L.G_NOSTAGE) == [hint]
        assert group(doctor(repo, "--stage", "S-2")[1], L.G_NOSTAGE) == [hint]
        assert group(doctor(repo, "--stage", "S-3")[1], L.G_NOSTAGE) == [hint]
        code, out = lrun(repo, "stage-close", "S-2", "--sign-off", "D-3")
        assert code == 0 and f"  {hint}\n" in out, out  # the pre-check: the same


def test_doctor_hint_one_open_stage() -> None:  # exp6-r7: the 0.2.3 form
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "stage", "paper-x", "--open")
        with (repo / L.LEDGER_REL).open("a") as fh:  # stage-less, S-1 alone open
            fh.write(ev_line("T-1", "inside"))
        assert group(doctor(repo)[1], L.G_NOSTAGE) == ["T-1 (S-1) inside"]


def test_doctor_stage_late_pass_sees_all_stages() -> None:  # blind16 F1
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "stage", "paper-a", "--open")
        lrun(repo, "add", "stage", "software-b", "--open")
        lrun(repo, "add", "decision", "ok", "--owner", "user", "--link", "S-1",
             "--stage", "S-1")
        lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")  # S-2 still open
        with (repo / L.LEDGER_REL).open("a") as fh:  # stage-less, after S-1 closed
            fh.write(ev_line("DB-1", "while S-2", typ="debt"))
        out: str = doctor(repo)[1]
        assert group(out, L.G_NOSTAGE) == ["DB-1 (S-2) while S-2"], out
        assert group(out, L.G_LATE) == [], out
        out = doctor(repo, "--stage", "S-1")[1]  # was "DB-1 (after S-1)"
        assert group(out, L.G_LATE) == [] and group(out, L.G_NOSTAGE) == [], out
        out = doctor(repo, "--stage", "S-2")[1]
        assert group(out, L.G_NOSTAGE) == ["DB-1 (S-2) while S-2"], out


def test_doctor_imported_open_stage_closed_here() -> None:  # crit8-r13 m1
    with tempfile.TemporaryDirectory() as d:
        repo: Path = closed_s1_repo(Path(d))
        lrun(repo, "add", "stage", "02-paper-x", "--imported", "--source", "a:1")
        lrun(repo, "add", "decision", "ok2", "--owner", "user", "--link", "S-2")
        assert lrun(repo, "stage-close", "S-2", "--sign-off", "D-2")[0] == 0
        lrun(repo, "add", "debt", "late")  # DB-1, right after S-2 closed
        out: str = doctor(repo)[1]
        assert group(out, L.G_LATE) == ["DB-1 (after S-2) late"], out


def test_record_of_reopened_stage() -> None:  # brief 025 fixes 1, 2
    with tempfile.TemporaryDirectory() as d:
        repo: Path = reopened_repo(Path(d))  # closed at 5, DB-1 at 6, reopened at 7
        lrun(repo, "stage-close", "S-1", "--sign-off", "D-2")  # line 9
        lines: list[str] = (repo / "pm/stages/01-paper-x/LEDGER.md").read_text(
        ).splitlines()
        assert lines[1] == "<!-- rk:stage-record S-1 close 9 -->", lines
        day: str = jl(repo)[6]["ts"][:10]
        i: int = lines.index("## Reopened (1)")
        assert lines[i + 1] == (
            f"- line 7, {day}, lead, after the close at line 5: closed too early"
        ), lines
        ts: list[str] = [ev["ts"] for ev in jl(repo)]  # times per span (blind13 F2)
        assert lines[i - 2] == (
            f"Window: ledger lines 1 to 5 ({ts[0]} to {ts[4]}), "
            f"7 to 9 ({ts[6]} to {ts[8]})."
        ), lines
        # fix 2: DB-1, written while S-1 was closed, is not claimed by the record
        assert not [x for x in lines if "DB-1" in x], lines
        assert "## Entries touched in the window, not of the stage (0)" in lines


def test_record_of_reopened_stage_imported_closed() -> None:  # blind13 F1
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "stage", "01-software-old", "--imported", "--status",
             "done", "--source", "old.md:1")
        (repo / "pm/stages/01-software-old").mkdir(parents=True)
        assert lrun(repo, "reopen", "S-1", "--note", "resume old")[0] == 0
        lrun(repo, "add", "decision", "sign-off", "--owner", "user", "--link", "S-1")
        assert lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")[0] == 0
        rec: Path = repo / "pm/stages/01-software-old/LEDGER.md"
        text: str = rec.read_text()
        lines: list[str] = text.splitlines()
        assert lines[1] == "<!-- rk:stage-record S-1 close 4 -->", lines
        i: int = lines.index("## Reopened (1)")
        assert lines[i + 1].startswith("- line 2, ") and lines[i + 1].endswith(
            "after the import at line 1 (done): resume old"  # blind14 F3
        ), lines
        assert lines[i - 2].startswith("Window: ledger lines 1 to 1 ("), lines
        code, out = lrun(repo, "stage-close", "S-1")  # current: plain refusal
        assert code == 1 and "S-1 is done, not open" in out, out
        assert rec.read_text() == text


def test_add_stage_one_per_kind() -> None:  # brief 025 fix 3
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "stage", "paper-x", "--open")
        n: int = len(jl(repo))
        code, out = lrun(repo, "add", "stage", "paper-y", "--open")
        assert code == 1 and out == (
            "error: cannot add stage 02-paper-y: S-1 (01-paper-x) is open, and at "
            "most one paper stage may be open: stage-close S-1 first\n"
        ), out
        assert len(jl(repo)) == n and not (repo / "pm/stages/02-paper-y").exists()
        assert lrun(repo, "add", "stage", "software-y", "--open")[0] == 0  # other kind
        assert lrun(repo, "add", "stage", "03-paper-z", "--imported",
                    "--source", "a:1")[0] == 0  # imported history: not checked


def test_add_stage_open_computes_nn() -> None:  # W1 T1, Q2, Q11, Q12
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        (repo / "AGENTS.md").write_text("<!-- research-kit: 2026-01-01a -->\n")
        code, out = lrun(repo, "add", "stage", "paper-x", "--open")
        assert code == 0 and out == (
            "logged S-1: 01-paper-x\n"
            "folder pm/stages/01-paper-x/ (deliverables/ notes/ code/ chat/)\n"
        ), out
        evs: list[dict[str, Any]] = jl(repo)
        assert len(evs) == 1 and evs[0]["ev"] == "add", evs  # one add event (Q11)
        assert evs[0]["f"]["status"] == "open" and evs[0]["f"]["title"] == "01-paper-x"
        assert evs[0]["f"]["refs"] == ["pm/stages/01-paper-x/"], evs[0]
        assert evs[0]["rules"] == {"AGENTS.md": "2026-01-01a"}, evs[0]
        folder: Path = repo / "pm/stages/01-paper-x"
        assert sorted(p.name for p in folder.iterdir()) == sorted(L.STAGE_DIRS)
        out = lrun(repo, "add", "stage", "software-y", "--open")[1]
        assert out.startswith("logged S-2: 02-software-y\n"), out
        lrun(repo, "add", "stage", "07-paper-old", "--imported", "--source", "a:1")
        assert L._max_nn(L.load(repo)) == 7  # imported NN titles count (Q2)
        out = lrun(repo, "add", "stage", "experiment-z", "--open")[1]
        assert out.startswith("logged S-4: 08-experiment-z\n"), out
        lrun(repo, "add", "task", "o", "--imported", "--source", "a:2",
             "--legacy-id", "09")  # T-1: code 09 names an entry: skipped (Q12)
        out = lrun(repo, "add", "stage", "thesis-w", "--open")[1]
        assert out.startswith("logged S-5: 10-thesis-w\n"), out
        assert not (repo / "pm/stages/09-thesis-w").exists()
        lrun(repo, "add", "stage", "99-paper-old", "--imported", "--source", "a:3")
        assert L._max_nn(L.load(repo)) == 99
        out = lrun(repo, "add", "stage", "reverse-v", "--open")[1]
        assert out.startswith("logged S-7: 100-reverse-v\n"), out


def test_add_stage_open_one_per_kind() -> None:  # W1 T1
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        assert lrun(repo, "add", "stage", "paper-x", "--open")[0] == 0
        n: int = len(jl(repo))
        code, out = lrun(repo, "add", "stage", "paper-y", "--open")
        assert code == 1 and out == (
            "error: cannot add stage 02-paper-y: S-1 (01-paper-x) is open, and at "
            "most one paper stage may be open: stage-close S-1 first\n"
        ), out
        assert len(jl(repo)) == n
        assert [p.name for p in (repo / "pm/stages").iterdir()] == ["01-paper-x"]


def test_add_stage_open_refuses_nn_title() -> None:  # W1 T1, Q1
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        repo: Path = new_repo(root)
        before: dict[str, bytes | None] = snapshot(root)
        for argv in (
            ("stage", "03-paper-x", "--open"),
            ("stage", "paper", "--open"),
            ("task", "x", "--note", "n", "--open"),
            ("task", "x", "--note", "n", "--follows", "S-1"),  # a stage only
        ):
            code, out = lrun(repo, "add", *argv)
            assert code == 1 and out.startswith("error: "), (argv, out)
        code, out = lrun(repo, "add", "stage", "03-paper-x", "--open")
        assert L.PLAN_FORM in out, out
        assert snapshot(root) == before


def test_open_title_follows() -> None:  # W1 T1, Q3, Q12
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "stage", "paper-x", "--open")  # S-1 01-paper-x
        st: dict[str, Any] = L.load(repo)
        assert L._open_title(st, "paper-y", "S-1") == "01b-paper-y"
        assert L._open_title(st, "paper-y", None) == "02-paper-y"
        lrun(repo, "add", "stage", "software-q", "--open", "--follows", "S-1")  # S-2
        st = L.load(repo)
        assert st["S-2"].title == "01b-software-q", st["S-2"]
        assert L._open_title(st, "paper-y", "S-1") == "01c-paper-y"
        assert L._open_title(st, "paper-y", "S-2") == "01c-paper-y"
        lrun(repo, "add", "stage", "old", "--imported", "--source", "a:1")  # S-3
        try:
            L._open_title(L.load(repo), "paper-y", "S-3")
            raise AssertionError("no NN title: refused")
        except L.LedgerError as err:
            assert "S-3" in str(err), err
        code, out = lrun(repo, "add", "stage", "thesis-z", "--open", "--follows", "S-1")
        assert code == 0 and out.startswith("logged S-4: 01c-thesis-z\n"), out
        assert (repo / "pm/stages/01c-thesis-z/notes").is_dir()


# T3, D-29/D-33: receipt, P- folder, queue; red: STAGE_RE refuses `paper-scan`
def test_add_stage_plans() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        (repo / "a.md").write_text("a")
        dirs: str = " ".join(f"{s}/" for s in L.STAGE_DIRS)
        assert L.STATUSES[-1] == "shelved" and "planned" in L.STATUSES
        assert L._queue_end(L.load(repo)) == "1"  # no stage yet
        code, out = lrun(repo, "add", "stage", "paper-scan")
        assert code == 0 and out == (
            "logged S-1: paper-scan (planned)\n"
            f"folder pm/stages/P-1-paper-scan/ ({dirs})\n"
        ), out
        folder: Path = repo / "pm/stages/P-1-paper-scan"
        assert sorted(p.name for p in folder.iterdir()) == sorted(L.STAGE_DIRS)
        st: Any = L.load(repo)
        assert st["S-1"].status == "planned" and st["S-1"].title == "paper-scan"
        assert st["S-1"].refs == ["pm/stages/P-1-paper-scan/"], st["S-1"].refs
        assert st["S-1"].extra["queue"] == "1", st["S-1"].extra
        assert not (repo / "pm/stages/paper-scan").exists()
        code, out = lrun(repo, "add", "stage", "software-y", "--ref", "a.md")
        assert code == 0 and out.splitlines()[0] == "logged S-2: software-y (planned)"
        assert out.splitlines()[1].startswith("folder pm/stages/P-2-software-y/ ("), out
        st = L.load(repo)
        assert st["S-2"].extra["queue"] == "2", st["S-2"].extra
        assert st["S-2"].refs == ["pm/stages/P-2-software-y/", "a.md"], st["S-2"].refs
        assert (repo / "pm/stages/P-2-software-y/notes").is_dir()
        assert L._queue_end(st) == "3"
        assert L._stage_dir(st["S-1"]) == "pm/stages/P-1-paper-scan/"
        code, out = lrun(repo, "add", "stage", "old", "--imported", "--source", "a:1")
        assert code == 0 and out == "logged S-3: old\n", out  # imported: as it was
        assert L._stage_dir(L.load(repo)["S-3"]) == "pm/stages/old/"
        assert not (repo / "pm/stages/old").exists()
        code, out = lrun(repo, "add", "stage", "paper-scan")  # a title names one
        assert code == 1 and "already names S-1" in out, out


# T3, D-32/D-34: planned is no open stage; entries may join it; red: add refused
def test_planned_not_open() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        repo: Path = new_repo(root)
        assert lrun(repo, "add", "stage", "paper-y")[0] == 0  # S-1, planned
        out: str = lrun(repo, "list")[1]
        assert out.splitlines()[0] == "open 0 (running 0)", out
        assert "S-1" not in out, out
        assert L._default_stage(L.load(repo), "task", False) == ""
        code, out = lrun(
            repo, "add", "debt", "later", "--owner", "lead", "--stage", "S-1"
        )
        assert code == 0 and "DB-1" in out, out
        code, out = lrun(repo, "add", "task", "t", "--note", "n", "--stage", "S-1")
        assert code == 0 and "T-1" in out, out
        assert lrun(repo, "add", "debt", "loose", "--owner", "lead")[0] == 0  # DB-2
        st: Any = L.load(repo)
        stages_of: list[str] = [st[i].stage for i in ("DB-1", "T-1", "DB-2")]
        assert stages_of == ["S-1", "S-1", ""], stages_of
        before: dict[str, bytes | None] = snapshot(root)
        code, out = lrun(repo, "stage-close", "S-1")
        assert code == 1 and "S-1 is planned, not open" in out, out
        assert snapshot(root) == before
        code, out = lrun(repo, "add", "stage", "paper-x", "--open")  # beside a plan
        assert code == 0 and out.startswith("logged S-2: 01-paper-x\n"), out
        assert L._default_stage(L.load(repo), "task", False) == "S-2"  # not S-1
        rows: list[str] = lrun(repo, "list")[1].splitlines()[1:]
        ids: list[str] = [ln.split()[0] for ln in rows]
        assert "S-2" in ids and "S-1" not in ids, ids
        assert L.load(repo)["S-1"].status == "planned"


# T3, D-29/Q1: an NN title is refused with the hint; red: today it opens the stage
def test_add_stage_refuses_nn_title() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        repo: Path = new_repo(root)
        before: dict[str, bytes | None] = snapshot(root)
        for title in ("03-paper-x", "03b-paper-x"):
            code, out = lrun(repo, "add", "stage", title)
            assert code == 1 and out == (
                f"error: stage title '{title}' has an NN: use <kind>-<topic>; "
                "the NN comes at stage-open; to open it now: rk add stage "
                "<kind>-<topic> --open\n"
            ), out
            assert snapshot(root) == before, title  # nothing written, no folder
        assert not (repo / "pm/stages").exists()
        code, out = lrun(
            repo, "add", "stage", "03-paper-x", "--imported", "--source", "a:1"
        )  # imported: as it was
        assert code == 0 and out == "logged S-1: 03-paper-x\n", out
        assert not (repo / "pm/stages").exists()


# T3, D-28/D-34: planned only by add stage; red: argparse choices lack `planned`
def test_planned_status_only_by_add_stage() -> None:
    msg: str = (
        "--status planned: a stage is planned by add stage <kind>-<topic> "
        "without --status; no other add and no import row sets it"
    )
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        repo: Path = new_repo(root)
        before: dict[str, bytes | None] = snapshot(root)
        for argv in (
            ("task", "t", "--note", "n", "--status", "planned"),
            ("debt", "d", "--status", "planned"),
            ("stage", "paper-q", "--status", "planned"),
            ("task", "t", "--imported", "--source", "a:1", "--status", "planned"),
        ):
            code, out = lrun(repo, "add", *argv)
            assert code == 1 and out == f"error: {msg}\n", (argv, out)
            assert snapshot(root) == before, argv
        for row in (
            {"type": "task", "title": "x", "source": "P:1", "status": "planned"},
            {"type": "stage", "title": "paper-q", "source": "P:2", "status": "planned"},
        ):
            rows: Path = write_rows(root, [row])
            before = snapshot(root)
            code, out = lrun(repo, "import", str(rows))
            assert code == 1 and f"{rows}:1: {msg}" in out, (row, out)
            assert snapshot(root) == before, row
        assert jl(repo) == []


# T3, D-29: a planned title has no stage code; red: code `paper` would clash
def test_planned_title_has_no_code() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        for title in ("paper-scan", "paper-draft"):  # same first word: no clash
            code, out = lrun(repo, "add", "stage", title)
            assert code == 0, (title, out)
        assert lrun(repo, "show", "paper-scan")[1].startswith("id: S-1\n")
        assert lrun(repo, "show", "paper-draft")[1].startswith("id: S-2\n")
        n: int = len(jl(repo))
        code, out = lrun(repo, "show", "paper")
        assert code == 1 and "no such entry paper" in out, out
        assert len(jl(repo)) == n


# T3, D-33: doctor knows the P- folder; red: a stage cannot be planned yet
def test_doctor_planned_stage_folder() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        assert lrun(repo, "add", "stage", "paper-scan")[0] == 0
        code, out = doctor(repo)
        assert code == 0 and "HARD" not in out, out
        shutil.rmtree(repo / "pm/stages/P-1-paper-scan")
        code, out = doctor(repo)
        assert code == 1, out
        assert group(out, "missing stage folder") == [
            "S-1 pm/stages/P-1-paper-scan/"
        ], out
        assert group(out, "missing ref") == [], out  # its own folder ref: once


def sign_off_close(repo: Path, sid: str) -> None:
    """Log a user decision linked to `sid`, then stage-close `sid` on it."""
    code, out = lrun(
        repo, "add", "decision", f"ok {sid}", "--owner", "user", "--link", sid
    )
    assert code == 0, out
    did: str = out.split()[1].rstrip(":")  # "logged D-1: ok S-1 (stage S-1)"
    code, out = lrun(repo, "stage-close", sid, "--sign-off", did)
    assert code == 0 and f"closed {sid}: sign-off {did}\n" in out, out


# T4, D-29/D-33: receipt, status, rename, ref rewrite, rules; red: stage-open unknown
def test_stage_open_basic() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        agents: Path = repo / "AGENTS.md"
        agents.write_text("<!-- research-kit: 2026-01-01a -->\n# x\n")
        assert lrun(repo, "add", "stage", "paper-scan")[0] == 0  # S-1, P-1-paper-scan
        old: str = "pm/stages/P-1-paper-scan"
        new: str = "pm/stages/01-paper-scan"
        (repo / old / "notes/a.md").write_text("a")
        near: Path = repo / "pm/stages/P-1-paper-scan2"  # same prefix, not the folder
        near.mkdir()
        (near / "x.md").write_text("x")
        (repo / "keep.md").write_text("k")
        debts: tuple[tuple[str, ...], ...] = (
            ("--stage", "S-1", "--ref", f"{old}/notes/a.md", "--ref", "keep.md"),
            ("--ref", "pm/stages/P-1-paper-scan2/x.md"),  # DB-2: not under the folder
            ("--ref", "keep.md"),  # DB-3: no ref under the folder
        )
        for i, argv in enumerate(debts, 1):  # DB-1, DB-2, DB-3
            code, out = lrun(repo, "add", "debt", f"d{i}", "--owner", "lead", *argv)
            assert code == 0, out
        n: int = len(jl(repo))
        agents.write_text("<!-- research-kit: 2026-01-05c -->\n# x\n")
        code, out = lrun(repo, "stage-open", "S-1")
        assert code == 0 and out == (
            "opened S-1: 01-paper-scan\n"
            f"folder {old}/ -> {new}/\n"
            "refs: 2 rewritten\n"  # the stage's own ref and DB-1's
        ), out
        st: Any = L.load(repo)
        assert st["S-1"].status == "open" and st["S-1"].title == "01-paper-scan"
        assert st["S-1"].refs == [f"{new}/"], st["S-1"].refs
        assert st["DB-1"].refs == [f"{new}/notes/a.md", "keep.md"], st["DB-1"].refs
        assert st["DB-2"].refs == ["pm/stages/P-1-paper-scan2/x.md"], st["DB-2"].refs
        assert st["DB-3"].refs == ["keep.md"] and st["DB-1"].stage == "S-1"
        assert not (repo / old).exists(), "P folder must be gone"
        assert (repo / new / "notes/a.md").read_text() == "a"
        assert sorted(p.name for p in (repo / new).iterdir()) == sorted(L.STAGE_DIRS)
        evs: list[dict[str, Any]] = jl(repo)[n:]  # one set on the stage, one per ref
        by_id: dict[str, dict[str, Any]] = {e["id"]: e for e in evs}
        assert sorted(by_id) == ["DB-1", "S-1"] and len(evs) == 2, evs
        assert by_id["S-1"]["ev"] == "set", evs
        assert set(by_id["S-1"]["f"]) == {"status", "title", "refs"}, evs
        assert by_id["S-1"]["rules"] == {"AGENTS.md": "2026-01-05c"}, evs  # at open
        assert by_id["DB-1"]["ev"] == "set" and list(by_id["DB-1"]["f"]) == ["refs"]
        assert "rules" not in by_id["DB-1"], evs
        commit_all(repo)
        code, out = doctor(repo)
        assert code == 0 and "HARD" not in out, out


# T4, D-29/Q7: only a planned stage opens, one per kind, no merge of folders; red: same
def test_stage_open_refusals() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        repo: Path = new_repo(root)
        stages: Path = repo / "pm/stages"
        only: str = ": only a planned stage opens\n"

        def refuse(argv: list[str], *want: str) -> None:
            """Refused with code 1, `want` in the message, nothing changed."""
            before: dict[str, bytes | None] = snapshot(root)
            code, out = lrun(repo, *argv)
            assert code == 1 and all(w in out for w in want), (argv, out)
            assert snapshot(root) == before, argv

        for title in ("paper-a", "paper-b"):  # S-1, S-2
            assert lrun(repo, "add", "stage", title)[0] == 0
        assert lrun(repo, "stage-open", "S-1")[0] == 0  # 01-paper-a
        refuse(["stage-open", "S-1"], f"error: S-1 is open{only}")
        refuse(  # the form of _check_one_per_kind, what = "stage-open S-2"
            ["stage-open", "S-2"],
            "error: cannot stage-open S-2: S-1 (01-paper-a) is open, and at most "
            "one paper stage may be open: stage-close S-1 first\n",
        )
        sign_off_close(repo, "S-1")
        refuse(["stage-open", "S-1"], f"error: S-1 is done{only}")
        code, out = lrun(
            repo, "add", "stage", "old3", "--imported", "--source", "a:1",
            "--status", "shelved",
        )  # fmt: skip
        assert code == 0 and out == "logged S-3: old3\n", out
        refuse(["stage-open", "S-3"], f"error: S-3 is shelved{only}")
        assert lrun(repo, "add", "task", "t", "--note", "n")[0] == 0  # T-1
        refuse(["stage-open", "T-1"], "error: T-1 is a task, not a stage\n")
        (stages / "02-paper-b").mkdir()  # the NN S-2 would take exists: no merge
        refuse(
            ["stage-open", "S-2"],
            "error: cannot stage-open S-2: pm/stages/02-paper-b/ is there already; "
            "folders are not merged: move it away first\n",
        )
        (stages / "02-paper-b").rmdir()
        (stages / "P-2-paper-b").rename(root / "moved")  # the P folder is missing
        refuse(
            ["stage-open", "S-2"],
            "error: cannot stage-open S-2: no folder pm/stages/P-2-paper-b/; "
            "restore it first\n",
        )
        (root / "moved").rename(stages / "P-2-paper-b")
        code, out = lrun(repo, "stage-open", "S-2")  # the refusals were all of it
        assert code == 0 and out.startswith("opened S-2: 02-paper-b\n"), out


# T4, D-26/D-31: the next free NN at open, not at plan; red: stage-open unknown
def test_stage_open_takes_next_nn() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        for title in ("paper-a", "software-b"):  # S-1, S-2: planned in this order
            assert lrun(repo, "add", "stage", title)[0] == 0
        code, out = lrun(repo, "stage-open", "S-2")
        assert code == 0 and out.splitlines()[:2] == [
            "opened S-2: 01-software-b",
            "folder pm/stages/P-2-software-b/ -> pm/stages/01-software-b/",
        ], out
        code, out = lrun(repo, "stage-open", "S-1")
        assert code == 0 and out.splitlines()[:2] == [
            "opened S-1: 02-paper-a",
            "folder pm/stages/P-1-paper-a/ -> pm/stages/02-paper-a/",
        ], out
        st: Any = L.load(repo)
        assert (st["S-1"].title, st["S-1"].status) == ("02-paper-a", "open")
        assert (st["S-2"].title, st["S-2"].status) == ("01-software-b", "open")
        assert sorted(p.name for p in (repo / "pm/stages").iterdir()) == [
            "01-software-b", "02-paper-a"
        ]


# T4, D-31 (+ lead's answers Q3): letter b first, c next, no number used; red: same
def test_stage_open_follows() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        assert lrun(repo, "add", "stage", "paper-x", "--open")[0] == 0  # S-1 01-paper-x
        sign_off_close(repo, "S-1")
        for title in ("paper-y", "paper-z", "software-w", "experiment-v"):
            assert lrun(repo, "add", "stage", title)[0] == 0  # S-2 .. S-5, planned
        n: int = len(jl(repo))
        code, out = lrun(repo, "stage-open", "S-4", "--follows", "S-3")  # S-3 planned
        assert code == 1 and out == (
            "error: --follows S-3: S-3 (paper-z) is planned and has no NN yet; "
            "follow an opened stage\n"
        ), out
        assert len(jl(repo)) == n
        assert sorted(p.name for p in (repo / "pm/stages").iterdir()) == [
            "01-paper-x", "P-2-paper-y", "P-3-paper-z", "P-4-software-w",
            "P-5-experiment-v",
        ]  # nothing renamed or made by the refusal
        code, out = lrun(repo, "stage-open", "S-2", "--follows", "S-1")
        assert code == 0 and out.splitlines()[:2] == [
            "opened S-2: 01b-paper-y",
            "folder pm/stages/P-2-paper-y/ -> pm/stages/01b-paper-y/",
        ], out
        code, out = lrun(repo, "stage-open", "S-4", "--follows", "S-1")
        assert code == 0 and out.splitlines()[0] == "opened S-4: 01c-software-w", out
        code, out = lrun(repo, "stage-open", "S-5")  # a letter uses up no number
        assert code == 0 and out.splitlines()[0] == "opened S-5: 02-experiment-v", out
        st: Any = L.load(repo)
        assert [st[f"S-{i}"].title for i in (1, 2, 3, 4, 5)] == [
            "01-paper-x", "01b-paper-y", "paper-z", "01c-software-w",
            "02-experiment-v",
        ]
        assert st["S-3"].status == "planned"
        assert sorted(p.name for p in (repo / "pm/stages").iterdir()) == [
            "01-paper-x", "01b-paper-y", "01c-software-w", "02-experiment-v",
            "P-3-paper-z",
        ]


# T4, D-33 (rename undone on a failure BEFORE the ledger line is written; a
# failure after it: test_stage_open_failure_after_write); red: stage-open unknown
def test_stage_open_rolls_back_rename() -> None:
    with tempfile.TemporaryDirectory() as d:  # injected in fold (plan section 11)
        repo: Path = new_repo(Path(d))
        assert lrun(repo, "add", "stage", "paper-scan")[0] == 0
        pdir: Path = repo / "pm/stages/P-1-paper-scan"
        (pdir / "notes/a.md").write_text("a")
        code, out = lrun(
            repo, "add", "debt", "d", "--stage", "S-1",
            "--ref", "pm/stages/P-1-paper-scan/notes/a.md",
        )  # fmt: skip
        assert code == 0, out
        before: dict[str, bytes | None] = snapshot(Path(d))
        real: Any = L.fold

        def fold_fails_after_rename(events: Any) -> Any:
            """append folds the new lines before it writes them; at that point the
            folder has been renamed: a failure after the rename, before the write."""
            if not pdir.exists():
                raise OSError(28, "injected: no space left on device")
            return real(events)

        L.fold = fold_fails_after_rename
        try:
            try:
                code, out = lrun(repo, "stage-open", "S-1")
            except OSError:  # re-raised, as the plan says
                pass
            else:
                raise AssertionError(f"no OSError: {code} {out}")
        finally:
            L.fold = real
        assert snapshot(Path(d)) == before  # P folder and file back, ledger as was
        assert (pdir / "notes/a.md").read_text() == "a"
        assert not (repo / "pm/stages/01-paper-scan").exists()
        st: Any = L.load(repo)
        assert st["S-1"].status == "planned" and st["S-1"].title == "paper-scan"
        code, out = lrun(repo, "stage-open", "S-1")  # a retry works
        assert code == 0 and out.startswith("opened S-1: 01-paper-scan\n"), out


# T4, spec Folder (doctor flags a ref into a gone P- folder); no new code, pins it
def test_doctor_ref_into_gone_p_folder() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        for title in ("paper-x", "software-y"):  # S-1 stays planned, S-2 opens
            assert lrun(repo, "add", "stage", title)[0] == 0
        assert lrun(repo, "stage-open", "S-2")[0] == 0  # pm/stages/01-software-y/
        ghost: Path = repo / "pm/stages/P-9-x"  # a P folder no stage owns
        ghost.mkdir(parents=True)
        (ghost / "a.md").write_text("a")
        code, out = lrun(repo, "add", "debt", "d", "--ref", "pm/stages/P-9-x/a.md")
        assert code == 0, out  # DB-1
        assert doctor(repo)[0] == 0  # the ref holds; P-1-paper-x of S-1 is there
        shutil.rmtree(ghost)
        code, out = doctor(repo)
        assert code == 1, out
        assert group(out, "missing ref") == ["DB-1 pm/stages/P-9-x/a.md"], out
        assert group(out, "missing stage folder") == [], out
        # the real case: a ref left on the P path after stage-open renamed it
        stale: Path = repo / "pm/stages/P-2-software-y/notes"
        stale.mkdir(parents=True)
        (stale / "b.md").write_text("b")
        code, out = lrun(
            repo, "add", "debt", "late", "--ref", "pm/stages/P-2-software-y/notes/b.md"
        )
        assert code == 0, out  # DB-2
        shutil.rmtree(repo / "pm/stages/P-2-software-y")
        code, out = doctor(repo)
        assert code == 1, out
        assert sorted(group(out, "missing ref")) == [
            "DB-1 pm/stages/P-9-x/a.md",
            "DB-2 pm/stages/P-2-software-y/notes/b.md",
        ], out
        assert group(out, "missing stage folder") == [], out  # S-2 is at 01-


# T5, D-33 (a planned add is no reopen); red: record has `Reopened (1)`, add-line window
def test_record_of_planned_stage() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        agents: Path = repo / "AGENTS.md"
        agents.write_text("<!-- research-kit: 2026-01-01a -->\n")
        assert lrun(repo, "add", "stage", "paper-x")[0] == 0  # line 1, planned
        lrun(repo, "add", "debt", "while planned", "--owner", "lead", "--stage", "S-1")
        lrun(repo, "add", "debt", "unrelated", "--owner", "lead")  # DB-2: no stage
        lrun(repo, "add", "task", "unrelated too", "--note", "n")  # T-1: no stage
        agents.write_text("<!-- research-kit: 2026-01-05c -->\n")
        code, out = lrun(repo, "stage-open", "S-1")
        assert code == 0 and out.startswith("opened S-1: 01-paper-x\n"), out
        assert lrun(repo, "add", "task", "t", "--note", "n")[0] == 0  # T-2, in S-1
        assert lrun(repo, "close", "T-2", "--note", "ok")[0] == 0
        agents.write_text("<!-- research-kit: 2026-01-09d -->\n")
        sign_off_close(repo, "S-1")  # D-1, closes
        rec: Path = repo / "pm/stages/01-paper-x/LEDGER.md"
        text: str = rec.read_text()
        events: list[tuple[int, dict[str, object]]] = L.read_events(repo)
        assert text == L.render_stage_record(events, "S-1"), text
        opened: list[tuple[int, dict[str, object]]] = []  # the stage-open event
        for n, ev in events:
            f: Any = ev.get("f")
            if (
                ev.get("id") == "S-1" and ev.get("ev") == "set"
                and isinstance(f, dict) and "title" in f
            ):
                opened.append((n, ev))
        assert len(opened) == 1 and opened[0][0] > 1, opened  # not the add line
        open_n, open_ev = opened[0]
        end, close_ev = events[-1]
        assert text.startswith("# Ledger of stage S-1 01-paper-x (generated)\n"), text
        assert "Reopened" not in text and "rk:stage-record" not in text, text
        assert L.RECORD_MARK_RE.search(text) is None, text
        assert text.count("Window: ledger lines") == 1, text  # one span, 0.2.3 form
        assert (
            f"Window: ledger lines {open_n} to {end}, "
            f"{open_ev['ts']} to {close_ev['ts']}.\n"
        ) in text, text  # starts at the open line and its time, not the add line
        assert "rules at open: AGENTS.md 2026-01-05c\n" in text, text
        assert text.endswith("rules at close: AGENTS.md 2026-01-09d\n"), text
        assert (
            "## Entries of the stage (3)\n"
            "- DB-1 debt open (lead) while planned\n"
            "- T-2 task done (lead) t\n"
            "- D-1 decision done (user) ok S-1\n"
        ) in text, text
        assert (
            "## Entries touched in the window, not of the stage (0)\nnone\n" in text
        ), text
        assert "DB-2" not in text and "T-1" not in text, text
        first: bytes = rec.read_bytes()
        code, out = lrun(repo, "stage-close", "S-1")  # the record is current: refusal
        assert code == 1 and "S-1 is done, not open" in out, out
        assert rec.read_bytes() == first


# T5, D-33: planned -> open is no reopen; red: _reopen_line counts it, close refused
def test_signoff_while_planned_accepted_at_close() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        assert lrun(repo, "add", "stage", "paper-x")[0] == 0  # S-1, planned
        code, out = lrun(
            repo, "add", "decision", "ok S-1", "--owner", "user",
            "--link", "S-1", "--stage", "S-1",
        )  # fmt: skip
        assert code == 0 and "D-1" in out, out  # logged while the stage is planned
        assert lrun(repo, "stage-open", "S-1")[0] == 0
        code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")
        assert code == 0 and "closed S-1: sign-off D-1\n" in out, out
        assert "reopened" not in out, out
        # a real reopen still needs a new sign-off (the 0.2.3 rule, unchanged)
        assert lrun(repo, "reopen", "S-1", "--note", "closed too early")[0] == 0
        code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")
        assert code == 1 and "D-1 was logged before S-1 was reopened" in out, out


def plan_stages(repo: Path, *titles: str) -> None:
    """Plan each `<kind>-<topic>` (T3 form); each add must succeed."""
    for t in titles:
        code, out = lrun(repo, "add", "stage", t)
        assert code == 0, (t, out)


def queue_ids(repo: Path) -> list[str]:
    return [e.id for e in L._queue(L.load(repo))]


def queue_values(repo: Path) -> dict[str, str]:
    return {e.id: e.extra["queue"] for e in L._queue(L.load(repo))}


def forecast_of(repo: Path) -> dict[str, str]:
    return L._forecast(L.load(repo))


def lrun_exit(repo: Path, *argv: str) -> int:
    """Exit code of an argv that argparse or the handler may refuse: the
    SystemExit code of an argparse error (stderr swallowed), else the return."""
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            code, _ = lrun(repo, *argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    return code


def refused(repo: Path, *argv: str) -> str:
    """argv must be refused by the handler (code 1) and write nothing."""
    before: bytes = (repo / L.LEDGER_REL).read_bytes()
    code, out = lrun(repo, *argv)
    assert code == 1 and out.startswith("error: "), (argv, code, out)
    assert (repo / L.LEDGER_REL).read_bytes() == before, argv
    return out


def plan_row(eid: str, title: str, queue: str, status: str = "planned") -> str:
    """A hand-written stage add line carrying a queue value (no CLI needed)."""
    f: dict[str, object] = {
        "type": "stage", "title": title, "status": status, "owner": "lead",
        "stage": "", "note": "", "links": [], "refs": [], "queue": queue,
    }
    return json.dumps(L.make_event("lead", "add", eid, f)) + "\n"


# T6 / D-27, plan 3.1; red: --before/--after, `queue`, ._queue, ._queue_slot missing
def test_queue_append_and_moves() -> None:
    target: str = "; the target must be a planned stage\n"
    mover: str = ": --before/--after move a planned stage\n"
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        plan_stages(repo, "paper-a", "paper-b", "paper-c")  # S-1 S-2 S-3
        st: dict[str, Any] = L.load(repo)
        assert [st[s].extra["queue"] for s in ("S-1", "S-2", "S-3")] == [
            "1", "2", "3",
        ]
        assert L._queue_slot(st, "S-2", None) == "3/2"  # midpoint of 1 and 2
        assert L._queue_slot(st, None, "S-1") == "3/2"
        assert L._queue_slot(st, None, "S-2") == "5/2"
        assert L._queue_slot(st, None, None) == "4"  # no place given: the end
        # insert: one add event carries the value, nobody else is touched
        n: int = len(jl(repo))
        code, out = lrun(repo, "add", "stage", "paper-d", "--before", "S-2")
        assert code == 0 and out.startswith("logged S-4: paper-d (planned)\n"), out
        assert len(jl(repo)) == n + 1
        ev: dict[str, Any] = jl(repo)[-1]
        assert ev["ev"] == "add" and ev["id"] == "S-4", ev
        assert ev["f"]["status"] == "planned" and ev["f"]["queue"] == "3/2", ev
        assert queue_ids(repo) == ["S-1", "S-4", "S-2", "S-3"]
        code, out = lrun(repo, "add", "stage", "paper-e", "--before", "S-2")
        assert code == 0, out  # S-2's neighbour is now S-4 (3/2): 2 and 3/2
        assert queue_values(repo)["S-5"] == "7/4"
        assert queue_ids(repo) == ["S-1", "S-4", "S-5", "S-2", "S-3"]
        # move: ONE set event holding only `queue`; no other value changes
        before: dict[str, str] = queue_values(repo)
        n = len(jl(repo))
        code, out = lrun(repo, "set", "S-3", "--after", "S-1")
        assert code == 0 and out == "updated S-3: queue\n", out
        assert len(jl(repo)) == n + 1
        ev = jl(repo)[-1]
        assert ev["ev"] == "set" and ev["id"] == "S-3", ev
        assert ev["f"] == {"queue": "5/4"}, ev  # midpoint of 1 and 3/2
        after: dict[str, str] = queue_values(repo)
        assert {k: v for k, v in after.items() if k != "S-3"} == {
            k: v for k, v in before.items() if k != "S-3"
        }, (before, after)
        assert queue_ids(repo) == ["S-1", "S-3", "S-4", "S-5", "S-2"]
        # to the end, to the front: X+1 after the last, X-1 before the first
        assert lrun(repo, "set", "S-1", "--after", "S-2")[0] == 0
        assert queue_values(repo)["S-1"] == "3"  # 2 + 1 (S-1 itself left out)
        assert queue_ids(repo) == ["S-3", "S-4", "S-5", "S-2", "S-1"]
        assert lrun(repo, "add", "stage", "paper-f", "--before", "S-3")[0] == 0
        assert lrun(repo, "add", "stage", "paper-g", "--after", "S-1")[0] == 0
        assert queue_values(repo)["S-6"] == "1/4"  # 5/4 - 1
        assert queue_values(repo)["S-7"] == "4"  # 3 + 1
        assert queue_ids(repo) == [
            "S-6", "S-3", "S-4", "S-5", "S-2", "S-1", "S-7",
        ]
        vals: dict[str, str] = queue_values(repo)
        assert len(set(vals.values())) == len(vals), vals  # all distinct
        # refusals: target or mover not planned; each writes nothing
        assert lrun(repo, "add", "stage", "software-o", "--open")[0] == 0  # S-8
        assert lrun(repo, "add", "task", "t", "--note", "n")[0] == 0  # T-1
        lrun(repo, "add", "stage", "05-paper-old", "--imported", "--source",
             "A:1", "--status", "shelved")  # S-9
        out = refused(repo, "add", "stage", "paper-x", "--before", "S-8")
        assert out == f"error: --before S-8: S-8 is open{target}", out
        out = refused(repo, "add", "stage", "paper-x", "--after", "S-9")
        assert out == f"error: --after S-9: S-9 is shelved{target}", out
        out = refused(repo, "add", "stage", "paper-x", "--before", "S-99")
        assert out == "error: no stage 'S-99'\n", out
        out = refused(repo, "add", "stage", "paper-x", "--before", "T-1")
        assert out == "error: T-1 is a task, not a stage\n", out
        out = refused(repo, "set", "S-2", "--before", "S-8")
        assert out == f"error: --before S-8: S-8 is open{target}", out
        out = refused(repo, "set", "S-8", "--before", "S-2")  # mover open
        assert out == f"error: S-8 is open{mover}", out
        out = refused(repo, "set", "S-9", "--after", "S-2")  # mover shelved
        assert out == f"error: S-9 is shelved{mover}", out
        out = refused(repo, "set", "T-1", "--before", "S-2")  # mover a task
        assert out == f"error: T-1 is a task{mover}", out
        # --before/--after with --open: refused, no line, no folder
        stages: dict[str, bytes | None] = snapshot(repo / "pm" / "stages")
        n = len(jl(repo))
        for flag in ("--before", "--after"):
            code, out = lrun(repo, "add", "stage", "paper-x", "--open", flag, "S-2")
            assert code == 1 and out == (
                "error: --before/--after: only when a stage is planned (add stage "
                "<kind>-<topic>, without --open)\n"
            ), (flag, out)
        assert len(jl(repo)) == n and snapshot(repo / "pm" / "stages") == stages
        # --before with --after: mutually exclusive (argparse), add and set
        assert lrun_exit(
            repo, "add", "stage", "paper-x", "--before", "S-2", "--after", "S-3"
        ) == 2
        assert lrun_exit(repo, "set", "S-2", "--before", "S-3", "--after", "S-4") == 2
        assert len(jl(repo)) == n
    # numeric order, not string order: "10" sorts before "9" as text
    with tempfile.TemporaryDirectory() as d:
        repo = new_repo(Path(d))
        plan_stages(repo, *[f"paper-t{i:02d}" for i in range(1, 11)])
        assert L.load(repo)["S-10"].extra["queue"] == "10"
        assert queue_ids(repo) == [f"S-{i}" for i in range(1, 11)]
    # _queue: planned only, by Fraction(queue) then id; a shelved stage keeps a
    # stale value that is ignored
    with tempfile.TemporaryDirectory() as d:
        repo = new_repo(Path(d))
        (repo / L.LEDGER_REL).write_text(
            plan_row("S-1", "paper-a", "1")
            + plan_row("S-2", "paper-b", "1")
            + plan_row("S-3", "paper-c", "1/2")
            + plan_row("S-4", "paper-d", "1/4", "shelved")
        )
        assert queue_ids(repo) == ["S-3", "S-1", "S-2"]


# T6 / D-26, D-31, spec Numbering; red: ._forecast missing
def test_forecast_shift_and_fix() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        assert lrun(repo, "add", "stage", "paper-x", "--open")[0] == 0  # 01
        plan_stages(repo, "software-a", "thesis-b", "experiment-c")  # S-2 S-3 S-4
        assert forecast_of(repo) == {"S-2": "~02", "S-3": "~03", "S-4": "~04"}
        # a stage is inserted and opened: the forecasts shift, nothing is written
        n: int = len(jl(repo))
        code, out = lrun(repo, "add", "stage", "experiment-i", "--open")  # S-5
        assert code == 0, out
        new: list[dict[str, Any]] = jl(repo)[n:]
        assert [(x["ev"], x["id"]) for x in new] == [("add", "S-5")], new
        assert L.load(repo)["S-5"].title == "02-experiment-i"
        assert forecast_of(repo) == {"S-2": "~03", "S-3": "~04", "S-4": "~05"}
        # its own open fixes the NN; the others keep theirs
        code, out = lrun(repo, "stage-open", "S-2")
        assert code == 0, out
        assert L.load(repo)["S-2"].title == "03-software-a"
        assert forecast_of(repo) == {"S-3": "~04", "S-4": "~05"}
        # imported NN titles count (Q2), shelved or not; same base as stage-open
        lrun(repo, "add", "stage", "07-paper-old", "--imported", "--source",
             "A:1", "--status", "shelved")  # S-6
        assert forecast_of(repo) == {"S-3": "~08", "S-4": "~09"}
        assert lrun(repo, "stage-open", "S-3")[0] == 0
        assert L.load(repo)["S-3"].title == "08-thesis-b"  # = its forecast
        # two digits pad, three do not
        lrun(repo, "add", "stage", "98-paper-huge", "--imported", "--source",
             "A:2", "--status", "shelved")  # S-7
        plan_stages(repo, "paper-d")  # S-8
        assert forecast_of(repo) == {"S-4": "~99", "S-8": "~100"}


# T6 / D-31, plan 3.2; red: `--follows` on a planned add unknown (SystemExit 2)
def test_forecast_follows() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        assert lrun(repo, "add", "stage", "paper-x", "--open")[0] == 0  # 01, S-1
        for title in ("software-y", "thesis-w"):  # S-2 S-3: follow-ups of S-1
            code, out = lrun(repo, "add", "stage", title, "--follows", "S-1")
            assert code == 0, out
        plan_stages(repo, "software-z")  # S-4, a plain planned stage
        st: dict[str, Any] = L.load(repo)
        assert st["S-2"].status == "planned" and st["S-2"].extra["follows"] == "S-1"
        assert st["S-3"].extra["follows"] == "S-1"
        assert "follows" not in st["S-4"].extra
        # a follow-up takes no place: S-4 is still the first plain planned stage
        assert forecast_of(repo) == {"S-2": "~01b", "S-3": "~01c", "S-4": "~02"}
        plan_stages(repo, "paper-q")  # S-5
        assert forecast_of(repo)["S-5"] == "~03"
        # S-3 opens as 01b (follows kept from plan time): S-2 moves to the next
        # free letter, the plain stages keep their numbers
        code, out = lrun(repo, "stage-open", "S-3")
        assert code == 0, out
        assert L.load(repo)["S-3"].title == "01b-thesis-w"
        assert forecast_of(repo) == {"S-2": "~01c", "S-4": "~02", "S-5": "~03"}
        # the target must be open or done
        n: int = len(jl(repo))
        out = refused(repo, "add", "stage", "paper-r", "--follows", "S-4")  # planned
        assert out == (
            "error: --follows S-4: S-4 (software-z) is planned and has no NN yet; "
            "follow an opened stage\n"
        ), out
        lrun(repo, "add", "stage", "05-paper-old", "--imported", "--source",
             "A:1", "--status", "shelved")  # S-6
        out = refused(repo, "add", "stage", "paper-r", "--follows", "S-6")  # shelved
        assert out == (
            "error: --follows S-6: S-6 (05-paper-old) is shelved; follow an open "
            "or done stage\n"
        ), out
        assert lrun(repo, "add", "task", "t", "--note", "n")[0] == 0  # T-1
        out = refused(repo, "add", "stage", "paper-r", "--follows", "T-1")
        assert out == "error: T-1 is a task, not a stage\n", out
        out = refused(repo, "add", "stage", "paper-r", "--follows", "S-99")
        assert out == "error: no stage 'S-99'\n", out
        assert len(jl(repo)) == n + 2  # only the import row and T-1
    with tempfile.TemporaryDirectory() as d:  # a done target is fine
        repo = new_repo(Path(d))
        lrun(repo, "add", "stage", "paper-x", "--open")  # S-1
        lrun(repo, "add", "decision", "ok", "--owner", "user", "--link", "S-1")
        code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")
        assert code == 0 and out.startswith("closed S-1"), out
        code, out = lrun(repo, "add", "stage", "software-y", "--follows", "S-1")
        assert code == 0, out
        assert L.load(repo)["S-2"].extra["follows"] == "S-1"
        assert forecast_of(repo) == {"S-2": "~01b"}


# T7 / D-28, D-34, lead Q4 Q5; red: `set --status` unknown (SystemExit 2)
def test_set_status_stage_transitions() -> None:
    table: str = (
        ": set --status takes planned -> shelved, shelved -> planned, planned "
        "or shelved -> dropped\n"
    )
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        plan_stages(repo, "paper-a", "paper-b", "paper-c")  # S-1 S-2 S-3
        assert lrun(repo, "add", "stage", "software-o", "--open")[0] == 0  # S-4
        assert lrun(repo, "add", "task", "t", "--note", "n")[0] == 0  # T-1, in S-4
        lrun(repo, "add", "stage", "05-paper-old", "--imported", "--source",
             "A:1", "--status", "shelved")  # S-5
        # planned -> shelved: the note is required and stored as `reason`
        out: str = refused(repo, "set", "S-1", "--status", "shelved")
        assert out == (
            "error: --status shelved needs --note: why (it is stored as the "
            "reason)\n"
        ), out
        why: str = "not now: waiting for data"
        code, out = lrun(repo, "set", "S-1", "--status", "shelved", "--note", why)
        assert code == 0 and out == "updated S-1: status, reason, note\n", out
        st: dict[str, Any] = L.load(repo)
        assert st["S-1"].status == "shelved" and st["S-1"].extra["reason"] == why
        ev: dict[str, Any] = jl(repo)[-1]
        assert ev["ev"] == "set" and ev["id"] == "S-1", ev
        assert ev["f"]["status"] == "shelved" and ev["f"]["reason"] == why, ev
        assert queue_ids(repo) == ["S-2", "S-3"]  # a shelved stage is out of it
        # no forecast for S-1; the base is 5 (the imported 05-paper-old counts)
        assert forecast_of(repo) == {"S-2": "~06", "S-3": "~07"}
        assert (repo / "pm/stages/P-1-paper-a").is_dir()  # folder untouched
        # shelved -> planned: no note, back at the queue end
        code, out = lrun(repo, "set", "S-1", "--status", "planned")
        assert code == 0 and out == "updated S-1: status, queue, reason\n", out
        assert L.load(repo)["S-1"].status == "planned"
        assert jl(repo)[-1]["f"]["status"] == "planned", jl(repo)[-1]
        assert jl(repo)[-1]["f"]["queue"] == "4", jl(repo)[-1]  # floor(max) + 1
        assert L.load(repo)["S-1"].extra["reason"] == ""  # the shelve's is cleared
        assert queue_ids(repo) == ["S-2", "S-3", "S-1"]
        assert forecast_of(repo) == {"S-2": "~06", "S-3": "~07", "S-1": "~08"}
        # the three refusals of the plan (text pinned), the S-n being the real id
        out = refused(repo, "set", "S-1", "--status", "open", "--note", "x")
        assert out == "error: --status open: only stage-open opens: rk stage-open S-1\n"
        for sid in ("S-1", "S-4"):
            out = refused(repo, "set", sid, "--status", "done", "--note", "x")
            assert out == (
                "error: --status done: a stage closes with its sign-off: use "
                f"stage-close {sid}\n"
            ), out
        for status in ("shelved", "planned", "dropped"):
            out = refused(repo, "set", "T-1", "--status", status, "--note", "x")
            assert out == (
                f"error: --status {status}: set gives a status to a stage only; "
                "for T-1 use close, drop, shelve or reopen\n"
            ), out
        # imported shelved -> planned (Q5), and what the table does not list
        out = refused(repo, "set", "S-5", "--status", "planned")
        assert out == (
            "error: S-5 is imported: it has no P- folder and is not planned "
            "again; drop it or plan a new stage\n"
        ), out
        for status in ("shelved", "dropped", "planned"):  # an open stage
            out = refused(repo, "set", "S-4", "--status", status, "--note", "x")
            assert out == f"error: cannot set S-4 from open to {status}{table}", out
        # planned -> dropped: note required, stored as reason, folder stays
        refused(repo, "set", "S-2", "--status", "dropped")
        code, out = lrun(repo, "set", "S-2", "--status", "dropped", "--note", "no")
        assert code == 0, out
        st = L.load(repo)
        assert st["S-2"].status == "dropped" and st["S-2"].extra["reason"] == "no"
        assert queue_ids(repo) == ["S-3", "S-1"]
        assert forecast_of(repo) == {"S-3": "~06", "S-1": "~07"}
        assert (repo / "pm/stages/P-2-paper-b").is_dir()
        # shelved -> dropped: the new reason replaces the old
        code, out = lrun(repo, "set", "S-3", "--status", "shelved", "--note", "later")
        assert code == 0, out
        code, out = lrun(repo, "set", "S-3", "--status", "dropped", "--note", "never")
        assert code == 0, out
        assert L.load(repo)["S-3"].extra["reason"] == "never"
        code, out = lrun(repo, "set", "S-5", "--status", "dropped", "--note", "old")
        assert code == 0, out  # an imported shelved stage may be dropped
        assert L.load(repo)["S-5"].status == "dropped"
        # a dropped stage does not come back
        for status in ("planned", "shelved"):
            out = refused(repo, "set", "S-2", "--status", status, "--note", "x")
            assert out == f"error: cannot set S-2 from dropped to {status}{table}"
        # `nothing to set` names the new flags
        out = refused(repo, "set", "S-1")
        assert out == (
            "error: nothing to set (give --title, --owner, --label, --stage, "
            "--status, --note, --note-replace, --link, --ref, --ref-drop, --before "
            "or --after)\n"
        ), out


# T7 / D-34 (drop refusal lists the open entries); red: `set --status` unknown
def test_drop_planned_stage_with_open_entries() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        assert lrun(repo, "add", "stage", "paper-x", "--open")[0] == 0  # S-1
        assert lrun(repo, "add", "task", "run", "--note", "n")[0] == 0  # T-1, S-1
        assert lrun(repo, "start", "T-1")[0] == 0
        plan_stages(repo, "software-p")  # S-2, folder P-2-software-p
        assert lrun(repo, "add", "debt", "flaky", "--stage", "S-2")[0] == 0  # DB-1
        moved: str = refused(repo, "set", "T-1", "--stage", "S-2")  # m4, D-32
        assert moved == (
            "error: S-2 is planned: a running task cannot go into it (work runs "
            "only in an open stage): close or shelve it first, or open the stage: "
            "rk stage-open S-2\n"
        ), moved
        assert L.load(repo)["T-1"].status == "running"
        assert lrun(
            repo, "add", "task", "next", "--note", "n", "--stage", "S-2"
        )[0] == 0  # T-2
        busy: str = (
            "error: cannot drop S-2: open entries are in it: DB-1 open, T-2 "
            "open; close, drop or re-stage each (set ID --stage S-x) first\n"
        )  # in ledger order
        out: str = refused(
            repo, "set", "S-2", "--status", "dropped", "--note", "not needed"
        )
        assert out == busy, out
        assert L.load(repo)["S-2"].status == "planned"
        # shelving is allowed with open entries; the drop is still refused
        code, out = lrun(repo, "set", "S-2", "--status", "shelved", "--note", "later")
        assert code == 0, out
        out = refused(repo, "set", "S-2", "--status", "dropped", "--note", "x")
        assert out == busy, out
        # closed or shelved entries do not block
        assert lrun(repo, "close", "DB-1", "--note", "done")[0] == 0
        assert lrun(repo, "close", "T-1", "--note", "done")[0] == 0
        assert lrun(repo, "close", "T-2", "--note", "done")[0] == 0
        assert lrun(repo, "add", "debt", "later", "--stage", "S-2")[0] == 0  # DB-2
        assert lrun(repo, "shelve", "DB-2", "--note", "later")[0] == 0
        folders: dict[str, bytes | None] = snapshot(repo / "pm" / "stages")
        code, out = lrun(repo, "set", "S-2", "--status", "dropped", "--note", "gone")
        assert code == 0, out
        st: dict[str, Any] = L.load(repo)
        assert st["S-2"].status == "dropped" and st["S-2"].extra["reason"] == "gone"
        assert snapshot(repo / "pm" / "stages") == folders  # waste step is later
        assert (repo / "pm/stages/P-2-software-p").is_dir()


# T11, D-41/D-42: open stage: folder, refs, receipt; red: stage-rename unknown
def test_stage_rename_open() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        assert lrun(repo, "add", "stage", "paper-x", "--open")[0] == 0  # 01-paper-x
        old: str = "pm/stages/01-paper-x"
        new: str = "pm/stages/01-paper-y"
        (repo / old / "notes/a.md").write_text("a")
        (repo / "keep.md").write_text("k")
        code, out = lrun(
            repo, "add", "debt", "d", "--owner", "lead",
            "--ref", f"{old}/notes/a.md", "--ref", "keep.md",
        )  # fmt: skip
        assert code == 0, out  # DB-1, in S-1
        assert L._renamed_title(L.load(repo)["S-1"], "paper-y") == "01-paper-y"
        n: int = len(jl(repo))
        code, out = lrun(repo, "stage-rename", "S-1", "paper-y")
        assert code == 0 and out.splitlines() == [
            "renamed S-1: 01-paper-x -> 01-paper-y",
            f"folder {old}/ -> {new}/",
            "refs: 2 rewritten",  # the stage's own ref and the debt's: every ref
        ], out
        st: Any = L.load(repo)
        assert st["S-1"].status == "open" and st["S-1"].title == "01-paper-y"
        assert st["S-1"].refs == [f"{new}/"], st["S-1"].refs
        assert st["DB-1"].refs == [f"{new}/notes/a.md", "keep.md"], st["DB-1"].refs
        assert not (repo / old).exists()
        assert (repo / new / "notes/a.md").read_text() == "a"
        assert sorted(p.name for p in (repo / new).iterdir()) == sorted(L.STAGE_DIRS)
        evs: list[dict[str, Any]] = jl(repo)[n:]  # one set on the stage, one per entry
        by_id: dict[str, dict[str, Any]] = {e["id"]: e for e in evs}
        assert sorted(by_id) == ["DB-1", "S-1"] and len(evs) == 2, evs
        assert all(e["ev"] == "set" for e in evs), evs
        assert set(by_id["S-1"]["f"]) == {"title", "refs"}, evs  # no status change
        assert list(by_id["DB-1"]["f"]) == ["refs"], evs
        commit_all(repo)
        code, out = doctor(repo)
        assert code == 0 and "HARD" not in out, out
        sign_off_close(repo, "S-1")  # a letter stays: 01b-paper-w -> 01b-paper-v
        rec: str = (repo / new / "LEDGER.md").read_text()  # renamed before the close
        assert rec.startswith("# Ledger of stage S-1 01-paper-y (generated)\n\n"), rec
        assert "renamed to" not in rec, rec  # D-43: no line
        code, out = lrun(repo, "add", "stage", "paper-w", "--open", "--follows", "S-1")
        assert code == 0 and out.startswith("logged S-2: 01b-paper-w\n"), out
        code, out = lrun(repo, "stage-rename", "S-2", "paper-v")
        assert code == 0 and out.splitlines()[:2] == [
            "renamed S-2: 01b-paper-w -> 01b-paper-v",
            "folder pm/stages/01b-paper-w/ -> pm/stages/01b-paper-v/",
        ], out


# T11, D-41/D-34: planned stage: P-<n> stays, queue and status untouched; red: same
def test_stage_rename_planned() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        for title in ("paper-scan", "paper-draft"):  # S-1, S-2: queue "1", "2"
            assert lrun(repo, "add", "stage", title)[0] == 0
        old: str = "pm/stages/P-1-paper-scan"
        new: str = "pm/stages/P-1-paper-survey"
        (repo / old / "notes/a.md").write_text("a")
        code, out = lrun(
            repo, "add", "debt", "d", "--owner", "lead", "--stage", "S-1",
            "--ref", f"{old}/notes/a.md",
        )  # fmt: skip
        assert code == 0, out
        assert L._renamed_title(L.load(repo)["S-1"], "paper-survey") == "paper-survey"
        n: int = len(jl(repo))
        code, out = lrun(repo, "stage-rename", "S-1", "paper-survey")
        assert code == 0 and out.splitlines() == [
            "renamed S-1: paper-scan -> paper-survey",
            f"folder {old}/ -> {new}/",
            "refs: 2 rewritten",
        ], out
        st: Any = L.load(repo)
        assert st["S-1"].title == "paper-survey" and st["S-1"].status == "planned"
        assert st["S-1"].extra["queue"] == "1" and st["S-2"].extra["queue"] == "2"
        assert st["S-1"].refs == [f"{new}/"], st["S-1"].refs
        assert st["DB-1"].refs == [f"{new}/notes/a.md"], st["DB-1"].refs
        assert not (repo / old).exists()
        assert (repo / new / "notes/a.md").read_text() == "a"
        assert set(jl(repo)[n]["f"]) == {"title", "refs"}, jl(repo)[n]
        assert lrun(repo, "show", "paper-survey")[1].startswith("id: S-1\n")
        code, out = lrun(repo, "stage-rename", "S-2", "software-draft")  # kind free
        assert code == 0 and out.splitlines()[:2] == [
            "renamed S-2: paper-draft -> software-draft",
            "folder pm/stages/P-2-paper-draft/ -> pm/stages/P-2-software-draft/",
        ], out
        assert (repo / "pm/stages/P-2-software-draft").is_dir()
        assert L.load(repo)["S-2"].extra["queue"] == "2"


# T11, D-42: done stage needs --note; record rewritten; red: stage-rename unknown
def test_stage_rename_done() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        repo: Path = new_repo(root)
        assert lrun(repo, "add", "stage", "paper-x", "--open")[0] == 0  # 01-paper-x
        old: str = "pm/stages/01-paper-x"
        new: str = "pm/stages/01-paper-y"
        (repo / old / "notes/a.md").write_text("a")
        code, out = lrun(
            repo, "add", "debt", "d", "--owner", "lead", "--ref", f"{old}/notes/a.md"
        )
        assert code == 0, out
        sign_off_close(repo, "S-1")
        before: dict[str, bytes | None] = snapshot(root)
        code, out = lrun(repo, "stage-rename", "S-1", "paper-y")
        assert code == 1 and out == (
            "error: S-1 is done: renaming a closed stage needs --note: why (text "
            "outside the ledger keeps the old path)\n"
        ), out  # a done stage: the cost is said
        assert snapshot(root) == before
        n: int = len(jl(repo))
        code, out = lrun(
            repo, "stage-rename", "S-1", "paper-y", "--note", "topic was wrong"
        )
        assert code == 0 and out.splitlines() == [
            "renamed S-1: 01-paper-x -> 01-paper-y",
            f"folder {old}/ -> {new}/",
            "refs: 2 rewritten",
            f"wrote {new}/LEDGER.md",
        ], out
        st: Any = L.load(repo)
        assert st["S-1"].status == "done" and st["S-1"].title == "01-paper-y"
        assert st["DB-1"].refs == [f"{new}/notes/a.md"]
        ev: dict[str, Any] = next(e for e in jl(repo)[n:] if e["id"] == "S-1")
        assert set(ev["f"]) == {"title", "refs", "note"}, ev  # the note: a new line
        assert st["S-1"].note.endswith("\ntopic was wrong"), st["S-1"].note
        assert not (repo / old).exists() and (repo / new / "notes/a.md").is_file()
        rec: Path = repo / new / "LEDGER.md"
        text: str = rec.read_text()
        assert text == L.render_stage_record(L.read_events(repo), "S-1"), text
        commit_all(repo)
        code, out = doctor(repo)
        assert code == 0 and "HARD" not in out, out
        stable: dict[str, bytes | None] = snapshot(root)
        code, out = lrun(repo, "stage-close", "S-1")  # the record is current
        assert code == 1 and "S-1 is done, not open" in out, out
        assert snapshot(root) == stable  # byte-stable: nothing rewritten
        # D-43: head and body as of the close, plus one line for the rename
        day: str = ev["ts"][:10]
        assert text.startswith(
            "# Ledger of stage S-1 01-paper-x (generated)\n"
            f"renamed to 01-paper-y on {day}\n\n"
        ), text
        assert text.count("renamed to") == 1, text
        # a second rename after the close: still one line, the last title
        code, out = lrun(repo, "stage-rename", "S-1", "paper-z", "--note", "again")
        assert code == 0, out
        evs2: list[dict[str, Any]] = [e for e in jl(repo) if e["id"] == "S-1"]
        last: str = evs2[-1]["ts"][:10]  # the date of the last title change
        rec = repo / "pm/stages/01-paper-z/LEDGER.md"
        text = rec.read_text()
        assert text == L.render_stage_record(L.read_events(repo), "S-1"), text
        assert text.startswith(
            "# Ledger of stage S-1 01-paper-x (generated)\n"
            f"renamed to 01-paper-z on {last}\n\n"
        ), text
        assert text.count("renamed to") == 1, text
        commit_all(repo)
        code, out = doctor(repo)
        assert code == 0 and "HARD" not in out, out
        stable = snapshot(root)
        code, out = lrun(repo, "stage-close", "S-1")  # current: byte-stable
        assert code == 1 and "S-1 is done, not open" in out, out
        assert snapshot(root) == stable
        # a record written before the rename (no line) is not current: rewritten
        rec.write_text(text.replace(f"renamed to 01-paper-z on {last}\n", ""))
        code, out = lrun(repo, "stage-close", "S-1")
        assert code == 0 and "wrote pm/stages/01-paper-z/LEDGER.md" in out, out
        assert rec.read_text() == text


# T11, D-41/D-42: each refusal names its reason and changes nothing; red: same
def test_stage_rename_refusals() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        repo: Path = new_repo(root)
        stages: Path = repo / "pm/stages"

        def refuse(argv: list[str], want: str) -> None:
            """Refused with code 1 and exactly `want`, nothing changed."""
            before: dict[str, bytes | None] = snapshot(root)
            code, out = lrun(repo, *argv)
            assert code == 1 and out == f"error: {want}\n", (argv, out)
            assert snapshot(root) == before, argv

        code, out = lrun(repo, "add", "stage", "old", "--imported", "--source", "a:1")
        assert code == 0 and out == "logged S-1: old\n", out
        for argv in (
            ["add", "stage", "paper-a", "--open"],  # S-2 01-paper-a
            ["add", "stage", "software-b"],  # S-3 planned
            ["add", "stage", "paper-c"],  # S-4 planned
            ["add", "stage", "software-d", "--open"],  # S-5 02-software-d
        ):
            assert lrun(repo, *argv)[0] == 0, argv
        refuse(  # legacy path: frozen
            ["stage-rename", "S-1", "paper-z"],
            "S-1 is imported: its folder is a legacy path and keeps its name",
        )
        refuse(
            ["stage-rename", "S-2", "paper-a"],
            "S-2 is named 01-paper-a already: nothing to rename",
        )
        for sid, bad in (
            ("S-2", "03-paper-x"), ("S-2", "paper"), ("S-3", "03-paper-x")
        ):
            refuse(  # planned too
                ["stage-rename", sid, bad],
                f"stage-rename {sid} '{bad}': want <kind>-<topic>, e.g. paper-scan "
                "(letters, digits, _ . - in the topic); the NN or P-<n> stays",
            )
        refuse(  # a name clash: the existing _check_names text
            ["stage-rename", "S-3", "paper-c"],
            "stage 'paper-c': 'paper-c' already names S-4 (paper-c); stage codes, "
            "stage titles and labels are unique",
        )
        refuse(  # kind change onto a kind with an open stage
            ["stage-rename", "S-2", "software-e"],
            "cannot stage-rename S-2: S-5 (02-software-d) is open, and at most one "
            "software stage may be open: stage-close S-5 first",
        )
        (stages / "01-paper-z").mkdir()  # the target folder exists: no merge
        refuse(
            ["stage-rename", "S-2", "paper-z"],
            "cannot stage-rename S-2: pm/stages/01-paper-z/ is there already; "
            "folders are not merged: move it away first",
        )
        (stages / "01-paper-z").rmdir()
        (stages / "01-paper-a").rename(root / "moved")  # the source folder is missing
        refuse(
            ["stage-rename", "S-2", "paper-z"],
            "cannot stage-rename S-2: no folder pm/stages/01-paper-a/; restore it "
            "first",
        )
        (root / "moved").rename(stages / "01-paper-a")
        code, out = lrun(repo, "set", "S-4", "--status", "dropped", "--note", "x")
        assert code == 0, out
        refuse(
            ["stage-rename", "S-4", "paper-q"],
            "S-4 is dropped: a dropped or superseded stage is not renamed",
        )
        code, out = lrun(repo, "stage-rename", "S-2", "paper-z")  # only those reasons
        assert code == 0, out
        assert out.startswith("renamed S-2: 01-paper-a -> 01-paper-z\n"), out


# T11, D-33 (rename undone on a failure before the ledger line is written;
# injection as in T4; after it: test_stage_rename_failure_after_write): red: same
def test_stage_rename_rolls_back() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        assert lrun(repo, "add", "stage", "paper-x", "--open")[0] == 0  # 01-paper-x
        old: Path = repo / "pm/stages/01-paper-x"
        (old / "notes/a.md").write_text("a")
        code, out = lrun(
            repo, "add", "debt", "d", "--owner", "lead",
            "--ref", "pm/stages/01-paper-x/notes/a.md",
        )  # fmt: skip
        assert code == 0, out
        before: dict[str, bytes | None] = snapshot(Path(d))
        real: Any = L.fold

        def fold_fails_after_rename(events: Any) -> Any:
            """append folds the new lines before it writes them; at that point the
            folder has been renamed: a failure after the rename, before the write."""
            if not old.exists():
                raise OSError(28, "injected: no space left on device")
            return real(events)

        L.fold = fold_fails_after_rename
        try:
            try:
                code, out = lrun(repo, "stage-rename", "S-1", "paper-y")
            except OSError:  # re-raised, as in stage-open
                pass
            else:
                raise AssertionError(f"no OSError: {code} {out}")
        finally:
            L.fold = real
        assert snapshot(Path(d)) == before  # folder and file back, ledger as was
        assert (old / "notes/a.md").read_text() == "a"
        assert not (repo / "pm/stages/01-paper-y").exists()
        assert L.load(repo)["S-1"].title == "01-paper-x"
        code, out = lrun(repo, "stage-rename", "S-1", "paper-y")  # a retry works
        assert code == 0 and out.startswith("renamed S-1: 01-paper-x -> 01-paper-y\n")


# W1 T10, DB-29 / spec "Done when" 4: the user's case end to end through the CLI
def test_db29_probe() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        p: str = "pm/stages/P-1-paper-scan"
        code, out = lrun(repo, "add", "stage", "paper-scan")  # S-1, planned
        assert code == 0 and out.startswith("logged S-1: paper-scan (planned)\n"), out
        (repo / p / "notes/a.md").write_text("a")
        code, out = lrun(repo, "add", "debt", "d", "--stage", "S-1", "--ref",
                         f"{p}/notes/a.md")  # DB-1, in the planned stage
        assert code == 0 and out == "logged DB-1: d (stage S-1)\n", out
        code, out = lrun(repo, "add", "task", "t", "--note", "n", "--stage", "S-1")
        assert code == 0 and out == "logged T-1: t (stage S-1)\n", out
        n: int = len(jl(repo))
        code, out = lrun(repo, "start", "T-1")  # not in a planned stage
        assert code == 1 and out == (
            "error: stage S-1 is planned: rk stage-open S-1 first\n"
        ), out
        assert len(jl(repo)) == n
        commit_all(repo)
        assert doctor(repo)[0] == 0
        code, out = lrun(repo, "add", "stage", "paper-draft", "--before", "S-1")
        assert code == 0 and out.startswith("logged S-2: paper-draft (planned)\n")
        assert queue_ids(repo) == ["S-2", "S-1"]
        assert forecast_of(repo) == {"S-2": "~01", "S-1": "~02"}
        n = len(jl(repo))
        code, out = lrun(repo, "add", "stage", "software-tool", "--open")  # between
        assert code == 0 and out.startswith("logged S-3: 01-software-tool\n"), out
        assert [(e["ev"], e["id"]) for e in jl(repo)[n:]] == [("add", "S-3")]
        assert forecast_of(repo) == {"S-2": "~02", "S-1": "~03"}  # shifted, unwritten
        commit_all(repo)
        assert doctor(repo)[0] == 0
        code, out = lrun(repo, "stage-open", "S-1")  # later: the next free NN
        assert code == 0 and out == (
            "opened S-1: 02-paper-scan\n"
            f"folder {p}/ -> pm/stages/02-paper-scan/\n"
            "refs: 2 rewritten\n"
        ), out
        st: Any = L.load(repo)
        assert (st["S-1"].status, st["S-1"].title) == ("open", "02-paper-scan")
        assert st["DB-1"].stage == "S-1" and st["T-1"].stage == "S-1"
        assert st["DB-1"].refs == ["pm/stages/02-paper-scan/notes/a.md"]
        assert (repo / "pm/stages/02-paper-scan/notes/a.md").read_text() == "a"
        assert not (repo / p).exists()
        assert forecast_of(repo) == {"S-2": "~03"}
        assert lrun(repo, "start", "T-1") == (0, "started T-1: t\n")
        commit_all(repo)
        code, out = doctor(repo)
        assert code == 0 and "HARD" not in out, out


def test_reopen_stage_without_folder() -> None:  # brief 025 fix 4
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "stage", "01-pilot", "--imported", "--source", "A.md:1")
        lrun(repo, "add", "decision", "ok", "--owner", "user", "--link", "S-1")
        assert lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")[0] == 0
        n: int = len(jl(repo))
        code, out = lrun(repo, "reopen", "S-1", "--note", "x")
        assert code == 1 and out == (
            "error: cannot reopen S-1: no folder pm/stages/01-pilot/ (an imported "
            "or folderless stage); restore it or add a new stage\n"
        ), out
        assert len(jl(repo)) == n and L.load(repo)["S-1"].status == "done"
        (repo / "pm/stages/01-pilot").mkdir(parents=True)  # restored: reopens
        assert lrun(repo, "reopen", "S-1", "--note", "x")[0] == 0


def test_record_recognised_by_mark() -> None:  # brief 025 fix 5
    with tempfile.TemporaryDirectory() as d:
        repo: Path = reopened_repo(Path(d))
        lrun(repo, "stage-close", "S-1", "--sign-off", "D-2")
        rec: Path = repo / "pm/stages/01-paper-x/LEDGER.md"
        text: str = rec.read_text()
        # a later kit may word the Window line otherwise: the mark still holds
        other: str = text.replace("Window: ledger lines", "Window (lines)")
        rec.write_text(other)
        code, out = lrun(repo, "stage-close", "S-1")
        assert code == 1 and "S-1 is done, not open" in out, out
        assert rec.read_text() == other  # recognised: not rewritten
        # a 0.2.3 record of the last close: no mark, Window from add to close
        events: list[tuple[int, dict[str, object]]] = L.read_events(repo)
        st: Any = L.fold(events)["S-1"]
        old: str = "\n".join([
            text.split("\n", 1)[0], "",
            f"Window: ledger lines 1 to 9, {st.created} to {st.updated}.", "",
        ])
        rec.write_text(old)
        code, out = lrun(repo, "stage-close", "S-1")
        assert code == 1 and "S-1 is done, not open" in out, out
        assert rec.read_text() == old  # recognised by the old match
        rec.write_text(old.replace("1 to 9", "1 to 5"))  # of the first close
        code, out = lrun(repo, "stage-close", "S-1")
        assert code == 0 and rec.read_text() == text, out  # stale: rewritten


def test_doctor_no_git() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = staged_repo(Path(d))
        code, out = doctor(repo)
        assert code == 0, out
        assert out.splitlines()[0] == "git: not a git repo; git checks skipped", out
        with env(PATH=str(Path(d) / "nobin")):
            out = doctor(repo)[1]
        assert out.splitlines()[0] == "git: no git binary; git checks skipped", out


def test_doctor_entries_without_stage() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "task", "before", "--note", "n")
        lrun(repo, "add", "stage", "paper-x", "--open")
        lrun(repo, "add", "stage", "software-y", "--open")  # two open: no default stage
        lrun(repo, "add", "task", "inside", "--note", "n")
        lrun(repo, "add", "task", "staged", "--note", "n", "--stage", "S-1")
        lrun(repo, "add", "task", "imp", "--imported", "--source", "A:1")
        g: str = L.G_NOSTAGE
        assert g.endswith(" (set ID --stage S-n)"), g  # the heading names the fix
        both: list[str] = ["T-2 (S-2, S-1) inside"]  # two open: both, S-2 first
        assert group(doctor(repo)[1], g) == both
        assert group(doctor(repo, "--stage", "S-1")[1], g) == both
        assert group(doctor(repo, "--stage", "S-2")[1], g) == both
        late: str = L.G_LATE
        assert "(set ID --stage S-n;" in late, late
        assert group(doctor(repo)[1], late) == []
        lrun(repo, "set", "T-2", "--stage", "S-1")
        lrun(repo, "close", "T-2", "--note", "ok")
        lrun(repo, "close", "T-3", "--note", "ok")
        for k in (1, 2):
            lrun(repo, "add", "decision", f"ok{k}", "--owner", "user",
                 "--link", f"S-{k}", "--stage", f"S-{k}")
            lrun(repo, "stage-close", f"S-{k}", "--sign-off", f"D-{k}")
        lrun(repo, "add", "debt", "found late")  # no stage open: no stage
        lrun(repo, "add", "stage", "paper-z", "--open")
        lrun(repo, "add", "debt", "in S-3")  # the default stage again
        out: str = doctor(repo)[1]
        assert group(out, g) == [] and group(out, late) == [
            "DB-1 (after S-2) found late"
        ], out
        assert group(doctor(repo, "--stage", "S-2")[1], late) == [
            "DB-1 (after S-2) found late"
        ]


def test_doctor_running_over_24h() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "task", "slow", "--note", "n")
        lrun(repo, "add", "task", "fast", "--note", "n")
        old: str = (datetime.now().astimezone() - timedelta(hours=30)).isoformat()
        ev: dict[str, object] = L.make_event(
            "lead", "set", "T-1", {"status": "running"}
        )
        ev["ts"] = old
        with (repo / L.LEDGER_REL).open("a") as fh:
            fh.write(json.dumps(ev) + "\n")
        lrun(repo, "start", "T-2")
        out: str = doctor(repo)[1]
        assert group(out, L.G_RUNNING) == ["T-1 (lead, 1d) slow"], out


def test_doctor_imported_missing_refs_counted() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        repo: Path = new_repo(root)
        rows: Path = write_rows(root, [
            {"type": "task", "title": f"i{k}", "source": f"A:{k}",
             "ref": [f"gone{k}.md", "https://x.org"]}
            for k in range(3)
        ])  # fmt: skip
        lrun(repo, "import", str(rows))
        code, out = doctor(repo)
        assert code == 0, out
        assert group(out, L.G_IMPORTED) == [
            "3 refs of 3 imported entries missing, e.g. T-1 gone0.md"
        ], out


def test_doctor_stamps_behind() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        kit: str | None = L._line1_stamp(L.TEMPLATE_DIR / "AGENTS.md")
        kpaper: str | None = L._line1_stamp(L.TEMPLATE_DIR / "kinds/paper.md")
        (repo / "AGENTS.md").write_text("<!-- research-kit: 2000-01-01a -->\n")
        (repo / "pm/kinds/paper.md").write_text(
            "<!-- research-kit-kind paper: 2000-01-01a -->\n"
        )
        (repo / "pm/kinds/software.md").write_text(
            "<!-- research-kit-kind software: 9999-01-01a -->\n"  # ahead: fine
        )
        (repo / "pm/kinds/own.md").write_text(
            "<!-- research-kit-kind own: 2000-01-01a -->\n"  # no template: skipped
        )
        out: str = doctor(repo)[1]
        assert group(out, "rule file behind the kit (run /rk-sync)") == [
            f"AGENTS.md 2000-01-01a, kit {kit}",
            f"pm/kinds/paper.md 2000-01-01a, kit {kpaper}",
        ], out


def test_doctor_stage_decisions_for_sign_off() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = staged_repo(Path(d))
        lrun(repo, "add", "decision", "scope cut", "--owner", "lead",
             "--link", "D-1", "--link", "T-1")
        lrun(repo, "add", "decision", "metric", "--owner", "sr1")
        g: str = "decisions of the stage not owned by user (for the sign-off)"
        out: str = doctor(repo, "--stage", "S-1")[1]
        assert group(out, g) == [
            "D-2 (lead; links D-1) scope cut", "D-3 (sr1) metric"
        ], out
        assert group(doctor(repo)[1], g) == []  # stage view only


def test_doctor_group_cap() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        (repo / "r.md").write_text("x")
        for k in range(23):
            lrun(repo, "add", "task", f"t{k}", "--note", "n", "--ref", "r.md")
        (repo / "r.md").rename(Path(d) / "moved.md")
        code, out = doctor(repo)
        lines: list[str] = group(out, "missing ref")
        assert code == 1 and len(lines) == 21, out
        assert lines[-1] == "+3 more (all: --limit 0)", out
        assert out.splitlines()[1] == "HARD missing ref (23)", out
        code, out = doctor(repo, "--limit", "0")
        assert code == 1 and len(group(out, "missing ref")) == 23, out
        assert len(group(doctor(repo, "--limit", "5")[1], "missing ref")) == 6
        assert doctor(repo, "--limit", "-1")[0] == 1


def test_stage_close_runs_stage_checks() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = staged_repo(Path(d))
        (repo / "r.md").write_text("x")
        lrun(repo, "close", "T-1", "--note", "ok", "--ref", "r.md")
        lrun(repo, "add", "decision", "cut", "--owner", "lead")
        (repo / "r.md").rename(Path(d) / "moved.md")
        n: int = len(jl(repo))
        code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")
        assert code == 1 and group(out, "missing ref") == ["T-1 r.md"], out
        assert "stage-close S-1 refused: 1 HARD finding(s) above" in out, out
        assert "--ref-drop" in out and len(jl(repo)) == n, out
        lrun(repo, "set", "T-1", "--ref-drop", "r.md")
        folder: Path = repo / "pm/stages/01-paper-x"
        folder.rename(Path(d) / "moved")
        code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")
        assert code == 1 and "missing stage folder" in out, out
        assert len(jl(repo)) == n + 1, out
        (Path(d) / "moved").rename(folder)
        code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")
        assert code == 0 and CLOSED_D1 in out, out
        assert "SOFT decisions of the stage not owned by user" in out, out
        assert "D-2 (lead) cut" in out, out


def test_doctor_start() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        kit: str = f"kit {L.kit_version()}"
        bare: Path = root / "bare"  # no ledger anywhere above: kit line only
        bare.mkdir()
        cwd: Path = Path.cwd()
        buf: io.StringIO = io.StringIO()
        try:
            os.chdir(bare)
            with contextlib.redirect_stdout(buf), env(PATH=str(root / "nobin")):
                code: int = L.main(["doctor", "--start"])
        finally:
            os.chdir(cwd)
        assert code == 0 and buf.getvalue() == f"{kit}\n", buf.getvalue()
        repo: Path = new_repo(root)
        code, out = lrun(repo, "doctor", "--start")
        assert code == 0 and out == f"{kit}\n", out
        (repo / "AGENTS.md").write_text("<!-- research-kit: 2000-01-01a -->\n")
        (repo / "pm/kinds/paper.md").write_text(
            "<!-- research-kit-kind paper: 2000-01-01a -->\n"
        )
        (repo / L.LEDGER_REL).write_text("{torn\n")  # no fold: still fine
        code, out = lrun(repo, "doctor", "--start")
        a_kit: str | None = L._line1_stamp(L.TEMPLATE_DIR / "AGENTS.md")
        p_kit: str | None = L._line1_stamp(L.TEMPLATE_DIR / "kinds/paper.md")
        assert code == 0 and out.splitlines() == [  # two behind: both shown
            kit,
            f"AGENTS.md 2000-01-01a, kit {a_kit}: run /rk-sync",
            f"pm/kinds/paper.md 2000-01-01a, kit {p_kit}: run /rk-sync",
        ], out
        for k in ("software", "thesis"):
            (repo / f"pm/kinds/{k}.md").write_text(
                f"<!-- research-kit-kind {k}: 2000-01-01a -->\n"
            )
        code, out = lrun(repo, "doctor", "--start")
        assert code == 0 and out.splitlines() == [  # more: still 3 lines (hook)
            kit,
            f"AGENTS.md 2000-01-01a, kit {a_kit}: run /rk-sync",
            "+3 more: rk doctor",
        ], out


# ---- reref, ref fixes in closed stages, compatibility (plan G1, G6, T5, T6) --


def reref_repo(root: Path) -> Path:
    """Refs into pm/waste/team/03b/ on an imported entry, a done task of a done
    stage, an open task of that done stage, and one ref with OLD in the middle."""
    repo: Path = new_repo(root)
    old: Path = repo / "pm/waste/team/03b"
    old.mkdir(parents=True)
    for name in ("a.md", "b.md", "c.md"):
        (old / name).write_text(name)
    (repo / "keep/pm/waste/team/03b").mkdir(parents=True)
    (repo / "keep/pm/waste/team/03b/a.md").write_text("x")
    lrun(repo, "add", "task", "imp", "--imported", "--source", "A:1",
         "--ref", "pm/waste/team/03b/a.md", "--status", "done")
    lrun(repo, "add", "stage", "paper-scan", "--open")
    lrun(repo, "add", "task", "done one", "--note", "n",
         "--ref", "pm/waste/team/03b/b.md", "--ref", "keep/pm/waste/team/03b/a.md")
    lrun(repo, "add", "debt", "open one", "--ref", "pm/waste/team/03b/c.md")
    lrun(repo, "close", "T-2", "--note", "ok")
    lrun(repo, "add", "decision", "ok", "--owner", "user", "--link", "S-1")
    code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")
    assert code == 0, out  # DB-1 stays open in the done stage
    return repo


def test_reref() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = reref_repo(Path(d))
        new: str = "pm/stages/01-paper-scan/notes/team/"
        n: int = len(jl(repo))
        code, out = lrun(repo, "reref", "pm/waste/team/03b/", new)
        assert code == 1 and "reref refused, nothing written: 3 new path" in out, out
        assert f"T-1 {new}a.md" in out and len(jl(repo)) == n, out
        (repo / new).mkdir(parents=True)
        for name in ("a.md", "b.md", "c.md"):
            (repo / "pm/waste/team/03b" / name).rename(repo / new / name)
        code, out = lrun(repo, "reref", "pm/waste/team/03b/", new, "--dry-run")
        assert code == 0 and out.endswith(
            "would change 3 refs of 3 entries (dry run, nothing written)\n"
        ), out
        assert len(jl(repo)) == n
        code, out = lrun(repo, "reref", "pm/waste/team/03b/", new)
        assert code == 0 and out.splitlines() == [
            f"T-1 pm/waste/team/03b/a.md -> {new}a.md",
            f"T-2 pm/waste/team/03b/b.md -> {new}b.md",
            f"DB-1 pm/waste/team/03b/c.md -> {new}c.md",
            "changed 3 refs of 3 entries",
        ], out
        evs: list[dict[str, Any]] = jl(repo)[n:]
        assert [(e["ev"], e["id"], list(e["f"])) for e in evs] == [
            ("set", "T-1", ["refs"]),
            ("set", "T-2", ["refs"]),
            ("set", "DB-1", ["refs"]),
        ], evs
        st: dict[str, Any] = L.load(repo)
        assert st["T-1"].refs == [f"{new}a.md"] and st["T-1"].status == "done"
        assert st["T-2"].refs == [f"{new}b.md", "keep/pm/waste/team/03b/a.md"]
        assert st["DB-1"].refs == [f"{new}c.md"] and st["DB-1"].status == "open"
        assert st["DB-1"].stage == "S-1"
        assert st["S-1"].status == "done"
        n = len(jl(repo))
        code, out = lrun(repo, "reref", "pm/waste/team/03b/", new)
        assert code == 0 and out == (
            "no ref starts with 'pm/waste/team/03b/'; nothing written\n"
        ), out
        assert len(jl(repo)) == n
        assert lrun(repo, "reref", "", new)[0] == 1


def test_ref_fix_on_imported_and_done_stage() -> None:
    """Plan G6: --ref-drop X --ref Y in one call on an imported entry and on an
    open entry of a done stage."""
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        for name in ("x.md", "y.md"):
            (repo / name).write_text(name)
        lrun(repo, "add", "task", "imp", "--imported", "--source", "A:1",
             "--ref", "gone.md")
        lrun(repo, "add", "stage", "paper-x", "--open")
        lrun(repo, "add", "debt", "left open", "--ref", "x.md")
        lrun(repo, "add", "decision", "ok", "--owner", "user", "--link", "S-1")
        assert lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")[0] == 0
        st: dict[str, Any] = L.load(repo)
        assert st["DB-1"].status == "open" and st["DB-1"].stage == "S-1"
        assert st["S-1"].status == "done"
        for eid, old in (("T-1", "gone.md"), ("DB-1", "x.md")):
            code, out = lrun(repo, "set", eid, "--ref-drop", old, "--ref", "y.md")
            assert code == 0 and out.startswith(f"updated {eid}: refs ("), (eid, out)
            assert L.load(repo)[eid].refs == ["y.md"], eid


# A ledger as the previous released tool (0.1.8, commit 05bf026) wrote it: no
# kit / sid / rules keys. Add one such fixture per release (plan T6).
COMPAT_0_1_8: list[dict[str, object]] = [
    {"ts": "2026-11-13T12:00:00+01:00", "who": "lead", "ev": "add", "id": "S-1",
     "f": {"type": "stage", "title": "01-paper-old", "status": "done",
           "owner": "lead", "stage": "", "note": "", "links": [], "refs": [],
           "imported": True, "source": "TASKS.md:1"}},
    {"ts": "2026-11-13T12:00:01+01:00", "who": "lead", "ev": "add", "id": "H-1",
     "f": {"type": "handoff", "title": "moved handoff", "status": "open",
           "owner": "lead", "stage": "", "note": "",
           "links": [], "refs": ["pm/handoffs/open/gone.md"], "imported": True,
           "source": "handoffs.jsonl:1"}},
    {"ts": "2026-11-13T12:10:00+01:00", "who": "lead", "ev": "add", "id": "T-1",
     "f": {"type": "task", "title": "migration", "status": "open", "owner": "lead",
           "stage": "", "note": "", "links": [],
           "refs": ["pm/waste/team/run1/sr1-r1.md"]}},
    {"ts": "2026-11-13T14:00:00+01:00", "who": "lead", "ev": "add", "id": "S-2",
     "f": {"type": "stage", "title": "02-paper-new", "status": "open",
           "owner": "lead", "stage": "", "note": "", "links": [], "refs": []}},
    {"ts": "2026-11-13T14:01:00+01:00", "who": "lead", "ev": "add", "id": "T-2",
     "f": {"type": "task", "title": "scan", "status": "open", "owner": "sr1",
           "stage": "S-2", "note": "", "links": [], "refs": []}},
    {"ts": "2026-11-13T14:02:00+01:00", "who": "hook", "ev": "set", "id": "T-2",
     "f": {"status": "running"}},
    {"ts": "2026-11-13T15:00:00+01:00", "who": "lead", "ev": "set", "id": "T-2",
     "f": {"status": "done", "note": "ok", "refs": ["pm/waste/team/02/sr1-r1.md"]}},
    {"ts": "2026-11-13T16:00:00+01:00", "who": "lead", "ev": "add", "id": "D-1",
     "f": {"type": "decision", "title": "sign-off", "status": "done",
           "owner": "user", "stage": "S-2", "note": "", "links": ["S-2"],
           "refs": []}},
    {"ts": "2026-11-13T16:01:00+01:00", "who": "lead", "ev": "set", "id": "S-2",
     "f": {"status": "done", "note": "closed; sign-off D-1",
           "links": ["D-1"]}},
    {"ts": "2026-11-13T17:00:00+01:00", "who": "lead", "ev": "add", "id": "T-3",
     "f": {"type": "task", "title": "chat archive", "status": "done",
           "owner": "lead", "stage": "", "note": "", "links": [], "refs": []}},
]  # fmt: skip


def test_compat_emptied_waste_is_soft() -> None:
    """crit6 B2: refs an older kit wrote into pm/waste/team/, after the user
    emptied pm/waste/: SOFT, own group; stage-close is not refused. A missing
    ref elsewhere stays HARD."""
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        open_stage: list[dict[str, object]] = [  # S-2 still open, T-2 closed in it
            e for e in COMPAT_0_1_8
            if not (e["id"] == "S-2" and e["ev"] == "set") and e["id"] != "T-3"
        ]
        (repo / L.LEDGER_REL).write_text(
            "".join(json.dumps(e) + "\n" for e in open_stage)
        )
        (repo / "pm/stages/02-paper-new/notes").mkdir(parents=True)
        code, out = doctor(repo)  # no waste folder at all: emptied by the user
        assert code == 0 and "HARD" not in out, out
        assert group(out, L.G_WASTE_GONE) == [
            "T-1 pm/waste/team/run1/sr1-r1.md", "T-2 pm/waste/team/02/sr1-r1.md"
        ], out
        code, out = lrun(repo, "stage-close", "S-2", "--sign-off", "D-1")
        assert code == 0 and "\nclosed S-2: sign-off D-1\nwrote " in out, out
        assert "SOFT ref into the waste folder, file gone" in out, out
        (repo / "x.md").write_text("x")
        lrun(repo, "add", "task", "new", "--note", "n", "--ref", "x.md")
        (repo / "x.md").rename(Path(d) / "moved.md")
        code, out = doctor(repo)
        assert code == 1 and group(out, "missing ref") == ["T-3 x.md"], out
        for ref in ("./pm/waste/team/02/sr1-r1.md", "pm/waste/../waste/team/x.md"):
            assert L._waste(ref), ref  # compared after normpath


def test_ref_forms() -> None:
    """crit6 m2, m4, m10: empty and ../ refs refused, DOI:/arXiv: pass, an old
    bad ref can still be dropped, long ref lines are clipped."""
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "task", "t", "--note", "n")
        for bad in ("", "../x.md", "pm/../../x.md"):
            code, out = lrun(repo, "set", "T-1", "--ref", bad)
            assert code == 1 and ("empty" in out or "outside the repo" in out), out
        for ok in ("DOI:10.1/X", "arXiv:2401.00001", "doi:10.2/y"):
            assert lrun(repo, "set", "T-1", "--ref", ok)[0] == 0, ok
        with (repo / L.LEDGER_REL).open("a") as fh:  # an old tool wrote ../
            ev: dict[str, object] = L.make_event(
                "lead", "set", "T-1", {"refs": ["../old.md", "doi:10.2/y"]}
            )
            fh.write(json.dumps(ev) + "\n")
        code, out = lrun(repo, "set", "T-1", "--ref-drop", "../old.md")
        assert code == 0 and L.load(repo)["T-1"].refs == ["doi:10.2/y"], out
        long: str = "a" * 300 + ".md"
        with (repo / L.LEDGER_REL).open("a") as fh:
            fh.write(json.dumps(L.make_event("lead", "set", "T-1", {"refs": [long]})))
            fh.write("\n")
        line: str = group(doctor(repo)[1], "missing ref")[0]
        assert len(line) == L.TITLE_MAX and line.endswith("..."), line


def test_reref_whole_path_components() -> None:
    """crit6 m3: OLD matches whole path components after normpath; NEW inside
    OLD is refused."""
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        for rel in ("old/a.md", "old2/a.md", "new/a.md", "new/H.md", "H.md.bak"):
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo / rel).write_text("x")
        lrun(repo, "add", "task", "t", "--note", "n", "--ref", "./old/a.md",
             "--ref", "old2/a.md", "--ref", "H.md.bak")
        with (repo / L.LEDGER_REL).open("a") as fh:  # a ref to a moved file
            ev: dict[str, object] = L.make_event(
                "lead", "set", "T-1", {"refs": ["./old/a.md", "old2/a.md",
                                                "H.md.bak", "H.md"]}
            )
            fh.write(json.dumps(ev) + "\n")
        code, out = lrun(repo, "reref", "old", "new/")
        assert code == 0 and out.splitlines()[0] == "T-1 ./old/a.md -> new/a.md", out
        assert lrun(repo, "reref", "H.md", "new/H.md")[0] == 0
        assert L.load(repo)["T-1"].refs == [
            "new/a.md", "old2/a.md", "H.md.bak", "new/H.md"
        ], L.load(repo)["T-1"].refs
        n: int = len(jl(repo))
        code, out = lrun(repo, "reref", "old2", "old2/sub")
        assert code == 1 and "inside OLD" in out and len(jl(repo)) == n, out


def test_compat_previous_ledger_doctor_no_hard() -> None:
    """Plan T6: a ledger of the previous release, with its folders, gives 0 hard."""
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        (repo / L.LEDGER_REL).write_text(
            "".join(json.dumps(e) + "\n" for e in COMPAT_0_1_8)
        )
        for rel in ("pm/waste/team/run1/sr1-r1.md", "pm/waste/team/02/sr1-r1.md",
                    "pm/stages/02-paper-new/notes/x.md"):
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo / rel).write_text("x")
        (repo / ".gitignore").write_text("pm/waste/\n")
        commit_all(repo)
        code, out = doctor(repo)
        assert code == 0 and out.endswith(" soft\n") and "HARD" not in out, out
        assert "doctor: 0 hard," in out, out
        code, out = doctor(repo, "--stage", "S-2")
        assert code == 0 and "HARD" not in out, out


# ---- follow-up round: clones, ref rules everywhere, worktrees (blind1 1-3) ----


def clone_of(repo: Path, dst: Path) -> Path:
    """`repo` committed (all files, its .gitignore applies) and cloned to `dst`."""
    commit_all(repo)
    git(repo, "clone", "-q", str(repo), str(dst))
    return dst


def test_doctor_in_fresh_clone() -> None:
    """blind1 1: a clone has no git-ignored files and no empty folders; refs
    there and such stage folders are SOFT. A ledger of the new kit and one of
    the previous release (0.1.8) both give 0 hard in the clone."""
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        repo: Path = new_repo(root / "a")
        (repo / ".gitignore").write_text("pm/waste/\npm/reviews/\npm/stages/*/chat/\n")
        lrun(repo, "add", "stage", "paper-goal", "--open")  # subfolders, no file
        chat: Path = repo / "pm/stages/01-paper-goal/chat/INDEX.md"
        chat.write_text("x")
        (repo / "pm/reviews").mkdir()
        (repo / "pm/reviews/crit.md").write_text("x")
        (repo / "kept.md").write_text("x")
        lrun(repo, "add", "task", "archive", "--note", "n", "--ref",
             "pm/stages/01-paper-goal/chat/INDEX.md", "--ref", "pm/reviews/crit.md",
             "--ref", "kept.md")
        code, out = doctor(repo)
        assert code == 0 and "HARD" not in out, out
        with env(**GIT_ENV):
            cl: Path = clone_of(repo, root / "clone")
        code, out = doctor(cl)
        assert code == 0 and "HARD" not in out, out
        assert group(out, L.G_IGNORED_GONE) == [
            "T-1 pm/stages/01-paper-goal/chat/INDEX.md", "T-1 pm/reviews/crit.md"
        ], out
        assert group(out, L.G_FOLDER_EMPTY) == ["S-1 pm/stages/01-paper-goal/"], out
        (cl / "kept.md").rename(root / "moved.md")  # tracked, then gone: damage
        assert group(doctor(cl)[1], "missing ref") == ["T-1 kept.md"]
        old: Path = new_repo(root / "b")  # the previous release's ledger
        lines: list[dict[str, object]] = [*COMPAT_0_1_8, {
            "ts": "2026-11-13T18:00:00+01:00", "who": "lead", "ev": "add",
            "id": "S-3", "f": {"type": "stage", "title": "03-paper-empty",
                               "status": "open", "owner": "lead", "stage": "",
                               "note": "", "links": [], "refs": []}}, {
            "ts": "2026-11-13T18:01:00+01:00", "who": "lead", "ev": "add",
            "id": "T-4", "f": {"type": "task", "title": "chat archive",
                               "status": "done", "owner": "lead", "stage": "S-3",
                               "note": "", "links": [],
                               "refs": ["pm/stages/03-paper-empty/chat/INDEX.md"]}},
        ]  # fmt: skip
        (old / L.LEDGER_REL).write_text("".join(json.dumps(e) + "\n" for e in lines))
        for rel in ("pm/waste/team/run1/sr1-r1.md", "pm/waste/team/02/sr1-r1.md",
                    "pm/stages/02-paper-new/notes/x.md",
                    "pm/stages/03-paper-empty/chat/INDEX.md"):
            (old / rel).parent.mkdir(parents=True, exist_ok=True)
            (old / rel).write_text("x")
        (old / ".gitignore").write_text("pm/waste/\npm/stages/*/chat/\n")
        assert doctor(old)[0] == 0
        with env(**GIT_ENV):
            ocl: Path = clone_of(old, root / "oclone")
        code, out = doctor(ocl)
        assert code == 0 and "HARD" not in out, out
        assert group(out, L.G_FOLDER_EMPTY) == ["S-3 pm/stages/03-paper-empty/"], out
        tracked: Path = ocl / "pm/stages/02-paper-new"  # had a tracked file
        tracked.rename(root / "moved-stage")
        assert group(doctor(ocl)[1], "missing stage folder") == [
            "S-2 pm/stages/02-paper-new/"
        ]


def test_reref_and_doctor_ref_rules() -> None:
    """blind1 2: reref NEW follows the --ref rules; an absolute OLD inside the
    repo is made relative; doctor reports stored absolute and ../ refs."""
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d).resolve()
        repo: Path = new_repo(root / "r")
        for rel in ("old/a.md", "new/a.md"):
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo / rel).write_text("x")
        lrun(repo, "add", "task", "t", "--note", "n", "--ref", "old/a.md")
        n: int = len(jl(repo))
        for bad in (str(root / "elsewhere"), "../elsewhere"):
            code, out = lrun(repo, "reref", "old", bad)
            assert code == 1 and "NEW" in out and "outside the repo" in out, out
        assert len(jl(repo)) == n
        code, out = lrun(repo, "reref", str(repo / "old"), str(repo / "new") + "/")
        assert code == 0 and out.splitlines()[0] == "T-1 old/a.md -> new/a.md", out
        assert L.load(repo)["T-1"].refs == ["new/a.md"]
        with (repo / L.LEDGER_REL).open("a") as fh:  # what an older tool stored
            ev: dict[str, object] = L.make_event(
                "lead", "set", "T-1",
                {"refs": [str(repo / "new/a.md"), "../up.md", "new/a.md"]},
            )
            fh.write(json.dumps(ev) + "\n")
        code, out = doctor(repo)
        assert code == 0 and group(out, L.G_OUTSIDE) == [
            f"T-1 {repo / 'new/a.md'}", "T-1 ../up.md"
        ], out
        code, out = lrun(repo, "reref", str(repo / "new"), "old")
        assert code == 0, out  # the absolute stored ref matched as well
        assert L.load(repo)["T-1"].refs == ["old/a.md", "../up.md"]


def test_ref_from_worktree_only() -> None:
    """blind1 3: a ref to a file that exists only in the worktree says so."""
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d).resolve()
        main: Path = new_repo(root)
        (main / ".git" / "worktrees" / "wt").mkdir(parents=True)
        wt: Path = new_repo(root / "wt")
        (wt / ".git").write_text(f"gitdir: {main}/.git/worktrees/wt\n")
        (wt / "only.md").write_text("x")
        (wt / "both.md").write_text("x")
        (main / "both.md").write_text("x")
        cwd: Path = Path.cwd()
        outs: list[tuple[int, str]] = []
        try:
            os.chdir(wt)
            for argv in (
                ["add", "task", "a", "--note", "n", "--ref", "only.md"],
                ["add", "task", "b", "--note", "n", "--ref", str(wt / "only.md")],
                ["add", "task", "c", "--note", "n", "--ref", str(wt / "both.md")],
            ):
                buf: io.StringIO = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    outs.append((L.main(argv), buf.getvalue()))
        finally:
            os.chdir(cwd)
        for code, out in outs[:2]:
            assert code == 1 and "exists in this worktree" in out, out
            assert f"main checkout {main}" in out and "merge first" in out, out
        assert outs[2][0] == 0, outs[2]
        assert [e["f"]["refs"] for e in jl(main)] == [["both.md"]]
        assert jl(wt) == []


# ---- 0.2.1: receipts, status-word titles, stage record ----------------------


def test_receipts_name_stage_or_none() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "task", "loose", "--note", "n")
        assert lrun(repo, "set", "T-1", "--owner", "sr1")[1] == (
            "updated T-1: owner (no stage)\n"
        )
        assert lrun(repo, "close", "T-1", "--note", "ok")[1] == (
            "closed T-1: ok (no stage)\n"
        )
        assert lrun(repo, "reopen", "T-1", "--note", "again")[1] == (
            "reopened T-1: again (no stage)\n"
        )
        assert lrun(repo, "drop", "T-1", "--note", "no")[1] == (
            "dropped T-1: no (no stage)\n"
        )
        lrun(repo, "add", "stage", "paper-x", "--open")
        lrun(repo, "add", "task", "in", "--note", "n")
        assert lrun(repo, "set", "T-2", "--owner", "sr2")[1] == (
            "updated T-2: owner (stage S-1)\n"
        )
        assert lrun(repo, "set", "T-1", "--stage", "S-1")[1] == (
            "updated T-1: stage (stage S-1)\n"
        )
        assert lrun(repo, "close", "T-2", "--note", "ok")[1] == (
            "closed T-2: ok (stage S-1)\n"
        )
        assert lrun(repo, "reopen", "T-1", "--note", "x")[1].endswith(" (stage S-1)\n")
        assert lrun(repo, "drop", "T-1", "--note", "no")[1].endswith(" (stage S-1)\n")


def test_set_same_stage_is_unchanged() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "stage", "paper-x", "--open")
        lrun(repo, "add", "task", "a", "--note", "n")
        n: int = len(jl(repo))
        code, out = lrun(repo, "set", "T-1", "--stage", "S-1")
        assert code == 0 and out == "unchanged T-1 (stage S-1)\n", out
        assert len(jl(repo)) == n  # no event
        code, out = lrun(repo, "set", "T-1", "--stage", "01", "--note", "more")
        assert code == 0 and out == "updated T-1: note (stage S-1)\n", out
        ev: dict[str, Any] = jl(repo)[-1]
        assert ev["f"] == {"note": "n\nmore"}, ev  # the stage is not rewritten
        lrun(repo, "add", "stage", "software-y", "--open")  # another kind: both open
        out = lrun(repo, "set", "T-1", "--stage", "S-2")[1]
        assert out == "updated T-1: stage (stage S-2)\n", out


def test_add_receipt_closed_stage_link() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "stage", "paper-x", "--open")
        lrun(repo, "add", "decision", "ok", "--owner", "user", "--link", "S-1")
        assert lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")[0] == 0
        out: str = lrun(repo, "add", "decision", "late", "--owner", "lead",
                        "--link", "S-1")[1]
        assert out == "logged D-2: late (no stage: S-1 is closed)\n", out
        assert "rk set" not in out  # the closed stage's record is frozen
        assert L.load(repo)["D-2"].stage == ""  # the rule is kept
        out = lrun(repo, "set", "D-2", "--stage", "S-1")[1]  # set is unchanged
        assert out == "updated D-2: stage (stage S-1)\n", out
        # an open entry gets the plain tail (it may be set into S-1 by hand)
        out = lrun(repo, "add", "fetch", "smith", "--link", "S-1")[1]
        assert out == "logged F-1: smith (no stage)\n", out
        # a link to something that is not a stage, or to an open stage
        out = lrun(repo, "add", "decision", "again", "--owner", "lead",
                   "--link", "D-1")[1]
        assert out == "logged D-3: again (no stage)\n", out


def test_doctor_status_word_titles() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        for k, title in enumerate(["OPEN: scan the rest", "todo port it",
                                   "Done reading", "opening move", "Doneness"]):
            lrun(repo, "add", "task", title, "--imported", "--source", f"A.md:{k}")
        for title in ["OPEN: old", "OPEN old"]:
            lrun(repo, "add", "fetch", title, "--status", "done")  # F-1, F-2
        for title in ["open access check", "open-source licence"]:
            lrun(repo, "add", "fetch", title, "--status", "done")  # titles, not states
        lrun(repo, "add", "fetch", "OPEN: not done yet")  # open: fine
        lrun(repo, "add", "fetch", "open: gone", "--status", "dropped")  # dropped
        lrun(repo, "add", "task", "todo later", "--note", "n")  # not imported: fine
        lrun(repo, "add", "task", "TODO: dropped row", "--imported", "--source", "A:9",
             "--status", "dropped")
        out: str = doctor(repo)[1]
        assert group(out, L.G_STATUS_WORD) == [
            "T-1 (open) OPEN: scan the rest",
            "T-2 (open) todo port it",
            "T-3 (open) Done reading",
        ], out  # the dropped imported row is not listed
        assert group(out, L.G_DONE_OPEN) == ["F-1 OPEN: old", "F-2 OPEN old"], out
        assert doctor(repo)[0] == 0  # soft only
        capped: str = doctor(repo, "--limit", "1")[1]  # both groups obey --limit
        assert group(capped, L.G_STATUS_WORD)[0] == "T-1 (open) OPEN: scan the rest"
        assert group(capped, L.G_DONE_OPEN)[0] == "F-1 OPEN: old", capped
        assert "T-2" not in capped and "F-2" not in capped, capped
        assert capped.count("+2 more") == 1 and capped.count("+1 more") == 1, capped
        lrun(repo, "set", "T-1", "--title", "scan the rest")
        assert len(group(doctor(repo)[1], L.G_STATUS_WORD)) == 2


def stage_ledger_lines() -> list[str]:
    """A hand-made ledger with fixed timestamps: stage S-1 from line 2 to 9."""
    rows: list[tuple[str, str, str, dict[str, object], dict[str, object]]] = [
        ("01", "add", "DB-1", {"type": "debt", "title": "old path", "status": "open",
                               "owner": "lead", "stage": "", "note": "",
                               "links": [], "refs": []}, {"kit": "0.2.0"}),
        ("02", "add", "S-1", {"type": "stage", "title": "01-paper-x",
                              "status": "open", "owner": "lead", "stage": "",
                              "note": "", "links": [], "refs": []},
         {"kit": "0.2.0", "sid": "s1", "rules": {"AGENTS.md": "2026-11-01a"}}),
        ("03", "add", "T-1", {"type": "task", "title": "Loader", "status": "open",
                              "owner": "sr1", "stage": "S-1", "note": "n",
                              "links": [], "refs": []}, {"kit": "0.2.0", "sid": "s1"}),
        ("04", "add", "D-1", {"type": "decision", "title": "use dE00",
                              "status": "done", "owner": "user", "stage": "S-1",
                              "note": "", "links": ["S-1"], "refs": []},
         {"kit": "0.2.0", "sid": "s1"}),
        ("05", "add", "D-2", {"type": "decision", "title": "cut scope",
                              "status": "done", "owner": "lead", "stage": "S-1",
                              "note": "", "links": [], "refs": []},
         {"kit": "0.2.1", "sid": "s2"}),
        ("06", "set", "T-1", {"status": "done"}, {"kit": "0.2.1", "sid": "s2"}),
        ("07", "add", "F-1", {"type": "fetch", "title": "smith2020",
                              "status": "open", "owner": "user", "stage": "S-1",
                              "note": "", "links": [], "refs": []}, {"kit": "0.2.1"}),
        ("08", "set", "DB-1", {"status": "dropped", "reason": "path is gone"},
         {"kit": "0.2.1", "sid": "s2"}),
        ("09", "set", "S-1", {"status": "done", "links": ["D-1"]},
         {"kit": "0.2.1", "sid": "s2", "rules": {"AGENTS.md": "2026-11-14a",
                                                 "pm/kinds/paper.md": "2026-11-14a"}}),
        ("10", "add", "T-2", {"type": "task", "title": "after", "status": "open",
                              "owner": "lead", "stage": "", "note": "n",
                              "links": [], "refs": []}, {"kit": "0.2.1"}),
    ]
    out: list[str] = []
    for day, kind, eid, f, extra in rows:
        ev: dict[str, object] = {
            "ts": f"2026-11-{day}T10:00:00+00:00", "who": "lead", "ev": kind,
            "id": eid, "f": f, **extra,
        }
        out.append(json.dumps(ev))
    return out


STAGE_RECORD_GOLDEN: str = """\
# Ledger of stage S-1 01-paper-x (generated)

Generated from pm/ledger.jsonl by rk.py when the stage was closed; frozen
with the stage. Do not edit: hand edits are blocked.
Window: ledger lines 2 to 9, 2026-11-02T10:00:00+00:00 to 2026-11-09T10:00:00+00:00.

## Entries of the stage (4)
- T-1 task done (sr1) Loader
- D-1 decision done (user) use dE00
- D-2 decision done (lead) cut scope
- F-1 fetch open (user) smith2020

## Entries touched in the window, not of the stage (1)
- DB-1 debt dropped (lead) old path -- reason: path is gone [no stage]

## Decisions by owner
### lead
- D-2 cut scope
### user
- D-1 use dE00

## Left open
- F-1 fetch open (user) smith2020

## Seen in the window
kit: 0.2.0, 0.2.1
sid: s1, s2
rules at open: AGENTS.md 2026-11-01a
rules at close: AGENTS.md 2026-11-14a, pm/kinds/paper.md 2026-11-14a
"""


def test_stage_record_golden() -> None:
    events: list[tuple[int, dict[str, object]]] = L._parse(
        ("\n".join(stage_ledger_lines()) + "\n").encode()
    )
    text: str = L.render_stage_record(events, "S-1")
    assert text == STAGE_RECORD_GOLDEN, text
    # frozen: lines after the close do not change it, nor does a rerun
    assert L.render_stage_record(events[:9], "S-1") == text
    assert L.render_stage_record(events, "S-1") == text


def test_stage_record_dropped_without_reason() -> None:
    """An old-style dropped entry (no `reason`, or an empty one) gets no tail."""
    for reason in (None, ""):
        rows: list[str] = stage_ledger_lines()
        ev: dict[str, Any] = json.loads(rows[7])  # the set that drops DB-1
        assert ev["id"] == "DB-1" and ev["f"]["status"] == "dropped", ev
        if reason is None:
            del ev["f"]["reason"]
        else:
            ev["f"]["reason"] = reason
        rows[7] = json.dumps(ev)
        events: list[tuple[int, dict[str, object]]] = L._parse(
            ("\n".join(rows) + "\n").encode()
        )
        text: str = L.render_stage_record(events, "S-1")
        assert "- DB-1 debt dropped (lead) old path [no stage]\n" in text, text
        assert "reason" not in text and "None" not in text, text


def test_status_commands_help_names_reason() -> None:
    for cmd in ("close", "drop", "shelve", "reopen"):
        buf: io.StringIO = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                L.main([cmd, "--help"])
        except SystemExit:
            pass
        text: str = " ".join(buf.getvalue().split())
        assert "required" in text and "stored as the entry's `reason`" in text, text
    assert "shelve" in L.G_RUNNING  # the over-24h hint names it too


def test_stage_close_writes_record() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "stage", "paper-x", "--open")
        rec: Path = repo / "pm/stages/01-paper-x/LEDGER.md"
        lrun(repo, "add", "task", "t", "--note", "n")
        lrun(repo, "add", "decision", "ok", "--owner", "user", "--link", "S-1")
        assert not rec.exists()  # nothing but stage-close writes it
        assert lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")[0] == 1
        assert not rec.exists()  # a refused close writes nothing
        lrun(repo, "close", "T-1", "--note", "ok")
        code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")
        assert code == 0 and out == (
            "closed S-1: sign-off D-1\nwrote pm/stages/01-paper-x/LEDGER.md\n"
        ), out
        text: str = rec.read_text()
        assert text == L.render_stage_record(L.read_events(repo), "S-1")
        assert text.startswith("# Ledger of stage S-1 01-paper-x (generated)\n")
        assert "- T-1 task done (lead) t\n" in text and "### user\n- D-1 ok" in text
        assert not (rec.parent / "LEDGER.md.tmp").exists()
        lrun(repo, "add", "task", "later", "--note", "n")  # other commands: untouched
        lrun(repo, "set", "T-2", "--owner", "sr1")
        assert rec.read_text() == text


def test_stage_close_record_imported_stage_without_folder() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "stage", "01-pilot", "--imported", "--source", "A.md:1")
        lrun(repo, "add", "decision", "ok", "--owner", "user", "--link", "S-1")
        code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")
        assert code == 0 and out.endswith(
            "no LEDGER.md: S-1 has no folder pm/stages/01-pilot/\n"
        ), out
        assert not (repo / "pm/stages").exists()  # no folder made for it


def test_reason_field_of_close_drop_reopen() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "task", "a", "--note", "n")
        lrun(repo, "add", "decision", "dd", "--owner", "user")
        old: str = ev_line("T-9", "old style")  # an entry from an older ledger
        with (repo / L.LEDGER_REL).open("a") as fh:
            fh.write(old)
        assert "reason:" not in lrun(repo, "show", "T-9")[1]
        lrun(repo, "drop", "T-1", "--note", "not needed\nsecond line")
        f: dict[str, Any] = jl(repo)[-1]["f"]
        assert f["reason"] == "not needed\nsecond line", f  # key "reason" in "f"
        assert f["note"] == "n\nnot needed\nsecond line", f  # the note keeps it too
        assert L.load(repo)["T-1"].extra["reason"] == "not needed\nsecond line"
        out: str = lrun(repo, "show", "T-1")[1]
        assert "\nreason: not needed\\nsecond line\n" in out, out
        lrun(repo, "reopen", "T-1", "--note", "needed after all")
        assert jl(repo)[-1]["f"]["reason"] == "needed after all"
        lrun(repo, "close", "T-1", "--note", "shipped")  # replaces it
        assert jl(repo)[-1]["f"]["reason"] == "shipped"
        out = lrun(repo, "show", "T-1")[1]
        assert "\nreason: shipped\n" in out, out
        assert out.count("\nreason: ") == 1, out  # one line, the current one
        # set, supersede, import and the status view do not carry it
        lrun(repo, "set", "T-1", "--note", "more")
        lrun(repo, "supersede", "D-1", "new dd", "--owner", "user")
        lrun(repo, "add", "task", "imp", "--imported", "--source", "A:1",
             "--status", "dropped")
        for ev in jl(repo)[-4:]:
            assert "reason" not in ev["f"], ev
        assert "reason" not in (repo / L.STATUS_REL).read_text()
        assert L.load(repo)["T-1"].extra["reason"] == "shipped"  # set kept it
        assert "reason" not in L.load(repo)["D-1"].extra


# ---- shelved: known, not planned now ----------------------------------------


def test_shelve_cycle() -> None:  # R1-R3, R8, R9, I1, I3
    assert L.STATUSES[-1] == "shelved" and L.OPEN_STATUSES == (
        "open", "running", "staged"
    )
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        (repo / "notes").mkdir()
        (repo / "notes/a.md").write_text("x")
        lrun(repo, "add", "task", "a", "--note", "n")  # T-1
        lrun(repo, "add", "task", "b", "--note", "n")  # T-2
        lrun(repo, "add", "debt", "flaky test")  # DB-1
        lrun(repo, "add", "decision", "dd", "--owner", "user")  # D-1
        lrun(repo, "add", "stage", "paper-x", "--open")  # S-1
        # refusals: no note, a stage, a decision
        code, out = lrun(repo, "shelve", "T-1")
        assert code == 1 and out == "error: shelve needs --note\n", out
        code, out = lrun(repo, "shelve", "S-1", "--note", "x")
        assert code == 1 and out == "error: S-1 is a stage: use stage-close\n", out
        code, out = lrun(repo, "shelve", "D-1", "--note", "x")
        assert code == 1 and out == (
            "error: D-1 is a decision; decisions are in force when logged: "
            "supersede or drop\n"
        ), out
        assert L.load(repo)["T-1"].status == "open"
        # the move: receipt (I3), event (I1)
        code, out = lrun(repo, "shelve", "T-1", "--note", "not now: no user need\nmore")
        assert code == 0 and out == (
            "shelved T-1: not now: no user need (no stage)\n"
        ), out
        ev: dict[str, Any] = jl(repo)[-1]
        assert ev["ev"] == "set" and ev["id"] == "T-1" and "kit" in ev, ev
        assert ev["f"] == {
            "status": "shelved",
            "note": "n\nnot now: no user need\nmore",
            "reason": "not now: no user need\nmore",
        }, ev["f"]
        # refs and links only when given
        code, out = lrun(repo, "shelve", "DB-1", "--note", "later", "--ref",
                         "notes/a.md", "--link", "T-2")
        assert code == 0 and out == "shelved DB-1: later (no stage)\n", out
        f: dict[str, Any] = jl(repo)[-1]["f"]
        assert set(f) == {"status", "note", "reason", "refs", "links"}, f
        assert f["refs"] == ["notes/a.md"] and f["links"] == ["T-2"], f
        # out of shelved: only reopen and drop; the existing refusal texts
        for cmd, text in (
            ("shelve", "cannot shelve T-1: it is shelved"),
            ("close", "cannot close T-1: it is shelved"),
            ("start", "T-1 is shelved: use reopen first"),
        ):
            argv: list[str] = [cmd, "T-1"] + ([] if cmd == "start" else ["--note", "x"])
            code, out = lrun(repo, *argv)
            assert code == 1 and out == f"error: {text}\n", (cmd, out)
        code, out = bcheck(repo, "DELIVERABLE: x\nTASK: T-1\n")  # R8
        assert code == 2 and "T-1 is shelved" in out, out
        code, out = lrun(repo, "reopen", "T-1", "--note", "wanted again")
        assert code == 0 and out == "reopened T-1: wanted again (no stage)\n", out
        e: Any = L.load(repo)["T-1"]
        assert e.status == "open" and e.extra["reason"] == "wanted again", e
        lrun(repo, "shelve", "T-1", "--note", "again not now")
        code, out = lrun(repo, "drop", "T-1", "--note", "never")
        assert code == 0 and out == "dropped T-1: never (no stage)\n", out
        assert L.load(repo)["T-1"].extra["reason"] == "never"
        # only from open or running
        lrun(repo, "start", "T-2")
        assert lrun(repo, "shelve", "T-2", "--note", "from running")[0] == 0
        code, out = lrun(repo, "shelve", "T-1", "--note", "x")  # dropped
        assert code == 1 and out == "error: cannot shelve T-1: it is dropped\n", out
        lrun(repo, "reopen", "T-2", "--note", "r")
        lrun(repo, "close", "T-2", "--note", "d")
        code, out = lrun(repo, "shelve", "T-2", "--note", "x")  # done
        assert code == 1 and out == "error: cannot shelve T-2: it is done\n", out
        # add --status shelved: import only, no reason; import rows may carry it
        code, out = lrun(repo, "add", "task", "z", "--note", "n", "--status", "shelved")
        assert code == 1 and "--status shelved: only with --imported" in out, out
        code, out = lrun(repo, "add", "task", "z", "--imported", "--source", "A:1",
                         "--status", "shelved")
        assert code == 0, out
        assert "reason" not in L.load(repo)["T-3"].extra
        rows: Path = write_rows(
            Path(d), [{"type": "debt", "title": "old", "source": "B:2",
                       "status": "shelved"}]
        )
        code, out = lrun(repo, "import", str(rows))
        assert code == 0 and "shelved 1" in out, out
        assert L.load(repo)["DB-2"].status == "shelved"


def test_shelve_views() -> None:  # R4-R6, I2
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "stage", "paper-x", "--open")  # S-1
        lrun(repo, "add", "task", "run me", "--note", "n")  # T-1
        lrun(repo, "add", "task", "keep", "--note", "n")  # T-2
        lrun(repo, "add", "task", "for the user", "--note", "n", "--owner", "user")
        lrun(repo, "add", "debt", "flaky timing test on CI")  # DB-1
        lrun(repo, "add", "fetch", "smith2020")  # F-1
        lrun(repo, "add", "deferred", "plot later")  # DF-1
        lrun(repo, "start", "T-1")
        before: str = (repo / L.STATUS_REL).read_text()
        assert "## Shelved" not in before and "Open: 7." in before, before
        lrun(repo, "add", "task", "imp", "--imported", "--source", "A:1")  # T-4
        for eid in ("T-1", "T-3", "DB-1", "T-4", "DF-1"):
            assert lrun(repo, "shelve", eid, "--note", "not now")[0] == 0
        st: str = (repo / L.STATUS_REL).read_text()
        assert "Open: 3." in st, st  # S-1, T-2, F-1
        sec: dict[str, str] = sections(st)
        assert "## Running" not in sec and "## Needs you" not in sec, st
        assert "T-2" in sec["## Open tasks"] and "T-1" not in st.split("## Shelved")[0]
        assert "tasks: 1 open" in sec["## Stages"], sec["## Stages"]
        heads: list[str] = [ln for ln in st.splitlines() if ln.startswith("## ")]
        assert heads == ["## Stages", "## Open tasks", "## Open fetches",
                         "## Shelved"], heads  # after the last open section
        lines: list[str] = sec["## Shelved"].splitlines()
        want: list[str] = [  # builtin type order, then id number; no reason
            "- T-1 (lead, ", "- T-3 (user, ", "- T-4 (lead, ", "- DF-1 (lead, ",
            "- DB-1 (lead, ",
        ]
        assert len(lines) == 5, lines
        for ln, w in zip(lines, want):
            assert ln.startswith(w) and "not now" not in ln, ln
        assert lines[0].endswith(") run me") and lines[2].endswith(") imp [imported]")
        assert lines[4].endswith(") flaky timing test on CI"), lines
        out: str = lrun(repo, "list")[1]  # R6: hidden, head line counts open only
        assert out.splitlines()[0].startswith("open 3 (running 0)"), out
        assert "shelved" not in out and "T-1" not in out and "DB-1" not in out, out
        out = lrun(repo, "list", "--all")[1]
        rows: list[str] = [ln for ln in out.splitlines() if "shelved" in ln]
        assert len(rows) == 5 and rows[0].startswith("T-3   shelved"), out
        assert out.index("F-1 ") < out.index("T-3 "), out  # after the open rows
        assert lrun(repo, "render")[1] == "wrote pm/STATUS.md (3 open)\n"
        lrun(repo, "reopen", "T-1", "--note", "back")
        assert "T-1" in sections((repo / L.STATUS_REL).read_text())["## Open tasks"]


def test_shelve_stage_close() -> None:  # R4, R7, D1
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        lrun(repo, "add", "stage", "paper-x", "--open")
        lrun(repo, "add", "task", "side", "--note", "n")  # T-1
        lrun(repo, "add", "task", "main", "--note", "n")  # T-2
        lrun(repo, "add", "decision", "ok", "--owner", "user", "--link", "S-1")
        code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")
        assert code == 1 and (
            "T-1 open, T-2 open: close, drop, shelve, re-stage (set T-1 --stage "
            "S-<x>) or defer them (add deferred ... --link T-1, then drop T-1 "
            '--note "deferred as DF-<k>")'
        ) in out, out
        long: str = "x" * 70 + "\nsecond line"
        lrun(repo, "shelve", "T-1", "--note", long)
        lrun(repo, "close", "T-2", "--note", "done")
        code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")  # no block
        assert code == 0 and "closed S-1: sign-off D-1" in out, out
        rec: str = (repo / "pm/stages/01-paper-x/LEDGER.md").read_text()
        assert f"- T-1 task shelved (lead) side -- reason: {'x' * 60}\n" in rec, rec
        assert "## Left open\nnone" in rec, rec  # shelved is not left open
        # D1: stays in the closed stage; reopen needs an open stage, drop does not
        code, out = lrun(repo, "reopen", "T-1", "--note", "again")
        assert code == 1 and out == (
            "error: S-1 is closed (done); an open task cannot go into it: "
            "re-stage it first: set T-1 --stage S-<x>\n"
        ), out
        lrun(repo, "add", "stage", "paper-y", "--open")  # S-2
        code, out = lrun(repo, "set", "T-1", "--stage", "S-2")  # any stage is fine
        assert code == 0 and out == "updated T-1: stage (stage S-2)\n", out
        assert L.load(repo)["T-1"].status == "shelved"
        assert lrun(repo, "reopen", "T-1", "--note", "again")[0] == 0


def closed_stage_repo(root: Path) -> Path:
    """Stage S-1 (01-paper-x) with a user sign-off D-1, not yet closed."""
    repo: Path = new_repo(root)
    lrun(repo, "add", "stage", "paper-x", "--open")
    lrun(repo, "add", "decision", "ok", "--owner", "user", "--link", "S-1")
    return repo


def test_stage_record_write_failure_and_regenerate() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = closed_stage_repo(Path(d))
        folder: Path = repo / "pm/stages/01-paper-x"
        real: Callable[..., None] = os.replace

        def deny(src: Any, dst: Any) -> None:
            if str(dst).endswith("LEDGER.md"):
                raise OSError(13, "denied")
            real(src, dst)

        L.os.replace = deny
        try:
            code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")
        finally:
            L.os.replace = real
        want: str = "pm/stages/01-paper-x/LEDGER.md could not be written: denied"
        assert code == 1 and want in out, out
        assert "rk stage-close S-1" in out, out  # says how to write it again
        assert L.load(repo)["S-1"].status == "done"  # the close line is there
        assert not (folder / "LEDGER.md").exists(), "no half record"
        assert not (folder / "LEDGER.md.tmp").exists(), "no tmp left behind"
        n: int = len(jl(repo))
        code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")
        assert code == 0 and out == (
            "S-1 is already closed; no ledger line written\n"
            "wrote pm/stages/01-paper-x/LEDGER.md\n"
        ), out
        assert len(jl(repo)) == n  # the record only, no ledger line
        text: str = (folder / "LEDGER.md").read_text()
        assert text == L.render_stage_record(L.read_events(repo), "S-1")
        code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")
        assert code == 1 and "S-1 is done, not open" in out, out  # as before
        assert len(jl(repo)) == n and (folder / "LEDGER.md").read_text() == text


def test_stage_record_of_retitled_imported_stage() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        (repo / "pm/stages/01-pilot").mkdir(parents=True)
        lrun(repo, "add", "stage", "01-pilot", "--imported", "--source", "A.md:1")
        lrun(repo, "add", "decision", "ok", "--owner", "user", "--link", "S-1")
        assert lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")[0] == 0
        head: str = "# Ledger of stage S-1 01-pilot (generated)"  # the title at close
        assert (repo / "pm/stages/01-pilot/LEDGER.md").read_text().startswith(head)
        assert lrun(repo, "set", "S-1", "--title", "02-renamed")[0] == 0
        (repo / "pm/stages/02-renamed").mkdir()
        code, out = lrun(repo, "stage-close", "S-1")  # the new folder has no record
        assert code == 0 and "wrote pm/stages/02-renamed/LEDGER.md" in out, out
        new: Path = repo / "pm/stages/02-renamed/LEDGER.md"
        assert new.read_text().startswith(head)  # as of the close, not the new title
        code, out = lrun(repo, "stage-close", "S-1")  # now it has one: plain refusal
        assert code == 1 and "S-1 is done, not open" in out, out
        assert "not a generated record" not in out, out
        new.write_text(head + "\nWindow: stale\n")  # a generated head, old window
        assert lrun(repo, "stage-close", "S-1")[0] == 0  # F5: head as of the close
        assert "stale" not in new.read_text()


def test_stage_record_not_over_a_hand_made_file() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = closed_stage_repo(Path(d))
        rec: Path = repo / "pm/stages/01-paper-x/LEDGER.md"
        rec.write_text("my own notes\n")
        code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")
        assert code == 1 and "pm/stages/01-paper-x/LEDGER.md is there" in out, out
        assert "not overwritten" in out, out
        assert rec.read_text() == "my own notes\n"
        assert L.load(repo)["S-1"].status == "done"  # the close line is written
        n: int = len(jl(repo))
        code, out = lrun(repo, "stage-close", "S-1")  # still refused, still intact
        assert code == 1 and "not overwritten" in out, out
        assert rec.read_text() == "my own notes\n" and len(jl(repo)) == n
        rec.unlink()  # moved away: now it can be written
        code, out = lrun(repo, "stage-close", "S-1")
        assert code == 0 and out.endswith("wrote pm/stages/01-paper-x/LEDGER.md\n")
        head: str = "# Ledger of stage S-1 01-paper-x (generated)"
        assert rec.read_text().startswith(head)


def test_stage_record_odd_folder_names() -> None:
    for title in ("..", "."):
        with tempfile.TemporaryDirectory() as d:
            repo: Path = new_repo(Path(d))
            (repo / "pm/stages").mkdir()
            lrun(repo, "add", "stage", title, "--imported", "--source", "A.md:1")
            lrun(repo, "add", "decision", "ok", "--owner", "user", "--link", "S-1")
            code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")
            assert code == 0 and out.endswith(
                f"no LEDGER.md: S-1 has no folder pm/stages/{title}/\n"
            ), out
            found: list[str] = [str(p) for p in Path(d).rglob("LEDGER.md")]
            assert found == [], found  # nothing written above or into pm/stages


# T8 / D-32, lead Q6 Q10; red: start succeeds in a planned stage today
def test_start_refused_in_planned_stage() -> None:
    planned: str = "stage S-1 is planned: rk stage-open S-1 first"
    shelved: str = (
        "stage S-1 is shelved: rk set S-1 --status planned, then rk stage-open S-1"
    )
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        plan_stages(repo, "paper-a")  # S-1
        for argv in (
            ("task", "t1", "--note", "n"),  # T-1
            ("task", "free", "--note", "n"),  # T-2: no stage (planned is no default)
            ("task", "t3", "--note", "n"),  # T-3
            ("task", "free2", "--note", "n"),  # T-4
            ("debt", "d"), ("fetch", "f"), ("deferred", "x"),  # DB-1 F-1 DF-1
        ):
            staged: bool = argv[1] not in ("free", "free2")
            extra: tuple[str, ...] = ("--stage", "S-1") if staged else ()
            code, out = lrun(repo, "add", *argv, *extra)
            assert code == 0, (argv, out)
        st: dict[str, Any] = L.load(repo)
        assert st["T-1"].stage == "S-1" and st["T-2"].stage == "", st
        # unit: the check raises the T8 sentence, or returns None
        try:
            L._check_stage_startable(st, st["T-1"])
            raise AssertionError("planned stage accepted")
        except L.LedgerError as err:
            assert str(err) == planned, str(err)
        assert L._check_stage_startable(st, st["T-2"]) is None
        # every type start accepts, exact error, ledger unchanged
        for eid in ("T-1", "DB-1", "F-1", "DF-1"):
            assert refused(repo, "start", eid) == f"error: {planned}\n", eid
        # brief-check: rc 2, nothing started, all or nothing
        raw: bytes = (repo / L.LEDGER_REL).read_bytes()
        code, out = bcheck(repo, "DELIVERABLE: x\nTASK: T-1\n")
        assert code == 2 and planned in out, out
        code, out = bcheck(repo, "DELIVERABLE: x\nTASK: T-4, T-1\n")
        assert code == 2 and planned in out, out
        assert (repo / L.LEDGER_REL).read_bytes() == raw
        assert L.load(repo)["T-4"].status == "open"
        # an unstaged task starts as before
        code, out = lrun(repo, "start", "T-2")
        assert code == 0 and out == "started T-2: free\n", out
        # shelved: the same, with its own sentence
        assert lrun(repo, "set", "S-1", "--status", "shelved", "--note", "r")[0] == 0
        for eid in ("T-1", "DB-1"):
            assert refused(repo, "start", eid) == f"error: {shelved}\n", eid
        raw = (repo / L.LEDGER_REL).read_bytes()
        code, out = bcheck(repo, "DELIVERABLE: x\nTASK: T-3\n")
        assert code == 2 and shelved in out, out
        assert (repo / L.LEDGER_REL).read_bytes() == raw
        st = L.load(repo)
        try:
            L._check_stage_startable(st, st["T-3"])
            raise AssertionError("shelved stage accepted")
        except L.LedgerError as err:
            assert str(err) == shelved, str(err)
        # after stage-open everything starts
        assert lrun(repo, "set", "S-1", "--status", "planned")[0] == 0
        assert lrun(repo, "stage-open", "S-1")[0] == 0
        st = L.load(repo)
        assert L._check_stage_startable(st, st["T-1"]) is None
        code, out = lrun(repo, "start", "T-1")
        assert code == 0 and out == "started T-1: t1\n", out
        assert lrun(repo, "start", "DB-1")[1] == "started DB-1: d\n"
        code, out = bcheck(repo, "DELIVERABLE: x\nTASK: T-3\n")
        assert code == 0 and out == "started T-3: t3\n", out
    with tempfile.TemporaryDirectory() as d:  # imported shelved: no way back, no advice
        repo = new_repo(Path(d))
        code, out = lrun(repo, "add", "stage", "05-paper-old", "--imported",
                         "--source", "A:1", "--status", "shelved")  # S-1
        assert code == 0, out
        code, out = lrun(repo, "add", "task", "old", "--imported", "--source",
                         "A:2", "--stage", "S-1")  # T-1
        assert code == 0, out
        assert refused(repo, "start", "T-1") == "error: stage S-1 is shelved\n"
        raw = (repo / L.LEDGER_REL).read_bytes()
        code, out = bcheck(repo, "DELIVERABLE: x\nTASK: T-1\n")
        assert code == 2 and "stage S-1 is shelved" in out, out
        assert "rk set S-1" not in out and (repo / L.LEDGER_REL).read_bytes() == raw


def bullets(text: str) -> list[str]:
    """The `- ` lines of one STATUS.md section (the blank line before the next
    heading belongs to the section text and is dropped)."""
    return [ln for ln in text.splitlines() if ln.startswith("- ")]


# T9 / D-35, lead Q8; red: no `## Planned stages` section
def test_status_md_planned_block() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        assert lrun(repo, "add", "stage", "paper-x", "--open")[0] == 0  # S-1, 01
        assert "## Planned stages" not in (repo / L.STATUS_REL).read_text()
        plan_stages(repo, "paper-scan", "software-b", "thesis-c")  # S-2 S-3 S-4
        assert lrun(repo, "add", "debt", "needs scan", "--stage", "S-2")[0] == 0
        st: str = (repo / L.STATUS_REL).read_text()
        sec: dict[str, str] = sections(st)
        rows: list[str] = bullets(sec["## Planned stages"])
        assert rows == [
            "- ~02 S-2 paper-scan (entries: 1)",
            "- ~03 S-3 software-b (entries: 0)",
            "- ~04 S-4 thesis-c (entries: 0)",
        ], rows
        assert "paper-scan" not in sec["## Stages"], sec["## Stages"]
        assert "Open: 1." in st, st  # S-1; DB-1 in planned S-2 shows planned (D-56)
        # shelved stages leave the block and sit in `## Shelved`, which follows it
        code, out = lrun(repo, "set", "S-3", "--status", "shelved", "--note", "later")
        assert code == 0, out
        # an open debt in S-1 for `## Open debt` (DB-1 shows planned, D-56)
        assert lrun(repo, "add", "debt", "in S-1", "--stage", "S-1")[0] == 0  # DB-2
        st = (repo / L.STATUS_REL).read_text()
        sec = sections(st)
        assert [r.split()[2] for r in bullets(sec["## Planned stages"])] == [
            "S-2", "S-4",
        ]
        assert "S-3" in sec["## Shelved"] and "S-3" not in sec["## Planned stages"]
        heads: list[str] = [ln for ln in st.splitlines() if ln.startswith("## ")]
        assert heads.index("## Shelved") == heads.index("## Planned stages") + 1, heads
        assert heads.index("## Open debt") < heads.index("## Planned stages"), heads
        # queue order and forecast follow a move
        assert lrun(repo, "set", "S-4", "--before", "S-2")[0] == 0
        rows = bullets(sections((repo / L.STATUS_REL).read_text())["## Planned stages"])
        assert [(r.split()[1], r.split()[2]) for r in rows] == [
            ("~02", "S-4"), ("~03", "S-2"),
        ], rows
        # a closed entry no longer counts
        assert lrun(repo, "close", "DB-1", "--note", "done")[0] == 0
        rows = bullets(sections((repo / L.STATUS_REL).read_text())["## Planned stages"])
        assert rows[1] == "- ~03 S-2 paper-scan (entries: 0)", rows
        # nothing planned: no section
        assert lrun(repo, "set", "S-2", "--status", "dropped", "--note", "x")[0] == 0
        assert lrun(repo, "set", "S-4", "--status", "shelved", "--note", "y")[0] == 0
        st = (repo / L.STATUS_REL).read_text()
        assert "## Planned stages" not in st and "## Shelved" in st, st


# T9 / D-35; red: `list --status` unknown (SystemExit 2)
def test_list_status_filter() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        assert lrun(repo, "add", "stage", "paper-x", "--open")[0] == 0  # S-1, 01
        plan_stages(repo, "paper-scan", "software-b", "thesis-c")  # S-2 S-3 S-4
        assert lrun(repo, "add", "debt", "d", "--stage", "S-2")[0] == 0  # DB-1
        for title in ("open", "gone", "later"):  # T-1 T-2 T-3, in S-1
            assert lrun(repo, "add", "task", title, "--note", "n")[0] == 0
        assert lrun(repo, "close", "T-2", "--note", "ok")[0] == 0
        assert lrun(repo, "shelve", "T-3", "--note", "later")[0] == 0
        assert lrun(repo, "set", "S-4", "--status", "shelved", "--note", "x")[0] == 0
        assert lrun(repo, "set", "S-3", "--before", "S-2")[0] == 0  # queue: S-3 S-2

        def ids(*argv: str) -> list[str]:
            code, out = lrun(repo, "list", *argv)
            assert code == 0, out
            return [ln.split()[0] for ln in out.splitlines()[1:]]

        code, out = lrun(repo, "list", "--status", "planned")
        lines: list[str] = out.splitlines()
        assert lines[0] == "open 0 (running 0)", lines
        assert [ln.split()[0] for ln in lines[1:]] == ["S-3", "S-2", "DB-1"], lines
        assert lines[1].split()[:3] == ["S-3", "planned", "lead"], lines
        assert lines[1].endswith("  ~02 software-b (0 entries)"), lines
        assert lines[2].endswith("  ~03 paper-scan (1 entry)"), lines  # DB-1
        assert set(ids("--status", "shelved")) == {"T-3", "S-4"}
        assert "~" not in lrun(repo, "list", "--status", "shelved")[1]
        assert set(ids("--status", "open")) == {"S-1", "T-1"}  # DB-1: planned, D-56
        assert ids("--status", "done") == ["T-2"]
        assert ids("--status", "planned", "--type", "task") == []
        assert lrun_exit(repo, "list", "--status", "bogus") == 2
        # the default list leaves planned stages out of its rows
        assert not {"S-2", "S-3", "S-4"} & set(ids())


# T9 / D-35, plan 3.3, lead Q9; red: `_planned_line` missing
def test_list_planned_line() -> None:
    exp: str = "planned 3: ~03 paper-scan, ~04 paper-draft, ~05 paper-review"
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        assert L._planned_line(L.load(repo)) == ""
        assert lrun(repo, "add", "stage", "paper-x", "--open")[0] == 0  # S-1, 01
        assert lrun(repo, "add", "stage", "software-y", "--open")[0] == 0  # S-2, 02
        assert "planned" not in lrun(repo, "list")[1]  # none planned: no line
        plan_stages(repo, "paper-scan", "paper-draft", "paper-review")  # S-3 S-4 S-5
        assert L._planned_line(L.load(repo)) == exp
        lines: list[str] = lrun(repo, "list")[1].splitlines()
        assert lines[0].startswith("open 2 (running 0)"), lines  # planned not counted
        assert lines[1] == exp, lines  # line 2, right after the head line
        assert lines[2].startswith("S-1") and lines[3].startswith("S-2"), lines
        # only the unfiltered list carries it (Q9)
        for argv in (
            ("--type", "stage"), ("--owner", "lead"), ("--stage", "S-1"),
            ("--status", "planned"), ("--type", "task"),
        ):
            out: str = lrun(repo, "list", *argv)[1]
            assert not any(ln.startswith("planned ") for ln in out.splitlines()), argv
        # a planned follow-up counts and shows `~NNx`, in queue order
        assert lrun(repo, "add", "stage", "paper-fu", "--follows", "S-1")[0] == 0
        assert L._planned_line(L.load(repo)) == (
            "planned 4: ~03 paper-scan, ~04 paper-draft, ~05 paper-review, "
            "~01b paper-fu"
        )
        # shelved or dropped stages are not planned
        for sid in ("S-3", "S-4", "S-5"):
            assert lrun(repo, "set", sid, "--status", "shelved", "--note", "x")[0] == 0
        assert lrun(repo, "set", "S-6", "--status", "dropped", "--note", "x")[0] == 0
        assert L._planned_line(L.load(repo)) == ""
        assert not any(
            ln.startswith("planned ") for ln in lrun(repo, "list")[1].splitlines()
        )
    # a long queue: cut to LINE_MAX between items, ending `+k more`
    with tempfile.TemporaryDirectory() as d:
        repo = new_repo(Path(d))
        plan_stages(repo, *[f"paper-t{i:02d}" for i in range(1, 13)])  # S-1..S-12
        out = lrun(repo, "list")[1]
        assert all(len(ln) <= L.LINE_MAX for ln in out.splitlines()), out
        line: str = out.splitlines()[1]
        assert line.startswith("planned 12: ~01 paper-t01, ~02 paper-t02"), line
        tail: list[str] = line.split()[-2:]
        assert tail[1] == "more" and tail[0][1:].isdigit(), line  # "+k more"
        k: int = int(tail[0][1:])
        body: str = line.split(": ", 1)[1].rsplit("+", 1)[0].rstrip(", ")
        shown: list[str] = body.split(", ")
        assert shown == [f"~{i:02d} paper-t{i:02d}" for i in range(1, len(shown) + 1)]
        assert len(shown) >= 3 and len(shown) + k == 12, (shown, k)


def _injected(*args: Any) -> None:
    raise OSError(28, "injected: no space left on device")


# fix r1, crit1 B1: a failure AFTER the ledger line is written (write_status)
# keeps the folder renamed: ledger and folder both new
def test_stage_open_failure_after_write() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        assert lrun(repo, "add", "stage", "paper-scan")[0] == 0
        (repo / "pm/stages/P-1-paper-scan/notes/a.md").write_text("a")
        code, out = lrun(
            repo, "add", "debt", "d", "--stage", "S-1",
            "--ref", "pm/stages/P-1-paper-scan/notes/a.md",
        )  # fmt: skip
        assert code == 0, out
        real: Any = L.write_status
        L.write_status = _injected
        try:
            try:
                code, out = lrun(repo, "stage-open", "S-1")
            except OSError:  # the error goes on, after the line is written
                pass
            else:
                raise AssertionError(f"no OSError: {code} {out}")
        finally:
            L.write_status = real
        st: Any = L.load(repo)
        assert st["S-1"].status == "open" and st["S-1"].title == "01-paper-scan"
        assert st["DB-1"].refs == ["pm/stages/01-paper-scan/notes/a.md"]
        assert (repo / "pm/stages/01-paper-scan/notes/a.md").read_text() == "a"
        assert not (repo / "pm/stages/P-1-paper-scan").exists()


# fix r1, crit1 B1: the same for stage-rename, failure in the ledger's fsync
def test_stage_rename_failure_after_write() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        assert lrun(repo, "add", "stage", "paper-x", "--open")[0] == 0  # 01-paper-x
        (repo / "pm/stages/01-paper-x/notes/a.md").write_text("a")
        code, out = lrun(
            repo, "add", "debt", "d", "--owner", "lead",
            "--ref", "pm/stages/01-paper-x/notes/a.md",
        )  # fmt: skip
        assert code == 0, out
        real: Any = os.fsync
        os.fsync = _injected
        try:
            try:
                code, out = lrun(repo, "stage-rename", "S-1", "paper-y")
            except OSError:
                pass
            else:
                raise AssertionError(f"no OSError: {code} {out}")
        finally:
            os.fsync = real
        st: Any = L.load(repo)
        assert st["S-1"].title == "01-paper-y"
        assert st["DB-1"].refs == ["pm/stages/01-paper-y/notes/a.md"]
        assert (repo / "pm/stages/01-paper-y/notes/a.md").read_text() == "a"
        assert not (repo / "pm/stages/01-paper-x").exists()


# fix r1, crit1 B2: a stage not added planned keeps the 0.2.4 record bytes; an
# imported stage with --date starts its window at that date (st.created)
def test_record_imported_dated_stage() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        (repo / "pm/stages/07-paper-old").mkdir(parents=True)
        code, out = lrun(
            repo, "add", "stage", "07-paper-old", "--imported",
            "--source", "old.md:1", "--date", "2025-01-01",
        )  # fmt: skip
        assert code == 0, out
        code, out = lrun(
            repo, "add", "decision", "sign-off: 07-paper-old", "--owner", "user",
            "--link", "S-1",
        )  # fmt: skip
        assert code == 0, out
        code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")
        assert code == 0, out
        st: Any = L.load(repo)["S-1"]
        rec: Path = repo / "pm/stages/07-paper-old/LEDGER.md"
        window: str = (
            f"Window: ledger lines 1 to {st.lines[-1]}, 2025-01-01 to {st.updated}."
        )
        assert window in rec.read_text().split("\n"), rec.read_text()
        before: bytes = rec.read_bytes()
        code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")
        assert code == 1 and "S-1 is done, not open" in out, out
        assert rec.read_bytes() == before


# fix r1, crit1 m1: a queue value that is no number is refused by fold, with
# the line, on every command; nothing is appended
def test_fold_refuses_bad_queue() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        plan_stages(repo, "paper-a", "software-b")
        good: str = (repo / L.LEDGER_REL).read_text()
        for val in ("x", "1/0", True):
            ev: dict[str, Any] = {
                "ts": "2026-11-16T10:00:00+01:00", "who": "hand", "ev": "set",
                "id": "S-2", "f": {"queue": val},
            }
            (repo / L.LEDGER_REL).write_text(good + json.dumps(ev) + "\n")
            for argv in (("list",), ("add", "debt", "x"), ("stage-open", "S-1")):
                out: str = refused(repo, *argv)
                assert out.startswith(
                    f"error: {L.LEDGER_REL}:3: bad queue {val!r}: want a number "
                    "like 2 or 3/2"
                ), (val, argv, out)
            assert (repo / "pm/stages/P-1-paper-a").is_dir()


# fix r1, crit1 m2: doctor's folder check skips a dropped stage (its P- folder
# goes to pm/waste)
def test_doctor_skips_dropped_stage_folder() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        plan_stages(repo, "paper-a")
        code, out = lrun(repo, "set", "S-1", "--status", "dropped", "--note", "no")
        assert code == 0, out
        (repo / "pm/waste").mkdir()
        (repo / "pm/stages/P-1-paper-a").rename(repo / "pm/waste/P-1-paper-a")
        code, out = doctor(repo)
        assert "P-1-paper-a" not in out and "S-1" not in out, out


# fix r1, crit1 m4 (D-32: work runs only in an open stage): a dropped stage
# takes no entry; a running entry does not go into a planned or shelved stage
def test_stage_guards_dropped_and_running() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        assert lrun(repo, "add", "stage", "paper-x", "--open")[0] == 0  # S-1
        plan_stages(repo, "software-p", "software-q")  # S-2, S-3
        code, out = lrun(repo, "set", "S-3", "--status", "dropped", "--note", "no")
        assert code == 0, out
        out = refused(repo, "add", "debt", "late", "--stage", "S-3")
        assert out == (
            "error: S-3 is dropped and takes no entry: pass --stage with an open "
            "stage\n"
        ), out
        assert lrun(repo, "add", "debt", "d", "--stage", "S-1")[0] == 0  # DB-1
        out = refused(repo, "set", "DB-1", "--stage", "S-3")
        assert out == "error: S-3 is dropped and takes no entry: pick an open stage\n"
        assert lrun(repo, "add", "task", "run", "--note", "n")[0] == 0  # T-1, S-1
        assert lrun(repo, "start", "T-1")[0] == 0
        code, out = lrun(repo, "set", "S-2", "--status", "shelved", "--note", "l")
        assert code == 0, out
        out = refused(repo, "set", "T-1", "--stage", "S-2")
        assert out == (
            "error: S-2 is shelved: a running task cannot go into it (work runs "
            "only in an open stage): close or shelve it first, or open the stage: "
            "rk set S-2 --status planned, then rk stage-open S-2\n"
        ), out
        # an open (not running) entry still moves into a planned or shelved stage
        assert lrun(repo, "set", "DB-1", "--stage", "S-2")[0] == 0
        # start in a planned stage keeps its own text
        assert lrun(repo, "set", "S-2", "--status", "planned")[0] == 0
        assert lrun(repo, "add", "task", "t2", "--note", "n", "--stage", "S-2")[0] == 0
        out = refused(repo, "start", "T-2")
        assert out == "error: stage S-2 is planned: rk stage-open S-2 first\n", out


# fix r1, blind2 (i) and (iii): close / shelve / drop of a planned stage name
# `set --status`; a drop names the P- folder that is left for pm/waste
def test_planned_stage_texts() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        plan_stages(repo, "paper-x")
        for cmd in ("close", "shelve", "drop"):
            out: str = refused(repo, cmd, "S-1", "--note", "x")
            assert out == (
                "error: S-1 is a planned stage: use rk set S-1 --status "
                "shelved|dropped --note ...\n"
            ), (cmd, out)
        code, out = lrun(repo, "set", "S-1", "--status", "dropped", "--note", "no")
        assert code == 0 and out.splitlines()[1:] == [
            "folder pm/stages/P-1-paper-x/ is left: move it to pm/waste"
        ], out
        assert (repo / "pm/stages/P-1-paper-x").is_dir()  # the waste step is later


# fix r2, crit1 N1: imported history loads as it was (as 0.2.4): the m4 guards
# (dropped stage takes no entry, no running entry in a planned or shelved stage)
# do not apply to import rows and --imported adds
def test_import_keeps_history_past_m4_guards() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        repo: Path = new_repo(root)
        rows: Path = write_rows(root, [
            {"type": "stage", "title": "03-paper-old", "source": "L:1",
             "status": "dropped"},
            {"type": "task", "title": "t", "source": "L:2", "status": "done",
             "stage": "03"},
            {"type": "stage", "title": "04-paper-later", "source": "L:3",
             "status": "shelved"},
            {"type": "task", "title": "r", "source": "L:4", "status": "running",
             "stage": "04"},
        ])
        code, out = lrun(repo, "import", str(rows))
        assert code == 0, out
        st: Any = L.load(repo)
        assert st["T-1"].stage == "S-1" and st["S-1"].status == "dropped"
        assert st["T-2"].stage == "S-2" and st["T-2"].status == "running"
        code, out = lrun(
            repo, "add", "debt", "old", "--imported", "--source", "L:5",
            "--stage", "S-1",
        )  # fmt: skip
        assert code == 0, out
        assert L.load(repo)["DB-1"].stage == "S-1"
        # not imported: the guard holds
        out = refused(repo, "add", "debt", "new", "--stage", "S-1")
        assert out.startswith("error: S-1 is dropped and takes no entry"), out


# ---- staged (spec-staged-status, D-49 to D-51) --------------------------------


def work_repo(root: Path) -> Path:
    """Open stage S-1 (01-paper-x), T-1 running, DB-1 open, both in S-1."""
    repo: Path = new_repo(root)
    assert lrun(repo, "add", "stage", "paper-x", "--open")[0] == 0
    assert lrun(repo, "add", "task", "run", "--note", "n")[0] == 0
    assert lrun(repo, "start", "T-1")[0] == 0
    assert lrun(repo, "add", "debt", "fix it")[0] == 0
    return repo


# spec table rows open/running -> staged; several ids, one write; the refusals
def test_staged_command() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = work_repo(Path(d))
        (repo / "notes.md").write_text("x")
        out: str = refused(repo, "staged", "DB-1")
        assert out == "error: staged needs --note\n", out
        n: int = len(jl(repo))
        code, out = lrun(
            repo, "staged", "T-1", "DB-1", "--note", "on w1 at abc1234",
            "--ref", "notes.md",
        )  # fmt: skip
        assert code == 0 and out == (
            "staged T-1: on w1 at abc1234 (stage S-1)\n"
            "staged DB-1: on w1 at abc1234 (stage S-1)\n"
        ), out
        assert len(jl(repo)) == n + 2
        st: Any = L.load(repo)
        for i in ("T-1", "DB-1"):
            assert st[i].status == "staged" and st[i].extra["reason"] == (
                "on w1 at abc1234"
            ), i
            assert st[i].note.endswith("on w1 at abc1234") and "notes.md" in st[i].refs
        # not again, not a stage, not a decision, not done; the whole call refused
        assert lrun(repo, "add", "decision", "use x", "--owner", "user")[0] == 0
        assert lrun(repo, "add", "debt", "other")[0] == 0  # DB-2, open
        for argv, want in (
            (("DB-2", "DB-1"), "cannot stage DB-1: it is staged"),
            (("S-1",), "S-1 is a stage: a stage closes with stage-close"),
            (("D-1",), "D-1 is a decision: decisions are in force when logged"),
        ):
            out = refused(repo, "staged", *argv, "--note", "x")
            assert out == f"error: {want}\n", (argv, out)
        assert L.load(repo)["DB-2"].status == "open"
        # one way in: not by set, not by add
        out = refused(repo, "set", "DB-2", "--status", "staged")
        assert out.startswith("error: --status staged: set gives a status"), out
        out = refused(repo, "add", "debt", "y", "--status", "staged")
        assert out == (
            "error: --status staged: an entry is staged by rk staged ID --note "
            "TEXT, no add sets it\n"
        ), out


# spec table rows staged -> done (close), -> running (start, brief-check),
# -> open (reopen)
def test_staged_ways_out() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = work_repo(Path(d))
        assert lrun(repo, "add", "task", "two", "--note", "n")[0] == 0  # T-2
        assert lrun(repo, "staged", "T-1", "T-2", "DB-1", "--note", "w1")[0] == 0
        code, out = lrun(repo, "close", "DB-1", "--note", "landed on dev")
        assert code == 0 and out == "closed DB-1: landed on dev (stage S-1)\n", out
        code, out = lrun(repo, "start", "T-1")
        assert code == 0 and out == "started T-1: run\n", out
        assert L.load(repo)["T-1"].status == "running"
        code, out = bcheck(repo, "DELIVERABLE: x\nTASK: T-2\n")
        assert code == 0 and out == "started T-2: two\n", out
        assert lrun(repo, "staged", "T-2", "--note", "w1 again")[0] == 0
        code, out = lrun(repo, "reopen", "T-2", "--note", "not done after all")
        assert code == 0 and out.startswith("reopened T-2: not done after all"), out
        assert L.load(repo)["T-2"].status == "open"


# spec Landing: all, named, --stage, refusal, landed 0
def test_land() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = work_repo(Path(d))
        code, out = lrun(repo, "land", "--note", "nothing yet")
        assert code == 0 and out == "landed 0\n", out
        assert lrun(repo, "add", "debt", "d2")[0] == 0  # DB-2
        assert lrun(repo, "add", "stage", "software-y", "--open")[0] == 0  # S-2
        assert lrun(repo, "add", "debt", "d3", "--stage", "S-2")[0] == 0  # DB-3
        assert lrun(repo, "add", "debt", "d4", "--stage", "S-2")[0] == 0  # DB-4
        assert lrun(
            repo, "staged", "T-1", "DB-1", "DB-2", "DB-3", "DB-4", "--note", "w1"
        )[0] == 0
        # a named entry that is not staged refuses the whole call
        assert lrun(repo, "add", "debt", "d5")[0] == 0  # DB-5, open
        out: str = refused(repo, "land", "DB-1", "DB-5", "--note", "dev")
        assert out == "error: cannot land DB-5: it is open, not staged\n", out
        out = refused(repo, "land", "--stage", "S-2", "DB-1", "--note", "dev")
        assert out == "error: cannot land DB-1: it is in S-1, not S-2\n", out
        n: int = len(jl(repo))
        code, out = lrun(repo, "land", "DB-2", "DB-1", "--note", "on dev 1a2b")
        assert code == 0 and out == (
            "landed DB-2: on dev 1a2b (stage S-1)\n"
            "landed DB-1: on dev 1a2b (stage S-1)\n"
        ), out
        assert len(jl(repo)) == n + 2
        code, out = lrun(repo, "land", "--stage", "S-2", "--note", "on dev 3c4d")
        assert code == 0 and out == (
            "landed DB-3: on dev 3c4d (stage S-2)\n"
            "landed DB-4: on dev 3c4d (stage S-2)\n"
        ), out
        code, out = lrun(repo, "land", "--note", "on dev 5e6f")
        assert code == 0 and out == "landed T-1: on dev 5e6f (stage S-1)\n", out
        st: Any = L.load(repo)
        assert [st[i].status for i in ("T-1", "DB-1", "DB-2", "DB-3", "DB-4")] == [
            "done"
        ] * 5
        assert st["DB-1"].extra["reason"] == "on dev 1a2b"
        assert st["DB-5"].status == "open"
        out = refused(repo, "land", "--note", "")
        assert out == "error: land needs --note\n", out


# spec "What staged counts as": not done for stage-close (text names rk land)
# and for the drop of a planned stage; no staging in a planned or shelved stage
def test_staged_blocks_and_guards() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = work_repo(Path(d))
        assert lrun(repo, "staged", "T-1", "--note", "w1")[0] == 0
        assert lrun(repo, "add", "decision", "sign-off", "--owner", "user")[0] == 0
        code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")
        assert code == 1 and (
            "T-1 staged: land the staged ones once merged (rk land T-<n>...), "
            "close, drop, shelve, re-stage"
        ) in out, out
        plan_stages(repo, "software-p")  # S-2
        assert lrun(repo, "add", "debt", "p", "--stage", "S-2")[0] == 0  # DB-2
        out = refused(repo, "staged", "DB-2", "--note", "w1")
        assert out.startswith(
            "error: S-2 is planned: a staged debt cannot go into it (work runs "
            "only in an open stage)"
        ), out
        out = refused(repo, "set", "T-1", "--stage", "S-2")
        assert out.startswith("error: S-2 is planned: a staged task cannot go"), out
        # a staged entry in a planned stage (only by a hand edit) blocks its drop
        ev: dict[str, Any] = L.make_event("hand", "set", "T-1", {"stage": "S-2"})
        with (repo / L.LEDGER_REL).open("a") as fh:
            fh.write(json.dumps(ev) + "\n")
        assert lrun(repo, "close", "DB-2", "--note", "x")[0] == 0
        out = refused(repo, "set", "S-2", "--status", "dropped", "--note", "no")
        assert out.startswith(
            "error: cannot drop S-2: open entries are in it: T-1 staged;"
        ), out


# spec Display: list head line, --status staged, STATUS.md block
def test_staged_display() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = work_repo(Path(d))
        before: str = lrun(repo, "list")[1]
        assert before.splitlines()[0] == "open 3 (running 1): task 1, debt 1, stage 1"
        assert "Staged" not in (repo / L.STATUS_REL).read_text()
        assert lrun(repo, "add", "debt", "mine", "--owner", "user")[0] == 0  # DB-2
        assert lrun(repo, "staged", "DB-1", "DB-2", "--note", "w1 at abc")[0] == 0
        lines: list[str] = lrun(repo, "list")[1].splitlines()
        assert lines[0] == "open 4 (running 1, staged 2): task 1, debt 2, stage 1"
        assert any(ln.startswith("DB-1  staged ") for ln in lines), lines
        lines = lrun(repo, "list", "--status", "staged")[1].splitlines()
        assert [ln.split()[0] for ln in lines[1:]] == ["DB-2", "DB-1"], lines
        sec: dict[str, str] = sections((repo / L.STATUS_REL).read_text())
        block: str = sec["## Staged (done, not landed)"]
        assert "DB-1" in block and "fix it" in block and "w1 at abc" in block, block
        assert "DB-2" in block and "DB-2" not in sec.get("## Needs you", "")
        assert "DB-1" not in sec.get("## Open debt", ""), sec
        st: str = (repo / L.STATUS_REL).read_text()
        assert st.index("## Staged") < st.index("## Running"), st


# spec "Done when" 4: the probe
def test_staged_probe() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        assert lrun(repo, "add", "debt", "dB-29 style fix")[0] == 0
        code, out = lrun(repo, "staged", "DB-1", "--note", "on w1-planned-stages")
        assert code == 0 and out == "staged DB-1: on w1-planned-stages (no stage)\n"
        out = lrun(repo, "list")[1]
        assert out.splitlines()[0] == "open 1 (running 0, staged 1): debt 1", out
        assert "DB-1  staged " in out, out
        code, out = lrun(repo, "land", "--note", "merged to dev")
        assert code == 0 and out == "landed DB-1: merged to dev (no stage)\n", out
        assert L.load(repo)["DB-1"].status == "done"


# ---- shown status (D-56, spec-staged-status "Addition ... (D-56)") -----------


def shown_repo(root: Path) -> Path:
    """S-1 01-software-a open; planned queue S-3 paper-c, S-2 paper-b, S-4
    paper-d (follows S-1); DB-1 open in S-2; T-1, DB-2 open in S-3; DB-3 open in
    S-1 (the spec example)."""
    repo: Path = new_repo(root)
    for argv in (
        ("stage", "software-a", "--open"),
        ("stage", "paper-b"),
        ("stage", "paper-c", "--before", "S-2"),
        ("stage", "paper-d", "--follows", "S-1"),
        ("debt", "dd", "--stage", "S-2"),
        ("task", "tt", "--note", "n", "--stage", "S-3"),
        ("debt", "ee", "--stage", "S-3"),
        ("debt", "ff", "--stage", "S-1"),
    ):
        code, out = lrun(repo, "add", *argv)
        assert code == 0, (argv, out)
    return repo


# D-56: the rule, owned by one function
def test_shown_status_rule() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = shown_repo(Path(d))
        st: dict[str, Any] = L.load(repo)
        shown: Any = L.shown_status
        assert [shown(st, st[i]) for i in ("DB-1", "T-1", "DB-2", "DB-3")] == [
            "planned", "planned", "planned", "open"
        ]
        assert [shown(st, st[i]) for i in ("S-1", "S-2")] == ["open", "planned"]
        assert lrun(repo, "set", "S-2", "--status", "shelved", "--note", "l")[0] == 0
        assert lrun(repo, "close", "DB-2", "--note", "x")[0] == 0
        st = L.load(repo)
        assert shown(st, st["DB-1"]) == "shelved" and st["DB-1"].status == "open"
        assert shown(st, st["DB-2"]) == "done"  # only stored open inherits
        assert lrun(repo, "start", "DB-3")[0] == 0
        st = L.load(repo)
        assert shown(st, st["DB-3"]) == "running"
        assert lrun(repo, "stage-open", "S-3")[0] == 0  # turns open by itself
        st = L.load(repo)
        assert shown(st, st["T-1"]) == "open" and st["S-3"].title == "02-paper-c"


# D-56: rk list: out of the open list and counts; planned line counts; filters
def test_list_shown_status() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = shown_repo(Path(d))
        lines: list[str] = lrun(repo, "list")[1].splitlines()
        assert lines[:2] == [
            "open 2 (running 0): debt 1, stage 1",
            "planned 3: ~02 paper-c (2 entries), ~03 paper-b (1), ~01b paper-d",
        ], lines
        assert [ln.split()[0] for ln in lines[2:]] == ["S-1", "DB-3"], lines
        lines = lrun(repo, "list", "--status", "planned")[1].splitlines()
        assert [ln.split()[:2] for ln in lines[1:]] == [
            ["S-3", "planned"], ["T-1", "planned"], ["DB-2", "planned"],
            ["S-2", "planned"], ["DB-1", "planned"], ["S-4", "planned"],
        ], lines
        lines = lrun(repo, "list", "--status", "open")[1].splitlines()
        assert [ln.split()[0] for ln in lines[1:]] == ["S-1", "DB-3"], lines
        lines = lrun(repo, "list", "--stage", "S-2")[1].splitlines()
        assert [ln.split()[:2] for ln in lines[1:]] == [["DB-1", "planned"]], lines
        assert lrun(repo, "set", "S-2", "--status", "shelved", "--note", "l")[0] == 0
        lines = lrun(repo, "list", "--status", "shelved")[1].splitlines()
        assert [ln.split()[:2] for ln in lines[1:]] == [
            ["S-2", "shelved"], ["DB-1", "shelved"]
        ], lines
        lines = lrun(repo, "list")[1].splitlines()
        assert lines[1] == "planned 2: ~02 paper-c (2 entries), ~01b paper-d", lines


# D-56: STATUS.md: out of the open list, "Open: N" and "Needs you"; the planned
# block keeps its count
def test_status_md_shown_status() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = shown_repo(Path(d))
        code, out = lrun(
            repo, "add", "debt", "ask", "--owner", "user", "--stage", "S-2"
        )
        assert code == 0, out  # DB-4
        text: str = (repo / L.STATUS_REL).read_text()
        assert "Open: 2." in text.splitlines()[2], text
        sec: dict[str, str] = sections(text)
        assert "DB-3" in sec["## Open debt"] and "DB-1" not in sec["## Open debt"]
        assert "DB-4" not in sec.get("## Needs you", ""), sec
        assert "T-1" not in sec.get("## Open tasks", ""), sec
        assert "S-2 paper-b (entries: 2)" in sec["## Planned stages"], sec
        code, out = lrun(repo, "render")
        assert code == 0 and out == f"wrote {L.STATUS_REL} (2 open)\n", out


# D-56: rk show adds one line when the shown status differs
def test_show_shown_status() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = shown_repo(Path(d))
        out: str = lrun(repo, "show", "DB-1")[1]
        lines: list[str] = out.splitlines()
        i: int = lines.index("status: open")
        assert lines[i + 1] == "shown: planned (stage S-2 is planned)", lines
        out = lrun(repo, "show", "DB-3")[1]
        assert "shown:" not in out, out


# D-56, known for 0.2.4 ledgers: open entries of an imported shelved stage
def test_shown_status_imported_shelved_stage() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        code, out = lrun(
            repo, "add", "stage", "07-paper-old", "--imported", "--status",
            "shelved", "--source", "old.md:1",
        )  # fmt: skip
        assert code == 0, out
        assert lrun(repo, "add", "debt", "old one", "--stage", "S-1")[0] == 0
        st: dict[str, Any] = L.load(repo)
        assert L.shown_status(st, st["DB-1"]) == "shelved"
        lines: list[str] = lrun(repo, "list")[1].splitlines()
        assert lines == ["open 0 (running 0)"], lines
        sec: dict[str, str] = sections((repo / L.STATUS_REL).read_text())
        assert "- DB-1 (" in sec["## Shelved"], sec  # blind7 F1: not lost


# blind7 F1 (T-67): an entry shown planned or shelved is in exactly one
# STATUS.md section (planned: under its stage in `## Planned stages`; shelved:
# `## Shelved`) and in `rk list --all` with its shown status
def test_status_md_inherited_entries_findable() -> None:
    def where(text: str, i: str) -> list[str]:
        return [h for h, body in sections(text).items() if f"- {i} (" in body]

    with tempfile.TemporaryDirectory() as d:
        repo: Path = shown_repo(Path(d))
        text: str = (repo / L.STATUS_REL).read_text()
        for i in ("T-1", "DB-2", "DB-1"):
            assert where(text, i) == ["## Planned stages"], (i, text)
        block: list[str] = sections(text)["## Planned stages"].splitlines()
        k: int = block.index("- ~02 S-3 paper-c (entries: 2)")
        assert [ln.split()[1] for ln in block[k + 1:k + 3]] == ["T-1", "DB-2"]
        assert where(text, "DB-3") == ["## Open debt"], text
        assert lrun(repo, "set", "S-2", "--status", "shelved", "--note", "l")[0] == 0
        text = (repo / L.STATUS_REL).read_text()
        assert where(text, "DB-1") == ["## Shelved"], text
        assert where(text, "S-2") == ["## Shelved"], text
        rows: dict[str, str] = {
            ln.split()[0]: ln.split()[1]
            for ln in lrun(repo, "list", "--all")[1].splitlines()[2:]
        }
        assert (rows["DB-1"], rows["T-1"], rows["DB-3"]) == (
            "shelved", "planned", "open"
        ), rows


# ---- local-only mode (S-4, design-local-only-mode R2 to R7; W1: red first) ---
# `pm` = "local" in pm/config.json: doctor, doctor --start and stage-close skip
# the git checks on pm/. Texts are those of design I5; the broken-config texts
# those of I2.

LOCAL_NOTICE: str = "pm: local only (pm/config.json): git checks on pm/ skipped"
NO_BINARY: str = "git: no git binary; git checks skipped"
NOT_A_REPO: str = "git: not a git repo; git checks skipped"
BROKEN_CONFIGS: list[tuple[str, str]] = [  # (file text, <what> of I2)
    ("[1]\n", "not a JSON object"),
    ("{torn", "not a JSON object"),
    ('{"pm": "x"}', '"pm" must be "local" or "tracked"'),
    ('{"pm": 1}', '"pm" must be "local" or "tracked"'),
]


def make_local(repo: Path, text: str = '{"pm": "local"}\n') -> None:
    """Write pm/config.json (default: the local declaration)."""
    (repo / "pm/config.json").write_text(text)


def fake_git_log(root: Path) -> tuple[Path, Path]:
    """A git on PATH that logs its arguments and stdin and does nothing else:
    (the bin folder, the argument log: one line per call, `-C DIR ARGS`)."""
    fakebin: Path = root / "fakebin"
    fakebin.mkdir()
    log: Path = root / "git-args"
    script: Path = fakebin / "git"
    script.write_text(
        f'#!/bin/sh\necho "$*" >> "{log}"\ncat >> "{root / "git-stdin"}"\nexit 0\n'
    )
    script.chmod(0o755)
    log.write_text("")
    return fakebin, log


def git_calls(log: Path) -> list[str]:
    """The logged calls without `-C DIR`: `ls-files -- pm/ledger.jsonl`, ..."""
    return [ln.split(" ", 2)[2] for ln in log.read_text().splitlines()]


def done_uncommitted(root: Path) -> Path:
    """Committed repo, then stage S-1 closed: its close is not in HEAD."""
    repo: Path = staged_repo(root)
    commit_all(repo)
    (repo / "pm/stages/01-paper-x/notes/n.md").write_text("x")
    assert lrun(repo, "close", "T-1", "--note", "ok")[0] == 0
    code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")
    assert code == 0, out
    return repo


def committed_refs_repo(root: Path, rels: list[str], ignore: str) -> Path:
    """staged_repo whose T-1 has the files `rels` as refs; `ignore` is the
    .gitignore; committed before the refs are set."""
    repo: Path = staged_repo(root)
    for rel in rels:
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text("x")
    (repo / ".gitignore").write_text(ignore)
    commit_all(repo)
    refs: list[str] = [x for rel in rels for x in ("--ref", rel)]
    code, out = lrun(repo, "set", "T-1", *refs)
    assert code == 0, out
    return repo


IGNORE_ALL: str = "build/\npm/waste/\npm/scratch/\npm/stages/*/chat/\n"


# I2: the one reader of pm/config.json
def test_local_read_config() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        cfg: Path = repo / "pm/config.json"
        before: dict[str, bytes | None] = snapshot(Path(d))
        assert L.read_config(repo) == {"pm": "tracked"}  # no file
        assert snapshot(Path(d)) == before  # read-only
        good: list[tuple[str, dict[str, object]]] = [
            ('{"pm": "local"}', {"pm": "local"}),
            ('{"pm": "tracked"}\n', {"pm": "tracked"}),
            ("{}", {"pm": "tracked"}),  # no key = tracked
            ('{"x": [1, 2]}', {"x": [1, 2], "pm": "tracked"}),
            ('{"x": 1, "pm": "local"}', {"x": 1, "pm": "local"}),
        ]
        for text, want in good:
            cfg.write_text(text)
            assert L.read_config(repo) == want, (text, L.read_config(repo))
        bad: list[tuple[str, str]] = [
            *BROKEN_CONFIGS, ("null", "not a JSON object"), ("", "not a JSON object"),
        ]
        for text, what in bad:
            cfg.write_text(text)
            try:
                L.read_config(repo)
            except L.LedgerError as e:
                assert str(e) == f"pm/config.json: {what}", (text, str(e))
            else:
                raise AssertionError(f"read_config accepted {text!r}")
        cfg.write_bytes(b"\xff\xfe{}")  # not UTF-8: same text
        for shape in ("bytes", "folder"):  # unreadable: same text
            if shape == "folder":
                cfg.unlink()
                cfg.mkdir()
            try:
                L.read_config(repo)
            except L.LedgerError as e:
                assert str(e) == "pm/config.json: not a JSON object", (shape, str(e))
            else:
                raise AssertionError(f"read_config accepted {shape}")


# I3: the read-only git helpers rk.py uses (rk.py itself holds no subprocess)
def test_local_git_helpers() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d).resolve()
        repo: Path = new_repo(root)
        plain: Path = root / "plain"
        plain.mkdir()
        with env(**GIT_ENV):
            assert L.git_exclude_file(plain) is None  # in no git repo
            assert L.git_tracked(plain, "pm/") is False
            git(repo, "init", "-q")
            got: Path | None = L.git_exclude_file(repo)
            assert got is not None and got.is_absolute(), got
            assert got.resolve() == (repo / ".git/info/exclude").resolve(), got
            (repo / "pm/x.md").write_text("x")
            assert L.git_tracked(repo, "pm/") is False  # untracked: no
            git(repo, "add", "pm/x.md")
            assert L.git_tracked(repo, "pm/") is True
            assert L.git_tracked(repo, "pm/x.md") is True
            assert L.git_tracked(repo, "other/") is False
            with env(PATH=str(root / "nobin")):  # git cannot run
                assert L.git_exclude_file(repo) is None
                assert L.git_tracked(repo, "pm/") is False


# I3 (addendum v2): the path of the repo folder below the git top level
def test_local_git_prefix() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d).resolve()
        top: Path = root / "top"
        (top / "sub/deep").mkdir(parents=True)
        plain: Path = root / "plain"
        plain.mkdir()
        with env(**GIT_ENV):
            assert L.git_prefix(plain) is None  # in no git repo
            git(top, "init", "-q")
            assert L.git_prefix(top) == ""  # the top level: empty, no slash
            assert L.git_prefix(top / "sub") == "sub/"
            assert L.git_prefix(top / "sub/deep") == "sub/deep/"
            with env(PATH=str(root / "nobin")):  # git cannot run
                assert L.git_prefix(top / "sub") is None


# R3: rk.py never parses the config itself (and holds no subprocess: the
# existing test_no_git_call)
def test_local_rk_py_does_not_parse_config() -> None:
    assert "json.load" not in RK_PY.read_text()


# R5: the notice is output line 1; a clean local repo prints it and the count
def test_local_doctor_notice_and_count() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = staged_repo(Path(d))
        commit_all(repo)
        assert doctor(repo)[1] == "doctor: no findings\n"  # tracked: no notice
        make_local(repo)
        code, out = doctor(repo)
        assert code == 0 and out == f"{LOCAL_NOTICE}\ndoctor: no findings\n", out
        code, out = doctor(repo, "--stage", "S-1")
        assert code == 0, out
        assert out == f"{LOCAL_NOTICE}\ndoctor S-1: no findings\n", out


# R5: no git binary, not a repo: notice line 1, the 0.2.5 `git:` line is line 2
def test_local_doctor_notice_before_git_line() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = staged_repo(Path(d))
        make_local(repo)
        code, out = doctor(repo)
        assert code == 0, out
        assert out.splitlines()[:2] == [LOCAL_NOTICE, NOT_A_REPO], out
        with env(PATH=str(Path(d) / "nobin")):
            out = doctor(repo)[1]
        assert out.splitlines()[:2] == [LOCAL_NOTICE, NO_BINARY], out
        out = doctor(repo, "--stage", "S-1")[1]
        assert out.splitlines()[:2] == [LOCAL_NOTICE, NOT_A_REPO], out


# R5 table row "ledger not append-only against HEAD": not run
def test_local_doctor_skips_ledger_against_head() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = staged_repo(Path(d))
        commit_all(repo)
        lrun(repo, "add", "task", "u", "--note", "n")
        path: Path = repo / L.LEDGER_REL
        lines: list[str] = path.read_text().splitlines(keepends=True)
        path.write_text(lines[0] + lines[2] + lines[1] + "".join(lines[3:]))
        code, out = doctor(repo)  # tracked: the 0.2.5 finding
        assert code == 1 and group(out, L.G_HEAD) != [], out
        make_local(repo)
        code, out = doctor(repo)
        assert out.splitlines()[0] == LOCAL_NOTICE, out
        assert group(out, L.G_HEAD) == [] and "append-only" not in out, out
        assert code == 0, out


# R5 table row "done stage not in HEAD": not run
def test_local_doctor_skips_done_stage_not_in_head() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = done_uncommitted(Path(d))
        code, out = doctor(repo)  # tracked: the 0.2.5 finding
        assert code == 0 and group(out, L.G_UNCOMMITTED) != [], out
        make_local(repo)
        code, out = doctor(repo)
        assert out.splitlines()[0] == LOCAL_NOTICE, out
        assert group(out, L.G_UNCOMMITTED) == [] and "not in HEAD" not in out, out
        assert code == 0 and out.endswith("doctor: no findings\n"), out


# R5 table row "ref in a git-ignored or waste folder": under pm/ only waste
def test_local_doctor_ignored_refs_under_pm() -> None:
    with tempfile.TemporaryDirectory() as d:
        rels: list[str] = [
            "pm/waste/team/r1.md", "pm/scratch/x.md",
            "pm/stages/01-paper-x/chat/INDEX.md", "build/out.md", "notes.md",
        ]
        repo: Path = committed_refs_repo(Path(d), rels, IGNORE_ALL)
        waste: str = "T-1 pm/waste/team/r1.md (waste)"
        outside: str = "T-1 build/out.md (ignored)"
        want: list[str] = [waste, "T-1 pm/scratch/x.md (ignored)", outside]
        assert group(doctor(repo)[1], L.G_IGNORED) == want  # tracked: 0.2.5
        make_local(repo)
        code, out = doctor(repo)
        assert out.splitlines()[0] == LOCAL_NOTICE, out
        assert code == 0, out  # a ref outside pm/ stays as in 0.2.5
        assert group(out, L.G_IGNORED) == [waste, outside], out


# R5 table row "ref to a git-ignored file that is not here": under pm/ (chat/
# refs included) a HARD missing ref instead; outside pm/ as in 0.2.5
def test_local_doctor_missing_ref_under_pm_is_hard() -> None:
    with tempfile.TemporaryDirectory() as d:
        rels: list[str] = [
            "pm/scratch/x.md", "pm/stages/01-paper-x/chat/INDEX.md",
            "build/out.md",
        ]
        repo: Path = committed_refs_repo(Path(d), rels, IGNORE_ALL)
        for rel in rels:
            (repo / rel).unlink()
        code, out = doctor(repo)  # tracked: all three SOFT
        assert code == 0 and group(out, L.G_REF) == [], out
        assert group(out, L.G_IGNORED_GONE) == [f"T-1 {r}" for r in rels], out
        make_local(repo)
        code, out = doctor(repo)
        assert out.splitlines()[0] == LOCAL_NOTICE, out
        assert code == 1, out
        assert group(out, L.G_REF) == [f"T-1 {r}" for r in rels[:2]], out
        assert group(out, L.G_IGNORED_GONE) == ["T-1 build/out.md"], out
        assert "HARD missing ref (2)" in out, out


# R5 table rows "unchanged": a ref into pm/waste/ whose file is gone stays SOFT
# (the user empties the waste folder); refs outside pm/ as in 0.2.5
def test_local_doctor_unchanged_groups() -> None:
    with tempfile.TemporaryDirectory() as d:
        rels: list[str] = ["pm/waste/team/r1.md", "build/out.md", "build/gone.md"]
        repo: Path = committed_refs_repo(Path(d), rels, IGNORE_ALL)
        (repo / rels[0]).unlink()
        (repo / rels[2]).unlink()
        want: dict[str, list[str]] = {
            L.G_WASTE_GONE: ["T-1 pm/waste/team/r1.md"],
            L.G_IGNORED: ["T-1 build/out.md (ignored)"],
            L.G_IGNORED_GONE: ["T-1 build/gone.md"],
        }
        code, out = doctor(repo)
        assert code == 0 and {g: group(out, g) for g in want} == want, out
        make_local(repo)
        code, out = doctor(repo)
        assert out.splitlines()[0] == LOCAL_NOTICE, out
        assert code == 0 and {g: group(out, g) for g in want} == want, out
        assert out.endswith("doctor: 0 hard, 3 soft\n"), out


# R5 table row "stage folder not here, and git has no file of it": HARD
def test_local_doctor_missing_stage_folder_is_hard() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = staged_repo(Path(d))
        commit_all(repo)
        shutil.rmtree(repo / "pm/stages/01-paper-x")
        code, out = doctor(repo)  # tracked: git has no file of it: SOFT
        assert code == 0, out
        assert group(out, L.G_FOLDER_EMPTY) == ["S-1 pm/stages/01-paper-x/"], out
        make_local(repo)
        code, out = doctor(repo)
        assert out.splitlines()[0] == LOCAL_NOTICE, out
        assert code == 1 and group(out, L.G_FOLDER_EMPTY) == [], out
        assert group(out, L.G_FOLDER) == ["S-1 pm/stages/01-paper-x/"], out
        assert "HARD missing stage folder (1)" in out, out


# R5: the count line counts the findings printed, not the skipped ones
def test_local_doctor_count_line_counts_printed() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = staged_repo(Path(d))
        commit_all(repo)
        waste: Path = repo / "pm/waste/team/w.md"
        waste.parent.mkdir(parents=True)
        waste.write_text("x")
        assert lrun(repo, "set", "T-1", "--ref", "pm/waste/team/w.md")[0] == 0
        (repo / "pm/stages/01-paper-x/notes/n.md").write_text("x")
        assert lrun(repo, "close", "T-1", "--note", "ok")[0] == 0
        assert lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")[0] == 0
        waste.unlink()
        code, out = doctor(repo)  # tracked: the waste row and not-in-HEAD
        assert code == 0 and out.endswith("doctor: 0 hard, 2 soft\n"), out
        make_local(repo)
        code, out = doctor(repo)
        assert code == 0 and out.splitlines()[0] == LOCAL_NOTICE, out
        assert out.endswith("doctor: 0 hard, 1 soft\n"), out


# R6: local doctor and stage-close run no `git show`, no `git status`, no
# check-ignore / ls-files on a path under pm/ except the _git_skip probe
def test_local_runs_no_git_on_pm() -> None:
    probe: str = f"ls-files -- {L.LEDGER_REL}"
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        fakebin, log = fake_git_log(root)
        path: str = f"{fakebin}{os.pathsep}{os.environ['PATH']}"

        def calls(repo: Path, *argv: str) -> list[str]:
            log.write_text("")
            with env(PATH=path):
                lrun(repo, *argv)
            return git_calls(log)

        def doctor_repo(sub: str) -> Path:
            """Done stage S-1 whose folder and a ref (under pm/) are gone."""
            repo: Path = staged_repo(root / sub)
            for rel in ("pm/scratch/x.md", "pm/scratch/y.md"):
                (repo / rel).parent.mkdir(parents=True, exist_ok=True)
                (repo / rel).write_text("x")
            lrun(repo, "set", "T-1", "--ref", "pm/scratch/x.md", "--ref",
                 "pm/scratch/y.md")
            assert lrun(repo, "close", "T-1", "--note", "ok")[0] == 0
            assert lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")[0] == 0
            (repo / "pm/scratch/y.md").unlink()
            shutil.rmtree(repo / "pm/stages/01-paper-x")
            return repo

        def close_repo(sub: str) -> Path:
            """Open stage S-1; T-1 has a present ref under pm/."""
            repo: Path = staged_repo(root / sub)
            (repo / "pm/scratch").mkdir()
            (repo / "pm/scratch/x.md").write_text("x")
            lrun(repo, "set", "T-1", "--ref", "pm/scratch/x.md")
            assert lrun(repo, "close", "T-1", "--note", "ok")[0] == 0
            return repo

        tracked: list[str] = calls(doctor_repo("t1"), "doctor")
        subs: set[str] = {c.split()[0] for c in tracked}
        assert {"check-ignore", "show", "status"} <= subs, tracked  # the scenario
        local: Path = doctor_repo("l1")
        make_local(local)
        got: list[str] = calls(local, "doctor")
        assert set(got) <= {probe}, got
        got = calls(local, "doctor", "--stage", "S-1")
        assert set(got) <= {probe}, got
        sc: list[str] = ["stage-close", "S-1", "--sign-off", "D-1"]
        assert "check-ignore" in " ".join(calls(close_repo("t2"), *sc))
        local = close_repo("l2")
        make_local(local)
        got = calls(local, *sc)
        assert set(got) <= {probe}, got
        assert L.load(local)["S-1"].status == "done"  # the close itself ran


# D-73 (Q5): stage-close prints the notice only when it prints findings; it is
# line 1, the `git:` line line 2
def test_local_stage_close_notice_only_with_findings() -> None:
    def ready(sub: str) -> Path:
        """Stage S-1 with its task closed: stage-close is not refused."""
        repo: Path = staged_repo(Path(d) / sub)
        assert lrun(repo, "close", "T-1", "--note", "ok")[0] == 0
        return repo

    with tempfile.TemporaryDirectory() as d:
        clean: Path = ready("a")
        make_local(clean)
        code, out = lrun(clean, "stage-close", "S-1", "--sign-off", "D-1")
        assert code == 0 and out.startswith("closed S-1: sign-off D-1\n"), out
        assert LOCAL_NOTICE not in out, out
        repo: Path = ready("b")
        assert lrun(repo, "add", "decision", "cut", "--owner", "lead")[0] == 0
        code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")
        assert code == 0, out
        assert "  D-2 (lead) cut" in out, out
        assert LOCAL_NOTICE not in out, out  # tracked: no notice
        repo = ready("c")
        make_local(repo)
        assert lrun(repo, "add", "decision", "cut", "--owner", "lead")[0] == 0
        code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")
        assert code == 0, out
        assert out.splitlines()[:2] == [LOCAL_NOTICE, NOT_A_REPO], out
        assert "  D-2 (lead) cut" in out, out
        assert "closed S-1: sign-off D-1" in out, out


# R7: doctor --start: `pm: local only` is line 2, at most 3 lines in all, one
# rule file behind = its line, several = `+N more: rk doctor` (D-71), no git
def test_local_doctor_start_lines() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        kit: str = f"kit {L.kit_version()}"
        repo: Path = new_repo(root)
        make_local(repo)
        fakebin, log = fake_git_log(root)

        def start() -> list[str]:
            log.write_text("")
            with env(PATH=f"{fakebin}{os.pathsep}{os.environ['PATH']}"):
                code, out = lrun(repo, "doctor", "--start")
            assert code == 0, out
            assert git_calls(log) == [], "doctor --start ran git"
            assert len(out.splitlines()) <= 3, out
            return out.splitlines()

        got: list[str] = start()
        assert got == [kit, "pm: local only"], got
        (repo / "AGENTS.md").write_text("<!-- research-kit: 2000-01-01a -->\n")
        a_kit: str | None = L._line1_stamp(L.TEMPLATE_DIR / "AGENTS.md")
        assert start() == [
            kit, "pm: local only", f"AGENTS.md 2000-01-01a, kit {a_kit}: run /rk-sync"
        ]
        for n, k in enumerate(("paper", "software"), start=2):
            (repo / f"pm/kinds/{k}.md").write_text(
                f"<!-- research-kit-kind {k}: 2000-01-01a -->\n"
            )
            assert start() == [kit, "pm: local only", f"+{n} more: rk doctor"]


# R4 + I5c: broken config: doctor lists HARD `pm/config.json does not parse`,
# exits 1 and checks the repo as tracked (no notice; the git groups run)
def test_local_broken_config_doctor() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = done_uncommitted(Path(d))
        assert group(doctor(repo)[1], L.G_UNCOMMITTED) != []  # tracked
        for text, what in BROKEN_CONFIGS:
            make_local(repo, text)
            code, out = doctor(repo)
            assert code == 1, (text, out)
            assert out.startswith("HARD pm/config.json does not parse (1)\n"), out
            assert group(out, "pm/config.json does not parse") == [what], out
            assert LOCAL_NOTICE not in out, out
            assert group(out, L.G_UNCOMMITTED) != [], out  # as tracked


# R4 + I5b: broken config: doctor --start prints its line and exits 0
def test_local_broken_config_doctor_start() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = new_repo(Path(d))
        kit: str = f"kit {L.kit_version()}"
        for text, _ in BROKEN_CONFIGS:
            make_local(repo, text)
            code, out = lrun(repo, "doctor", "--start")
            assert code == 0, out
            assert out.splitlines()[:2] == [kit, "pm/config.json does not parse"], out
            assert "pm: local only" not in out, out


# R4: broken config: stage-close exits 1 with `pm/config.json: <what>`, writes
# nothing (no ledger line, no stage record)
def test_local_broken_config_stage_close() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = staged_repo(Path(d))
        assert lrun(repo, "close", "T-1", "--note", "ok")[0] == 0  # not refused
        for text, what in BROKEN_CONFIGS:
            make_local(repo, text)
            before: dict[str, bytes | None] = snapshot(Path(d))
            code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")
            assert code == 1 and f"pm/config.json: {what}" in out, (text, out)
            assert snapshot(Path(d)) == before, text
        make_local(repo, "{}")  # no key = tracked: the same call now closes
        code, out = lrun(repo, "stage-close", "S-1", "--sign-off", "D-1")
        assert code == 0 and "closed S-1: sign-off D-1" in out, out


# R4: add, set, list, show, start, close never read the file (a guard: green
# before the build, must stay green)
def test_local_broken_config_ledger_commands_unaffected() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = staged_repo(Path(d))
        for text, _ in BROKEN_CONFIGS:
            make_local(repo, text)
            code, out = lrun(repo, "add", "task", "x", "--note", "n")
            assert code == 0, (text, out)
            tid: str = out.split()[1].rstrip(":")
            for argv in (
                ("set", tid, "--owner", "sr1"), ("list", "--all"), ("show", tid),
                ("start", tid), ("close", tid, "--note", "ok"),
            ):
                code, out = lrun(repo, *argv)
                assert code == 0, (text, argv, out)


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
