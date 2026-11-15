---
description: Start or stop the read-only ledger viewer (rk ui) in the browser
argument-hint: "[start|stop] [--port N] [--repo DIR]"
---

The ledger viewer is a local, read-only web page for `pm/ledger.jsonl`. It
listens on 127.0.0.1 only and never writes the ledger.

Arguments: $ARGUMENTS. No argument, or `start`: start it. `stop`: stop it.

**Start**

1. If this session already runs the viewer as a background task, do not start
   a second one: give the user its URL and stop here.
2. Run this command with the Bash tool as a background task
   (`run_in_background: true`), from the repo root, passing on any `--port` or
   `--repo` the user gave:

   `python3 -I "${CLAUDE_PLUGIN_ROOT}/skills/research-kit/scripts/rk.py" ui`

   It opens a browser tab by itself and keeps running until it is stopped.
3. Read the first line of the task's output and tell the user the URL from it
   (`rk ui: <repo> at http://127.0.0.1:<port>/`) and that `/rk-viewer stop`
   ends it. The viewer ends with the session.
4. If the output is an error instead, show it and do no more:
   - `cannot listen on 127.0.0.1:<port>`: the port is taken, most often by a
     viewer of another session. Tell the user the URL `http://127.0.0.1:<port>/`
     to try, and that `/rk-viewer start --port <other>` starts a second one.
   - no ledger in this repo, or no built bundle: say so.

**Stop**

Stop the background task this session started for the viewer (TaskStop with
its task id) and confirm. If this session started none, say so: a viewer of
another session is stopped there. Never kill a process by port or by name.
