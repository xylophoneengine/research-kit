#!/usr/bin/env python3
"""Anonymity gate over what git would publish. Run it via scripts/anon_check.sh.

usage: anon_check.sh [--no-denylist] [--allow-from REV] [--name TEXT]...
                     [--tag NAME]... [--all | REV-LIST-ARGS...]

Scans every commit of a range: added lines (as text, also files marked -diff),
added file names, the message, author and committer. Default range: commits on
HEAD that are on no origin/* ref. --all: all history. REV-LIST-ARGS: e.g.
origin/main..HEAD. A multi-word denylist term is also found across a line wrap
(within one hunk or message, also into unchanged neighbour lines, line prefixes
such as "# ", "> ", "* ", "// ", "% " dropped). An added file that is not UTF-8
text (NUL byte, invalid UTF-8) is a hit unless a "binary:<dir>/<glob>" allowlist
entry names it: <dir> holds no wildcard and <glob> matches the file name only.
Denylist: <main checkout>/docs/private/denylist.txt (found from any worktree),
or $ANON_DENYLIST; one term per line, case-insensitive, '#' comments.
Missing or empty denylist: exit 2, unless --no-denylist (pattern scans only).
Allowlist: scripts/anon_allow.txt of the working tree, or of REV with
--allow-from REV (the gate passes the pushed tip); the output names the source.
Entries: fixed string (case-insensitive), "re:" regex, or "binary:<dir>/<glob>". An
entry excuses a hit only when it matches exactly the hit's span; an entry that
matches the empty string or a denylist term is refused (exit 2), so denylist
hits cannot be excused. Denylist matches inside a lockfile integrity hash
(random base64) are skipped.
Annotated tags that point into the range: message and tagger are scanned.
--tag NAME (the pre-push hook passes each pushed tag): that tag's name, and for
an annotated tag its tagger and message, are scanned wherever it points.
--name TEXT: scan TEXT, e.g. a pushed ref name (the pre-push hook passes the
local and the remote ref name of every pushed ref).
Owner rule: every commit carries the author and committer identity of
origin/main's tip (one pseudonymous identity publishes).
Exit 0 clean, 1 hits, 2 setup error.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from fnmatch import fnmatchcase
from pathlib import Path
from typing import NoReturn

UUID: str = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
# Written so that no pattern matches its own source line.
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "home-path",
        re.compile(
            r"(?:(?<![\w$}./-])|(?<=file://))(?:/Users|/home)/[A-Za-z][A-Za-z0-9._-]*"
        ),
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
COMMIT_MARK: bytes = b"\x00\x01"
# Comment, quote and list marks at a line start; a wrapped term continues after.
WRAP_PREFIX: re.Pattern[str] = re.compile(r"^[#>*/%\s-]+")


def die(msg: str) -> NoReturn:
    print(f"anon_check: ERROR {msg}", file=sys.stderr)
    sys.exit(2)


def git_bytes(*args: str) -> bytes:
    r: subprocess.CompletedProcess[bytes] = subprocess.run(
        ["git", "-c", "core.quotePath=false", *args], capture_output=True
    )
    if r.returncode != 0:
        err: str = r.stderr.decode("utf-8", errors="replace").strip()
        die(f"git {' '.join(args)}: {err}")
    return r.stdout


def git(*args: str) -> str:
    return git_bytes(*args).decode("utf-8", errors="replace")


def entries(text: str) -> list[tuple[int, str]]:
    """Non-blank, non-comment lines with their line numbers."""
    out: list[tuple[int, str]] = []
    for n, line in enumerate(text.splitlines(), 1):
        s: str = line.strip()
        if s and not s.startswith("#"):
            out.append((n, s))
    return out


def squash(text: str) -> str:
    return " ".join(text.split()).lower()


class Scanner:
    def __init__(
        self, terms: list[tuple[int, str]], allow: list[re.Pattern[str]]
    ) -> None:
        self.term_line: dict[str, int] = {squash(t): n for n, t in terms}
        alt: str = "|".join(re.escape(t) for _, t in terms)
        self.deny: re.Pattern[str] | None = re.compile(alt, re.I) if terms else None
        words: list[list[str]] = [t.split() for _, t in terms if len(t.split()) > 1]
        multi: str = "|".join(r"\s+".join(map(re.escape, w)) for w in words)
        self.multi: re.Pattern[str] | None = re.compile(multi, re.I) if words else None
        # unchanged lines a wrapped term can reach into from an added line
        # ponytail: a split with blank lines between its words reaches further
        self.reach: int = max((len(w) for w in words), default=1) - 1
        self.allow: list[re.Pattern[str]] = allow
        self.hits: int = 0

    def mask(self, text: str) -> str:
        """Hide denylist terms, so output and logs never repeat them."""

        def sub(m: re.Match[str]) -> str:
            return f"<denylist:{self.term_line.get(squash(m.group()), '?')}>"

        for pat in (self.multi, self.deny):
            if pat is not None:
                text = pat.sub(sub, text)
        return text

    def report(self, rule: str, where: str, text: str, start: int, end: int) -> None:
        ws: int = max(0, start - CONTEXT)
        we: int = end + CONTEXT
        for pat in (self.multi, self.deny):  # never cut a term at the window edge
            for m in pat.finditer(text) if pat is not None else []:
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

    def scan_wrapped(
        self, lines: list[str], where: str, added: list[bool] | None = None
    ) -> None:
        """Multi-word terms split across lines; single-line forms were scanned.

        added marks the new lines among unchanged context lines: a match must
        touch one of them, since the context alone was published before.
        """
        if self.multi is None or len(lines) < 2:
            return
        parts: list[str] = [WRAP_PREFIX.sub("", ln) for ln in lines]
        flat: str = " ".join(parts)
        spans: list[tuple[int, int]] = []
        pos: int = 0
        for p in parts:
            spans.append((pos, pos + len(p)))
            pos += len(p) + 1
        for m in self.multi.finditer(flat):
            touched: list[int] = [
                i for i, (a, b) in enumerate(spans) if a < m.end() and m.start() < b
            ]
            if len(touched) > 1 and (added is None or any(added[i] for i in touched)):
                self.report("denylist", where, flat, m.start(), m.end())
                return


def load_allow(
    text: str, source: str, terms: list[tuple[int, str]]
) -> tuple[list[re.Pattern[str]], list[str]]:
    out: list[re.Pattern[str]] = []
    globs: list[str] = []
    for n, s in entries(text):
        if s.startswith("binary:"):
            g: str = s[7:]
            d, _, b = g.rpartition("/")
            # Why: a wildcard in the folder, or no folder, leaves binary files
            # of the whole repo unscanned (fnmatch's * also crosses "/").
            if not d or not b or any(c in d for c in "*?["):
                die(f"{source}:{n}: binary glob must be <dir>/<glob>: {g!r}")
            globs.append(g)
            continue
        try:
            a: re.Pattern[str] = (
                re.compile(s[3:])
                if s.startswith("re:")
                else re.compile(re.escape(s), re.I)
            )
        except re.error as e:
            die(f"{source}:{n}: bad regex: {e}")
        if a.search(""):
            die(f"{source}:{n}: entry matches the empty string")
        for tn, t in terms:
            if a.search(t):
                die(f"{source}:{n}: entry matches denylist term {tn}; drop one")
        out.append(a)
    return out, globs


def binary_allowed(path: str, globs: list[str]) -> bool:
    """A glob's folder must equal the path's; its pattern sees the name only."""
    d, _, b = path.rpartition("/")
    return any(
        g.rpartition("/")[0] == d and fnmatchcase(b, g.rpartition("/")[2])
        for g in globs
    )


def scan_file(
    sc: Scanner, where: str, lines: list[tuple[int, bytes, bool]], globs: list[str]
) -> None:
    """lines: (line number, text, added); not added = unchanged context."""
    if not any(new for _, _, new in lines):
        return  # context only: the hunks removed lines
    data: bytes = b"\n".join(b for _, b, new in lines if new)
    path: str = where.split(" ", 1)[1]
    try:
        if b"\0" in data:
            raise ValueError("NUL byte")
        data.decode("utf-8")
    except (UnicodeDecodeError, ValueError):
        if binary_allowed(path, globs):
            print(f"NOTE binary not scanned (allowlisted): {where}")
            return
        msg: str = (
            "not UTF-8 text, cannot be scanned; allowlist it as binary:<dir>/<glob>"
        )
        sc.report("binary", where, msg, 0, len(msg))
        return
    hunk: list[str] = []
    added: list[bool] = []
    prev: int = -2
    for n, b, new in lines:
        t: str = b.decode("utf-8", errors="replace")
        if new:
            sc.scan(t, f"{where}:{n}")
        if n != prev + 1:
            sc.scan_wrapped(hunk, f"{where}:{prev}", added)
            hunk, added = [], []
        hunk.append(t)
        added.append(new)
        prev = n
    sc.scan_wrapped(hunk, f"{where}:{prev}", added)


def scan_diffs(sc: Scanner, rng: list[str], globs: list[str]) -> None:
    out: bytes = git_bytes(
        "log", "-p", "--text", "--no-color", "--no-ext-diff", "--no-textconv",
        "--no-renames", f"-U{sc.reach}", "--src-prefix=a/", "--dst-prefix=b/",
        "--diff-merges=first-parent", "--format=%x00%x01%H", *rng,
    )
    sha: str = ""
    path: str = ""
    lineno: int = 0
    header: bool = False
    lines: list[tuple[int, bytes, bool]] = []

    def flush() -> None:
        if lines:
            scan_file(sc, f"{sha} {path}", lines, globs)
        lines.clear()

    for raw in out.split(b"\n"):
        if raw.startswith(COMMIT_MARK):
            flush()
            sha, header = raw[2:10].decode(), False
        elif raw.startswith(b"diff --git "):
            flush()
            header = True
            path = raw.decode("utf-8", errors="replace").rsplit(" b/", 1)[-1]
        elif header and raw.startswith(b"+++ "):
            p: str = raw[4:].decode("utf-8", errors="replace")
            path = p[3:-1] if p.startswith('"b/') else p.removeprefix("b/")
        elif raw.startswith(b"@@"):
            header = False
            m: re.Match[bytes] | None = re.match(rb"@@ -\S+ \+(\d+)", raw)
            lineno = int(m.group(1)) if m else 0
        elif not header and raw[:1] in (b"+", b" "):
            lines.append((lineno, raw[1:], raw[:1] == b"+"))
            lineno += 1
    flush()


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
        sc.scan_wrapped(body.splitlines(), f"{sha} message")
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
        sc.scan_wrapped(body.splitlines(), f"tag {name} message")


def main(argv: list[str]) -> int:
    no_deny: bool = False
    rng: list[str] = []
    wanted: set[str] = set()
    names: list[str] = []
    allow_from: str = ""
    args: list[str] = list(argv)
    while args:
        a: str = args.pop(0)
        if a == "--no-denylist":
            no_deny = True
        elif a == "--tag" and args:
            wanted.add(args.pop(0).removeprefix("refs/tags/"))
        elif a == "--name" and args:
            names.append(args.pop(0))
        elif a == "--allow-from" and args:
            allow_from = args.pop(0)
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
    terms: list[tuple[int, str]] = (
        entries(deny_path.read_text(encoding="utf-8")) if deny_path.is_file() else []
    )
    if not terms and not no_deny:
        die(
            f"denylist {deny_path} is missing or has no terms. Create it, set "
            "ANON_DENYLIST, or pass --no-denylist to run the pattern scans only."
        )
    rel: str = "scripts/anon_allow.txt"
    if allow_from:
        source: str = f"{allow_from}:{rel}"
        found: bool = subprocess.run(
            ["git", "cat-file", "-e", source], capture_output=True
        ).returncode == 0
        allow_text: str = git("show", source) if found else ""
    else:
        source = f"working tree {rel}"
        found = (top / rel).is_file()
        allow_text = (top / rel).read_text(encoding="utf-8") if found else ""
    allow, globs = load_allow(allow_text, source, terms)
    git("rev-parse", "-q", "--verify", "origin/main^{commit}")  # author reference
    n: str = git("rev-list", "--count", *rng).strip()
    print(f"anon_check: {n} commits ({' '.join(rng)})")
    state: str = "" if found else ", file absent"
    print(
        f"anon_check: allowlist from {source} ({len(allow)} entries, "
        f"{len(globs)} binary globs{state})"
    )
    sc: Scanner = Scanner(terms, allow)
    if terms:
        print(f"anon_check: denylist {sc.mask(str(deny_path))} ({len(terms)} terms)")
    else:
        print("anon_check: WARNING no denylist: private terms are NOT checked")
    for name in names:
        sc.scan(name, f"ref name {name}")
    scan_meta(sc, rng, wanted)
    scan_names(sc, rng)
    scan_diffs(sc, rng, globs)
    if sc.hits:
        print(f"anon_check: FAIL {sc.hits} hits")
        return 1
    tail: str = "" if terms else " (WITHOUT denylist: private terms NOT checked)"
    print(f"anon_check: clean{tail}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
