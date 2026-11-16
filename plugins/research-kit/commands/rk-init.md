---
description: Set up a research repo (AGENTS.md, pm/ folder, kind files)
argument-hint: "[repo_dir]"
---

Invoke the `research-kit:research-kit` skill, mode init. Arguments: $ARGUMENTS

The skill asks its questions in two calls (at most four per call): the first four are kinds, mode, git policy and "Keep pm/ and the rule files out of git (local only)?", which sets `--pm local` (default no, `--pm tracked`); the global note comes in a second call. `--pm local|tracked` may also be given directly. `--pm local` writes `pm/config.json`; `rk doctor` then starts with `pm: local only (pm/config.json): git checks on pm/ skipped`.
