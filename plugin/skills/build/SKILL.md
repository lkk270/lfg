---
name: build
description: >
  Implements the planned tickets test-first. One ticket runs in quick mode in the working
  tree; several run as parallel implementer subagents in throwaway git worktrees that
  return patches, which a merger applies in depends_on order with affected tests after
  each. Never commits. Use when the user says "build it", "implement this", "do the
  tickets", "write the code", or when a run has an approved tasks.json with unfinished tickets.
author: Varun Singh
phase: build
lanes: [express, standard, full, hotfix]
reads: [tasks.json, 01-brief.md, 02-design.md, code-review-graph, graphify]
writes: [code + tests (unstaged), 03-build-*.md, patches/*.patch, tasks.json, progress.md]
auto-trigger: true
preflight: graphs
adapted-from: mattpocock/skills/implement-spec + implement + tdd (MIT, © 2026 Matt Pocock)
---

## Step 0: preflight

1. Run `lfg graphs ensure`. If it exits non-zero, stop and show its output (only `--allow-stale` from the user overrides).
2. Run `lfg run path` → `RUN` (in the repo's `.lfg/runs/`, committed) and `lfg run scratch` → `SCRATCH` (this machine only, for ticket worktrees). No run or no `RUN/01-brief.md` → stop and suggest `/grill` (or `/lfg`). Run `lfg run doing build`.
3. Load `lfg rule tdd-rules`. Read `RUN/tasks.json`; if absent (Express), build one ticket from the brief's acceptance criteria and agree its seam with the user (unattended: the highest existing seam the graph shows), then write it to `RUN/tasks.json`.

## Steps

**Frontier** = tickets with `passes: false` whose `depends_on` all have `passes: true`.

### Quick mode (exactly one ticket in total, or the user asks for it)

1. Get context: `get_minimal_context_tool` + `get_review_context_tool` on the ticket's `graph_scope`; open only those files.
2. Red → green per `tdd-rules`, one test at a time, at the ticket's `test_seams`.
3. Type-check and run the touched test files often; run the affected tests (`tests_for` on changed nodes) at the end.
4. Write `RUN/03-build-<id>.md`; set `passes: true` only after the affected tests are green.

### Parallel mode (two or more tickets)

1. **Worktrees.** For each frontier ticket: `git worktree add --detach SCRATCH/wt/<id> HEAD`. In it, apply already-merged patches of its `depends_on` chain in order with `git apply --index RUN/patches/<dep>.patch` (the worktree's baseline; never a commit).
2. **Implementers** (background, one per ticket, agent = ticket `owner_role`: `software-engineer` or `ai-engineer`). Prompt contains only pointers:
   > Implement ticket `<id>` from `RUN/tasks.json` in worktree `SCRATCH/wt/<id>`. Read `RUN/01-brief.md`, `RUN/02-design.md`. Context: graph_scope `<…>`. Load `lfg rule tdd-rules`; test only at the ticket's `test_seams`. Do not commit or stage beyond what is stated. When green: `git -C SCRATCH/wt/<id> add -N . && git -C SCRATCH/wt/<id> diff --binary --full-index > RUN/patches/<id>.patch`. Write `RUN/03-build-<id>.md` (what changed, why, tests, open questions). Return only the two paths.
   `ai-engineer` tickets also produce prompt/version files, an eval suite with a baseline score, and a cost/latency budget table.
3. **Merger** (this session, or one `software-engineer` subagent), as each implementer finishes, in `depends_on` order:
   1. `git apply --3way RUN/patches/<id>.patch` in the main working tree; then `git reset -q -- <paths in the patch>` so the change stays unstaged (index only; never `--hard`).
   2. Conflict markers → resolve them using both tickets' `03-build-*.md`, keeping both behaviours.
   3. Run the affected tests (`tests_for` on the patch's changed nodes). Red → send the failure back to that ticket's implementer; do not mark it done.
   4. Green → set `passes: true` for the ticket, run `lfg issue sync-tasks` (marks its issue done), update `progress.md`, run `lfg graphs ensure`.
   5. Recompute the frontier and start implementers for newly unblocked tickets immediately.
4. **Integration pass.** When all tickets pass: type-check, run the full test suite once, list changed nodes with no test. All green: run `lfg run done build`.
5. **Cleanup.** `git worktree remove --force SCRATCH/wt/<id>` for every worktree, then `git worktree prune`. Keep `RUN/patches/` for the record.

## Output

- Code + tests in the working tree, **unstaged**.
- `RUN/03-build-<id>.md` per ticket; `RUN/patches/<id>.patch` in parallel mode.
- `RUN/tasks.json` with `passes` flipped only for verified tickets; `RUN/progress.md` updated (next: `/check`).
- Chat summary: tickets done / blocked, tests added, full-suite result (command + pass/fail counts), untested nodes, any new dependency (must already be in the brief).

## Rules

- No commits, merges, rebases or stashes anywhere, including worktrees. No new dependency unless the brief lists it.
- The run is for a branch other than the checked-out one: do it in `lfg worktree new <branch>`, never switch the user's checkout (`lfg rule worktrees`). `SCRATCH/wt/<id>` ticket worktrees are created inside that worktree's repo as usual.
- Tests come with the change; never skip, delete or weaken a test, never add lint/type suppressions.
- Stay inside each ticket's `graph_scope`; out-of-scope findings become a dev-graph `Issue`.
- Report exactly what ran. A failed ticket stays `passes: false` with its output in `notes`.
