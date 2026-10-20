Rule module: worktrees · LFG · author Varun Singh

# worktrees: another branch without touching the user's checkout

## Graphs: one per repo, every branch

The graphs live in the main checkout, in `.code-review-graph/` and `graphify-out/` (git-ignored, never committed). Every branch and every worktree uses that one graph; `lfg graphs ensure` syncs it to whatever the main checkout has now, uncommitted edits included. Never build a second graph inside a worktree.

## You decide, the user does nothing

Worktrees are your tool, not the user's chore. Decide on your own whether one is needed, create it, use it and clean it up. Don't ask for permission, don't ask the user to run anything, and never `git checkout`/`switch`/`stash` their checkout.

| Situation | Do |
|---|---|
| The work belongs on a branch other than the one checked out (the user named one, the issue/PR is on one, a bug only on `release/x`, reviewing a PR branch) | `lfg worktree new <branch>` (an existing branch is checked out as is) |
| New, separate work while the checkout has uncommitted changes that belong to something else | `lfg worktree new lfg/<run-slug>` (a new branch from HEAD; `--from <ref>` for another base) so the two never mix |
| Parallel `/build` tickets | `/build`'s own throwaway worktrees in `SCRATCH/wt/<id>` (patches, cleaned up by `/build`); not `lfg worktree` |
| Work on the branch already checked out, on a clean checkout or on its own changes | No worktree |

If `lfg worktree new` fails because the branch is already checked out elsewhere, work in that existing worktree (`lfg worktree list`).

## Working in a worktree

- Run every command with the worktree as the working directory (`git -C <wt>`, `cd <wt> && …`).
- Graph tools see the main checkout's code, which may be another branch. Use them to find where to look, then confirm in the worktree's own files before relying on a fact:
  - code-review-graph MCP tools: pass `repo_root=<main checkout>`.
  - graphify: `--graph <main checkout>/graphify-out/graph.json`.
- `lfg run …`, `lfg gate`, `lfg secure`, `lfg shipcheck` work from the worktree too: the repo id is the same.
- Leave changes unstaged in the worktree, like anywhere else. No commits, merges, rebases or stashes; the user commits from the worktree.

## Telling the user

In your final reply, one line: where the changes are (`<path>`, branch `<branch>`) so they can review and commit there. Nothing else is needed from them.

## Cleaning up (yours to do)

- `lfg worktree list` shows every worktree; `*` marks the ones `lfg worktree` made.
- When a task ends with no changes in its worktree, run `lfg worktree remove <name>` yourself. SessionStart already removes `*` worktrees that are clean and unused for 24 hours (for example, the user committed there), so nobody has to. `remove` is safe to call: it refuses when there are uncommitted or untracked changes, never forces, and keeps the branch. A refusal means the user's work is there, so leave it.
- Never `git worktree remove --force` or delete a worktree folder by hand outside `/build`'s `SCRATCH/wt/`.
