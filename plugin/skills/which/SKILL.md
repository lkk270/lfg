---
name: which
description: >
  Looks at graph status, the current run folder, git status and Linear, then tells
  you the single next skill to run and why. Use when the user says "which skill do
  I use?", "what now?", "what next?", "where was I?", "I'm lost", or starts a session
  without saying what they want.
author: Varun Singh
phase: helper
lanes: [express, standard, full, hotfix]
reads: [lfg graphs status, lfg run path, git status, run folder, tasks.json, dev-graph]
writes: []
auto-trigger: true
preflight: graphs
---

## Step 0: preflight

1. Run `lfg graphs ensure`. If it exits non-zero, stop, show its output, and recommend fixing that first (`lfg doctor`).
2. `lfg run path`. Exit 1 means no current run; that is a valid state, not an error.

## Steps

1. **Collect facts** (read-only, in parallel): `lfg graphs status`, `lfg run path`, `git status --short`, `git diff --stat`, `ls <run>`, `tasks.json` (open tasks with satisfied `depends_on`), `ready.json`, `06-review.json` verdict, `HANDOFF.md` "Next step". If dev-graph has an open map `Epic`, its frontier.
2. **Walk the tree**, first match wins:

| State | Next |
|---|---|
| User's words describe a bug / failure | `/lfg:fix` |
| User asks how something works | `/lfg:explain` |
| User asks what a change breaks | `/lfg:impact` |
| Diff or plan adds a package, URL, image, action or model without `05-secure.json` | `/lfg:secure <thing>` |
| `HANDOFF.md` exists with a next step | that step |
| No run, idea is huge / multi-session | `/lfg:map` |
| No run, new idea | `/lfg:lfg <idea>` (or `/lfg:wizard` for guided) |
| Open map Epic, nothing in progress | `/lfg:map <epic>` (next frontier ticket) |
| Run has no `01-brief.md` | `/lfg:grill` |
| Brief but no `02-design.md`/`tasks.json` (Standard/Full) | `/lfg:plan` |
| Open unblocked tasks in `tasks.json` | `/lfg:build` |
| Code changed, no `ready.json` or it is red | `/lfg:check` |
| Green, no `06-review.json` | `/lfg:review-coach` |
| Verdict `changes` | `/lfg:fix`, then `/lfg:check` |
| Verdict `approve`, no `07-shipcheck.json`/`COMMIT_MSG.md` | `/lfg:ship` |
| Ship packet written, uncommitted | You commit and push; then `lfg watch` |
| Merged | `/lfg:learn` |
| Approach unclear: try it / read up | `/lfg:spike` / `/lfg:research` |
| Ending the session | `/lfg:handoff` |

3. If two rows match, pick the earlier one and mention the other.

## Output

Three lines in chat:
```
Next: /lfg:<skill> <args>
Why: <the fact that decided it>
Then: /lfg:<skill> → /lfg:<skill>
```

## Rules

- Read-only. Never runs the recommended skill itself; the user types it.
- Always name skills with the `lfg:` prefix: a personal skill with the same short name (e.g. `/ship`) would win.
- Base the answer on files and command output you just read, not memory.
- Never recommend committing as an agent step; the human commits.
