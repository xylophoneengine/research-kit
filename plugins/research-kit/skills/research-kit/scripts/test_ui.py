#!/usr/bin/env python3
"""Tests for ui.py. Run: python3 -I test_ui.py (prints PASS/FAIL per test)."""

from __future__ import annotations

import contextlib
import hashlib
import http.client
import importlib.util
import io
import json
import socket
import subprocess
import sys
import tempfile
import threading
import traceback
from collections.abc import Callable, Iterator
from http.server import ThreadingHTTPServer
from importlib.machinery import ModuleSpec
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import urlsplit

# -I drops the script dir from sys.path, so load ui.py by path.
_spec: ModuleSpec | None = importlib.util.spec_from_file_location(
    "ui", Path(__file__).with_name("ui.py")
)
assert _spec is not None and _spec.loader is not None
ui: ModuleType = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ui)

REAL_DIST: Path = ui.DIST
RK_PY: Path = Path(__file__).with_name("rk.py")

TWO: list[str] = [
    '{"ts":"2026-11-13T12:00:00+01:00","who":"lead","ev":"add","id":"T-1","f":'
    '{"type":"task","title":"a","status":"open","owner":"x","stage":"","note":"n",'
    '"links":[],"refs":[]}}',
    '{"ts":"2026-11-13T12:05:00+01:00","who":"hook","ev":"set","id":"T-1","f":'
    '{"status":"running"}}',
    '{"ts":"2026-11-13T12:06:00+01:00","who":"lead","ev":"add","id":"D-1","f":'
    '{"type":"decision","title":"b","status":"done","owner":"user","stage":"",'
    '"note":"","links":["T-1"],"refs":[],"source":"old.md:3","legacy_id":"D-07",'
    '"imported":true,"date":"2026-10-01"}}',
]


@contextlib.contextmanager
def tmpdir() -> Iterator[Path]:
    with tempfile.TemporaryDirectory() as d:
        yield Path(d).resolve()


def mk_repo(tmp: Path, lines: list[str]) -> Path:
    """A repo dir under tmp whose pm/ledger.jsonl holds `lines`."""
    repo: Path = tmp / "repo"
    (repo / "pm").mkdir(parents=True)
    (repo / "pm" / "ledger.jsonl").write_text("".join(ln + "\n" for ln in lines))
    return repo


def mk_dist(tmp: Path) -> Path:
    """A fake built bundle tmp/ui/dist, plus tmp/ui/secret.txt beside it."""
    dist: Path = tmp / "ui" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><p>rk ui</p>")
    (dist / "assets" / "app.js").write_text("console.log(1);")
    (tmp / "ui" / "secret.txt").write_text("secret")
    return dist


