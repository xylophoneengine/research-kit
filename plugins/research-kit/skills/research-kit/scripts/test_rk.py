#!/usr/bin/env python3
"""Tests for rk.py. Run: python3 -I test_rk.py (prints PASS/FAIL per test)."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import re
import shutil
import sys
import tempfile
import traceback
from collections.abc import Callable
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType

# -I drops the script dir from sys.path, so load rk.py by path.
_spec: ModuleSpec | None = importlib.util.spec_from_file_location(
    "rk", Path(__file__).with_name("rk.py")
)
assert _spec is not None and _spec.loader is not None
rk: ModuleType = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rk)

REAL_TEMPLATE: Path = rk.TEMPLATE_DIR

FAKE_CORE: str = (
    "<!-- research-kit: T1 -->\n# core\nrule A\nrule B\n"
    "## Project appendix\n\nMode: light\nGit policy: user commits\n"
    "<!-- rk:kinds -->\n<!-- /rk:kinds -->\n"
)


def fake_template(root: Path) -> Path:
    """Copy of the real gitignore + pm/ skeletons, synthetic core and kinds."""
    tpl: Path = root / "template"
    (tpl / "kinds").mkdir(parents=True)
    shutil.copy(REAL_TEMPLATE / "gitignore", tpl / "gitignore")
    shutil.copytree(REAL_TEMPLATE / "pm", tpl / "pm")
    shutil.copy(
        REAL_TEMPLATE / "compact-instructions.md", tpl / "compact-instructions.md"
    )
    (tpl / "AGENTS.md").write_text(FAKE_CORE)
    for k in rk.KINDS:
        (tpl / "kinds" / f"{k}.md").write_text(
            f"<!-- research-kit-kind {k}: T1 -->\n# Kind {k}\nkind rule {k}\n"
        )
    return tpl


def setup(root: Path) -> Path:
    """Point rk at a fake template under root; return an empty repo dir."""
    rk.TEMPLATE_DIR = fake_template(root)
    repo: Path = root / "repo"
    repo.mkdir()
    return repo


def run(fn: Callable[..., int], *args: object) -> tuple[int, str]:
    buf: io.StringIO = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code: int = fn(*args)
    return code, buf.getvalue()


def snapshot(root: Path) -> dict[str, bytes | None]:
    """Every path under root (dirs too) -> file bytes or None for a dir."""
    return {
        str(p.relative_to(root)): (p.read_bytes() if p.is_file() else None)
        for p in sorted(root.rglob("*"))
    }


def appendix(repo: Path) -> str:
    return rk.split((repo / "AGENTS.md").read_text(), "repo")[1]


# ---- Task 2: helpers + init ---------------------------------------------------


def test_merge_and_drops() -> None:
    tpl: str = "<!-- research-kit: 2 -->\nrule A v2\nrule B\n## Project appendix\nX\n"
    rep: str = "<!-- research-kit: 1 -->\nrule A v1\nPROJ: local\nrule B\n"
    rep += "## Project appendix\nmine\n"
    out: str = rk.merge(tpl, rep)
    assert out.endswith("## Project appendix\nmine\n"), out
    assert "rule A v2" in out and "PROJ: local" not in out, out
    assert rk.dropped_lines(tpl, rep) == [
        "<!-- research-kit: 1 -->",
        "rule A v1",
        "PROJ: local",
    ], rk.dropped_lines(tpl, rep)
    assert rk.stamp(tpl) == "2" and rk.stamp("x") == "none"
    assert rk.split("no heading\n", "kind:paper") == ("no heading\n", "")
    assert rk.is_legacy("<!-- paper-playbook: 1 -->\n")
    assert not rk.is_legacy("<!-- paper-playbook: 1 -->\n<!-- research-kit: 2 -->\n")


def test_fields_and_kinds_block() -> None:
    app: str = "## Project appendix\nMode:    light\nxMode: no\n"
    assert rk.get_field(app, "Mode") == "light"
    app = rk.set_field(app, "Mode", "full")
    assert "Mode: full\n" in app and "xMode: no" in app, app
    app = rk.set_field(app, "Git policy", "user commits")
    assert rk.get_field(app, "Git policy") == "user commits"
    assert rk.get_field(app, "Legacy stages") is None
    assert rk.kinds_block(["thesis", "paper"]) == (
        "<!-- rk:kinds -->\n"
        "- Kind `paper`: read `pm/kinds/paper.md` at session start and after "
        "every compact.\n"
        "- Kind `thesis`: read `pm/kinds/thesis.md` at session start and after "
        "every compact.\n"
        "<!-- /rk:kinds -->"
    )
    # Inline mention of the marker in prose is not the block.
    prose: str = "See the `<!-- rk:kinds -->` block.\n"
    app2: str = rk.set_kinds(prose, ["paper"])
    assert app2.startswith(prose) and rk.active_kinds(app2) == ["paper"], app2


def test_init_full() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = setup(Path(d))
        code, out = run(rk.cmd_init, repo, ["software"], "full", "user")
        assert code == 0, out
        text: str = (repo / "AGENTS.md").read_text()
        assert re.match(r"<!-- research-kit: \S+ -->", text), text[:80]
        app: str = appendix(repo)
        assert "Mode: full" in app and "Git policy: user commits" in app, app
        assert rk.kinds_block(["software"]) in app, app
        assert app.count("- Kind `software`") == 1, app
        assert rk.active_kinds(app) == ["software"]
        assert (repo / "pm/kinds/software.md").is_file()
        for sub in [*rk.PM_DIRS, "stages"]:
            assert (repo / "pm" / sub).is_dir(), sub
        for f in ("README.md", "DECISIONS.md", "DEFERRED.md"):
            assert (repo / "pm" / f).is_file(), f


def test_init_light_has_no_stages() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = setup(Path(d))
        code, out = run(rk.cmd_init, repo, ["paper"], "light", "orchestrator")
        assert code == 0, out
        assert not (repo / "pm/stages").exists()
        app: str = appendix(repo)
        assert rk.get_field(app, "Mode") == "light"
        assert rk.get_field(app, "Git policy") == "orchestrator commits"


def test_init_refuses_existing() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = setup(Path(d))
        assert run(rk.cmd_init, repo, ["paper"], "full", "user")[0] == 0
        before: dict[str, bytes | None] = snapshot(repo)
        code, out = run(rk.cmd_init, repo, ["software"], "light", "user")
        assert code == 1, out
        assert snapshot(repo) == before


def test_init_rejects_unknown_kind() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = setup(Path(d))
        code, out = run(rk.cmd_init, repo, ["poetry"], "full", "user")
        assert code == 1, out
        assert snapshot(repo) == {}, snapshot(repo)


def test_gitignore_block_idempotent() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = setup(Path(d))
        gi: Path = repo / ".gitignore"
        gi.write_text("node_modules/")  # no trailing newline on purpose

        def check() -> None:
            text: str = gi.read_text()
            assert "node_modules/\n" in text, text
            assert text.count(rk.GI_START) == 1, text
            assert text.count(rk.GI_END) == 1, text
            assert "pm/waste/" in text and "_dry/" in text, text

        assert run(rk.cmd_init, repo, ["paper"], "full", "user")[0] == 0
        check()
        assert rk.ensure_gitignore(repo) is False
        check()
        for _ in range(2):
            assert run(rk.cmd_add_kind, repo, "software")[0] == 0
            check()
            assert run(rk.cmd_sync, repo, True, False)[0] == 0
            check()


# ---- Task 3: add-kind + upgrade -----------------------------------------------


def test_add_kind() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = setup(Path(d))
        assert run(rk.cmd_init, repo, ["paper"], "full", "user")[0] == 0
        code, out = run(rk.cmd_add_kind, repo, "experiment")
        assert code == 0, out
        app: str = appendix(repo)
        assert rk.kinds_block(["paper", "experiment"]) in app, app
        assert rk.active_kinds(app) == ["paper", "experiment"]
        assert (repo / "pm/kinds/experiment.md").is_file()


def test_add_kind_active_is_noop() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = setup(Path(d))
        assert run(rk.cmd_init, repo, ["paper"], "full", "user")[0] == 0
        before: bytes = (repo / "AGENTS.md").read_bytes()
        code, out = run(rk.cmd_add_kind, repo, "paper")
        assert code == 0, out
        assert (repo / "AGENTS.md").read_bytes() == before


def test_add_kind_unknown() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = setup(Path(d))
        assert run(rk.cmd_init, repo, ["paper"], "full", "user")[0] == 0
        before: dict[str, bytes | None] = snapshot(repo)
        code, out = run(rk.cmd_add_kind, repo, "poetry")
        assert code == 1, out
        assert all(k in out for k in rk.KINDS), out
        assert snapshot(repo) == before


def test_upgrade() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = setup(Path(d))
        assert run(rk.cmd_init, repo, ["paper"], "light", "user")[0] == 0
        code, out = run(rk.cmd_upgrade, repo)
        assert code == 0, out
        assert rk.get_field(appendix(repo), "Mode") == "full"
        assert (repo / "pm/stages").is_dir()
        code, out = run(rk.cmd_upgrade, repo)
        assert code == 0 and "already full" in out, out


# ---- Task 4: sync + legacy migration ------------------------------------------


def test_sync_up_to_date() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = setup(Path(d))
        assert run(rk.cmd_init, repo, ["software", "paper"], "full", "user")[0] == 0
        code, out = run(rk.cmd_sync, repo, False, False)
        assert code == 0 and "up to date" in out, out


def test_sync_updates_kind() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = setup(Path(d))
        assert run(rk.cmd_init, repo, ["software"], "full", "user")[0] == 0
        kfile: Path = repo / "pm/kinds/software.md"
        old: str = kfile.read_text()
        tpl: Path = rk.TEMPLATE_DIR / "kinds/software.md"
        # Version bump + new rule: the old stamp must not count as a drop.
        new_tpl: str = tpl.read_text().replace(": T1 -->", ": T2 -->") + "new rule\n"
        tpl.write_text(new_tpl)
        code, out = run(rk.cmd_sync, repo, False, False)
        assert code == 0 and "+new rule" in out and "DROPPED" not in out, out
        assert kfile.read_text() == old
        code, out = run(rk.cmd_sync, repo, True, False)
        assert code == 0, out
        assert kfile.read_text() == new_tpl
        assert "up to date" in run(rk.cmd_sync, repo, False, False)[1]


def test_sync_kind_drop_refused() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = setup(Path(d))
        assert run(rk.cmd_init, repo, ["software"], "full", "user")[0] == 0
        kfile: Path = repo / "pm/kinds/software.md"
        edited: str = kfile.read_text() + "my local line\n"
        kfile.write_text(edited)
        code, out = run(rk.cmd_sync, repo, False, False)
        assert code == 0 and "DROPPED" in out and "my local line" in out, out
        code, out = run(rk.cmd_sync, repo, True, False)
        assert code == 2, out
        assert kfile.read_text() == edited
        code, out = run(rk.cmd_sync, repo, True, True)
        assert code == 0, out
        assert kfile.read_text() == (rk.TEMPLATE_DIR / "kinds/software.md").read_text()


def test_migrate_legacy_moves_nothing() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = setup(Path(d))
        legacy: str = (
            "<!-- paper-playbook: 2026-11-12d -->\n# old\nold rule\n"
            "## Project appendix\nmine\n"
        )
        (repo / "AGENTS.md").write_text(legacy)
        (repo / "WASTE").mkdir()
        (repo / "WASTE/x").write_text("x\n")
        (repo / "paper/stages/01").mkdir(parents=True)
        (repo / "paper/stages/01/README.md").write_text("stage 01\n")
        assert rk.is_legacy(legacy)
        assert run(rk.cmd_add_kind, repo, "software")[0] == 1
        assert run(rk.cmd_upgrade, repo)[0] == 1
        before: dict[str, bytes | None] = snapshot(repo)

        code, out = run(rk.cmd_sync, repo, False, False)
        assert code == 0 and "DROPPED" in out and "old rule" in out, out
        assert snapshot(repo) == before, "dry run wrote something"
        code, out = run(rk.cmd_sync, repo, True, False)
        assert code == 2, out
        assert snapshot(repo) == before, "refused write wrote something"

        code, out = run(rk.cmd_sync, repo, True, True)
        assert code == 0, out
        after: dict[str, bytes | None] = snapshot(repo)
        for k, v in before.items():  # nothing moved or changed except AGENTS.md
            if k != "AGENTS.md":
                assert after.get(k, b"<gone>") == v, k
        text: str = (repo / "AGENTS.md").read_text()
        assert not rk.is_legacy(text) and "old rule" not in text, text
        app: str = appendix(repo)
        assert "mine" in app, app
        assert rk.get_field(app, "Legacy stages") == "paper/stages/", app
        assert rk.get_field(app, "Legacy waste") == "WASTE/", app
        assert rk.get_field(app, "Mode") == "full", app
        assert rk.get_field(app, "Git policy") == "user commits", app
        assert rk.active_kinds(app) == ["paper"], app
        assert (repo / "pm/kinds/paper.md").is_file()
        assert (repo / "pm/stages").is_dir()
        assert "up to date" in run(rk.cmd_sync, repo, False, False)[1]


# ---- Tasks 5-8: real template content (other teammates deliver it) -----------


def test_template_core() -> None:
    text: str = (REAL_TEMPLATE / "AGENTS.md").read_text()
    n: int = len(text.splitlines())
    assert n <= 300, f"core template has {n} lines (> 300)"
    need: tuple[str, ...] = (
        "## Project appendix",
        "<!-- rk:kinds -->",
        "Mode:",
        "Git policy:",
        "CONFIRMED",
        "Done when",
        "pm/DEFERRED.md",
        "research-kit:worker-high",
    )
    missing: list[str] = [s for s in need if s not in text]
    assert not missing, f"core template lacks: {missing}"
    assert "paper-playbook" not in text, "core template mentions paper-playbook"


def _cells(row: str) -> list[str]:
    return [c.strip().strip("*` ").strip() for c in row.strip().strip("|").split("|")]


def _stage_table_problems(text: str) -> list[str]:
    """Each data row of a table whose header has a 'Stage' cell needs Done when."""
    problems: list[str] = []
    tables: list[list[str]] = []
    cur: list[str] = []
    for ln in [*text.splitlines(), ""]:
        if ln.lstrip().startswith("|"):
            cur.append(ln)
        elif cur:
            tables.append(cur)
            cur = []
    for rows in tables:
        header: list[str] = [c.lower() for c in _cells(rows[0])]
        if not any("stage" in c for c in header):
            continue
        col: int | None = header.index("done when") if "done when" in header else None
        for row in rows[1:]:
            if re.fullmatch(r"\s*\|?[\s:|-]+\|?\s*", row):
                continue  # separator row
            cells: list[str] = _cells(row)
            ok: bool = "done when" in row.lower() or (
                col is not None and col < len(cells) and bool(cells[col])
            )
            if not ok:
                problems.append(f"stage row without Done when: {row.strip()[:60]}")
    return problems


def test_kind_files() -> None:
    problems: list[str] = []
    for k in rk.KINDS:
        path: Path = REAL_TEMPLATE / "kinds" / f"{k}.md"
        if not path.is_file():
            problems.append(f"{k}: missing {path.name}")
            continue
        text: str = path.read_text()
        lines: list[str] = text.splitlines()
        if not lines or not re.fullmatch(
            rf"<!-- research-kit-kind {re.escape(k)}: \S+ -->", lines[0]
        ):
            problems.append(f"{k}: line 1 is not the research-kit-kind stamp")
        cap: int = 200 if k == "paper" else 150
        if len(lines) > cap:
            problems.append(f"{k}: {len(lines)} lines (> {cap})")
        if "paper-playbook" in text:
            problems.append(f"{k}: mentions paper-playbook")
        if "|" not in text and "Done when" not in text:
            problems.append(f"{k}: no stage table / Done when (placeholder?)")
        problems += [f"{k}: {p}" for p in _stage_table_problems(text)]
    assert not problems, "\n    ".join(["kind file problems:", *problems])


def test_init_real_template() -> None:
    """Round trip on the shipped template (needs Task 5 core AGENTS.md)."""
    with tempfile.TemporaryDirectory() as d:
        repo: Path = Path(d)
        code, out = run(rk.cmd_init, repo, ["software", "paper"], "full", "user")
        assert code == 0, out
        app: str = appendix(repo)
        assert rk.get_field(app, "Mode") == "full", app
        assert rk.get_field(app, "Git policy") == "user commits", app
        assert rk.active_kinds(app) == ["paper", "software"], app
        assert app.count("<!-- rk:kinds -->") == 1, app
        code, out = run(rk.cmd_sync, repo, False, False)
        assert code == 0 and "up to date" in out, out


def _block(repo: Path) -> str:
    return (repo / "CLAUDE.md").read_text()


def _init(repo: Path) -> None:
    code, out = run(rk.cmd_init, repo, ["software"], "light", "user")
    assert code == 0, out


def test_compact_block_created_on_init() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = setup(Path(d))
        _init(repo)
        body: str = (rk.TEMPLATE_DIR / "compact-instructions.md").read_text()
        want: str = f"{rk.CB_START}\n{body}{rk.CB_END}\n"
        assert _block(repo) == want, _block(repo)


def test_compact_block_idempotent() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = setup(Path(d))
        _init(repo)
        for _ in range(2):
            code, out = run(rk.cmd_sync, repo, True, False)
            assert code == 0 and "up to date" in out, out
        assert _block(repo).count(rk.CB_START) == 1, _block(repo)
        assert _block(repo).count(rk.CB_END) == 1, _block(repo)


def test_compact_block_preserves_user_text() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = setup(Path(d))
        _init(repo)
        above: str = "# My repo\n\nuser rule 1  \n\tuser rule 2\n\n"
        below: str = "\n## Mine\nkeep me\nno trailing newline"
        old: str = f"{rk.CB_START}\n## Compact Instructions\nOLD TEXT\n{rk.CB_END}\n"
        (repo / "CLAUDE.md").write_text(above + old + below)
        code, out = run(rk.cmd_sync, repo, True, False)
        assert code == 0, out
        text: str = _block(repo)
        assert text.startswith(above) and text.endswith(below), text
        assert "OLD TEXT" not in text and "Keep verbatim" in text, text
        assert text.count(rk.CB_START) == 1, text


def test_compact_block_appended_when_missing_markers() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = setup(Path(d))
        _init(repo)
        (repo / "CLAUDE.md").write_text("user line\n")
        code, out = run(rk.cmd_sync, repo, True, False)
        assert code == 0, out
        text: str = _block(repo)
        assert text.startswith(f"user line\n\n{rk.CB_START}\n"), text
        assert text.endswith(f"{rk.CB_END}\n") and text.count(rk.CB_START) == 1, text


def test_sync_dry_run_does_not_write_compact() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = setup(Path(d))
        _init(repo)
        (repo / "CLAUDE.md").write_text("user line\n")
        before: dict[str, bytes | None] = snapshot(repo)
        code, out = run(rk.cmd_sync, repo, False, False)
        assert code == 0 and "Compact Instructions" in out, out
        assert "DROPPED" not in out and "dry run" in out, out
        assert snapshot(repo) == before


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
        except BaseException as e:  # SystemExit from rk.split too
            failed.append(name)
            print(f"FAIL {name}: {type(e).__name__}: {e}")
            if not isinstance(e, AssertionError):
                traceback.print_exc(limit=3, file=sys.stdout)
        finally:
            rk.TEMPLATE_DIR = REAL_TEMPLATE
    if failed:
        print(f"{len(failed)} of {len(tests)} failed: {', '.join(failed)}")
        return 1
    print("all ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
