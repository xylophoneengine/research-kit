#!/usr/bin/env python3
"""Tests for rk.py. Run: python3 -I test_rk.py (prints PASS/FAIL per test)."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import re
import os
import shutil
import subprocess
import sys
import tempfile
import traceback
from collections.abc import Callable
from collections.abc import Iterator
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
RK_PY: Path = Path(__file__).with_name("rk.py")

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
    shutil.copy(REAL_TEMPLATE / "gitattributes", tpl / "gitattributes")
    shutil.copytree(REAL_TEMPLATE / "pm", tpl / "pm")
    shutil.copy(
        REAL_TEMPLATE / "compact-instructions.md", tpl / "compact-instructions.md"
    )
    shutil.copy(REAL_TEMPLATE / "global-claude.md", tpl / "global-claude.md")
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
        assert (repo / "pm/logs/team").is_dir() and not (repo / "pm/waste").exists()
        for f in ("README.md", "ledger.jsonl"):
            assert (repo / "pm" / f).is_file(), f
        assert (repo / "pm/ledger.jsonl").read_bytes() == b""
        for f in ("DECISIONS.md", "DEFERRED.md"):
            assert not (repo / "pm" / f).exists(), f
        readme: str = (repo / "pm/README.md").read_text()
        assert "## Stages" not in readme, readme
        assert "## Open handoffs" not in readme, readme


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
            assert "pm/STATUS.md" in text, text

        assert run(rk.cmd_init, repo, ["paper"], "full", "user")[0] == 0
        check()
        assert rk.ensure_gitignore(repo) is False
        check()
        for _ in range(2):
            assert run(rk.cmd_add_kind, repo, "software")[0] == 0
            check()
            assert run(rk.cmd_sync, repo, True, False)[0] == 0
            check()


def test_gitignore_keeps_team_reports_tracked() -> None:
    """The real template block ignores pm/waste/ but never the report folders."""
    exe: str | None = shutil.which("git")
    assert exe is not None, "git not found"
    with tempfile.TemporaryDirectory() as d:
        repo: Path = Path(d)
        rk.TEMPLATE_DIR = REAL_TEMPLATE
        (repo / ".gitignore").write_text(rk.gitignore_text(""))
        genv: dict[str, str] = {
            **os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"
        }
        subprocess.run([exe, "-C", d, "init", "-q"], env=genv, check=True)

        def ignored(rel: str) -> bool:
            r: subprocess.CompletedProcess[bytes] = subprocess.run(
                [exe, "-C", d, "check-ignore", "-q", rel], env=genv, capture_output=True
            )
            assert r.returncode in (0, 1), r
            return r.returncode == 0

        assert ignored("pm/waste/team/x/sr1-r1.md")
        for rel in ("pm/logs/team/2026-11-14-1916/sr1-r1.md",
                    "pm/stages/03b-paper-scan/notes/team/sr1-r1.md"):
            assert not ignored(rel), rel


def test_gitattributes_block() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = setup(Path(d))
        assert run(rk.cmd_init, repo, ["paper"], "full", "user")[0] == 0
        ga: Path = repo / ".gitattributes"
        line: str = "pm/ledger.jsonl merge=union"
        text: str = ga.read_text()
        assert text == f"{rk.GI_START}\n{line}\n{rk.GI_END}\n", text
        above: str = "*.png binary\n"
        ga.write_text(above + text.replace(line, "OLD") + "tail")
        before: dict[str, bytes | None] = snapshot(repo)
        code, out = run(rk.cmd_sync, repo, False, False)
        assert code == 0 and "== .gitattributes ==" in out and f"+{line}" in out, out
        assert snapshot(repo) == before, "dry run wrote something"
        assert run(rk.cmd_sync, repo, True, False)[0] == 0
        text = ga.read_text()
        assert text.startswith(above) and text.endswith("tail"), text
        assert line in text and "OLD" not in text, text
        assert text.count(rk.GI_START) == 1 and text.count(rk.GI_END) == 1, text
        assert "up to date" in run(rk.cmd_sync, repo, True, False)[1]


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
        assert (repo / "pm/ledger.jsonl").is_file()
        assert "up to date" in run(rk.cmd_sync, repo, False, False)[1]


def _legacy_repo(root: Path, appendix_text: str, claude: str | None = None) -> Path:
    repo: Path = setup(root)
    (repo / "AGENTS.md").write_text(
        "<!-- paper-playbook: 1 -->\n# old\nold rule\n## Project appendix\n"
        + appendix_text
    )
    if claude is not None:
        (repo / "CLAUDE.md").write_bytes(claude.encode())
    return repo


def test_sync_dropped_line_printed_in_full() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = _legacy_repo(Path(d), "mine\n")
        tail: str = "repo-specific tail " + "x" * 600 + " END"
        text: str = (repo / "AGENTS.md").read_text()
        (repo / "AGENTS.md").write_text(text.replace("old rule", "old rule " + tail))
        out: str = run(rk.cmd_sync, repo, False, False)[1]
        assert f"  AGENTS.md | old rule {tail}\n" in out, out


def test_migrate_one_blank_line_before_appended_block() -> None:
    for app in ("mine\n", "mine", "mine\n\n", "mine\n\n\n\n"):
        with tempfile.TemporaryDirectory() as d:
            repo: Path = _legacy_repo(Path(d), app)
            assert run(rk.cmd_sync, repo, True, True)[0] == 0
            got: str = appendix(repo)
            assert got.startswith("## Project appendix\nmine\n\nMode: full\n"), got
            assert "\n\n\n" not in got, repr(got)
            assert "up to date" in run(rk.cmd_sync, repo, False, False)[1]


def test_migrate_appendix_with_fields_gets_no_blank() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = _legacy_repo(Path(d), "Mode: light\nGit policy: x\nmine\n")
        assert run(rk.cmd_sync, repo, True, True)[0] == 0
        got: str = appendix(repo)
        assert got.startswith(
            "## Project appendix\nMode: full\nGit policy: user commits\nmine\n"
        ), got


def test_migrate_claude_md_pointer() -> None:
    claude: str = (
        "Read paper/README.md first.\n"
        "See docs/paper/README.md and xpaper/README.md and paper/README.mdx.\n"
        "Also `paper/README.md`.\n"
    )
    want: str = claude.replace("Read paper/", "Read pm/").replace("`paper/", "`pm/")
    with tempfile.TemporaryDirectory() as d:
        repo: Path = _legacy_repo(Path(d), "mine\n", claude)
        before: dict[str, bytes | None] = snapshot(repo)
        code, out = run(rk.cmd_sync, repo, False, False)
        assert code == 0 and "pointer paper/README.md -> pm/README.md" in out, out
        assert snapshot(repo) == before, "dry run wrote something"
        assert run(rk.cmd_sync, repo, True, True)[0] == 0
        got: bytes = (repo / "CLAUDE.md").read_bytes()
        assert got.decode().startswith(want), got
        # the research-kit block is appended after the untouched text
        assert b"research-kit:compact" in got
        assert "up to date" in run(rk.cmd_sync, repo, False, False)[1]


def test_pointer_dot_slash_yes_dot_dot_slash_no() -> None:
    old: str = "a ./paper/README.md b ../paper/README.md c x./paper/README.md\n"
    want: str = "a ./pm/README.md b ../paper/README.md c x./paper/README.md\n"
    assert rk.repoint_paper_readme(old) == want, rk.repoint_paper_readme(old)


def test_claude_md_pointer_only_for_legacy() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = setup(Path(d))
        assert run(rk.cmd_init, repo, ["paper"], "full", "user")[0] == 0
        text: str = (repo / "CLAUDE.md").read_text() + "see paper/README.md\n"
        (repo / "CLAUDE.md").write_text(text)
        code, out = run(rk.cmd_sync, repo, True, True)
        assert code == 0 and "up to date" in out, out
        assert (repo / "CLAUDE.md").read_text() == text


def test_help_usage_lists_ledger_commands() -> None:
    r: subprocess.CompletedProcess[str] = subprocess.run(
        [sys.executable, "-I", str(RK_PY), "--help"], capture_output=True, text=True
    )
    usage: str = r.stdout.split("\n\n", 1)[0]
    positional: str = r.stdout.split("positional arguments:", 1)[1]
    positional = positional.split("options:", 1)[0]
    cmds: tuple[str, ...] = (
        "sync", "add", "import", "list", "stage-close", "stage-open",
        "stage-rename", "brief-check", "shelve",
    )
    for cmd in cmds:
        assert re.search(rf"[{{,]{cmd}[,}}]", usage), usage
        assert re.search(rf"[{{,]{cmd}[,}}]", positional), positional
    assert "rk.py shelve ID --note TEXT" in r.stdout, r.stdout  # the reference


def test_help_usage_lists_staged_and_land() -> None:  # spec-staged-status, D-50/51
    r: subprocess.CompletedProcess[str] = subprocess.run(
        [sys.executable, "-I", str(RK_PY), "--help"], capture_output=True, text=True
    )
    usage: str = r.stdout.split("\n\n", 1)[0]
    for cmd in ("staged", "land"):
        assert re.search(rf"[{{,]{cmd}[,}}]", usage), usage
    assert "rk.py staged ID [ID ...] --note TEXT [--ref PATH]..." in r.stdout
    assert "rk.py land --note TEXT [--ref PATH]... [--stage S] [ID ...]" in r.stdout


# ---- Tasks 5-8: real template content (other teammates deliver it) -----------


def test_template_core() -> None:
    text: str = (REAL_TEMPLATE / "AGENTS.md").read_text()
    n: int = len(text.splitlines())
    assert n <= 300, f"core template has {n} lines (> 300)"
    assert not re.search(r"\b(haiku|sonnet|opus|fable)\b", text, re.IGNORECASE)
    need: tuple[str, ...] = (
        "## Project appendix",
        "<!-- rk:kinds -->",
        "Mode:",
        "Git policy:",
        "CONFIRMED",
        "Done when",
        "pm/ledger.jsonl",
        "rk stage-close",
        "rk stage-open",
        "TASK: T-",
        "manual handoff/archive",
        "Briefs and reports on disk",
    )
    missing: list[str] = [s for s in need if s not in text]
    assert not missing, f"core template lacks: {missing}"
    for gone in (
        "DECISIONS.md",
        "DEFERRED.md",
        "NEXT_STEPS",
        "TASKS.md",
        "FETCH_FAILED",
        "Open handoffs",
        "open-handoffs",
    ):
        assert gone not in text, gone
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


def test_global_rules() -> None:
    with tempfile.TemporaryDirectory() as d:
        setup(Path(d))
        f: Path = Path(d) / "home" / "CLAUDE.md"
        before: dict[str, bytes | None] = snapshot(Path(d))
        code, out = run(rk.cmd_global_rules, f, False)
        assert code == 0 and "dry run" in out and "team roles" in out, out
        assert snapshot(Path(d)) == before and not f.exists()
        code, out = run(rk.cmd_global_rules, f, True)
        body: str = (rk.TEMPLATE_DIR / "global-claude.md").read_text()
        want: str = f"{rk.GB_START}\n{body}{rk.GB_END}\n"
        assert code == 0 and f.read_text() == want, f.read_text()
        _, out = run(rk.cmd_global_rules, f, True)
        assert out == "up to date\n" and f.read_text() == want, out
        above: str = "# Mine\n\n\tuser rule  \n"
        below: str = "\n## Tail\nno trailing newline"
        f.write_text(above + want.replace("team roles", "OLD") + below)
        run(rk.cmd_global_rules, f, True)
        text: str = f.read_text()
        assert text == above + want + below, text
        assert rk.CB_START not in text


def test_ledger_end_to_end() -> None:
    """Spec 9: open, spawn, close, decide, supersede; no git call; one file dirty."""
    real_git: str | None = shutil.which("git")
    assert real_git is not None, "git not found"
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        repo: Path = root / "repo"
        repo.mkdir()
        code, out = run(rk.cmd_init, repo, ["software"], "full", "user")
        assert code == 0, out
        fake: Path = root / "fakebin"
        fake.mkdir()
        marker: Path = root / "git-called"
        script: Path = fake / "git"
        script.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
        script.chmod(0o755)
        genv: dict[str, str] = {
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
        }
        git: list[str] = [
            real_git, "-C", str(repo), "-c", "user.name=t",
            "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
            "-c", "core.hooksPath=/dev/null",
        ]  # fmt: skip
        for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "base"]):
            r = subprocess.run([*git, *args], env=genv, capture_output=True, text=True)
            assert r.returncode == 0, r.stderr
        tenv: dict[str, str] = {**os.environ, "PATH": f"{fake}:{os.environ['PATH']}"}

        def tool(*argv: str, stdin: str = "") -> str:
            r = subprocess.run(
                [sys.executable, "-I", str(RK_PY), *argv, "--repo", str(repo)],
                env=tenv, input=stdin, capture_output=True, text=True,
            )  # fmt: skip
            assert r.returncode == 0, (argv, r.stdout, r.stderr)
            return r.stdout

        tool("add", "stage", "software-x", "--open")
        tool("add", "task", "build", "--owner", "sr1", "--note", "n")
        tool(
            "brief-check", "--who", "hook",
            stdin="You are sr1\nDELIVERABLE: d\nTASK: T-1\n",
        )  # fmt: skip
        tool("close", "T-1", "--note", "done", "--ref", "AGENTS.md")  # must exist
        tool("add", "decision", "metric dE76", "--owner", "user")
        tool("supersede", "D-1", "metric dE00", "--owner", "user")
        assert not marker.exists(), "the tool called git"
        status: str = (repo / "pm" / "STATUS.md").read_text()
        recent: str = status.split("## Recent decisions", 1)[1].split("\n## ", 1)[0]
        assert "D-2" in recent and "D-1" not in status and "T-1" not in status, status
        stages: str = status.split("## Stages", 1)[1].split("\n## ", 1)[0]
        assert "S-1" in stages, status
        r = subprocess.run(
            [*git, "status", "--porcelain"], env=genv, capture_output=True, text=True
        )
        assert r.stdout == " M pm/ledger.jsonl\n", r.stdout


# ---- local-only mode (S-4, design-local-only-mode R2 to R14; W1: red first) ---
# `rk init|sync --pm local` declares pm/config.json {"pm": "local"} and writes
# a block into git's exclude file instead of .gitignore/.gitattributes. Texts
# are those of design I4 (block) and I5 (output lines).

START_LOCAL: str = "# >>> research-kit (local only)"


def block(prefix: str = "") -> str:
    """The exclude block of design I4 (addendum v2, D-76, D-77, D-78): anchored to
    the repo folder, `prefix` = its path below the git top level ("" or "sub/");
    its start line carries the prefix (D-78), so each kit folder owns a block."""
    body: str = "".join(
        f"/{prefix}{p}\n" for p in ("pm/", "AGENTS.md", "CLAUDE.md", "**/_dry/")
    )
    start: str = f"{START_LOCAL} {prefix}" if prefix else START_LOCAL
    return f"{start}\n{body}# <<< research-kit\n"


BLOCK: str = block()  # a repo folder at the git top level
# the block of the first build: same markers, unanchored lines
LEGACY_BLOCK: str = (
    f"{START_LOCAL}\npm/\nAGENTS.md\nCLAUDE.md\n_dry/\n# <<< research-kit\n"
)
OLD_BLOCK: str = f"{START_LOCAL}\nOLD\n# <<< research-kit\n"
TRACKED_BLOCK: str = "# >>> research-kit\npm/waste/\n# <<< research-kit\n"
CONFIG_LOCAL: str = '{\n  "pm": "local"\n}\n'
CONFIG_TRACKED: str = '{\n  "pm": "tracked"\n}\n'
NO_GIT: str = "no git repo: exclude block not written"
REFUSAL: str = (
    "pm/ has files in git; local-only needs them untracked first "
    "(git rm -r --cached pm/ is yours to run)"
)
NOTE_EXCLUDE: str = (
    "note: .git/info/exclude holds a research-kit block; remove it by hand"
)
BROKEN: list[tuple[str, str]] = [  # (file text, <what> of design I2)
    ("[1]\n", "not a JSON object"),
    ("{torn", "not a JSON object"),
    ('{"pm": "x"}', '"pm" must be "local" or "tracked"'),
    ('{"pm": 1}', '"pm" must be "local" or "tracked"'),
]


def runk(fn: Callable[..., int], *args: object, **kw: object) -> tuple[int, str]:
    """Like run, with keyword arguments (pm=...)."""
    buf: io.StringIO = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code: int = fn(*args, **kw)
    return code, buf.getvalue()


@contextlib.contextmanager
def _path(value: str) -> Iterator[None]:
    """PATH set to `value`, restored afterwards."""
    old: str | None = os.environ.get("PATH")
    os.environ["PATH"] = value
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = old


def _fake_git(root: Path) -> tuple[Path, str]:
    """A git on PATH that only touches a marker: (marker, PATH value)."""
    fake: Path = root / "fakebin"
    fake.mkdir()
    marker: Path = root / "git-called"
    script: Path = fake / "git"
    script.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
    script.chmod(0o755)
    return marker, f"{fake}{os.pathsep}{os.environ['PATH']}"


def _g(repo: Path, *args: str) -> str:
    """A real git command in `repo` without the user's config; its stdout."""
    exe: str | None = shutil.which("git")
    assert exe is not None, "git not found"
    r: subprocess.CompletedProcess[str] = subprocess.run(
        [exe, "-C", str(repo), "-c", "user.name=t",
         "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
         "-c", "core.hooksPath=/dev/null", *args],
        env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1",
             "GIT_CONFIG_GLOBAL": "/dev/null"},
        capture_output=True, text=True,
    )  # fmt: skip
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout


