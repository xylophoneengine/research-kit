#!/usr/bin/env python3
"""Install and sync research-kit files in a user repo.

AGENTS.md = template generic part (everything above "## Project appendix")
+ the repo's own appendix (that heading and everything below it).
Kind files pm/kinds/<kind>.md are generic as a whole.

Usage:
  python3 -I rk.py init <repo_dir> --kinds paper,software --mode full --git user
      [--pm local|tracked]
  python3 -I rk.py add-kind <repo_dir> <kind>
  python3 -I rk.py upgrade <repo_dir>
  python3 -I rk.py sync <repo_dir> [--write] [--accept-drop] [--pm local|tracked]
      (--pm local: pm/ stays out of git: pm/config.json {"pm": "local"} and a
      block in git's exclude file instead of .gitignore/.gitattributes)

Ledger store (pm/ledger.jsonl, see ledger.py; every command takes --repo DIR
and --who NAME; every ID argument also takes a label (form <stage code>/<item>,
e.g. 03b/W4, the / is required) or a stage code such as 03b; receipts print
the real ID; an add receipt ends with "(stage S-n)" or "(no stage)". Every
event records the kit version and, when set, the session id; a stage's add and
close also record the stamps of AGENTS.md and pm/kinds/*.md. --ref PATH must
exist relative to the repo root; an absolute path inside the repo is stored
repo-relative; a path outside the repo (absolute or ../) and an empty ref are
refused; a URL (://), doi:... and arXiv:... (any case) pass unchecked; imported
entries are exempt):
  python3 -I rk.py add <type> <title> [--owner NAME] [--label L] [--stage S]
      [--note TEXT] [--link ID]... [--ref PATH]... [--status STATUS]
      [--imported --source FILE:LINE [--legacy-id OLD] [--date YYYY-MM-DD]]
      (title: one line, at most 160 characters; --label L is unique; a stage's
      title is its folder name, changed only by stage-rename; add task without
      --note is refused, imports exempt; add stage "kind-topic" plans a stage:
      status planned, folder pm/stages/P-<n>-kind-topic/ with its subfolders,
      recorded as ref; [--open] opens it at once, [--follows S-m] gives it a
      suffix letter, [--before S-n | --after S-n] place it among the planned
      stages)
  python3 -I rk.py start ID [--owner NAME]
      (refused for an entry of a planned or shelved stage)
  python3 -I rk.py close ID --note TEXT [--ref PATH]... [--link ID]...
  python3 -I rk.py drop ID --note TEXT [--ref PATH]... [--link ID]...
  python3 -I rk.py shelve ID --note TEXT [--ref PATH]... [--link ID]...
      (known, not planned now; out of it: reopen or drop)
  python3 -I rk.py reopen ID --note TEXT [--ref PATH]...
  python3 -I rk.py staged ID [ID ...] --note TEXT [--ref PATH]...
      (work done, not landed: open or running -> staged; the note says where it
      sits; not for stages and decisions, not in a planned or shelved stage;
      out of it: land or close (done), start (more work), reopen)
  python3 -I rk.py land --note TEXT [--ref PATH]... [--stage S] [ID ...]
      (staged -> done: every staged entry, the named ones, or one stage's; a
      named entry that is not staged refuses the whole call)
  python3 -I rk.py set ID [--title T] [--owner N] [--label L] [--stage S]
      [--note T | --note-replace T] [--link ID]... [--ref PATH]...
      [--ref-drop PATH]... [--status planned|shelved|dropped]
      [--before S-n | --after S-n]   (--ref-drop removes a ref; the history
      keeps it; --status and --before/--after are for stages: shelved and
      dropped need --note; only stage-open opens, only stage-close closes)
  python3 -I rk.py supersede ID TITLE --owner NAME [--note T] [--link ID]...
      [--ref PATH]...
  python3 -I rk.py list [--type T] [--owner N] [--stage S] [--status STATUS]
      [--limit N] [--all]   (planned stages add a line "planned N: ~NN title
      (n entries), ..."; an open entry of a planned or shelved stage shows as
      planned / shelved and is out of the open list; --status and --stage show it)
  python3 -I rk.py show ID [ID ...]   (a shown status that differs: "shown:")
  python3 -I rk.py search [TEXT] [--source S] [--label L] [--type T] [--limit N]
  python3 -I rk.py recent [-n N]
  python3 -I rk.py render
  python3 -I rk.py stage-open S-n [--follows S-m]   (a planned stage gets the
      next NN, its folder P-<n>-... is renamed, refs are rewritten)
  python3 -I rk.py stage-rename S-n kind-topic [--note TEXT]   (changes the
      kind-topic part of a title; folder and refs follow; a done stage needs
      --note)
  python3 -I rk.py stage-close S-n --sign-off D-m [--ref PATH]...
      (runs the doctor checks of S-n first: refuses on a missing ref or
      stage folder, prints the soft findings, then closes)
  python3 -I rk.py reref OLD NEW [--dry-run]   (after moving files: every ref
      starting with OLD gets NEW instead, on all entries incl. imported and
      done ones; all or nothing, refused if a new path does not exist)
  python3 -I rk.py doctor [--stage S] [--limit N]   (read-only; exit 1 on a
      HARD finding; N lines per group, default 20, 0 = all)
  python3 -I rk.py doctor --start       (kit version, rule files behind the
      kit; the kit part is at most 3 lines, then one `spec: ` line per open
      stage without a user decision labelled <stage code>/SPEC; always exit 0)
  python3 -I rk.py brief-check < message.txt    (hook gate: rc 0 pass, 2 refuse)
  python3 -I rk.py import FILE.jsonl [FILE.jsonl ...] [--dry-run]
      (imported history, all or nothing; rows: type, title, source; optional
      owner, stage, note, link, ref, status, legacy_id, date, key; see
      `rk.py import --help`)
  python3 -I rk.py ui [--repo DIR] [--port N] [--no-open]   (read-only browser)
"""

