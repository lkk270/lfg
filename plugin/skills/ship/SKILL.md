---
name: ship
description: >
  Proves the change is shippable and hands it to you: re-runs the green gate, runs the ship
  check (Docker build, scan, run, smoke test, delete, verify cleanup) and the shipping
  checklist, then writes COMMIT_MSG.md and PR_BODY.md. Never commits, pushes or deploys.
  Use when the user says "ship it", "ready for a PR", "prep the commit", "is it shippable?".
author: Varun Singh
phase: ship
lanes: [express, standard, full, hotfix]
reads: [01-brief.md, 02-design.md, tasks.json, 04-qa.md, 05-secure.json, 05-pentest.json, 06-review.json, ready.json]
writes: [ready.json, 07-shipcheck.json, COMMIT_MSG.md, PR_BODY.md]
auto-trigger: false
preflight: graphs
---

# /ship: prove it, package it, hand it over

## Step 0: preflight

1. `lfg graphs ensure`. Non-zero exit: stop and show its output. Continue on a stale graph only if the user typed `--allow-stale`.
2. `lfg run path`. Exit 1: stop and tell the user to run `/check` first (there is nothing to ship from).

## Steps

1. **Gates 1–7 again.** `lfg gate` (rewrites `ready.json`). Read `06-review.json`: verdict `block`, or unresolved `changes` items without a linked `Issue`, fail gate 5. Run `lfg run review-status`: exit 1 means the review was written while checks were red and commits landed since, so it read code that has changed; ask for a fresh `/lfg:expert` (gate 5 fails until then). A review on red checks with the code unchanged stands. A check `lfg gate` shows as N/A (can't run here: a tool isn't installed) is not a failure: name the tool and its install hint, say CI runs it, and carry on. Read `05-secure.json` / `05-pentest.json` for open blockers (gates 7, 4). Anything red → stop, name it, point to `/check`, `/fix` or `/secure`.
2. **Pipeline.** `lfg ci-local`; then read-only `gh pr checks` / `gh run list --branch <branch>` if logged in. Report anything that would break CI or deploy.
3. **Ship check.** `lfg shipcheck` (one line per check; details in `07-shipcheck.json`). Docker not running → ask the user to start it, then re-run. Explain each step in plain words: Dockerfile lint, build (CI's target/platform), image scan and size change, run on the internal network, smoke test (routes skipped for real third-party credentials are reported as skipped), cleanup, cleanup verified. No Dockerfile → part A is N/A and the CI start command was smoke-tested instead; say so.
4. **Cleanup.** It is automatic and verified by `lfg shipcheck`. If its output reports leftovers, run `lfg shipcheck --cleanup` (LFG-labelled resources only) and show that the label-filtered `docker ps -a/images/network ls/volume ls` are empty.
5. **Shipping checklist** (from `07-shipcheck.json`): each of the 10 items is pass, fail, or N/A with a reason. Fill item 6 yourself by reading the diff: debug prints, focused tests, TODOs added in this run, commented-out code. Any fail → fix (or `/fix`) and re-run from step 1.
6. **Write `COMMIT_MSG.md`** in the run folder: Conventional-Commit subject ≤ 72 chars, blank line, body on *why* and what changed, `Refs: LIN-<n>` if there is an issue, blank line, and the last line exactly:
   `Co-Authored-By: Claude <noreply@anthropic.com>`
7. **Write `PR_BODY.md`**: summary (from the brief), design notes, QA matrix (from `04-qa.md`), secure summary, Strix summary, review verdict and deferred items, ship-check summary, `ready.json` gate table, and how to test. One-line security summaries only; no secrets, internal hostnames or exploit details.
8. **Leave it unstaged.** Show `git status --short`. Nothing is staged, committed or pushed by you.

**Done when:** all 8 gates pass in this run, cleanup is verified, and both files exist. Otherwise report what is red and stop.

## Output

Reply with the gate table, the ship-check summary, then the exact commands for the user to run in their own terminal:

```bash
git status                                   # review the change
git add <the files listed above>             # stage what you approve
git commit -F <run-folder>/COMMIT_MSG.md
git push -u origin <branch>
gh pr create --title "<subject line>" --body-file <run-folder>/PR_BODY.md
lfg watch                                    # follow CI read-only
```

**After merge** (when the user says it merged): propose moving the Linear issue to Done, showing the exact change; make it only after an explicit yes. Then suggest `/learn`.

## Rules

- **A run filed under another repo** (this repo's tasks live in another repo's run, e.g. `/lfg` resumed that repo's handoff): write this repo's results as `ready-<repo>.json` and `07-shipcheck-<repo>.json`, with `<repo>` the repo's folder name (e.g. `aegis-compliance-portal`), never over the run's own files. The dashboard shows them under this repo, and the owner repo keeps its own.
- Never deploy, `docker push`, `docker login`, or run deploy commands. The ship check is the only Docker work, through `lfg shipcheck`.
- Never commit, push, stage, or run `gh pr create`; the user does. See `lfg rule git-guard`.
- Never pass `.env` into a container or delete Docker resources without the run's `lfg.shipcheck` label.
- Report honestly: a skipped smoke route or N/A item is stated with its reason.