def _git_repo(root: Path) -> Path:
    """setup(root) plus `git init` in its repo dir."""
    repo: Path = setup(root)
    _g(repo, "init", "-q")
    return repo


def _tree(repo: Path) -> dict[str, bytes | None]:
    """snapshot without .git (git's own files change by themselves)."""
    return {
        k: v for k, v in snapshot(repo).items()
        if k != ".git" and not k.startswith(".git/")
    }


def _excl(repo: Path) -> Path:
    return repo / ".git/info/exclude"


def _excl_text(repo: Path) -> str:
    return _excl(repo).read_text() if _excl(repo).exists() else ""


def _created_line(out: str) -> str:
    return next(ln for ln in out.splitlines() if ln.startswith("created pm/"))


# R2: a repo that is not local runs no git command (a guard: green before the
# build, must stay green)
def test_local_r2_no_git_without_pm() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        repo: Path = setup(root)
        marker, path = _fake_git(root)
        with _path(path):
            assert run(rk.cmd_init, repo, ["paper"], "light", "user")[0] == 0
            assert run(rk.cmd_sync, repo, False, False)[0] == 0
            assert run(rk.cmd_sync, repo, True, False)[0] == 0
            assert run(rk.cmd_add_kind, repo, "software")[0] == 0
            assert run(rk.cmd_upgrade, repo)[0] == 0
            (repo / "pm/config.json").write_text(CONFIG_TRACKED)  # declared
            assert run(rk.cmd_sync, repo, True, False)[0] == 0
            assert run(rk.cmd_add_kind, repo, "thesis")[0] == 0
        assert not marker.exists(), "rk ran git in a tracked repo"


