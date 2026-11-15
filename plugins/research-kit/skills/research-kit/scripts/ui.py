#!/usr/bin/env python3
"""Read-only local browser for pm/ledger.jsonl (rk.py ui).

Serves GET /api/ledger (the whole ledger, read fresh per request) and the built
frontend bundle in ../ui/dist on 127.0.0.1. Never writes the ledger or STATUS.md.

Usage:
  python3 -I rk.py ui [--repo DIR] [--port N] [--no-open]
  python3 -I rk.py ui --status       list running viewers
  python3 -I rk.py ui --statusline   segment for a Claude Code status line

While serving it keeps ~/.cache/research-kit/ui/<port>.json (pid, port, repo)
for the two options above and removes it on exit (SIGTERM included).
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
import errno
import mimetypes
import os
import select
import signal
import socket
import stat
import sys
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import FrameType, ModuleType
from typing import Any
from urllib.parse import unquote

DIST: Path = Path(__file__).resolve().parent.parent / "ui" / "dist"
# One <port>.json per running viewer, for --status and --statusline.
STATE_DIR: Path = Path.home() / ".cache" / "research-kit" / "ui"
MAX_REPO_CHARS: int = 4096  # longest repo path --status will print
STATE_BYTES: int = 1 << 16  # a state file is a few hundred bytes; read at most this
DEFAULT_PORT: int = 8765  # first port tried when no --port is given
PORT_TRIES: int = 10  # ports tried from DEFAULT_PORT upward without --port
# A write to a socket whose peer is gone. macOS is said to report EPROTOTYPE or
# EINVAL for it instead of EPIPE / ECONNRESET (not reproduced here; covered by
# a unit test); ConnectionError covers the usual two.
HANGUP_ERRNOS: frozenset[int] = frozenset(
    {errno.EPIPE, errno.ECONNRESET, errno.EPROTOTYPE, errno.EINVAL}
)


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


def _read(
    repo: Path,
) -> tuple[list[tuple[int, dict[str, object]]], dict[str, Any]]:
    """Events and folded state (values are ledger.Entry)."""
    events: list[tuple[int, dict[str, object]]] = ledger.read_events(repo)
    return events, ledger.fold(events)


def _meta(ev: dict[str, object]) -> dict[str, object]:
    """kit, sid, rules of a ledger event; a key of the wrong type is left out."""
    out: dict[str, object] = {}
    for k in ("kit", "sid"):
        if isinstance(ev.get(k), str):
            out[k] = ev[k]
    r: object = ev.get("rules")
    if isinstance(r, dict) and all(isinstance(v, str) for v in r.values()):
        out["rules"] = r
    return out


def payload(repo: Path) -> dict[str, object]:
    """The whole ledger as JSON-ready data: entries, raw events, known types."""
    try:
        events, state = _read(repo)
    except ledger.LedgerError:
        # ponytail: a reader can catch a half-written last line; one retry, no
        # shared lock with writers. Add a lock if retries show up as 500s.
        time.sleep(0.05)
        events, state = _read(repo)
    return {
        "repo": str(repo),  # first key on purpose: the port probe reads a prefix
        "entries": [dataclasses.asdict(e) for e in state.values()],
        "events": [
            {
                "line": n,
                **{k: ev.get(k) for k in ("ts", "who", "ev", "id", "f")},
                **_meta(ev),
            }
            for n, ev in events
        ],
        "types": ledger.known_types(repo),
    }


def make_handler(repo: Path, dist: Path) -> type[BaseHTTPRequestHandler]:
    root: Path = dist.resolve()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def handle_one_request(self) -> None:
            """A client that hangs up early (a probing second rk ui) is not an
            error on any path, send_error's 403 / 404 / 405 included."""
            try:
                super().handle_one_request()
            except OSError as e:
                if not (isinstance(e, ConnectionError) or e.errno in HANGUP_ERRNOS):
                    raise  # e.g. a failing file read is not a hang-up
                self.close_connection = True

        def _send(self, code: int, ctype: str, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj: object) -> None:
            body: bytes = json.dumps(obj).encode()
            self._send(code, "application/json; charset=utf-8", body)

        def _host_ok(self) -> bool:
            """Host is 127.0.0.1:<port> or localhost:<port>: blocks DNS rebinding."""
            port: int = self.connection.getsockname()[1]
            ok: bool = self.headers.get("Host") in (
                f"127.0.0.1:{port}",
                f"localhost:{port}",
            )
            if not ok:
                self.send_error(403, "bad Host header")
            return ok

        def do_GET(self) -> None:
            if not self._host_ok():
                return
            path: str = self.path.split("?", 1)[0].split("#", 1)[0]
            if path == "/api/ledger":
                try:
                    data: dict[str, object] = payload(repo)
                except ledger.LedgerError as e:
                    self._json(500, {"error": str(e)})
                    return
                except Exception as e:  # e.g. a non-UTF-8 pm/kinds file
                    self._json(500, {"error": f"{type(e).__name__}: {e}"})
                    return
                self._json(200, data)
                return
            rel: str = unquote(path).lstrip("/") or "index.html"
            try:
                target: Path = (root / rel).resolve()
                ok: bool = target.is_file() and target.is_relative_to(root)
            except (OSError, ValueError):  # e.g. an embedded NUL byte
                ok = False
            if not ok:
                self.send_error(404)
                return
            guess: str | None = mimetypes.guess_type(target.name)[0]
            ctype: str = guess or "application/octet-stream"
            self._send(200, ctype, target.read_bytes())

        def _not_allowed(self) -> None:
            if self._host_ok():
                self.send_error(405)

        do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _not_allowed

    return Handler