from __future__ import annotations

import argparse
import difflib
import importlib.util
import json
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
    "scratch",
    "logs",
    "logs/team",  # teammate reports outside an open stage (AGENTS 2.3)
    "reviews",
    "living",
    "kinds",
)
MODES: tuple[str, ...] = ("light", "full")
GIT_POLICIES: dict[str, str] = {
    "user": "user commits",
    "orchestrator": "orchestrator commits",
}
CORE_STAMP_RE: re.Pattern[str] = re.compile(r"<!-- research-kit: \S+ -->")
LEGACY_STAMP_RE: re.Pattern[str] = re.compile(r"<!-- paper-playbook: \S+ -->")
KINDS_RE: re.Pattern[str] = re.compile(
    r"^<!-- rk:kinds -->[ \t]*$.*?^<!-- /rk:kinds -->[ \t]*$", re.M | re.S
)
KIND_LINE_RE: re.Pattern[str] = re.compile(r"^- Kind `([^`]+)`", re.M)
GI_START: str = "# >>> research-kit"
GI_END: str = "# <<< research-kit"
# local-only mode: block of git's exclude file (design I4) and output lines (I5)
_EXCL_START: str = "# >>> research-kit (local only)"
_EXCL_LINES: list[str] = ["pm/", "AGENTS.md", "CLAUDE.md", "**/_dry/"]  # I4
_NO_GIT: str = "no git repo: exclude block not written"
_REFUSAL: str = (
    "pm/ has files in git; local-only needs them untracked first "
    "(git rm -r --cached pm/ is yours to run)"
)
_EXCL_LABEL: str = ".git/info/exclude"
_PM_MODES: tuple[str, ...] = ("local", "tracked")


def _load_sibling(name: str, file: str) -> ModuleType:
    """`file` next to this file: python3 -I drops the script dir from sys.path."""
    if name in sys.modules:
        return sys.modules[name]
    spec: ModuleSpec | None = importlib.util.spec_from_file_location(
        name, Path(__file__).with_name(file)
    )
    assert spec is not None and spec.loader is not None
    mod: ModuleType = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclasses look the module up here
    spec.loader.exec_module(mod)
    return mod


ledger: ModuleType = _load_sibling("rk_ledger", "ledger.py")
STAMP_RE: re.Pattern[str] = ledger.STAMP_RE  # one pattern for sync and doctor


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


def _marked_block(old: str, start: str, lines: list[str]) -> str:
    """`old` with the block start..GI_END added once or refreshed in place."""
    block: str = "\n".join([start, *lines, GI_END]) + "\n"
    pat: re.Pattern[str] = re.compile(
        rf"^{re.escape(start)}$.*?^{re.escape(GI_END)}$\n?", re.M | re.S
    )
    if pat.search(old):
        return pat.sub(lambda _m: block, old, count=1)
    if old and not old.endswith("\n"):
        old += "\n"
    return old + ("\n" if old else "") + block


def gitignore_text(old: str) -> str:
    """`old` with the research-kit block added once or refreshed in place."""
    lines: list[str] = (TEMPLATE_DIR / "gitignore").read_text().splitlines()
    return _marked_block(old, GI_START, lines)


def _excl_start(prefix: str) -> str:
    """Start line of this kit folder's block; the prefix tells folders apart (D-78)."""
    return f"{_EXCL_START} {prefix}" if prefix else _EXCL_START