# R2, design D1: `--pm tracked` on a repo that is not local runs no git command
# and writes no pm/config.json
def test_local_r2_pm_tracked_runs_no_git() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        repo: Path = setup(root)
        marker, path = _fake_git(root)
        with _path(path):
            code, out = runk(
                rk.cmd_init, repo, ["paper"], "light", "user", pm="tracked"
            )
            assert code == 0, out
            for write in (False, True):
                code, out = runk(rk.cmd_sync, repo, write, False, pm="tracked")
                assert code == 0, out
        assert not marker.exists(), "rk ran git for --pm tracked"
        assert not (repo / "pm/config.json").exists()


# I6: the CLI flag `--pm {local,tracked}` on init and sync
def test_local_cli_pm_flag() -> None:
    def cli(*argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-I", str(RK_PY), *argv], capture_output=True, text=True
        )

    with tempfile.TemporaryDirectory() as d:
        repo: Path = Path(d) / "repo"
        repo.mkdir()
        for sub in ("init", "sync"):
            assert "--pm {local,tracked}" in cli(sub, "--help").stdout, sub
        init: list[str] = ["init", str(repo), "--kinds", "paper", "--mode", "light"]
        bad: subprocess.CompletedProcess[str] = cli(*init, "--pm", "bogus")
        assert bad.returncode == 2 and list(repo.iterdir()) == [], bad
        r: subprocess.CompletedProcess[str] = cli(*init, "--pm", "local")
        assert r.returncode == 0, (r.stdout, r.stderr)
        assert (repo / "pm/config.json").read_text() == CONFIG_LOCAL
        assert NO_GIT in r.stdout, r.stdout  # a temp dir is no git repo
        r = cli("sync", str(repo), "--pm", "tracked")
        assert r.returncode == 0 and "== pm/config.json ==" in r.stdout, r.stdout
        assert (repo / "pm/config.json").read_text() == CONFIG_LOCAL  # dry run


# R4: broken config: init, sync (dry run and write), add-kind, upgrade exit 1,
# print a line with `pm/config.json: <what>` and write nothing
def test_local_broken_config_writes_nothing() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        repo: Path = setup(root)
        assert run(rk.cmd_init, repo, ["paper"], "light", "user")[0] == 0
        fresh: Path = root / "fresh"  # init: no AGENTS.md yet
        (fresh / "pm").mkdir(parents=True)
        for text, what in BROKEN:
            want: str = f"pm/config.json: {what}"
            (repo / "pm/config.json").write_text(text)
            before: dict[str, bytes | None] = _tree(repo)
            calls: list[tuple[str, Callable[..., int], tuple[object, ...]]] = [
                ("sync", rk.cmd_sync, (repo, False, False)),
                ("sync --write", rk.cmd_sync, (repo, True, False)),
                ("add-kind", rk.cmd_add_kind, (repo, "software")),
                ("upgrade", rk.cmd_upgrade, (repo,)),
            ]
            for name, fn, args in calls:
                code, out = run(fn, *args)
                assert code == 1 and want in out, (name, text, out)
                assert _tree(repo) == before, (name, text)
            (fresh / "pm/config.json").write_text(text)
            before = _tree(fresh)
            code, out = run(rk.cmd_init, fresh, ["paper"], "light", "user")
            assert code == 1 and want in out, ("init", text, out)
            assert _tree(fresh) == before, ("init", text)


# R8, I5i: a local repo's init, sync, add-kind and upgrade neither create nor
# change .gitignore and .gitattributes
def test_local_never_touches_gitignore_files() -> None:
    for present in (False, True):
        with tempfile.TemporaryDirectory() as d:
            repo: Path = _git_repo(Path(d))
            gi: Path = repo / ".gitignore"
            ga: Path = repo / ".gitattributes"
            if present:
                gi.write_bytes(b"keep-me/")  # no newline at the end on purpose
                ga.write_bytes(b"*.png binary")
            steps: list[tuple[str, Callable[[], tuple[int, str]]]] = [
                ("init", lambda: runk(
                    rk.cmd_init, repo, ["paper"], "light", "user", pm="local")),
                ("add-kind", lambda: run(rk.cmd_add_kind, repo, "software")),
                ("upgrade", lambda: run(rk.cmd_upgrade, repo)),
                ("sync", lambda: run(rk.cmd_sync, repo, True, False)),
            ]  # fmt: skip
            for name, step in steps:
                code, out = step()
                assert code == 0, (name, out)
                if name == "init":
                    line: str = _created_line(out)
                    assert "pm/config.json" in line, line
                    assert ".gitignore" not in line, line
                    assert ".gitattributes" not in line, line
                if present:
                    assert gi.read_bytes() == b"keep-me/", (name, gi.read_bytes())
                    assert ga.read_bytes() == b"*.png binary", name
                else:
                    assert not gi.exists() and not ga.exists(), name