def _taken(port: int) -> bool:
    """Something answers on 127.0.0.1:port. Catches a 0.0.0.0 listener, which
    SO_REUSEADDR lets a 127.0.0.1 bind shadow on macOS; SO_REUSEADDR itself stays
    on so a restart does not fail on the last run's TIME_WAIT sockets."""
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
    except (OSError, OverflowError, ValueError):
        return False
    return True


PROBE_BYTES: int = 1 << 20  # read at most this much of a holder's answer
PROBE_SECONDS: float = 2.0  # one deadline over connect and all reads


def _is_viewer_of(port: int, repo: Path) -> bool:
    """True if 127.0.0.1:port answers GET /api/ledger like a viewer of `repo`.

    The holder is untrusted and nothing it sends is kept: the answer must be a
    200 whose body starts with the exact bytes our own payload() would start
    with for this repo (`{"repo": "<str(repo)>"` then `,` or `}`). A raw socket,
    so no redirect is followed and the one deadline (PROBE_SECONDS, checked
    between reads, per-operation timeout <= 1 s) also covers a holder that
    drips header bytes. Any failure is False."""
    want: bytes = b'{"repo": ' + json.dumps(str(repo)).encode()
    req: bytes = (
        f"GET /api/ledger HTTP/1.0\r\nHost: 127.0.0.1:{port}\r\n\r\n".encode()
    )
    deadline: float = time.monotonic() + PROBE_SECONDS
    buf: bytearray = bytearray()
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1) as s:
            s.sendall(req)
            while len(buf) < PROBE_BYTES:
                left: float = deadline - time.monotonic()
                if left <= 0:
                    return False
                s.settimeout(min(1.0, left))
                chunk: bytes = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
                end: int = buf.find(b"\r\n\r\n")
                if end >= 0 and len(buf) > end + 4 + len(want):
                    break
    except (OSError, OverflowError, ValueError):
        return False
    end = buf.find(b"\r\n\r\n")
    if end < 0 or not bytes(buf[:12]).startswith(b"HTTP/1."):
        return False
    if bytes(buf[8:13]) != b" 200 ":
        return False
    body: bytes = bytes(buf[end + 4 :])
    return body.startswith(want) and body[len(want) : len(want) + 1] in (b",", b"}")


