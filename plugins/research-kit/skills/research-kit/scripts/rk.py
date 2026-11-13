#!/usr/bin/env python3
"""Install and sync research-kit files in a user repo.

AGENTS.md = template generic part (everything above "## Project appendix")
+ the repo's own appendix (that heading and everything below it).
Kind files pm/kinds/<kind>.md are generic as a whole.

Usage:
  python3 -I rk.py init <repo_dir> --kinds paper,software --mode full --git user
  python3 -I rk.py add-kind <repo_dir> <kind>
  python3 -I rk.py upgrade <repo_dir>
  python3 -I rk.py sync <repo_dir> [--write] [--accept-drop]

Ledger store (pm/ledger.jsonl, see ledger.py; every command takes --repo DIR
and --who NAME):
  python3 -I rk.py add <type> <title> [--owner NAME] [--stage S] [--note TEXT]
      [--link ID]... [--ref PATH]... [--status STATUS]
      [--imported --source FILE:LINE [--legacy-id OLD] [--date YYYY-MM-DD]]
  python3 -I rk.py start ID [--owner NAME]
  python3 -I rk.py close ID --note TEXT [--ref PATH]... [--link ID]...
  python3 -I rk.py drop ID --note TEXT [--link ID]...
  python3 -I rk.py reopen ID --note TEXT
  python3 -I rk.py set ID [--title T] [--owner N] [--stage S]
      [--note T | --note-replace T] [--link ID]... [--ref PATH]...
  python3 -I rk.py supersede ID TITLE --owner NAME [--note T] [--link ID]...
      [--ref PATH]...
  python3 -I rk.py list [--type T] [--owner N] [--stage S] [--limit N] [--all]
  python3 -I rk.py show ID
  python3 -I rk.py search [TEXT] [--source S] [--legacy-id L] [--type T] [--limit N]
  python3 -I rk.py recent [-n N]
  python3 -I rk.py render
  python3 -I rk.py stage-close S-n --sign-off D-m
  python3 -I rk.py brief-check < message.txt    (hook gate: rc 0 pass, 2 refuse)
  python3 -I rk.py import FILE.jsonl [FILE.jsonl ...] [--dry-run]
      (imported history, all or nothing; rows: type, title, source; optional
      owner, stage, note, link, ref, status, legacy_id, date, key; see
      `rk.py import --help`)
"""

from __future__ import annotations

import argparse
import difflib
import importlib.util
import re
import sys
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType

TEMPLATE_DIR: Path = Path(__file__).resolve().parents[1] / "template"
APPENDIX: str = "## Project appendix"
KINDS: tuple[str, ...] = ("paper", "software", "reverse-eng", "experiment", "thesis")
PM_DIRS: tuple[str, ...] = (
    "handoffs/open",
    "handoffs/done",
    "handoffs/compact",
    "waste/team",
    "scratch",
    "logs",
    "reviews",
    "living",
    "kinds",
)
MODES: tuple[str, ...] = ("light", "full")
GIT_POLICIES: dict[str, str] = {
    "user": "user commits",
    "orchestrator": "orchestrator commits",
}
STAMP_RE: re.Pattern[str] = re.compile(
    r"<!-- (?:research-kit|research-kit-kind \S+|paper-playbook): (\S+) -->"
)
CORE_STAMP_RE: re.Pattern[str] = re.compile(r"<!-- research-kit: \S+ -->")
LEGACY_STAMP_RE: re.Pattern[str] = re.compile(r"<!-- paper-playbook: \S+ -->")
KINDS_RE: re.Pattern[str] = re.compile(
    r"^<!-- rk:kinds -->[ \t]*$.*?^<!-- /rk:kinds -->[ \t]*$", re.M | re.S
)
KIND_LINE_RE: re.Pattern[str] = re.compile(r"^- Kind `([^`]+)`", re.M)
GI_START: str = "# >>> research-kit"
GI_END: str = "# <<< research-kit"


def _load_ledger() -> ModuleType:
    """ledger.py next to this file: python3 -I drops the script dir from sys.path."""
    name: str = "rk_ledger"
    if name in sys.modules:
        return sys.modules[name]
    spec: ModuleSpec | None = importlib.util.spec_from_file_location(
        name, Path(__file__).with_name("ledger.py")
    )
    assert spec is not None and spec.loader is not None
    mod: ModuleType = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclasses look the module up here
    spec.loader.exec_module(mod)
    return mod