# R9, I1, I4, I5i: init in a git repo: config, one exclude block, nothing else
def test_local_init_in_git_repo() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = _git_repo(Path(d))
        old: str = _excl_text(repo)
        code, out = runk(rk.cmd_init, repo, ["paper"], "full", "user", pm="local")
        assert code == 0, out
        assert (repo / "pm/config.json").read_text() == CONFIG_LOCAL
        text: str = _excl(repo).read_text()
        assert text.startswith(old) and text.endswith(BLOCK), text
        assert text.count(START_LOCAL) == 1 and text.count(rk.GI_END) == 1, text
        assert not (repo / ".gitignore").exists(), "init wrote .gitignore"
        assert not (repo / ".gitattributes").exists(), "init wrote .gitattributes"
        line: str = _created_line(out)
        assert "pm/config.json" in line and ".git/info/exclude" in line, line
        assert ".gitignore" not in line and ".gitattributes" not in line, line
        assert _g(repo, "status", "--porcelain") == "", "something is not excluded"
        _g(repo, "check-ignore", "-q", "pm/ledger.jsonl")  # rc 0: ignored


# R9: text outside the markers stays byte-equal; a 0.2.5 tracked block in the
# exclude file (start line `# >>> research-kit`) is never matched by the block
def test_local_exclude_block_keeps_text_outside() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        (root / "a").mkdir()
        repo: Path = _git_repo(root / "a")  # appended after other text
        above: str = f"# mine\nmy/\n{TRACKED_BLOCK}\nmid/\n"
        _excl(repo).write_text(above)
        code, out = runk(rk.cmd_init, repo, ["paper"], "full", "user", pm="local")
        assert code == 0, out
        text: str = _excl(repo).read_text()
        assert text.startswith(above) and text.endswith(BLOCK), text
        assert text.count(START_LOCAL) == 1, text
        (root / "b").mkdir()
        repo = _git_repo(root / "b")  # last line without a newline
        _excl(repo).write_text("mine/")
        assert runk(rk.cmd_init, repo, ["paper"], "full", "user", pm="local")[0] == 0
        text = _excl(repo).read_text()
        assert text.startswith("mine/\n") and text.endswith(BLOCK), text
        assert text.count(START_LOCAL) == 1, text
        (root / "c").mkdir()
        repo = _git_repo(root / "c")  # an old block is refreshed in place
        below: str = "\nbelow/\nno-newline-at-end"
        _excl(repo).write_text(above + OLD_BLOCK + below)
        assert runk(rk.cmd_init, repo, ["paper"], "full", "user", pm="local")[0] == 0
        assert _excl(repo).read_text() == above + BLOCK + below, _excl(repo).read_text()


# R9, I5e: sync --write refreshes the block in place; a second run changes
# nothing (same bytes); one block after every run
def test_local_exclude_block_twice_same_bytes() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = _git_repo(Path(d))
        assert runk(rk.cmd_init, repo, ["paper"], "full", "user", pm="local")[0] == 0
        done: bytes = _excl(repo).read_bytes()
        code, out = run(rk.cmd_sync, repo, True, False)
        assert code == 0 and "up to date" in out, out
        assert _excl(repo).read_bytes() == done
        _excl(repo).write_text(_excl(repo).read_text().replace(BLOCK, OLD_BLOCK))
        for want in ("wrote .git/info/exclude", "up to date"):  # refresh, then none
            code, out = run(rk.cmd_sync, repo, True, False)
            assert code == 0 and want in out, (want, out)
            assert ("wrote " in out) == (want != "up to date"), out
            assert _excl(repo).read_bytes() == done, _excl(repo).read_text()
            assert _excl(repo).read_text().count(START_LOCAL) == 1


def _ignored(top: Path, rel: str) -> bool:
    """Does git (run at `top`, the git top level) ignore the path `rel`?"""
    exe: str | None = shutil.which("git")
    assert exe is not None, "git not found"
    r: subprocess.CompletedProcess[bytes] = subprocess.run(
        [exe, "-C", str(top), "check-ignore", "-q", "--no-index", rel],
        env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1",
             "GIT_CONFIG_GLOBAL": "/dev/null"},
        capture_output=True,
    )  # fmt: skip
    assert r.returncode in (0, 1), r
    return r.returncode == 0


# R9 (a), D-77, addendum v2: top-level repo: the block is anchored; `_dry/` at
# any depth is ignored
def test_local_exclude_block_anchored_top_level() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = _git_repo(Path(d))
        assert runk(rk.cmd_init, repo, ["paper"], "full", "user", pm="local")[0] == 0
        assert _excl(repo).read_text().endswith(BLOCK), _excl(repo).read_text()
        assert "/pm/\n/AGENTS.md\n/CLAUDE.md\n/**/_dry/\n" in BLOCK
        for rel in ("pm/f", "AGENTS.md", "CLAUDE.md", "_dry/f", "x/_dry/f"):
            assert _ignored(repo, rel), rel
        for rel in ("x/pm/f", "x/CLAUDE.md", "x/AGENTS.md", "template/pm/f"):
            assert not _ignored(repo, rel), rel


# R9 (b), D-77: repo folder `sub/` of a git repo: the lines carry `/sub/`
def test_local_exclude_block_anchored_in_subfolder() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        rk.TEMPLATE_DIR = fake_template(root)
        top: Path = root / "top"
        sub: Path = top / "sub"
        sub.mkdir(parents=True)
        _g(top, "init", "-q")
        assert runk(rk.cmd_init, sub, ["paper"], "full", "user", pm="local")[0] == 0
        assert _excl(top).read_text().endswith(block("sub/")), _excl(top).read_text()
        assert _excl(top).read_text().count(START_LOCAL) == 1
        lines: str = "/sub/pm/\n/sub/AGENTS.md\n/sub/CLAUDE.md\n/sub/**/_dry/\n"
        assert lines in block("sub/")  # the helper itself
        for rel in ("sub/pm/f", "sub/AGENTS.md", "sub/CLAUDE.md", "sub/_dry/f",
                    "sub/x/_dry/f"):
            assert _ignored(top, rel), rel
        for rel in ("pm/f", "sub/x/pm/f", "_dry/f", "AGENTS.md", "sub/x/CLAUDE.md"):
            assert not _ignored(top, rel), rel
        assert _g(top, "status", "--porcelain") == "", "not excluded in sub/"
        before: bytes = _excl(top).read_bytes()  # sync --write: the same bytes
        code, out = run(rk.cmd_sync, sub, True, False)
        assert code == 0 and _excl(top).read_bytes() == before, out


# R9 (c), addendum v2: a file with the first build's unanchored block ends with
# exactly one anchored block, the text outside the markers byte-equal (init and
# sync --write)
def test_local_exclude_block_unanchored_rewritten() -> None:
    above: str = "# mine\nmy/\n\n"
    below: str = "\nbelow/\nno-newline-at-end"
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        (root / "a").mkdir()
        repo: Path = _git_repo(root / "a")
        _excl(repo).write_text(above + LEGACY_BLOCK + below)
        assert runk(rk.cmd_init, repo, ["paper"], "full", "user", pm="local")[0] == 0
        assert _excl(repo).read_text() == above + BLOCK + below, _excl(repo).read_text()
        (root / "b").mkdir()
        repo = _git_repo(root / "b")
        assert runk(rk.cmd_init, repo, ["paper"], "full", "user", pm="local")[0] == 0
        _excl(repo).write_text(above + LEGACY_BLOCK + below)
        code, out = run(rk.cmd_sync, repo, True, False)
        assert code == 0 and "wrote .git/info/exclude" in out, out
        text: str = _excl(repo).read_text()
        assert text == above + BLOCK + below, text
        assert text.count(START_LOCAL) == 1 and "\n_dry/\n" not in text, text