def _port_taken_message(port: int, viewer: bool) -> str:
    """One of two texts built only from our own values, never the holder's. The
    second makes no claim about the holder: it also covers a slow or broken
    viewer of this repo and a path spelled differently."""
    if viewer:
        return (
            "error: a ledger viewer for this repo already runs at "
            f"http://127.0.0.1:{port}/; pick another --port for a second one"
        )
    return (
        f"error: 127.0.0.1:{port} is taken, and what holds it was not confirmed "
        "as this repo's ledger viewer; pick another --port"
    )


def _state_dir_ok() -> bool:
    """STATE_DIR is a real directory (no symlink) owned by us and not group or
    world writable: only then are files in it written or trusted."""
    try:
        st: os.stat_result = os.lstat(STATE_DIR)
    except OSError:
        return False
    if not stat.S_ISDIR(st.st_mode):
        return False
    if not hasattr(os, "getuid"):  # no uids or modes to check (Windows)
        return True
    return st.st_uid == os.getuid() and not st.st_mode & 0o022


def _write_state(port: int, repo: Path) -> Path | None:
    """Write STATE_DIR/<port>.json ({"pid", "port", "repo"}) for --status and
    --statusline: a temp file in the same dir, then os.replace. None (the caller
    says so) if the dir is not ours or private, or on any write error."""
    try:
        STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not _state_dir_ok():
            return None
        tmp: Path = STATE_DIR / f".{port}.{os.getpid()}.tmp"
        tmp.write_text(
            json.dumps({"pid": os.getpid(), "port": port, "repo": str(repo)})
        )
        final: Path = STATE_DIR / f"{port}.json"
        os.replace(tmp, final)
    except OSError:
        return None
    return final


def _pid_alive(pid: int) -> bool:
    if pid <= 0:  # os.kill(0, 0) would address a whole process group
        return False
    if sys.platform == "win32":  # os.kill terminates the process there
        return True  # ponytail: no liveness check on Windows; --status still probes
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True  # it exists, another user owns it
    except (OSError, OverflowError):
        return False
    return True


