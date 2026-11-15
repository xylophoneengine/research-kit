#!/usr/bin/env python3
"""Read-only local browser for pm/ledger.jsonl (rk.py ui).

Serves GET /api/ledger (the whole ledger, read fresh per request) and the built
frontend bundle in ../ui/dist on 127.0.0.1. Never writes the ledger or STATUS.md.

Usage:
  python3 -I rk.py ui [--repo DIR] [--port N] [--no-open]
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib.util
import json
import errno
import mimetypes
import socket
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import unquote

DIST: Path = Path(__file__).resolve().parent.parent / "ui" / "dist"
DEFAULT_PORT: int = 8765


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
        "repo": str(repo),
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


def main(argv: list[str]) -> int:
    p: argparse.ArgumentParser = argparse.ArgumentParser(
        prog="rk.py ui",
        description="Serve a read-only browser for pm/ledger.jsonl on 127.0.0.1.",
    )
    p.add_argument("--repo", type=Path, help="dir holding pm/ledger.jsonl")
    p.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help="default %(default)s"
    )
    p.add_argument("--no-open", action="store_true", help="do not open a browser")
    a: argparse.Namespace = p.parse_args(argv)
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
    try:
        if _taken(a.port):
            raise OSError(errno.EADDRINUSE, "Address already in use")
        server: ThreadingHTTPServer = ThreadingHTTPServer(
            ("127.0.0.1", a.port), make_handler(repo, DIST)
        )
    except (OSError, OverflowError) as e:
        why: str = (e.strerror if isinstance(e, OSError) else None) or str(e)
        print(
            f"error: cannot listen on 127.0.0.1:{a.port}: {why}; pick another --port",
            file=sys.stderr,
        )
        return 1
    url: str = f"http://127.0.0.1:{server.server_port}/"
    print(f"rk ui: {repo} at {url}", flush=True)
    if not a.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