# R9, I5e: in a linked worktree the file written is the main checkout's
# .git/info/exclude (pattern test_gitignore_keeps_team_reports_tracked: real git)
def test_local_worktree_writes_main_exclude() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        main: Path = _git_repo(root)
        (main / "README.md").write_text("x\n")
        _g(main, "add", "README.md")
        _g(main, "commit", "-q", "-m", "c")
        wt: Path = root / "wt"
        _g(main, "worktree", "add", "-q", "-b", "wtb", str(wt))
        assert (wt / ".git").is_file()
        code, out = runk(rk.cmd_init, wt, ["paper"], "full", "user", pm="local")
        assert code == 0, out
        text: str = _excl(main).read_text()
        assert text.endswith(BLOCK) and text.count(START_LOCAL) == 1, text
        assert ".git/info/exclude" in _created_line(out), out
        assert _g(wt, "status", "--porcelain") == "", "not excluded in the worktree"
        _excl(main).write_text(text.replace(BLOCK, OLD_BLOCK))
        code, out = run(rk.cmd_sync, wt, True, False)  # file outside repo_dir
        assert code == 0, out
        assert "wrote .git/info/exclude" in out, out
        assert _excl(main).read_text() == text, _excl(main).read_text()


# R10, I5i: no git binary / not a git repo: no exclude file, the line, the
# config written, exit 0
def test_local_init_without_git() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        (root / "plain").mkdir()
        repo: Path = setup(root / "plain")  # not a git repo
        code, out = runk(rk.cmd_init, repo, ["paper"], "full", "user", pm="local")
        assert code == 0 and NO_GIT in out, out
        assert (repo / "pm/config.json").read_text() == CONFIG_LOCAL
        assert not (repo / ".git").exists()
        (root / "nobin").mkdir()
        (root / "bin").mkdir()
        repo = _git_repo(root / "bin")  # a repo, but git cannot run
        old: str = _excl_text(repo)
        with _path(str(root / "nobin")):
            code, out = runk(rk.cmd_init, repo, ["paper"], "full", "user", pm="local")
        assert code == 0 and NO_GIT in out, out
        assert (repo / "pm/config.json").read_text() == CONFIG_LOCAL
        assert _excl_text(repo) == old, "the exclude file was written"
        line: str = _created_line(out)
        assert "pm/config.json" in line and ".git/info/exclude" not in line, line
        assert ".gitignore" not in line and ".gitattributes" not in line, line


# R10, I5e: the same for sync --write
def test_local_sync_write_without_git() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        (root / "plain").mkdir()
        repo: Path = setup(root / "plain")
        assert run(rk.cmd_init, repo, ["paper"], "full", "user")[0] == 0
        code, out = runk(rk.cmd_sync, repo, True, False, pm="local")
        assert code == 0 and NO_GIT in out and "wrote pm/config.json" in out, out
        assert (repo / "pm/config.json").read_text() == CONFIG_LOCAL
        assert not (repo / ".git").exists()
        (root / "nobin").mkdir()
        (root / "bin").mkdir()
        repo = _git_repo(root / "bin")
        assert run(rk.cmd_init, repo, ["paper"], "full", "user")[0] == 0
        old: str = _excl_text(repo)
        with _path(str(root / "nobin")):
            code, out = runk(rk.cmd_sync, repo, True, False, pm="local")
        assert code == 0 and NO_GIT in out and "wrote pm/config.json" in out, out
        assert (repo / "pm/config.json").read_text() == CONFIG_LOCAL
        assert _excl_text(repo) == old, "the exclude file was written"


# R11, I5d: sync without --write writes nothing, names the config and the
# exclude file, never `== .gitignore ==` or `== .gitattributes ==`
def test_local_sync_dry_run() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = _git_repo(Path(d))
        assert run(rk.cmd_init, repo, ["paper"], "full", "user")[0] == 0
        old: str = "# >>> research-kit\nOLD\n# <<< research-kit\n"
        (repo / ".gitignore").write_text(old)
        (repo / ".gitattributes").write_text(old)  # tracked: both headings
        assert "== .gitignore ==" in run(rk.cmd_sync, repo, False, False)[1]
        before: dict[str, bytes | None] = _tree(repo)
        excl: bytes = _excl(repo).read_bytes()
        code, out = runk(rk.cmd_sync, repo, False, False, pm="local")
        assert code == 0, out
        assert any(ln.startswith("== pm/config.json ==") for ln in out.splitlines())
        want: str = "== .git/info/exclude == research-kit block added/refreshed"
        assert want in out, out
        assert "== .gitignore ==" not in out, out
        assert "== .gitattributes ==" not in out, out
        assert "dry run" in out, out
        assert _tree(repo) == before and not (repo / "pm/config.json").exists()
        assert _excl(repo).read_bytes() == excl, "a dry run wrote the exclude file"


# R12, I5h: `--pm local` with files of pm/ in git: exit 1, the refusal, nothing
# written (AGENTS.md included), for init and for sync (dry run and write)
def test_local_refuses_tracked_pm() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        (root / "a").mkdir()
        repo: Path = _git_repo(root / "a")
        (repo / "pm").mkdir()
        (repo / "pm/x.md").write_text("x\n")
        _g(repo, "add", "pm/x.md")
        before: dict[str, bytes | None] = _tree(repo)
        excl: bytes = _excl(repo).read_bytes()
        code, out = runk(rk.cmd_init, repo, ["paper"], "full", "user", pm="local")
        assert code == 1 and REFUSAL in out, out
        assert _tree(repo) == before and not (repo / "AGENTS.md").exists()
        assert _excl(repo).read_bytes() == excl
        (root / "b").mkdir()
        repo = _git_repo(root / "b")
        assert run(rk.cmd_init, repo, ["paper"], "full", "user")[0] == 0
        _g(repo, "add", "pm/ledger.jsonl")
        before = _tree(repo)
        excl = _excl(repo).read_bytes()
        for write in (False, True):
            code, out = runk(rk.cmd_sync, repo, write, False, pm="local")
            assert code == 1 and REFUSAL in out, (write, out)
            assert _tree(repo) == before, write
            assert _excl(repo).read_bytes() == excl, write


# R13, I5g, I5e: `sync --pm tracked --write` on a local repo: config tracked,
# the 0.2.5 blocks, the exclude file byte-equal, the note
def test_local_switch_to_tracked() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = _git_repo(Path(d))
        assert runk(rk.cmd_init, repo, ["paper"], "full", "user", pm="local")[0] == 0
        excl: bytes = _excl(repo).read_bytes()
        before: dict[str, bytes | None] = _tree(repo)
        code, out = runk(rk.cmd_sync, repo, False, False, pm="tracked")  # dry run
        assert code == 0 and NOTE_EXCLUDE in out, out
        assert "== .gitignore ==" in out, out
        assert _tree(repo) == before, "a dry run wrote something"
        code, out = runk(rk.cmd_sync, repo, True, False, pm="tracked")
        assert code == 0, out
        assert NOTE_EXCLUDE in out and "wrote pm/config.json" in out, out
        assert "wrote .gitignore" in out and "wrote .gitattributes" in out, out
        assert (repo / "pm/config.json").read_text() == CONFIG_TRACKED
        assert (repo / ".gitignore").read_text() == rk.gitignore_text(""), out
        line: str = "pm/ledger.jsonl merge=union"
        want: str = f"{rk.GI_START}\n{line}\n{rk.GI_END}\n"
        assert (repo / ".gitattributes").read_text() == want
        assert _excl(repo).read_bytes() == excl, "the exclude file was changed"
        code, out = run(rk.cmd_sync, repo, True, False)  # now a tracked repo
        assert code == 0 and "up to date" in out and "note:" not in out, out