def _read_small(f: Path) -> bytes | None:
    """Content of a regular file of at most STATE_BYTES, else None. A symlink is
    not followed and a FIFO or device is never read, so this cannot block."""
    flags: int = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
    try:
        fd: int = os.open(f, flags | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        data: bytes = os.read(fd, STATE_BYTES + 1)
    except OSError:
        return None
    finally:
        os.close(fd)
    return data if len(data) <= STATE_BYTES else None


def _valid_state(d: object, name: str) -> tuple[int, int, str] | None:
    """(port, pid, repo) if `d` is the content of the state file `name`: a dict
    with pid (1 to 2**31-1) and port (1 to 65535) as real ints (no bool) and a
    printable repo of 1 to MAX_REPO_CHARS chars, stored as <port>.json."""
    if not isinstance(d, dict):
        return None
    pid, port, repo = d.get("pid"), d.get("port"), d.get("repo")
    if type(pid) is not int or type(port) is not int or not isinstance(repo, str):
        return None
    if not (0 < pid < 2**31 and 0 < port < 65536 and name == f"{port}.json"):
        return None
    if not (0 < len(repo) <= MAX_REPO_CHARS and repo.isprintable()):
        return None
    return port, pid, repo


def _read_states(prune: bool) -> list[tuple[int, int, str]]:
    """(port, pid, repo) of every valid state file (see _valid_state) with a live
    pid, sorted by port. Nothing is read from a directory that is not ours and
    private. prune: delete the file of a dead pid (our own stale file). Nothing
    is probed here."""
    out: list[tuple[int, int, str]] = []
    if not _state_dir_ok():
        return out
    for f in STATE_DIR.glob("*.json"):
        raw: bytes | None = _read_small(f)
        try:
            d: object = None if raw is None else json.loads(raw)
        except (ValueError, RecursionError):
            continue
        valid: tuple[int, int, str] | None = _valid_state(d, f.name)
        if valid is None:
            continue
        port, pid, repo = valid
        if _pid_alive(pid):
            out.append((port, pid, repo))
        elif prune:
            try:
                f.unlink()
            except OSError:
                pass
    return sorted(out)


def _status() -> int:
    """One line per live viewer, `<port>  <repo>`, by port; else `no viewer runs`.
    Live: typed state file, live pid, and the port confirmed as a viewer of that
    repo (probed in parallel). The repo shown is the state file's, never the
    port holder's."""
    states: list[tuple[int, int, str]] = _read_states(prune=True)
    with ThreadPoolExecutor(max_workers=max(1, len(states))) as pool:
        ok: list[bool] = list(
            pool.map(
                _is_viewer_of, [s[0] for s in states], [Path(s[2]) for s in states]
            )
        )
    lines: list[str] = [f"{s[0]}  {s[2]}" for s, good in zip(states, ok) if good]
    print("\n".join(lines) if lines else "no viewer runs")
    return 0


def _stdin_dir() -> Path | None:
    """workspace.current_dir or cwd of the JSON a status line command gets on
    stdin (Claude Code pipes it); None for a tty, no data, or anything else."""
    if sys.stdin is None or sys.stdin.isatty():
        return None
    raw: str | bytes
    try:
        fd: int = sys.stdin.fileno()
    except (OSError, ValueError):  # not a real file descriptor (a test double)
        raw = sys.stdin.read(1 << 20)
    else:
        try:
            if not select.select([fd], [], [], 0.5)[0]:
                return None  # an open pipe nobody writes to: do not wait for it
            raw = os.read(fd, 1 << 20)  # what is there; no wait for EOF
        except OSError:
            return None
    try:
        data: object = json.loads(raw)
    except (ValueError, RecursionError):
        return None
    if not isinstance(data, dict):
        return None
    ws: object = data.get("workspace")
    d: object = ws.get("current_dir") if isinstance(ws, dict) else None
    d = d or data.get("cwd")
    return Path(d) if isinstance(d, str) and d else None


def _statusline(repo_arg: Path | None) -> int:
    """Print `🔍rk:<port>` (lowest port, wrapped in an OSC 8 hyperlink to
    http://127.0.0.1:<port>/) if a state file of the repo here has a live pid,
    else nothing. For a status line script: no probe, no network, never an error
    text, exit 0 always."""
    try:
        start: Path = repo_arg or _stdin_dir() or Path.cwd()
        repo: Path = ledger.find_repo(start, explicit=repo_arg is not None)
        # ponytail: pid alive only, so a reused pid could show a stale port;
        # `--status` does the real check.
        ports: list[int] = [
            port for port, _pid, r in _read_states(prune=False) if r == str(repo)
        ]
        if ports:  # an OSC 8 terminal link to our own port; plain text elsewhere
            link: str = f"\x1b]8;;http://127.0.0.1:{ports[0]}/\x1b\\"
            print(f"{link}🔍rk:{ports[0]}\x1b]8;;\x1b\\", end="", flush=True)
    except Exception:  # a status line must stay quiet, whatever went wrong
        pass
    return 0


def _on_term(signum: int, frame: FrameType | None) -> None:
    raise KeyboardInterrupt  # SIGTERM / SIGHUP end serve_forever like Ctrl-C


def main(argv: list[str]) -> int:
    p: argparse.ArgumentParser = argparse.ArgumentParser(
        prog="rk.py ui",
        description="Serve a read-only browser for pm/ledger.jsonl on 127.0.0.1.",
    )
    p.add_argument("--repo", type=Path, help="dir holding pm/ledger.jsonl")
    p.add_argument(
        "--port",
        type=int,
        help=f"default: the first free port from {DEFAULT_PORT}, {PORT_TRIES} tried",
    )
    p.add_argument("--no-open", action="store_true", help="do not open a browser")
    p.add_argument(
        "--status", action="store_true", help="list running viewers and exit"
    )
    p.add_argument(
        "--statusline",
        action="store_true",
        help="print the status line segment for this repo's viewer, or nothing",
    )
    a: argparse.Namespace = p.parse_args(argv)
    if a.status:
        return _status()
    if a.statusline:
        return _statusline(a.repo)
    try:
        repo: Path = (
            ledger.find_repo(a.repo, explicit=True)
            if a.repo
            else ledger.find_repo(Path.cwd())
        )
    except ledger.LedgerError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if not (DIST / "index.html").is_file():
        print(
            f"error: no built bundle in {DIST}; run: cd {DIST.parent} && npm ci && "
            "npm run build",
            file=sys.stderr,
        )
        return 1
    explicit: bool = a.port is not None  # an explicit port means that port
    ports: list[int] = (
        [a.port] if explicit else [DEFAULT_PORT + i for i in range(PORT_TRIES)]
    )
    # check and probe all ports at once: about one deadline, not one per port
    with ThreadPoolExecutor(max_workers=len(ports)) as pool:
        taken: list[int] = [q for q, t in zip(ports, pool.map(_taken, ports)) if t]
        found: list[bool] = list(pool.map(_is_viewer_of, taken, [repo] * len(taken)))
    viewers: list[int] = [q for q, ok in zip(taken, found) if ok]
    if viewers or (explicit and taken):  # never a second viewer by accident
        shown: int = viewers[0] if viewers else taken[0]  # ports ascend
        print(_port_taken_message(shown, bool(viewers)), file=sys.stderr)
        return 1
    server: ThreadingHTTPServer | None = None
    for port in ports:
        if port in taken:
            continue
        try:
            server = ThreadingHTTPServer(
                ("127.0.0.1", port), make_handler(repo, DIST)
            )
            break
        except (OSError, OverflowError) as e:
            if not (isinstance(e, OSError) and e.errno == errno.EADDRINUSE):
                why: str = (e.strerror if isinstance(e, OSError) else None) or str(e)
                print(
                    f"error: cannot listen on 127.0.0.1:{port}: {why}; "
                    "pick another --port",
                    file=sys.stderr,
                )
                return 1
            if explicit:  # taken after all (e.g. bound, not listening): say so
                print(
                    _port_taken_message(port, _is_viewer_of(port, repo)),
                    file=sys.stderr,
                )
                return 1
            # ponytail: lost a race for this port; go on to the next free one with
            # no new probe round, so a viewer of this repo that won it is not seen.
    if server is None:
        print(
            f"error: 127.0.0.1:{ports[0]} to {ports[-1]} are all taken; "
            "pick a --port",
            file=sys.stderr,
        )
        return 1
    url: str = f"http://127.0.0.1:{server.server_port}/"
    # SIGTERM (a stopped background task) and SIGHUP (a closed terminal) end
    # serve_forever like Ctrl-C; installed before the state file exists
    sigs: list[int] = [signal.SIGTERM]
    if hasattr(signal, "SIGHUP"):
        sigs.append(signal.SIGHUP)
    old: dict[int, Any] = {s: signal.signal(s, _on_term) for s in sigs}
    state: Path | None = None
    try:
        state = _write_state(server.server_port, repo)
        print(f"rk ui: {repo} at {url}", flush=True)
        if state is None:  # after the first line, which is the one that is read
            print(
                f"warning: cannot write a state file in {STATE_DIR}; --status "
                "and --statusline will not list this viewer",
                file=sys.stderr,
            )
        if not a.no_open:
            webbrowser.open(url)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for s, h in old.items():
            signal.signal(s, signal.SIG_DFL if h is None else h)
        server.server_close()
        if state is not None:
            try:
                state.unlink()
            except OSError:
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