ledger: ModuleType = _load_ledger()


# ---- text helpers -----------------------------------------------------------


def split(text: str, name: str) -> tuple[str, str]:
    """Return (generic part, appendix part) split at the appendix heading.

    Kind files (name starting with "kind:") may lack the heading: whole text
    is generic then.
    """
    m: re.Match[str] | None = re.search(rf"^{re.escape(APPENDIX)}", text, re.M)
    if m is None:
        if name.startswith("kind:"):
            return text, ""
        sys.exit(f"error: no '{APPENDIX}' heading in {name}")
    return text[: m.start()], text[m.start() :]


def stamp(text: str) -> str:
    m: re.Match[str] | None = STAMP_RE.search(text)
    return m.group(1) if m else "none"


def merge(template: str, repo: str, name: str = "repo AGENTS.md") -> str:
    tname: str = name if name.startswith("kind:") else "template"
    return split(template, tname)[0] + split(repo, name)[1]


def dropped_lines(
    template: str, repo: str, name: str = "repo AGENTS.md", extra: str = ""
) -> list[str]:
    """Non-blank lines in the repo's generic part that the template lacks.

    `extra` = more text whose lines count as kept (legacy: the paper kind).
    """
    tname: str = name if name.startswith("kind:") else "template"
    keep: set[str] = set(split(template, tname)[0].splitlines())
    keep |= set(extra.splitlines())
    r_head: str = split(repo, name)[0]
    return [ln for ln in r_head.splitlines() if ln.strip() and ln not in keep]


def is_legacy(text: str) -> bool:
    return bool(LEGACY_STAMP_RE.search(text)) and not CORE_STAMP_RE.search(text)


def _field_re(key: str) -> re.Pattern[str]:
    return re.compile(rf"^{re.escape(key)}:[ \t]*(.*?)[ \t]*$", re.M)


def get_field(appendix: str, key: str) -> str | None:
    m: re.Match[str] | None = _field_re(key).search(appendix)
    return m.group(1) if m else None


def set_field(appendix: str, key: str, value: str) -> str:
    """Rewrite the first `Key:` line; append `Key: value` if there is none."""
    line: str = f"{key}: {value}"
    pat: re.Pattern[str] = _field_re(key)
    if pat.search(appendix):
        return pat.sub(lambda _m: line, appendix, count=1)
    sep: str = "" if appendix.endswith("\n") else "\n"
    return f"{appendix}{sep}{line}\n"


def kinds_block(kinds: list[str]) -> str:
    """Managed block, one line per kind, in KINDS order."""
    lines: list[str] = ["<!-- rk:kinds -->"]
    for k in sorted(set(kinds), key=lambda k: KINDS.index(k) if k in KINDS else 99):
        lines.append(
            f"- Kind `{k}`: read `pm/kinds/{k}.md` at session start and after "
            "every compact."
        )
    lines.append("<!-- /rk:kinds -->")
    return "\n".join(lines)


def active_kinds(appendix: str) -> list[str]:
    m: re.Match[str] | None = KINDS_RE.search(appendix)
    return KIND_LINE_RE.findall(m.group(0)) if m else []


def set_kinds(appendix: str, kinds: list[str]) -> str:
    block: str = kinds_block(kinds)
    if KINDS_RE.search(appendix):
        return KINDS_RE.sub(lambda _m: block, appendix, count=1)
    sep: str = "" if appendix.endswith("\n") else "\n"
    return f"{appendix}{sep}{block}\n"


def gitignore_text(old: str) -> str:
    """`old` with the research-kit block added once or refreshed in place."""
    lines: list[str] = (TEMPLATE_DIR / "gitignore").read_text().splitlines()
    block: str = "\n".join([GI_START, *lines, GI_END]) + "\n"
    pat: re.Pattern[str] = re.compile(
        rf"^{re.escape(GI_START)}$.*?^{re.escape(GI_END)}$\n?", re.M | re.S
    )
    if pat.search(old):
        return pat.sub(lambda _m: block, old, count=1)
    if old and not old.endswith("\n"):
        old += "\n"
    return old + ("\n" if old else "") + block


