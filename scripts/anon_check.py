#!/usr/bin/env python3
"""Anonymity gate over what git would publish. Run it via scripts/anon_check.sh.

usage: anon_check.sh [--no-denylist] [--tag NAME]... [--all | REV-LIST-ARGS...]

Scans every commit of a range: added lines, added file names, the message,
author and committer. Default range: commits on HEAD that are on no origin/*
ref. --all: all history. REV-LIST-ARGS: e.g. origin/main..HEAD.
Denylist: <main checkout>/docs/private/denylist.txt (found from any worktree),
or $ANON_DENYLIST; one term per line, case-insensitive, '#' comments.
Missing or empty denylist: exit 2, unless --no-denylist (pattern scans only).
Allowlist: scripts/anon_allow.txt (fixed string, case-insensitive, or "re:"
regex). An entry excuses a hit only when it matches exactly the hit's span; an
entry that matches the empty string or a denylist term is refused (exit 2), so
denylist hits cannot be excused. Denylist matches inside a lockfile integrity
hash (random base64) are skipped.
Annotated tags that point into the range: message and tagger are scanned.
--tag NAME (the pre-push hook passes each pushed tag): that tag's name, and for
an annotated tag its tagger and message, are scanned wherever it points.
Owner rule: every commit carries the author and committer identity of
origin/main's tip (one pseudonymous identity publishes).
Exit 0 clean, 1 hits, 2 setup error.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

UUID: str = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
# Written so that no pattern matches its own source line.
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "home-path",
        re.compile(r"(?<![\w$}./-])(?:/Users|/home)/[A-Za-z][A-Za-z0-9._-]*"),
    ),
    ("windows-path", re.compile(r"\b[A-Za-z]:\\{1,2}Users\\{1,2}[A-Za-z0-9._-]+")),
    ("temp-path", re.compile(r"/tmp/claude-[0-9]|/var/folders/[A-Za-z0-9_+-]{2}/")),
    (
        "email",
        re.compile(
            r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"
        ),
    ),
    (
        "secret",
        re.compile(
            r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}"
            r"|xox[bpas]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16})"
        ),
    ),
    (
        "secret-assign",
        re.compile(
            r"\b(?:api[_-]?key|token|secret|passw(?:or)?d)['\"]?\s*[:=]\s*['\"]?"
            r"[A-Za-z0-9/+_-]{8,}",
            re.I,
        ),
    ),
    ("session-id", re.compile(rf"session.{{0,40}}{UUID}|{UUID}.{{0,40}}session", re.I)),
]
CONTEXT: int = 60
# Random base64 in lockfiles; a short denylist term can occur in it by chance.
INTEGRITY: re.Pattern[str] = re.compile(
    r'"integrity": "sha(?:1|256|384|512)-[A-Za-z0-9+/=]{20,}"'
)


def die(msg: str) -> NoReturn:
    print(f"anon_check: ERROR {msg}", file=sys.stderr)
    sys.exit(2)


def git(*args: str) -> str:
    r: subprocess.CompletedProcess[bytes] = subprocess.run(
        ["git", "-c", "core.quotePath=false", *args], capture_output=True
    )
    if r.returncode != 0:
        err: str = r.stderr.decode("utf-8", errors="replace").strip()
        die(f"git {' '.join(args)}: {err}")
    return r.stdout.decode("utf-8", errors="replace")


def entries(path: Path) -> list[tuple[int, str]]:
    """Non-blank, non-comment lines with their line numbers."""
    out: list[tuple[int, str]] = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        s: str = line.strip()
        if s and not s.startswith("#"):
            out.append((n, s))
    return out


class Scanner:
    def __init__(
        self, terms: list[tuple[int, str]], allow: list[re.Pattern[str]]
    ) -> None:
        self.term_line: dict[str, int] = {t.lower(): n for n, t in terms}
        alt: str = "|".join(re.escape(t) for _, t in terms)
        self.deny: re.Pattern[str] | None = re.compile(alt, re.I) if terms else None
        self.allow: list[re.Pattern[str]] = allow
        self.hits: int = 0

    def mask(self, text: str) -> str:
        """Hide denylist terms, so output and logs never repeat them."""
        if self.deny is None:
            return text

        def sub(m: re.Match[str]) -> str:
            return f"<denylist:{self.term_line.get(m.group().lower(), '?')}>"

        return self.deny.sub(sub, text)

    def report(self, rule: str, where: str, text: str, start: int, end: int) -> None:
        ws: int = max(0, start - CONTEXT)
        we: int = end + CONTEXT
        if self.deny is not None:  # never cut a term in half at the window edge
            for m in self.deny.finditer(text):
                if m.start() < ws < m.end():
                    ws = m.start()
                if m.start() < we < m.end():
                    we = m.end()
        excerpt: str = self.mask(text[ws:we]).replace("\t", " ").strip()
        print(f"HIT {rule:<13} {self.mask(where)}: {excerpt}")
        self.hits += 1

    def excused(self, rule: str, text: str, m: re.Match[str]) -> bool:
        s, e = m.span()
        if rule == "denylist":
            spans: list[tuple[int, int]] = [i.span() for i in INTEGRITY.finditer(text)]
            return any(a <= s and e <= b for a, b in spans)
        return any(a.fullmatch(text, s, e) for a in self.allow)

    def scan(self, text: str, where: str) -> None:
        rules: list[tuple[str, re.Pattern[str]]] = list(PATTERNS)
        if self.deny is not None:
            rules.insert(0, ("denylist", self.deny))
        for rule, pat in rules:
            for m in pat.finditer(text):
                if not self.excused(rule, text, m):
                    self.report(rule, where, text, m.start(), m.end())
                    break


def load_allow(path: Path, terms: list[tuple[int, str]]) -> list[re.Pattern[str]]:
    if not path.is_file():
        return []
    out: list[re.Pattern[str]] = []
    for n, s in entries(path):
        try:
            a: re.Pattern[str] = (
                re.compile(s[3:])
                if s.startswith("re:")
                else re.compile(re.escape(s), re.I)
            )
        except re.error as e:
            die(f"{path}:{n}: bad regex: {e}")
        if a.search(""):
            die(f"{path}:{n}: entry matches the empty string")
        for tn, t in terms:
            if a.search(t):
                die(f"{path}:{n}: entry matches denylist term {tn}; remove one of them")
        out.append(a)
    return out


def scan_diffs(sc: Scanner, rng: list[str]) -> None:
    out: str = git(
        "log", "-p", "--no-color", "--no-ext-diff", "--no-textconv", "--no-renames",
        "-U0", "--src-prefix=a/", "--dst-prefix=b/", "--diff-merges=first-parent",
        "--format=%x00%H", *rng,
    )
    sha: str = ""
    path: str = ""
    lineno: int = 0
    header: bool = False
    for line in out.split("\n"):
        if line.startswith("\0"):
            sha, header = line[1:9], False
        elif line.startswith("diff --git "):
            header, path = True, line.rsplit(" b/", 1)[-1]
        elif header:
            if line.startswith("+++ b/"):
                path = line[6:]
            elif line.startswith('+++ "b/'):
                path = line[7:-1]
            elif line.startswith("Binary files"):
                print(f"NOTE binary not scanned: {sha} {path}")
            elif line.startswith("@@"):
                header = False
                m: re.Match[str] | None = re.match(r"@@ -\S+ \+(\d+)", line)
                lineno = int(m.group(1)) if m else 0
        elif line.startswith("@@"):
            m2: re.Match[str] | None = re.match(r"@@ -\S+ \+(\d+)", line)
            lineno = int(m2.group(1)) if m2 else 0
        elif line.startswith("+"):
            sc.scan(line[1:], f"{sha} {path}:{lineno}")
            lineno += 1


def scan_names(sc: Scanner, rng: list[str]) -> None:
    out: str = git(
        "log", "--name-only", "-z", "--no-renames", "--diff-filter=A",
        "--diff-merges=first-parent", "--format=%x01%H", *rng,
    )
    sha: str = ""
    for field in out.split("\0"):  # "\x01<sha>", then one field per name
        field = field.lstrip("\n")
        if field.startswith("\x01"):
            sha = field[1:9]
        elif field:
            sc.scan(field, f"{sha} file name")


def scan_meta(sc: Scanner, rng: list[str], wanted: set[str]) -> None:
    fmt: str = "--format=%an <%ae>%x1f%cn <%ce>"
    ref: str = git("log", "-1", fmt, "origin/main").strip()
    want_a, want_c = ref.split("\x1f")
    out: str = git("log", "--format=%H%x1f%an <%ae>%x1f%cn <%ce>%x1f%B%x1e", *rng)
    commits: set[str] = set()
    for rec in out.split("\x1e"):
        rec = rec.strip("\n")
        if not rec:
            continue
        h, author, committer, body = rec.split("\x1f", 3)
        commits.add(h)
        sha: str = h[:8]
        if author != want_a or committer != want_c:
            text: str = f"author {author}, committer {committer}; expected {want_a}"
            sc.report("author", sha, text, 0, len(text))
        sc.scan(author, f"{sha} author")
        sc.scan(committer, f"{sha} committer")
        for line in body.splitlines():
            sc.scan(line, f"{sha} message")
    tags: str = git(
        "for-each-ref", "refs/tags",
        "--format=%(objecttype)%1f%(*objectname)%1f%(refname)"
        "%1f%(taggername) %(taggeremail)%1f%(contents)%1e",
    )
    for rec in tags.split("\x1e"):
        rec = rec.strip("\n")
        if not rec:
            continue
        kind, target, ref, tagger, body = rec.split("\x1f", 4)
        name: str = ref.removeprefix("refs/tags/")
        annotated: bool = kind == "tag"
        if name not in wanted and not (annotated and target in commits):
            continue  # wanted = being pushed, wherever it points
        sc.scan(name, f"tag {name}")
        if not annotated:
            continue  # a lightweight tag has no text beyond its name
        sc.scan(tagger, f"tag {name} tagger")
        for line in body.splitlines():
            sc.scan(line, f"tag {name} message")


def main(argv: list[str]) -> int:
    no_deny: bool = False
    rng: list[str] = []
    wanted: set[str] = set()
    args: list[str] = list(argv)
    while args:
        a: str = args.pop(0)
        if a == "--no-denylist":
            no_deny = True
        elif a == "--tag" and args:
            wanted.add(args.pop(0).removeprefix("refs/tags/"))
        elif a in ("-h", "--help"):
            print(__doc__)
            return 0
        elif a == "--all":
            rng = ["--all"]
        else:
            rng = [a, *args]
            break
    rng = rng or ["HEAD", "--not", "--remotes=origin"]

    top: Path = Path(git("rev-parse", "--show-toplevel").strip())
    env: str = os.environ.get("ANON_DENYLIST", "")
    common: str = git("rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    default: Path = Path(common).parent / "docs/private/denylist.txt"
    deny_path: Path = Path(env) if env else default
    terms: list[tuple[int, str]] = entries(deny_path) if deny_path.is_file() else []
    if not terms and not no_deny:
        die(
            f"denylist {deny_path} is missing or has no terms. Create it, set "
            "ANON_DENYLIST, or pass --no-denylist to run the pattern scans only."
        )
    allow: list[re.Pattern[str]] = load_allow(top / "scripts/anon_allow.txt", terms)
    git("rev-parse", "-q", "--verify", "origin/main^{commit}")  # author reference
    n: str = git("rev-list", "--count", *rng).strip()
    print(f"anon_check: {n} commits ({' '.join(rng)}), {len(allow)} allowlist entries")
    sc: Scanner = Scanner(terms, allow)
    if terms:
        print(f"anon_check: denylist {sc.mask(str(deny_path))} ({len(terms)} terms)")
    else:
        print("anon_check: WARNING no denylist: private terms are NOT checked")
    scan_meta(sc, rng, wanted)
    scan_names(sc, rng)
    scan_diffs(sc, rng)
    if sc.hits:
        print(f"anon_check: FAIL {sc.hits} hits")
        return 1
    tail: str = "" if terms else " (WITHOUT denylist: private terms NOT checked)"
    print(f"anon_check: clean{tail}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
