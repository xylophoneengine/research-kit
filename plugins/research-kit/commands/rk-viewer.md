---
description: Start or stop the read-only ledger viewer (rk ui) in the browser
argument-hint: "[start|stop] [--port N] [--repo DIR]"
---

The ledger viewer is a local, read-only web page for `pm/ledger.jsonl`. It
listens on 127.0.0.1 only and never writes the ledger. It has no login: while
it runs, any user logged in on this machine can read the ledger through it.

Arguments: $ARGUMENTS. No argument, or `start`: start it. `stop`: stop it.
The words `start` and `stop` are for you; never pass them to the script.

**Start**

1. If this session already runs the viewer as a background task, do not start
   a second one: give the user its URL and stop here.
2. Run this command with the Bash tool as a background task
   (`run_in_background: true`), from the repo root. Append only the options
   the user gave, `--port N` and `--repo DIR`, and nothing else from the
   arguments:

   `python3 -I "${CLAUDE_PLUGIN_ROOT}/skills/research-kit/scripts/rk.py" ui`

   It opens a browser tab by itself and keeps running until it is stopped.
3. Read the first line of the task's output and tell the user the URL from it
   (`rk ui: <repo> at http://127.0.0.1:<port>/`) and that
   `/research-kit:rk-viewer stop` ends it. The viewer ends with the session.
4. If the output is an error instead, show it and do no more:
   - `a ledger viewer for <repo> already runs at <url>`: the port answers
     like a viewer, most likely another session's (the viewer has no login,
     so this is not proof). Tell the user that repo and URL, and that
     `/research-kit:rk-viewer start --port <other>` starts a second one.
   - `a ledger viewer already runs at <url> (its ledger does not load)`: the
     same, but that viewer's ledger is broken; say so.
   - `is taken by something that is not a ledger viewer`: do not send the user
     to that address; offer `/research-kit:rk-viewer start --port <other>`.
   - no ledger in this repo, or no built bundle: say so.

**Stop**

Stop the background task this session started for the viewer (TaskStop with
its task id) and confirm. If this session started none, say so: a viewer of
another session is stopped there. Never kill a process by port or by name.
