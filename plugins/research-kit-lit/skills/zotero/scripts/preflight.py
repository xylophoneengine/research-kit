"""Zotero preflight: shell-checkable facts before any Zotero MCP write.

Run:  python3 -I <plugin>/skills/zotero/scripts/preflight.py
      python3 -I <plugin>/skills/zotero/scripts/preflight.py --file-check ATTKEY

Read-only. Stdlib only. Never prints or writes an API key (presence only).
Exit 0 = verdict OK, 1 = ASK_USER.
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

LOCAL_API: str = "http://127.0.0.1:23119/api/users/0"
WEB_API: str = "https://api.zotero.org/users"
HOME: Path = Path.home()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Make a 3xx surface as HTTPError instead of being followed."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        return None


def get(url: str, headers: dict[str, str] | None = None) -> tuple[int, bytes]:
    """GET without following redirects. Returns (status, body); status 0 = no answer."""
    opener: urllib.request.OpenerDirector = urllib.request.build_opener(NoRedirect)
    req: urllib.request.Request = urllib.request.Request(url, headers=headers or {})
    try:
        with opener.open(req, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0, b""


def mcp_env_blocks() -> list[tuple[str, dict[str, str]]]:
    """Every zotero MCP server env block: ~/.claude.json (global + per project), ./.mcp.json."""
    out: list[tuple[str, dict[str, str]]] = []
    cj: Path = HOME / ".claude.json"
    if cj.exists():
        d: dict = json.loads(cj.read_text())
        if "zotero" in d.get("mcpServers", {}):
            out.append(("~/.claude.json global", d["mcpServers"]["zotero"].get("env", {})))
        for proj, pd in d.get("projects", {}).items():
            srv: dict = (pd.get("mcpServers") or {}).get("zotero") or {}
            if srv:
                out.append((f"~/.claude.json project {proj}", srv.get("env", {})))
    pm: Path = Path.cwd() / ".mcp.json"
    if pm.exists():
        srv2: dict = json.loads(pm.read_text()).get("mcpServers", {}).get("zotero") or {}
        if srv2:
            out.append((str(pm), srv2.get("env", {})))
    return out


def checks() -> list[tuple[str, str, str]]:
    """Return (level, name, message); level PASS / FAIL / WARN / INFO."""
    res: list[tuple[str, str, str]] = []

    # 1 Zotero desktop running (process name is lowercase "zotero" on macOS)
    p: subprocess.CompletedProcess[str] = subprocess.run(
        ["pgrep", "-i", "zotero"], check=False, capture_output=True, text=True
    )
    res.append(
        ("PASS", "desktop", "Zotero process running")
        if p.returncode == 0
        else ("FAIL", "desktop", "Zotero desktop not running: ask the user to start it")
    )

    # 2 local API reachable
    code: int
    body: bytes
    code, _ = get(f"{LOCAL_API}/items/top?limit=1")
    res.append(
        ("PASS", "local-api", "127.0.0.1:23119 local API = 200")
        if code == 200
        else (
            "FAIL",
            "local-api",
            (
                f"local API status {code}: Zotero Settings > Advanced > 'Allow other "
                "applications on this computer to communicate with Zotero'"
            ),
        )
    )

    # 3 desktop file sync target (prefs.js snapshot, written on change / exit)
    prefs: list[str] = glob.glob(
        str(HOME / "Library/Application Support/Zotero/Profiles/*/prefs.js")
    ) + glob.glob(str(HOME / ".zotero/zotero/*/prefs.js"))
    if not prefs:
        res.append(("FAIL", "sync-target", "no Zotero prefs.js found: cannot see sync target"))
    for pf in prefs:
        m: re.Match[str] | None = re.search(
            r'"extensions\.zotero\.sync\.storage\.protocol",\s*"(\w+)"',
            Path(pf).read_text(errors="replace"),
        )
        proto: str = m.group(1) if m else "zotero (default, line absent)"
        res.append(
            ("PASS", "sync-target", f"file sync protocol = webdav ({Path(pf).parent.name})")
            if proto == "webdav"
            else ("FAIL", "sync-target", f"file sync protocol = {proto}: files would go to zotero.org")
        )

    # 4 MCP server env: web key masked, local on, sqlite backend
    shell_key: bool = bool(os.environ.get("ZOTERO_API_KEY"))
    blocks: list[tuple[str, dict[str, str]]] = mcp_env_blocks()
    if not blocks:
        res.append(("FAIL", "mcp-config", "no zotero MCP server config found"))
    for where, env in blocks:
        if env.get("ZOTERO_API_KEY", None) == "":
            res.append(("PASS", "mcp-key-mask", f"{where}: ZOTERO_API_KEY masked to empty"))
        elif "ZOTERO_API_KEY" in env:
            res.append(("FAIL", "mcp-key-mask", f"{where}: ZOTERO_API_KEY set -> hybrid/web risk"))
        elif shell_key:
            res.append(
                ("FAIL", "mcp-key-mask", f"{where}: no ZOTERO_API_KEY mask, shell exports one -> hybrid risk")
            )
        else:
            res.append(("PASS", "mcp-key-mask", f"{where}: no web key anywhere"))
        local: str = env.get("ZOTERO_LOCAL", "").lower()
        res.append(
            ("PASS", "mcp-local", f"{where}: ZOTERO_LOCAL on")
            if local in ("true", "1", "yes")
            else ("FAIL", "mcp-local", f"{where}: ZOTERO_LOCAL = '{local}' (want true)")
        )
        backend: str = env.get("ZOTERO_SEARCH_BACKEND", "")
        res.append(
            ("PASS", "mcp-backend", f"{where}: ZOTERO_SEARCH_BACKEND = sqlite")
            if backend == "sqlite"
            else ("WARN", "mcp-backend", f"{where}: SEARCH_BACKEND '{backend}': search_all_libraries fails")
        )

    # 5 local write key held (presence only)
    cfg: Path = HOME / ".config/zotero-mcp/config.json"
    la: dict = json.loads(cfg.read_text()).get("local_api", {}) if cfg.exists() else {}
    res.append(
        ("PASS", "local-write-key", "zotero-mcp config holds a granted local write key")
        if la.get("granted") and la.get("key")
        else (
            "FAIL",
            "local-write-key",
            "no local write key: user switches to Zotero, agent calls zotero_authorize_local_writes",
        )
    )

    # 6 read-only web key in shell (only for the /file check)
    has_id: bool = bool(os.environ.get("ZOTERO_LIBRARY_ID"))
    res.append(
        ("INFO", "web-check", "ZOTERO_API_KEY + ZOTERO_LIBRARY_ID in shell: --file-check possible")
        if shell_key and has_id
        else ("INFO", "web-check", "no web key/id in shell: --file-check impossible, use WebDAV-server evidence")
    )

    # 7 group libraries: their files always sync to zotero.org, never WebDAV
    code, body = get(f"{LOCAL_API}/groups")
    n: int = len(json.loads(body)) if code == 200 and body else 0
    res.append(
        ("WARN", "groups", f"{n} group library(ies): attach ONLY in My Library (users/0)")
        if n
        else ("INFO", "groups", "no group libraries")
    )
    return res


def file_check(att: str) -> int:
    """Web API: is attachment `att` stored on zotero.org? Prints status codes only."""
    key: str = os.environ.get("ZOTERO_API_KEY", "")
    lib: str = os.environ.get("ZOTERO_LIBRARY_ID", "")
    if not (key and lib):
        print("FILE-CHECK: ASK_USER -- no ZOTERO_API_KEY / ZOTERO_LIBRARY_ID in shell env")
        return 1
    hdr: dict[str, str] = {"Zotero-API-Key": key, "Zotero-API-Version": "3"}
    ic: int
    ib: bytes
    ic, ib = get(f"{WEB_API}/{lib}/items/{att}", hdr)
    fc: int
    fc, _ = get(f"{WEB_API}/{lib}/items/{att}/file", hdr)
    md5: bool = bool(ic == 200 and json.loads(ib).get("data", {}).get("md5"))
    print(f"FILE-CHECK {att}: item={ic} md5_set={md5} file={fc}")
    if fc in (301, 302, 303, 307):
        print("STOP: file is on zotero.org storage. Notify the user, attach nothing more.")
        return 1
    if ic != 200:
        print("NO EVIDENCE: item not on the server yet (sync pending). Retry later.")
        return 1
    if fc == 404 and md5:
        print("OK: file synced (md5 set) and not on zotero.org -> WebDAV.")
        return 0
    if fc == 404:
        print("WEAK: not on zotero.org now, but file sync not finished (md5 unset). Retry.")
        return 1
    print("UNCLEAR: unexpected status. Notify the user.")
    return 1


def main() -> int:
    ap: argparse.ArgumentParser = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file-check", metavar="ATTKEY", help="Web API /file check")
    a: argparse.Namespace = ap.parse_args()
    if a.file_check:
        return file_check(a.file_check)
    res: list[tuple[str, str, str]] = checks()
    for lvl, name, msg in res:
        print(f"{lvl:4} {name:15} {msg}")
    fails: list[str] = [f"{n}: {m}" for lvl, n, m in res if lvl == "FAIL"]
    print(
        "\nMCP STEP (shell cannot do it; the live MCP env may differ from config):\n"
        "  ToolSearch select:mcp__zotero__zotero_write_capabilities\n"
        "  zotero_write_capabilities()  -> require BOTH lines:\n"
        "    '**Mode:** local'  and  'Web API credentials: not set'\n"
        "  Mode none/'key not held' -> zotero_authorize_local_writes (user clicks Always Allow).\n"
        "  hybrid / web / credentials set -> STOP, notify the user, ask for guidance."
    )
    if fails:
        print("\nVERDICT: ASK_USER")
        for f in fails:
            print(f"  - {f}")
        return 1
    print("\nVERDICT: OK (shell side). Metadata writes ok after the MCP step; "
          "attach only after the one-file sync test in the skill.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