def _exclude_state(repo_dir: Path) -> tuple[Path, str, str] | None:
    """(git's exclude file, its text, text with the local block); None: no git."""
    path: Path | None = ledger.git_exclude_file(repo_dir)
    prefix: str | None = ledger.git_prefix(repo_dir)  # anchors the lines (D-76)
    if path is None or prefix is None:
        return None
    old: str = path.read_text(encoding="utf-8") if path.exists() else ""
    anchor: str = re.sub(r"([\\*?\[\]])", r"\\\1", prefix)  # glob characters
    lines: list[str] = [f"/{anchor}{ln}" for ln in _EXCL_LINES]
    return path, old, _marked_block(old, _excl_start(prefix), lines)


def _ensure_exclude(repo_dir: Path) -> Path | None:
    """Add or refresh the local block in git's exclude file and return the
    file; None (line printed) when there is no git repo."""
    state: tuple[Path, str, str] | None = _exclude_state(repo_dir)
    if state is None:
        print(_NO_GIT)
        return None
    path, old, new = state
    if new != old:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new, encoding="utf-8")
    return path


def _ensure_ignore(repo_dir: Path, local: bool) -> None:
    """The ignore write of add-kind and upgrade for the repo's mode."""
    if local:
        _ensure_exclude(repo_dir)
    else:
        ensure_gitignore(repo_dir)


def _config(repo_dir: Path) -> dict[str, object] | None:
    """pm/config.json through the ledger's reader; None (line printed) if broken."""
    try:
        return ledger.read_config(repo_dir)
    except ledger.LedgerError as e:
        print(e)
        return None


def _config_text(cfg: dict[str, object], pm: str) -> str:
    """The text of pm/config.json with `pm` set, every other key kept."""
    return json.dumps({**cfg, "pm": pm}, indent=2, ensure_ascii=False) + "\n"


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


def cmd_init(
    repo_dir: Path, kinds: list[str], mode: str, git_policy: str, pm: str | None = None
) -> int:
    """`pm` None: pm/config.json decides (tracked without a file)."""
    target: Path = repo_dir / "AGENTS.md"
    bad: list[str] = _bad_kinds(kinds)
    if bad:
        print(f"unknown kind(s): {', '.join(bad)}; valid: {', '.join(KINDS)}")
        return 1
    if mode not in MODES or git_policy not in GIT_POLICIES:
        print(f"mode must be one of {MODES}, git one of {tuple(GIT_POLICIES)}")
        return 1
    if pm is not None and pm not in _PM_MODES:
        print(f"pm must be one of {_PM_MODES}")
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
    cfg: dict[str, object] | None = _config(repo_dir)
    if cfg is None:
        return 1
    local: bool = (pm or cfg["pm"]) == "local"  # the flag wins over the file
    if pm == "local" and ledger.git_tracked(repo_dir, "pm/"):
        print(_REFUSAL)
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
    if pm is not None and pm != cfg["pm"]:
        (repo_dir / "pm" / "config.json").write_text(
            _config_text(cfg, pm), encoding="utf-8"
        )
    ignored: str = ".gitignore, .gitattributes"
    if local:
        ignored = "pm/config.json" + (
            f", {_EXCL_LABEL}" if _ensure_exclude(repo_dir) else ""
        )
    else:
        ensure_gitignore(repo_dir)
        ensure_block(
            repo_dir / ".gitattributes", ".gitattributes", "gitattributes",
            GI_START, GI_END, True,
        )  # fmt: skip
    ensure_compact_block(repo_dir, True)
    print(f"created {target} (template {stamp(template)}), mode {mode}, "
          f"git policy '{GIT_POLICIES[git_policy]}', kinds {', '.join(kinds)}")
    print(f"created pm/ ({len(dirs)} dirs, {len(files)} skeleton files), "
          f"{ignored}, CLAUDE.md Compact Instructions block")
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
    cfg: dict[str, object] | None = _config(repo_dir)
    if cfg is None:
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
    _ensure_ignore(repo_dir, cfg["pm"] == "local")
    print(f"kind '{kind}' added to AGENTS.md appendix")
    return 0


def cmd_upgrade(repo_dir: Path) -> int:
    text: str | None = _read_agents(repo_dir)
    if text is None:
        return 1
    if is_legacy(text):
        print("legacy paper-playbook AGENTS.md; run sync first to migrate")
        return 1
    cfg: dict[str, object] | None = _config(repo_dir)
    if cfg is None:
        return 1
    head, app = split(text, "repo AGENTS.md")
    if get_field(app, "Mode") == "full":
        print("already full; nothing to do")
        return 0
    (repo_dir / "AGENTS.md").write_text(head + set_field(app, "Mode", "full"))
    (repo_dir / "pm" / "stages").mkdir(parents=True, exist_ok=True)
    _ensure_ignore(repo_dir, cfg["pm"] == "local")
    print("upgraded to full: Mode: full, pm/stages/ created")
    return 0