def _multi_repo(root: Path, *rels: str) -> tuple[Path, list[Path]]:
    """One git repo `root/top` and the kit folders `rels` in it (top-level folder
    = "" -> the repo root itself); (repo, folders)."""
    rk.TEMPLATE_DIR = fake_template(root)
    top: Path = root / "top"
    dirs: list[Path] = [top / rel for rel in rels]
    for folder in dirs:
        folder.mkdir(parents=True, exist_ok=True)
    _g(top, "init", "-q")
    return top, dirs


def _init_local(folder: Path) -> None:
    code, out = runk(rk.cmd_init, folder, ["paper"], "full", "user", pm="local")
    assert code == 0, out


def _block_text(text: str, start: str) -> str:
    """The block that starts with the exact line `start` ('' when none)."""
    m: re.Match[str] | None = re.search(
        rf"^{re.escape(start)}$.*?^{re.escape(rk.GI_END)}$\n?", text, re.M | re.S
    )
    return m.group(0) if m else ""


# D-78 (crit1 N1): one block per kit folder: two kit folders of one git repo
def test_local_two_kit_folders_two_blocks() -> None:
    with tempfile.TemporaryDirectory() as d:
        top, (inner, two) = _multi_repo(Path(d), "inner", "sub/two")
        _init_local(inner)
        _init_local(two)
        text: str = _excl(top).read_text()
        assert block("inner/") in text and block("sub/two/") in text, text
        assert f"{START_LOCAL} inner/\n" in text, text
        assert f"{START_LOCAL} sub/two/\n" in text, text
        assert text.count(rk.GI_END) == 2 and text.count(START_LOCAL) == 2, text
        listed: list[str] = _g(top, "status", "--porcelain").splitlines()
        for under in ("inner/pm", "inner/AGENTS.md", "sub/two/pm"):
            assert not [ln for ln in listed if under in ln], (under, listed)
        assert _ignored(top, "inner/pm/f") and _ignored(top, "sub/two/AGENTS.md")
        assert not _ignored(top, "pm/f") and not _ignored(top, "sub/pm/f")


# D-78: a kit at the git root and a kit in sub/: the root block keeps today's
# start line, the sub block carries its prefix; either init order
def test_local_root_kit_and_sub_kit_two_blocks() -> None:
    for first_root in (True, False):
        with tempfile.TemporaryDirectory() as d:
            top, (root_kit, sub) = _multi_repo(Path(d), "", "sub")
            for folder in ((root_kit, sub) if first_root else (sub, root_kit)):
                _init_local(folder)
            text: str = _excl(top).read_text()
            assert START_LOCAL in text.splitlines(), (first_root, text)  # root
            assert f"{START_LOCAL} sub/" in text.splitlines(), (first_root, text)
            assert block() in text and block("sub/") in text, (first_root, text)
            assert text.count(rk.GI_END) == 2, (first_root, text)
            assert _g(top, "status", "--porcelain") == "", first_root


# D-78: a rerun (sync --pm local --write) in one folder neither duplicates its
# block nor touches the other folder's block (byte-equal, also a changed one)
def test_local_rerun_leaves_other_block() -> None:
    with tempfile.TemporaryDirectory() as d:
        top, (inner, two) = _multi_repo(Path(d), "inner", "sub/two")
        _init_local(inner)
        _init_local(two)
        done: bytes = _excl(top).read_bytes()
        code, out = runk(rk.cmd_sync, inner, True, False, pm="local")
        assert code == 0 and _excl(top).read_bytes() == done, out
        s_inner: str = f"{START_LOCAL} inner/"
        s_two: str = f"{START_LOCAL} sub/two/"
        text: str = done.decode()
        stale: str = text.replace(
            _block_text(text, s_inner), f"{s_inner}\nOLD\n{rk.GI_END}\n"
        ).replace(_block_text(text, s_two), f"{s_two}\nOLD\n{rk.GI_END}\n")
        _excl(top).write_text(stale)
        code, out = runk(rk.cmd_sync, inner, True, False, pm="local")
        assert code == 0 and "wrote .git/info/exclude" in out, out
        now: str = _excl(top).read_text()
        assert _block_text(now, s_inner) == block("inner/"), now  # refreshed
        assert _block_text(now, s_two) == f"{s_two}\nOLD\n{rk.GI_END}\n", now
        assert now.count(s_inner) == 1 and now.count(s_two) == 1, now
        assert now.count(rk.GI_END) == 2, now


# D-78: switch back to tracked in one folder (today: config tracked, the 0.2.5
# blocks, the exclude file byte-equal, the note): the other block is untouched
def test_local_switch_back_leaves_other_block() -> None:
    with tempfile.TemporaryDirectory() as d:
        top, (inner, two) = _multi_repo(Path(d), "inner", "sub/two")
        _init_local(inner)
        _init_local(two)
        done: bytes = _excl(top).read_bytes()
        code, out = runk(rk.cmd_sync, two, True, False, pm="tracked")
        assert code == 0 and NOTE_EXCLUDE in out, out
        assert (two / "pm/config.json").read_text() == CONFIG_TRACKED
        assert (inner / "pm/config.json").read_text() == CONFIG_LOCAL
        assert _excl(top).read_bytes() == done, "the exclude file was changed"
        mine: str = _block_text(done.decode(), f"{START_LOCAL} inner/")
        assert mine == block("inner/"), done.decode()  # inner's block exists


# R14, I1: a rewrite of pm/config.json keeps every other key and its value
def test_local_config_rewrite_keeps_other_keys() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = setup(Path(d))
        assert run(rk.cmd_init, repo, ["paper"], "full", "user")[0] == 0
        cfg: Path = repo / "pm/config.json"
        for text in (
            '{"x": 1, "pm": "tracked"}', '{"x": 1}', '{"pm": "tracked", "y": [1, 2]}'
        ):
            cfg.write_text(text)
            want: str = json.dumps({**json.loads(text), "pm": "local"}, indent=2)
            code, out = runk(rk.cmd_sync, repo, True, False, pm="local")
            assert code == 0, (text, out)
            assert cfg.read_text() == want + "\n", (text, cfg.read_text())
        cfg.write_text('{"x": 1, "pm": "local"}')  # back to tracked, x kept
        code, out = runk(rk.cmd_sync, repo, True, False, pm="tracked")
        assert code == 0, out
        want = json.dumps({"x": 1, "pm": "tracked"}, indent=2) + "\n"
        assert cfg.read_text() == want, cfg.read_text()


# I5g, Q2: sync in a local repo finds a research-kit block in .gitignore or
# .gitattributes: prints the note (dry run and write), removes nothing, and a
# note alone is no write
def test_local_sync_notes_existing_blocks() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = _git_repo(Path(d))
        assert runk(rk.cmd_init, repo, ["paper"], "full", "user", pm="local")[0] == 0
        gi: Path = repo / ".gitignore"
        ga: Path = repo / ".gitattributes"
        gi.write_text("mine/\n")
        ga.write_text("*.png binary\n")
        code, out = run(rk.cmd_sync, repo, False, False)
        assert code == 0 and "holds a research-kit block" not in out, out
        gi.write_text(rk.gitignore_text("mine/\n"))
        ga.write_text(f"{rk.GI_START}\npm/ledger.jsonl merge=union\n{rk.GI_END}\n")
        _g(repo, "add", ".gitignore", ".gitattributes")  # R25 (T-82): git tracks both
        before: dict[str, bytes | None] = _tree(repo)
        excl: bytes = _excl(repo).read_bytes()
        for write in (False, True):
            code, out = run(rk.cmd_sync, repo, write, False)
            assert code == 0, out
            for f in (".gitignore", ".gitattributes"):
                note: str = f"note: {f} holds a research-kit block; remove it by hand"
                assert note in out, (write, out)
            assert "wrote " not in out, out
            assert "== .gitignore ==" not in out, out
            assert _tree(repo) == before, write
            assert _excl(repo).read_bytes() == excl, write


