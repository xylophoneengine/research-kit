---
name: surviving-compaction
description: Use when the user says "get ready for compact", "prepare for compaction", "I'm stopping here" or similar in a long session; when context is nearly full during multi-step or multi-agent work; when a session starts from a context summary ("This session is being continued from a previous conversation"); or when the user asks "where did we leave off?" after a break. Also use when spawning subagents or recording user decisions in a session long enough to be compacted.
---

# Surviving compaction

Files and commits are the store. The summary is only an index that says where to look, and after a compact it is a hypothesis until checked.

Compaction can arrive unannounced, so the handoff file is kept current during the session. "Prepare" is a short verification pass, not the moment the file gets written.

## The handoff file

One file per session, named `handoff-<YYYY-MM-DD>.md`, in `pm/handoffs/compact/` when the repo has a `pm/` folder, else in the folder the project names for session notes (ask once if it names none); at most four levels below the project root: the compact hooks (this plugin's `hooks/handoff-hook.sh`) find it by that name. Every slot is REQUIRED; write "none" when empty.

```markdown
# Handoff <date>
## User decisions and rules   (verbatim quotes, safety rules first)
## Done                       (each line: what + commit hash or log file path)
## In flight                  (per agent: name, worktree/branch, brief file path,
                               last commit hash, uncommitted file count, last known state)
## Open questions for the user
## Instructions given to the user  (path of the file that holds them)
## Next step                  (one action, with its precondition)
```

## As you go

| When | Do |
|---|---|
| Spawning an agent | Save its brief to a file first; append every later clarification to that file |
| User decides something or sets a rule | Quote it into the handoff file |
| A run proves something (tests, build) | Redirect output to a log file; put the path under Done |
| You give the user steps to follow | Write them to a file; chat only points at it |
| A question for the user comes up | Add it to Open questions |

## Prepare (user announces a compact, or context is nearly full)

1. Ask each running agent for a WIP commit and its hash.
2. If an agent does not answer in time, record its worktree, `git status --short` file count and the word "uncommitted" under In flight. Never commit, stash or reset in a worktree an agent may still be using.
3. Re-read the handoff file against the template and fill every slot that is stale.
4. Tell the user the handoff file path and anything that could not be saved.
5. End with the line the user must type, since only they can start a compact: `/compact Read <handoff file path> first.`

## Resume (session starts from a summary, or after a break)

Do these before answering "where did we leave off" and before any next step:

1. Read the handoff file.
2. Check each claim against the repo: `git log`, `git status` per worktree, tags, the files the handoff names.
3. For each agent under In flight, look at the live agent list:
   - listed: message it and ask for its state;
   - not listed: start a new agent from the brief file plus the last commit, telling it what is uncommitted in the worktree.
4. Tell the user what matched and what differed, then carry on from Next step.

A detail missing from the handoff file is recovered from the session transcript file, not from memory.

## Common mistakes

- Writing the handoff only at prepare time: an unannounced compact loses it.
- "Tests green" with no log path: the claim cannot be checked later.
- Treating a "still running" line in the summary as true: the agent may be gone and its work uncommitted.
- Restarting an agent that is still listed: two agents edit one worktree.
- Spreading state over memory, ledger and notes with no single file naming them all.