def _diff(old: str, new: str, name: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            old.splitlines(), new.splitlines(), name, "synced", lineterm="", n=1
        )
    )


def cmd_sync(
    repo_dir: Path, write: bool, accept_drop: bool, pm: str | None = None
) -> int:
    """Dry-run by default; one combined report and one write decision.

    `pm` None: the mode is read from pm/config.json."""
    if pm is not None and pm not in _PM_MODES:
        print(f"pm must be one of {_PM_MODES}")
        return 1
    cfg: dict[str, object] | None = _config(repo_dir)
    if cfg is None:
        return 1
    repo: str | None = _read_agents(repo_dir)
    if repo is None:
        return 1
    local: bool = (pm or cfg["pm"]) == "local"
    if pm == "local" and ledger.git_tracked(repo_dir, "pm/"):
        print(_REFUSAL)
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

    excl: Path | None = None  # git's exclude file, when it gets the local block
    cfg_path: Path = repo_dir / "pm" / "config.json"
    if pm is not None and pm != cfg["pm"]:
        writes[cfg_path] = _config_text(cfg, pm)
        print(f'\n== pm/config.json == "pm": {cfg["pm"]} -> {pm}')

    if local:
        state: tuple[Path, str, str] | None = _exclude_state(repo_dir)
        if state is None:
            print(f"\n{_NO_GIT}")
        else:
            excl_file, excl_old, excl_new = state
            if excl_new != excl_old:
                excl = excl_file
                writes[excl] = excl_new
                print(f"\n== {_EXCL_LABEL} == research-kit block added/refreshed")
        for name in (".gitignore", ".gitattributes"):  # only to find a 0.2.5 block
            f: Path = repo_dir / name
            if (f.exists() and GI_START in f.read_text().splitlines()
                    and ledger.git_tracked(repo_dir, name)):
                print(f"\nnote: {name} holds a research-kit block; remove it by hand")
    else:
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
        if pm == "tracked" and cfg["pm"] == "local":  # the switch back
            old_excl: Path | None = ledger.git_exclude_file(repo_dir)
            prefix: str | None = ledger.git_prefix(repo_dir)
            if (old_excl is not None and prefix is not None and old_excl.exists()
                    and _excl_start(prefix)
                    in old_excl.read_text(encoding="utf-8").splitlines()):
                print(f"\nnote: {_EXCL_LABEL} holds a research-kit block; "
                      "remove it by hand")

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
        utf8: bool = path == excl or path == cfg_path
        path.write_text(content, encoding="utf-8" if utf8 else None)
        print(f"wrote {_EXCL_LABEL if path == excl else path.relative_to(repo_dir)}")
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "ui":
        return _load_sibling("rk_ui", "ui.py").main(sys.argv[2:])
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
    pi.add_argument("--pm", choices=_PM_MODES)
    pa: argparse.ArgumentParser = sub.add_parser("add-kind")
    pa.add_argument("repo_dir", type=Path)
    pa.add_argument("kind")
    pu: argparse.ArgumentParser = sub.add_parser("upgrade")
    pu.add_argument("repo_dir", nargs="?", type=Path, default=Path.cwd())
    ps: argparse.ArgumentParser = sub.add_parser("sync")
    ps.add_argument("repo_dir", nargs="?", type=Path, default=Path.cwd())
    ps.add_argument("--write", action="store_true")
    ps.add_argument("--accept-drop", action="store_true")
    ps.add_argument("--pm", choices=_PM_MODES)
    pg: argparse.ArgumentParser = sub.add_parser("global-rules")
    pg.add_argument("--claude-md", type=Path, default=Path("~/.claude/CLAUDE.md"))
    pg.add_argument("--write", action="store_true")
    for name in sorted(ledger.COMMANDS):  # listed in --help; main() dispatches them
        sub.add_parser(name, add_help=False)
    sub.add_parser("ui", add_help=False)  # dispatched in main() to ui.py
    a: argparse.Namespace = p.parse_args()
    if a.cmd == "init":
        kinds: list[str] = [k.strip() for k in a.kinds.split(",") if k.strip()]
        return cmd_init(a.repo_dir, kinds, a.mode, a.git, a.pm)
    if a.cmd == "add-kind":
        return cmd_add_kind(a.repo_dir, a.kind)
    if a.cmd == "upgrade":
        return cmd_upgrade(a.repo_dir)
    if a.cmd == "global-rules":
        return cmd_global_rules(a.claude_md.expanduser(), a.write)
    return cmd_sync(a.repo_dir, a.write, a.accept_drop, a.pm)


if __name__ == "__main__":
    sys.exit(main())