# crit1 m3, m4: a bad `pm` value from Python is refused, writing nothing; a
# non-ASCII value of another key is written as it is
def test_local_pm_value_checked_and_utf8_kept() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = setup(Path(d))
        assert run(rk.cmd_init, repo, ["paper"], "light", "user")[0] == 0
        before: dict[str, bytes | None] = _tree(repo)
        assert runk(rk.cmd_sync, repo, True, False, pm="bogus")[0] == 1
        assert runk(rk.cmd_init, repo, ["paper"], "light", "user", pm="bogus")[0] == 1
        assert _tree(repo) == before
        cfg: Path = repo / "pm/config.json"
        cfg.write_text('{"name": "Zoë", "pm": "tracked"}', encoding="utf-8")
        assert runk(rk.cmd_sync, repo, True, False, pm="local")[0] == 0
        assert "Zoë" in cfg.read_text(encoding="utf-8")


# Q1 (D-69): add-kind and upgrade in a local repo refresh the exclude block
def test_local_add_kind_upgrade_refresh_exclude() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = _git_repo(Path(d))
        assert runk(rk.cmd_init, repo, ["paper"], "light", "user", pm="local")[0] == 0
        for fn, args in ((rk.cmd_add_kind, "software"), (rk.cmd_upgrade, None)):
            _excl(repo).write_text(OLD_BLOCK)
            code, out = run(fn, repo, *([args] if args else []))
            assert code == 0, out
            assert _excl(repo).read_text() == BLOCK, (fn.__name__, _excl(repo))
            assert not (repo / ".gitignore").exists(), fn.__name__


# ---- debt batch (S-4, design-debt-batch R1, R2, R7, R10, R22 to R25; T-82) ----
# Red first, except R1, R2 and R7 (jr1 writes those texts in parallel).

PLUGIN_ROOT: Path = RK_PY.resolve().parents[3]  # plugins/research-kit
REPO_ROOT: Path = RK_PY.resolve().parents[5]  # the repo that holds README.md


# R1: the core rule line of the design step (AGENTS.md 3.3), I3 verbatim in its
# key strings; the file stays at 300 lines and its stamp moved
def test_template_design_step() -> None:
    lines: list[str] = (REAL_TEMPLATE / "AGENTS.md").read_text().splitlines()
    text: str = "\n".join(lines)
    assert len(lines) <= 300, f"core template has {len(lines)} lines (> 300)"
    need: tuple[str, ...] = (
        "- **Design step** (every kind; before any design or plan work of a stage):",
        "(1) the lead asks the user via AskUserQuestion whether the architect "
        "(`arch1`, 2.1) does the planning",
        "(2) the lead itself holds the design talk with the user: one question at a "
        "time, discrete options via AskUserQuestion, recommended option first "
        "(section 8)",
        "(3) the spec is a file in the stage `notes/`; no code and no implementer "
        "brief before the user said yes to it",
        '(4) the yes is logged as `rk add decision "<spec approved>" --owner user '
        "--label <stage code>/SPEC --ref <spec file>`",
        "(03, 03b)",  # (T-88) was "(stage code = NN of the stage folder, ...)"
        "has no user decision labelled <stage code>/SPEC (AGENTS.md 3.3)",
        "no `rk` command is refused",
    )
    missing: list[str] = [s for s in need if s not in text]
    assert not missing, f"design step lacks: {missing}"
    assert rk.stamp(text) != "2026-11-16d", "template stamp not bumped"


# T-88 (design-step follow-up R1, R2, R5, R6, R7): one key string each; the
# stage code reads (03, 03b); no "takeover prompt"; the stamp moved
def test_template_design_step_followup() -> None:
    lines: list[str] = (REAL_TEMPLATE / "AGENTS.md").read_text().splitlines()
    text: str = "\n".join(lines)
    for s in ("the user's answer wins", "only the user decides", "(03, 03b)"):
        assert s in text, s
    assert "takeover prompt" not in text
    assert "NN of the stage folder" not in text
    assert len(lines) <= 300, f"core template has {len(lines)} lines (> 300)"
    # Independently versioned rule files keep their own stamps.
    stamp_form: str = r"\d{4}-\d{2}-\d{2}[a-z]"
    tpl: re.Match[str] | None = re.fullmatch(
        rf"<!-- research-kit: ({stamp_form}) -->", lines[0]
    )
    assert tpl is not None, lines[0]
    kind_line: str = (REAL_TEMPLATE / "kinds/software.md").read_text().splitlines()[0]
    assert re.fullmatch(rf"<!-- research-kit-kind software: {stamp_form} -->", kind_line)


# T-105 (DB-70, crit1 F5 d): 2.1 and the team skill call the architect triggers a
# recommendation in the design-step question, not the choice (R1 of the follow-up)
def test_architect_triggers_are_a_recommendation() -> None:
    def flat(path: Path) -> str:
        return " ".join(path.read_text().split())  # a wrapped line reads as one

    core: str = flat(REAL_TEMPLATE / "AGENTS.md")
    skill: str = flat(PLUGIN_ROOT / "skills/team/SKILL.md")
    for name, text in (("AGENTS.md 2.1", core), ("team SKILL.md", skill)):
        assert "recommendation in the design-step question" in text, name
        assert "not the choice" in text, name
    assert "a step 1 trigger only recommends it" in skill


# R2: the software kind's stage row 1 is the design step; its stamp moved
def test_software_kind_design_row() -> None:
    text: str = (REAL_TEMPLATE / "kinds/software.md").read_text()
    rows: list[str] = [ln for ln in text.splitlines() if ln.startswith("| 1 |")]
    assert len(rows) == 1, rows
    for s in ("core 3.3", "/SPEC", "superpowers:brainstorming", "grilling"):
        assert s in rows[0], (s, rows[0])
    stamp_line: str = text.splitlines()[0]
    assert "2026-11-14b" not in stamp_line, stamp_line


# R7: SKILL.md and README.md name the label form and the start line once
def test_design_step_named_in_skill_and_readme() -> None:
    for path in (PLUGIN_ROOT / "skills/research-kit/SKILL.md", REPO_ROOT / "README.md"):
        text: str = path.read_text()
        n: int = text.count("has no user decision labelled")
        assert n == 1, (path.name, n)
        assert "/SPEC" in text, path.name


# R10 (I6): `rk sync <worktree>` where the worktree has no pm/ (a local-only repo's
# linked worktree) reads the main checkout's config: local, no `.gitignore` block
def test_sync_in_worktree_without_pm_is_local() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        main: Path = _git_repo(root)
        assert runk(rk.cmd_init, main, ["paper"], "full", "user", pm="local")[0] == 0
        wt: Path = root / "wt"  # the ledger's linked worktree: a .git file, no pm/
        (main / ".git" / "worktrees" / "wt").mkdir(parents=True)
        wt.mkdir()
        (wt / ".git").write_text(f"gitdir: {main.resolve()}/.git/worktrees/wt\n")
        (wt / "AGENTS.md").write_text((main / "AGENTS.md").read_text())  # tracked
        before: dict[str, bytes | None] = _tree(wt)
        code, out = run(rk.cmd_sync, wt, False, False)
        assert code == 0, out
        assert "== .gitignore ==" not in out, out
        assert "== .gitattributes ==" not in out, out
        assert _tree(wt) == before, "a dry run wrote something"