def ensure_gitignore(repo_dir: Path) -> bool:
    """Add or refresh the research-kit block in .gitignore; True if changed."""
    path: Path = repo_dir / ".gitignore"
    old: str = path.read_text() if path.exists() else ""
    new: str = gitignore_text(old)
    if new == old:
        return False
    path.write_text(new)
    return True


CB_START: str = "<!-- research-kit:compact >>> -->"
CB_END: str = "<!-- <<< research-kit:compact -->"


def compact_text(
    old: str,
    tpl: str = "compact-instructions.md",
    start: str = CB_START,
    end: str = CB_END,
) -> str:
    """`old` with the marked template block added once or refreshed."""
    body: str = (TEMPLATE_DIR / tpl).read_text().rstrip("\n")
    block: str = f"{start}\n{body}\n{end}\n"
    pat: re.Pattern[str] = re.compile(
        rf"^{re.escape(start)}$.*?^{re.escape(end)}$\n?", re.M | re.S
    )
    if pat.search(old):
        return pat.sub(lambda _m: block, old, count=1)
    if not old:
        return block
    sep: str = "\n" if old.endswith("\n") else "\n\n"
    return f"{old}{sep}{block}"


def ensure_block(
    path: Path, name: str, tpl: str, start: str, end: str, write: bool
) -> tuple[bool, str]:
    """Add/refresh a marked block in `path`; (changed, unified diff)."""
    old: str = path.read_text() if path.exists() else ""
    new: str = compact_text(old, tpl, start, end)
    if new == old:
        return False, ""
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new)
    return True, _diff(old, new, name)


def ensure_compact_block(repo_dir: Path, write: bool) -> tuple[bool, str]:
    """Add/refresh the marked block in CLAUDE.md; (changed, unified diff)."""
    return ensure_block(
        repo_dir / "CLAUDE.md",
        "CLAUDE.md",
        "compact-instructions.md",
        CB_START,
        CB_END,
        write,
    )


LEGACY_README: str = "paper/README.md"
NEW_README: str = "pm/README.md"
# bare or ./paper/README.md; not ../paper/README.md (outside the repo root)
LEGACY_README_RE: re.Pattern[str] = re.compile(
    r"(?<![\w/.-])((?:\./)?)paper/README\.md(?!\w)"
)


def repoint_paper_readme(text: str) -> str:
    """`text` with the legacy README path replaced; nothing else touched."""
    return LEGACY_README_RE.sub(lambda m: m.group(1) + NEW_README, text)


GB_START: str = "<!-- research-kit:global >>> -->"
GB_END: str = "<!-- <<< research-kit:global -->"


def cmd_global_rules(claude_md: Path, write: bool) -> int:
    """Team-roles block in the global CLAUDE.md; dry run unless `write`."""
    changed, diff = ensure_block(
        claude_md, str(claude_md), "global-claude.md", GB_START, GB_END, write
    )
    if not changed:
        print("up to date")
    elif write:
        print(f"wrote {claude_md}")
    else:
        print(f"{diff}\n\ndry run; rerun with --write to apply")
    return 0


def migrate_text(
    repo_agents: str,
    core_template: str,
    legacy_stages: str | None = "paper/stages/",
    legacy_waste: str | None = None,
) -> str:
    """Legacy paper-playbook AGENTS.md -> research-kit core + old appendix."""
    app: str = split(repo_agents, "repo AGENTS.md")[1]
    first: bool = True

    def take(new: str) -> None:
        """Adopt `new`; the first pure append gets one blank line before it."""
        nonlocal app, first
        tail: str = new[len(app) :]
        if first and new != app and new.startswith(app) and (
            app.endswith("\n") or tail.startswith("\n")
        ):
            new = app.rstrip("\n") + "\n\n" + tail.lstrip("\n")
            first = False
        app = new

    take(set_field(app, "Mode", "full"))
    take(set_field(app, "Git policy", GIT_POLICIES["user"]))
    if legacy_stages:
        take(set_field(app, "Legacy stages", legacy_stages))
    if legacy_waste:
        take(set_field(app, "Legacy waste", legacy_waste))
    take(set_kinds(app, ["paper"]))
    return split(core_template, "template")[0] + app


# ---- file helpers -----------------------------------------------------------


def _kind_template(kind: str) -> Path:
    return TEMPLATE_DIR / "kinds" / f"{kind}.md"


def _pm_dirs(repo_dir: Path, mode: str) -> list[Path]:
    rels: list[str] = [*PM_DIRS, *(["stages"] if mode == "full" else [])]
    return [repo_dir / "pm" / r for r in rels]


