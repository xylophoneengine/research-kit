#!/usr/bin/env python3
"""Offline smoke test for both installations and the shared workflow."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
PYTHON = (sys.executable, "-I")


def test_adapters() -> None:
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        repo = root / "project"
        repo.mkdir()
        home = root / "test home"
        env = {**os.environ, "HOME": str(home),
               "XDG_CONFIG_HOME": str(root / "config"),
               "XDG_DATA_HOME": str(root / "data"),
               "HERMES_HOME": str(root / "profile"), "RK_SESSION_ID": " test-session "}

        def run(*argv: str, code: int = 0, text: str | None = None) -> str:
            result = subprocess.run(argv, cwd=repo, env=env, input=text,
                                    capture_output=True, text=True)
            assert result.returncode == code, (argv, result.stdout, result.stderr)
            return result.stdout + result.stderr

        def install(harness: str, code: int = 0) -> str:
            return run(*PYTHON, str(ROOT / "scripts/install_adapter.py"), harness, code=code)

        oc = root / "config/opencode"
        command = oc / "commands/team.md"
        command.parent.mkdir(parents=True)
        command.write_text("local command")
        assert "Not replacing existing path" in install("opencode", 1)
        assert command.read_text() == "local command"
        assert not (root / "data").exists()
        command.unlink()
        for harness, config in (("opencode", oc), ("hermes", root / "profile")):
            install(harness)
            install(harness)
            assert (config / "skills/team/SKILL.md").is_file()
            assert (config / "skills/research-kit/SKILL.md").is_file()
            assert (config / "skills/team/references/architect.md").is_file()
            assert (config / "skills/team/references/transport.md").readlink() == (
                ROOT / "adapters" / harness / "transport.md"
            )
        assert command.is_symlink()

        core = root / "data/research-kit/core"
        assert (core / "ui/dist/index.html").is_file()
        rk = (*PYTHON, str(core / "scripts/rk.py"))
        run("git", "init", "-q")
        run(*rk, "init", "--no-claude", "--kinds", "software", "--mode", "light")
        claude = repo / "CLAUDE.md"
        assert not claude.exists()
        claude.write_bytes(b"existing rules\r\n")
        run(*rk, "upgrade")
        assert "up to date" in run(*rk, "sync", "--no-claude", "--write")
        assert claude.read_bytes() == b"existing rules\r\n"

        run(*rk, "add", "task", "smoke", "--owner", "sr1", "--note", "write report")
        assert "no TASK:" in run(*rk, "brief-check", code=2, text="DELIVERABLE: report\n")
        assert "started T-1" in run(
            *rk, "brief-check", text="DELIVERABLE: report\nTASK: T-1\n"
        )
        report = repo / "pm/logs/team/smoke/sr1-r1.md"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text("Verified by the smoke test.\n")
        run(*rk, "close", "T-1", "--note", "verified", "--ref", str(report))
        run(*rk, "doctor")
        events = (repo / "pm/ledger.jsonl").read_text().splitlines()
        assert [json.loads(line)["sid"] for line in events] == ["test-session"] * 3


if __name__ == "__main__":
    test_adapters()
    print("adapter smoke test passed")