def serve(repo: Path, dist: Path) -> tuple[ThreadingHTTPServer, str]:
    """Handler on 127.0.0.1, free port, daemon thread; returns server, base URL."""
    server: ThreadingHTTPServer = ThreadingHTTPServer(
        ("127.0.0.1", 0), ui.make_handler(repo, dist)
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


def req(
    base: str, path: str, method: str = "GET", host: str | None = None
) -> tuple[int, dict[str, str], bytes]:
    """Raw request (path sent as given, no client-side normalising).

    host: None = the client's default Host header, "" = no Host header."""
    u = urlsplit(base)
    conn: http.client.HTTPConnection = http.client.HTTPConnection(
        u.hostname or "", u.port, timeout=5
    )
    try:
        if host is None:
            conn.request(method, path)
        else:
            conn.putrequest(method, path, skip_host=True)
            if host:
                conn.putheader("Host", host)
            conn.endheaders()
        r: http.client.HTTPResponse = conn.getresponse()
        return r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()
    finally:
        conn.close()


@contextlib.contextmanager
def running(lines: list[str]) -> Iterator[tuple[Path, Path, str]]:
    """repo, dist, base URL of a served temp repo; shuts the server down."""
    with tmpdir() as tmp:
        repo: Path = mk_repo(tmp, lines)
        dist: Path = mk_dist(tmp)
        server, base = serve(repo, dist)
        try:
            yield repo, dist, base
        finally:
            server.shutdown()
            server.server_close()


def call_main(argv: list[str]) -> tuple[int, str]:
    """ui.main(argv) with stderr captured."""
    err: io.StringIO = io.StringIO()
    with contextlib.redirect_stderr(err):
        rc: int = ui.main(argv)
    return rc, err.getvalue()


def test_payload_shape() -> None:
    with tmpdir() as tmp:
        repo: Path = mk_repo(tmp, TWO)
        p: dict[str, Any] = ui.payload(repo)  # Any: JSON-shaped nesting
    assert set(p) == {"repo", "entries", "events", "types"}
    assert p["repo"] == str(repo)
    entries: list[dict[str, Any]] = p["entries"]
    events: list[dict[str, Any]] = p["events"]
    types: dict[str, str] = p["types"]
    assert [e["id"] for e in entries] == ["T-1", "D-1"]
    t1: dict[str, Any] = entries[0]
    assert t1["status"] == "running" and t1["started"] == "2026-11-13T12:05:00+01:00"
    assert entries[1]["extra"] == {
        "source": "old.md:3",
        "legacy_id": "D-07",
        "imported": True,
        "date": "2026-10-01",
    }
    assert entries[1]["created"] == "2026-10-01"
    assert [(e["line"], e["id"], e["ev"]) for e in events] == [
        (1, "T-1", "add"),
        (2, "T-1", "set"),
        (3, "D-1", "add"),
    ]
    assert events[1]["f"] == {"status": "running"}
    assert set(events[0]) == {"line", "ts", "who", "ev", "id", "f"}
    assert list(types)[:2] == ["task", "decision"] and types["deferred"] == "DF"
    json.dumps(p)


def test_api_ledger_200() -> None:
    with running(TWO) as (repo, _dist, base):
        status, headers, body = req(base, "/api/ledger")
        assert status == 200, status
        assert headers["content-type"].startswith("application/json"), headers
        assert headers["cache-control"] == "no-store", headers
        assert json.loads(body) == json.loads(json.dumps(ui.payload(repo)))
        status, _h, _b = req(base, "/api/ledger?x=1")
        assert status == 200, status


def test_broken_ledger_500() -> None:
    with running(TWO + ["not json"]) as (_repo, _dist, base):
        status, headers, body = req(base, "/api/ledger")
    assert status == 500, status
    assert headers["content-type"].startswith("application/json"), headers
    got: object = json.loads(body)
    assert isinstance(got, dict) and set(got) == {"error"}, got
    assert "pm/ledger.jsonl:4" in got["error"], got


def test_kinds_not_utf8_500() -> None:
    with running(TWO) as (repo, _dist, base):
        (repo / "pm" / "kinds").mkdir()
        (repo / "pm" / "kinds" / "x.md").write_bytes(b"\xff\xfe bad")
        err: io.StringIO = io.StringIO()
        with contextlib.redirect_stderr(err):
            status, headers, body = req(base, "/api/ledger")
    assert status == 500, status
    assert headers["content-type"].startswith("application/json"), headers
    got: object = json.loads(body)
    assert isinstance(got, dict) and set(got) == {"error"}, got
    assert got["error"].startswith("UnicodeDecodeError: "), got
    assert err.getvalue() == "", err.getvalue()


def test_host_check_403() -> None:
    with running(TWO) as (_repo, _dist, base):
        port: int | None = urlsplit(base).port
        for path in ("/api/ledger", "/", "/assets/app.js"):
            assert req(base, path, host=f"localhost:{port}")[0] == 200, path
            for host in (f"evil.example:{port}", "127.0.0.1", f"localhost:{port}1", ""):
                status, _h, body = req(base, path, host=host)
                assert status == 403 and b"entries" not in body, (path, host, status)
        assert req(base, "/api/ledger", "POST", host=f"evil.example:{port}")[0] == 403


def test_post_405() -> None:
    with running(TWO) as (_repo, _dist, base):
        for method in ("POST", "PUT", "DELETE", "PATCH", "HEAD"):
            for path in ("/api/ledger", "/"):
                status, _h, _b = req(base, path, method)
                assert status == 405, (method, path, status)


def test_static_and_traversal() -> None:
    with running(TWO) as (_repo, dist, base):
        status, _h, body = req(base, "/")
        assert status == 200 and body == (dist / "index.html").read_bytes()
        status, headers, body = req(base, "/assets/app.js")
        assert status == 200 and body == b"console.log(1);"
        assert "javascript" in headers["content-type"], headers
        for path in (
            "/nope.js",
            "/../secret.txt",
            "/%2e%2e/secret.txt",
            "/assets/../../secret.txt",
            "/assets/%2e%2e/%2e%2e/secret.txt",
            "//etc/passwd",
            "/assets",
            "/%00",
        ):
            status, _h, body = req(base, path)
            assert status == 404 and b"secret" not in body, (path, status)


def test_read_only() -> None:
    with running(TWO) as (repo, _dist, base):
        led: Path = repo / "pm" / "ledger.jsonl"
        before: str = hashlib.sha256(led.read_bytes()).hexdigest()
        listing: list[str] = sorted(p.name for p in (repo / "pm").iterdir())
        for _ in range(3):
            assert req(base, "/api/ledger")[0] == 200
        assert hashlib.sha256(led.read_bytes()).hexdigest() == before
        assert not (repo / "pm" / "STATUS.md").exists()
        assert sorted(p.name for p in (repo / "pm").iterdir()) == listing


def test_missing_bundle_exit_1() -> None:
    with tmpdir() as tmp:
        repo: Path = mk_repo(tmp, TWO)
        (tmp / "ui" / "dist").mkdir(parents=True)
        ui.DIST = tmp / "ui" / "dist"
        rc, err = call_main(["--repo", str(repo), "--no-open"])
    assert rc == 1, rc
    assert err.count("\n") == 1 and err.startswith("error: "), repr(err)
    assert "npm run build" in err and str(tmp / "ui") in err, err


def test_port_taken_exit_1() -> None:
    for addr in ("127.0.0.1", "0.0.0.0"):  # 0.0.0.0: SO_REUSEADDR would shadow it
        with tmpdir() as tmp, socket.socket() as s:
            s.bind((addr, 0))
            s.listen()
            port: int = s.getsockname()[1]
            repo: Path = mk_repo(tmp, TWO)
            ui.DIST = mk_dist(tmp)
            argv: list[str] = ["--repo", str(repo), "--port", str(port), "--no-open"]
            rc, err = call_main(argv)
        assert rc == 1, (addr, rc)
        assert err.count("\n") == 1 and err.startswith("error: "), repr(err)
        assert str(port) in err and "Traceback" not in err, err


def test_no_ledger_exit_1() -> None:
    with tmpdir() as tmp:
        rc, err = call_main(["--repo", str(tmp), "--no-open"])
    assert rc == 1, rc
    assert err.startswith("error: no pm/ledger.jsonl"), err


def test_rk_dispatch() -> None:
    r: subprocess.CompletedProcess[str] = subprocess.run(
        [sys.executable, "-I", str(RK_PY), "ui", "--help"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0 and "--port" in r.stdout, (r.returncode, r.stderr)
    r = subprocess.run(
        [sys.executable, "-I", str(RK_PY), "--help"], capture_output=True, text=True
    )
    assert r.returncode == 0 and "ui" in r.stdout.split("{", 1)[1].split("}")[0], (
        r.stdout
    )


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
        except BaseException as e:  # SystemExit from argparse too
            failed.append(name)
            print(f"FAIL {name}: {type(e).__name__}: {e}")
            if not isinstance(e, AssertionError):
                traceback.print_exc(limit=3, file=sys.stdout)
        finally:
            ui.DIST = REAL_DIST
    if failed:
        print(f"{len(failed)} of {len(tests)} failed: {', '.join(failed)}")
        return 1
    print("all ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