def _pm_skeletons(repo_dir: Path) -> list[tuple[Path, Path]]:
    """(template file, repo target) for every template/pm file."""
    src: Path = TEMPLATE_DIR / "pm"
    return [
        (p, repo_dir / "pm" / p.relative_to(src))
        for p in sorted(src.rglob("*"))
        if p.is_file()
    ]


def _missing(repo_dir: Path, mode: str) -> tuple[list[Path], list[tuple[Path, Path]]]:
    dirs: list[Path] = [d for d in _pm_dirs(repo_dir, mode) if not d.is_dir()]
    files: list[tuple[Path, Path]] = [
        (s, t) for s, t in _pm_skeletons(repo_dir) if not t.exists()
    ]
    return dirs, files


def _create(dirs: list[Path], files: list[tuple[Path, Path]]) -> None:
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
    for src, dst in files:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text())


def _read_agents(repo_dir: Path) -> str | None:
    path: Path = repo_dir / "AGENTS.md"
    if not path.exists():
        print(f"{path} missing; run: init {repo_dir}")
        return None
    return path.read_text()


def _bad_kinds(kinds: list[str]) -> list[str]:
    return [k for k in kinds if k not in KINDS]


# ---- commands ---------------------------------------------------------------


def cmd_init(repo_dir: Path, kinds: list[str], mode: str, git_policy: str) -> int:
    target: Path = repo_dir / "AGENTS.md"
    bad: list[str] = _bad_kinds(kinds)
    if bad:
        print(f"unknown kind(s): {', '.join(bad)}; valid: {', '.join(KINDS)}")
        return 1
    if mode not in MODES or git_policy not in GIT_POLICIES:
        print(f"mode must be one of {MODES}, git one of {tuple(GIT_POLICIES)}")
        return 1
    if not repo_dir.is_dir():
        print(f"{repo_dir} is not a directory")
        return 1
    if target.exists():
        print(f"{target} exists; use: sync {repo_dir}")
        return 1
    missing: list[str] = [k for k in kinds if not _kind_template(k).exists()]
    if missing:
        print(f"template missing for kind(s): {', '.join(missing)}")
        return 1
    template: str = (TEMPLATE_DIR / "AGENTS.md").read_text()
    head, app = split(template, "template")
    app = set_field(app, "Mode", mode)
    app = set_field(app, "Git policy", GIT_POLICIES[git_policy])
    app = set_kinds(app, kinds)
    target.write_text(head + app)
    dirs, files = _missing(repo_dir, mode)
    _create(dirs, files)
    for k in kinds:
        kpath: Path = repo_dir / "pm" / "kinds" / f"{k}.md"
        if not kpath.exists():
            kpath.write_text(_kind_template(k).read_text())
    ensure_gitignore(repo_dir)
    ensure_block(
        repo_dir / ".gitattributes", ".gitattributes", "gitattributes",
        GI_START, GI_END, True,
    )  # fmt: skip
    ensure_compact_block(repo_dir, True)
    print(f"created {target} (template {stamp(template)}), mode {mode}, "
          f"git policy '{GIT_POLICIES[git_policy]}', kinds {', '.join(kinds)}")
    print(f"created pm/ ({len(dirs)} dirs, {len(files)} skeleton files), .gitignore, "
          ".gitattributes, CLAUDE.md Compact Instructions block")
    return 0


def cmd_add_kind(repo_dir: Path, kind: str) -> int:
    if kind not in KINDS:
        print(f"unknown kind '{kind}'; valid: {', '.join(KINDS)}")
        return 1
    text: str | None = _read_agents(repo_dir)
    if text is None:
        return 1
    if is_legacy(text):
        print("legacy paper-playbook AGENTS.md; run sync first to migrate")
        return 1
    head, app = split(text, "repo AGENTS.md")
    kinds: list[str] = active_kinds(app)
    if kind in kinds:
        print(f"kind '{kind}' already active; nothing to do")
        return 0
    if not _kind_template(kind).exists():
        print(f"template missing for kind '{kind}'")
        return 1
    (repo_dir / "AGENTS.md").write_text(head + set_kinds(app, [*kinds, kind]))
    kpath: Path = repo_dir / "pm" / "kinds" / f"{kind}.md"
    if kpath.exists():
        print(f"{kpath} exists; kept (run sync to compare with the template)")
    else:
        kpath.parent.mkdir(parents=True, exist_ok=True)
        kpath.write_text(_kind_template(kind).read_text())
        print(f"created {kpath}")
    ensure_gitignore(repo_dir)
    print(f"kind '{kind}' added to AGENTS.md appendix")
    return 0


