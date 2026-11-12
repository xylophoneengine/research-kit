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


def ev_line(eid: str, title: str, typ: str = "task", status: str = "open") -> str:
    f: dict[str, object] = {
        "type": typ, "title": title, "status": status, "owner": "lead",
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