# R22 (I7): `--pm tracked` given on the command line wins over a pm/config.json
# that says local; `--pm local` keeps it; without the flag the file decides
def test_init_pm_flag_wins_over_config() -> None:
    def fresh(name: str, root: Path) -> Path:
        (root / name).mkdir()
        repo: Path = setup(root / name)
        (repo / "pm").mkdir()
        (repo / "pm/config.json").write_text(CONFIG_LOCAL)
        return repo

    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        repo: Path = fresh("flag-tracked", root)
        code, out = runk(rk.cmd_init, repo, ["paper"], "light", "user", pm="tracked")
        assert code == 0, out
        got: str = (repo / "pm/config.json").read_text()
        assert got == CONFIG_TRACKED, (got, out)
        assert (repo / ".gitignore").read_text() == rk.gitignore_text(""), out
        assert (repo / ".gitattributes").exists(), out
        repo = fresh("flag-local", root)
        code, out = runk(rk.cmd_init, repo, ["paper"], "light", "user", pm="local")
        assert code == 0, out
        assert (repo / "pm/config.json").read_text() == CONFIG_LOCAL
        assert not (repo / ".gitignore").exists()
        repo = fresh("no-flag", root)
        code, out = run(rk.cmd_init, repo, ["paper"], "light", "user")
        assert code == 0, out
        assert (repo / "pm/config.json").read_text() == CONFIG_LOCAL  # file decides
        for name in (".gitignore", ".gitattributes"):
            assert not (repo / name).exists(), name


# R22: the same on the command line (real template); the flag has no default
def test_init_cli_pm_flag_wins_over_config() -> None:
    def cli(repo: Path, *flag: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-I", str(RK_PY), "init", str(repo), "--kinds", "paper",
             "--mode", "light", *flag],
            capture_output=True, text=True,
        )  # fmt: skip

    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        for name, flag, want in (
            ("tracked", ("--pm", "tracked"), CONFIG_TRACKED),
            ("local", ("--pm", "local"), CONFIG_LOCAL),
            ("none", (), CONFIG_LOCAL),
        ):
            repo: Path = root / name
            (repo / "pm").mkdir(parents=True)
            (repo / "pm/config.json").write_text(CONFIG_LOCAL)
            r: subprocess.CompletedProcess[str] = cli(repo, *flag)
            assert r.returncode == 0, (name, r.stdout, r.stderr)
            assert (repo / "pm/config.json").read_text() == want, (name, r.stdout)
            assert (repo / ".gitignore").exists() == (name == "tracked"), name
        assert "--pm {local,tracked}" in subprocess.run(
            [sys.executable, "-I", str(RK_PY), "init", "--help"],
            capture_output=True, text=True,
        ).stdout


# R23: pm/config.json and git's exclude file are read and written as UTF-8 under
# any locale: LC_ALL=C with the interpreter's UTF-8 mode off (-X utf8=0)
def test_local_utf8_under_c_locale() -> None:
    env: dict[str, str] = {**os.environ, "LC_ALL": "C", "LANG": "C"}
    env.pop("LC_CTYPE", None)
    base: list[str] = [sys.executable, "-I", "-X", "utf8=0"]
    probe: subprocess.CompletedProcess[str] = subprocess.run(
        [*base, "-c", "import locale; print(locale.getpreferredencoding(False))"],
        env=env, capture_output=True, text=True,
    )
    if "UTF" in probe.stdout.upper():
        return  # the locale cannot be forced to a non-UTF-8 encoding here
    with tempfile.TemporaryDirectory() as d:
        repo: Path = Path(d) / "repo"  # the real template: the subprocess uses it
        repo.mkdir()
        rk.TEMPLATE_DIR = REAL_TEMPLATE
        _g(repo, "init", "-q")
        assert run(rk.cmd_init, repo, ["paper"], "full", "user")[0] == 0
        cfg: Path = repo / "pm/config.json"
        cfg.write_bytes('{"pm": "tracked", "note": "café"}\n'.encode("utf-8"))
        with _excl(repo).open("ab") as fh:
            fh.write("# café\n".encode("utf-8"))
        old: bytes = _excl(repo).read_bytes()
        r: subprocess.CompletedProcess[str] = subprocess.run(
            [*base, str(RK_PY), "sync", str(repo), "--pm", "local", "--write"],
            env=env, capture_output=True, text=True,
        )
        assert r.returncode == 0, (r.stdout, r.stderr[-400:])
        got: object = json.loads(cfg.read_bytes().decode("utf-8"))
        assert got == {"pm": "local", "note": "café"}, got
        new: bytes = _excl(repo).read_bytes()
        assert new.startswith(old) and new.endswith(BLOCK.encode("utf-8")), new
        r = subprocess.run(
            [*base, str(RK_PY), "doctor", "--repo", str(repo)],
            env=env, capture_output=True, text=True,
        )
        assert r.stdout.startswith("pm: local only"), (r.stdout, r.stderr[-400:])


# R24 (real git): `\`, `*`, `?` and `[` of the kit folder's prefix are escaped in
# the block's lines; the start marker keeps the raw prefix
def test_local_exclude_block_escapes_prefix() -> None:
    with tempfile.TemporaryDirectory() as d:
        root: Path = Path(d)
        names: tuple[str, ...] = ("a[b]*", "c?d", "e\\f")
        top, dirs = _multi_repo(root, *names)
        for folder in dirs:
            _init_local(folder)
        text: str = _excl(top).read_text()
        for name, esc in zip(names, ("a\\[b\\]\\*", "c\\?d", "e\\\\f")):
            assert f"{START_LOCAL} {name}/\n" in text, (name, text)  # raw prefix
            assert f"/{esc}/pm/\n" in text and f"/{esc}/**/_dry/\n" in text, text
        for rel, want in (
            ("a[b]*/pm/f", True), ("ab/pm/f", False), ("a[b]*/x/_dry/f", True),
            ("c?d/pm/f", True), ("cxd/pm/f", False),
            ("e\\f/pm/f", True), ("ef/pm/f", False),
        ):
            assert _ignored(top, rel) == want, (rel, want, text)
        assert _g(top, "status", "--porcelain") == "", "not excluded"


# R25: in a local repo, sync notes a research-kit block of .gitignore or
# .gitattributes only when git tracks the file
def test_local_sync_note_only_for_tracked_files() -> None:
    with tempfile.TemporaryDirectory() as d:
        repo: Path = _git_repo(Path(d))
        assert runk(rk.cmd_init, repo, ["paper"], "full", "user", pm="local")[0] == 0
        gi: Path = repo / ".gitignore"
        ga: Path = repo / ".gitattributes"
        gi.write_text(rk.gitignore_text("mine/\n"))
        ga.write_text(f"{rk.GI_START}\npm/ledger.jsonl merge=union\n{rk.GI_END}\n")
        for write in (False, True):  # untracked: the user's own, no note
            code, out = run(rk.cmd_sync, repo, write, False)
            assert code == 0 and "holds a research-kit block" not in out, out
        _g(repo, "add", ".gitignore")  # only one of the two is tracked
        code, out = run(rk.cmd_sync, repo, False, False)
        assert code == 0, out
        assert "note: .gitignore holds a research-kit block; remove it by hand" in out
        assert "note: .gitattributes holds" not in out, out
        _g(repo, "add", ".gitattributes")
        code, out = run(rk.cmd_sync, repo, False, False)
        assert "note: .gitattributes holds a research-kit block; remove it" in out, out


def _ledger_tests() -> list[tuple[str, Callable[[], None]]]:
    """The test_* functions of test_ledger.py (loaded by path, like rk.py)."""
    spec: ModuleSpec | None = importlib.util.spec_from_file_location(
        "test_ledger", Path(__file__).with_name("test_ledger.py")
    )
    assert spec is not None and spec.loader is not None
    mod: ModuleType = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return [
        (n, f) for n, f in vars(mod).items() if n.startswith("test_") and callable(f)
    ]


def main() -> int:
    tests: list[tuple[str, Callable[[], None]]] = [
        (n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)
    ]
    tests += _ledger_tests()
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