def cmd_upgrade(repo_dir: Path) -> int:
    text: str | None = _read_agents(repo_dir)
    if text is None:
        return 1
    if is_legacy(text):
        print("legacy paper-playbook AGENTS.md; run sync first to migrate")
        return 1
    head, app = split(text, "repo AGENTS.md")
    if get_field(app, "Mode") == "full":
        print("already full; nothing to do")
        return 0
    (repo_dir / "AGENTS.md").write_text(head + set_field(app, "Mode", "full"))
    (repo_dir / "pm" / "stages").mkdir(parents=True, exist_ok=True)
    ensure_gitignore(repo_dir)
    print("upgraded to full: Mode: full, pm/stages/ created")
    return 0


def _diff(old: str, new: str, name: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            old.splitlines(), new.splitlines(), name, "synced", lineterm="", n=1
        )
    )


def cmd_sync(repo_dir: Path, write: bool, accept_drop: bool) -> int:
    """Dry-run by default; one combined report and one write decision."""
    repo: str | None = _read_agents(repo_dir)
    if repo is None:
        return 1
    template: str = (TEMPLATE_DIR / "AGENTS.md").read_text()
    writes: dict[Path, str] = {}
    drops: list[tuple[str, str]] = []
    legacy: bool = is_legacy(repo)
    print(f"template stamp: {stamp(template)}  repo stamp: {stamp(repo)}")

    if legacy:
        stages: str | None = next(
            (f"{d}/" for d in ("paper/stages", "stages") if (repo_dir / d).is_dir()),
            None,
        )
        waste: str | None = "WASTE/" if (repo_dir / "WASTE").is_dir() else None
        new: str = migrate_text(repo, template, stages, waste)
        paper: Path = _kind_template("paper")
        extra: str = paper.read_text() if paper.exists() else ""
        agent_drops: list[str] = dropped_lines(template, repo, extra=extra)
        print(f"legacy paper-playbook repo: migrating (Legacy stages: {stages}, "
              f"Legacy waste: {waste}); nothing is moved")
    else:
        new = merge(template, repo)
        agent_drops = dropped_lines(template, repo)
    drops += [("AGENTS.md", ln) for ln in agent_drops]
    if new != repo:
        writes[repo_dir / "AGENTS.md"] = new
        print(f"\n== AGENTS.md ==\n{_diff(repo, new, 'AGENTS.md')}")

    app: str = split(new, "repo AGENTS.md")[1]
    for k in active_kinds(app):
        rel: str = f"pm/kinds/{k}.md"
        tpath: Path = _kind_template(k)
        if not tpath.exists():
            print(f"\n== {rel} == no template for kind '{k}'; skipped")
            continue
        ktpl: str = tpath.read_text()
        kpath: Path = repo_dir / rel
        if not kpath.exists():
            writes[kpath] = ktpl
            print(f"\n== {rel} == new file ({len(ktpl.splitlines())} lines)")
            continue
        krepo: str = kpath.read_text()
        knew: str = merge(ktpl, krepo, f"kind:{k}")
        drops += [(rel, ln) for ln in dropped_lines(ktpl, krepo, f"kind:{k}")]
        if knew != krepo:
            writes[kpath] = knew
            print(f"\n== {rel} == stamps {stamp(krepo)} -> {stamp(ktpl)}")
            print(_diff(krepo, knew, rel))

    gi: Path = repo_dir / ".gitignore"
    gi_old: str = gi.read_text() if gi.exists() else ""
    gi_new: str = gitignore_text(gi_old)
    if gi_new != gi_old:
        writes[gi] = gi_new
        print("\n== .gitignore == research-kit block added/refreshed")

    ga: Path = repo_dir / ".gitattributes"
    ga_old: str = ga.read_text() if ga.exists() else ""
    ga_new: str = compact_text(ga_old, "gitattributes", GI_START, GI_END)
    if ga_new != ga_old:
        writes[ga] = ga_new
        print(f"\n== .gitattributes == research-kit block (ledger merge=union)\n"
              f"{_diff(ga_old, ga_new, '.gitattributes')}")

    claude: Path = repo_dir / "CLAUDE.md"
    ptr_old: str = claude.read_bytes().decode() if claude.exists() else ""
    ptr_new: str = repoint_paper_readme(ptr_old) if legacy else ptr_old
    if ptr_new != ptr_old:
        print(f"\n== CLAUDE.md == pointer {LEGACY_README} -> {NEW_README}\n"
              f"{_diff(ptr_old, ptr_new, 'CLAUDE.md')}")

    compact_changed, compact_diff = ensure_compact_block(repo_dir, False)
    if compact_changed:
        print(f"\n== CLAUDE.md == Compact Instructions block\n{compact_diff}")

    mode: str = get_field(app, "Mode") or "light"
    dirs, files = _missing(repo_dir, mode)
    for d in dirs:
        print(f"create dir {d.relative_to(repo_dir)}/")
    for _src, dst in files:
        print(f"create {dst.relative_to(repo_dir)}")

    # Stamp lines are template-owned: a version bump is not a dropped rule.
    drops = [(f, ln) for f, ln in drops if not STAMP_RE.search(ln)]
    ptr_changed: bool = ptr_new != ptr_old
    if not (writes or dirs or files or compact_changed or ptr_changed):
        print("up to date")
        return 0
    if drops:
        print(f"\nDROPPED: {len(drops)} line(s) only in the repo's generic text.")
        print("Old template text -> fine to drop. Repo-specific -> move to appendix.")
        for f, ln in drops:
            print(f"  {f} | {ln}")
    if not write:
        print("\ndry run; rerun with --write to apply")
        return 0
    if drops and not accept_drop:
        print("\nrefused: dropped lines present; resolve them or pass --accept-drop")
        return 2
    _create(dirs, files)
    if ptr_changed:
        claude.write_bytes(ptr_new.encode())  # bytes: other lines stay identical
        print("wrote CLAUDE.md (pointer)")
    if compact_changed:
        ensure_compact_block(repo_dir, True)
        print("wrote CLAUDE.md")
    for path, content in writes.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        print(f"wrote {path.relative_to(repo_dir)}")
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in ledger.COMMANDS:
        return ledger.main(sys.argv[1:])
    p: argparse.ArgumentParser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    pi: argparse.ArgumentParser = sub.add_parser("init")
    pi.add_argument("repo_dir", nargs="?", type=Path, default=Path.cwd())
    pi.add_argument("--kinds", required=True, help="comma list: " + ",".join(KINDS))
    pi.add_argument("--mode", required=True, choices=MODES)
    pi.add_argument("--git", default="user", choices=tuple(GIT_POLICIES))
    pa: argparse.ArgumentParser = sub.add_parser("add-kind")
    pa.add_argument("repo_dir", type=Path)
    pa.add_argument("kind")
    pu: argparse.ArgumentParser = sub.add_parser("upgrade")
    pu.add_argument("repo_dir", nargs="?", type=Path, default=Path.cwd())
    ps: argparse.ArgumentParser = sub.add_parser("sync")
    ps.add_argument("repo_dir", nargs="?", type=Path, default=Path.cwd())
    ps.add_argument("--write", action="store_true")
    ps.add_argument("--accept-drop", action="store_true")
    pg: argparse.ArgumentParser = sub.add_parser("global-rules")
    pg.add_argument("--claude-md", type=Path, default=Path("~/.claude/CLAUDE.md"))
    pg.add_argument("--write", action="store_true")
    for name in sorted(ledger.COMMANDS):  # listed in --help; main() dispatches them
        sub.add_parser(name, add_help=False)
    a: argparse.Namespace = p.parse_args()
    if a.cmd == "init":
        kinds: list[str] = [k.strip() for k in a.kinds.split(",") if k.strip()]
        return cmd_init(a.repo_dir, kinds, a.mode, a.git)
    if a.cmd == "add-kind":
        return cmd_add_kind(a.repo_dir, a.kind)
    if a.cmd == "upgrade":
        return cmd_upgrade(a.repo_dir)
    if a.cmd == "global-rules":
        return cmd_global_rules(a.claude_md.expanduser(), a.write)
    return cmd_sync(a.repo_dir, a.write, a.accept_drop)


if __name__ == "__main__":
    sys.exit(main())
