---
name: spike
description: >
  Builds a throwaway prototype to answer one design question, in a scratch folder
  inside the run folder, then deletes it and keeps only the conclusion. Use when the
  user says "try a quick prototype", "would this approach work?", "spike this",
  "let me feel this state model", "show me a few UI options", or when a plan has an
  open question that a cheap working artifact would settle.
author: Varun Singh
phase: helper
lanes: [standard, full]
reads: [01-brief.md, 02-design.md, code-review-graph, graphify]
writes: [spike-<slug>.md]
auto-trigger: true
preflight: graphs
adapted-from: mattpocock/skills/prototype (MIT, © 2026 Matt Pocock)
---

## Step 0: preflight

1. Run `lfg graphs ensure`. If it exits non-zero, stop and show its output (only `--allow-stale` overrides).
2. `lfg run path`. If it exits 1, run `lfg run new spike-<slug>` and use the path it prints. Call it `<run>`.

## Steps

1. **State the question** in one paragraph: what is unknown, and what result would settle it. Write it at the top of `<run>/spike-<slug>.md` before any code.
2. **Pick the shape** from the question:
   - *Logic / state / data shape* → one self-contained HTML file: a pure logic module in its own `<script>` (reducer, state machine or pure functions; no DOM inside it), a readable state panel re-rendered after every action, one button per action, and tabbed walkthroughs for the happy path, an awkward edge case and an illegal move. Labels in domain language.
   - *What should it look like* → a few clearly different variants on one throwaway page, switched by a URL param.
   - *Does library/API X behave like Y* → the smallest script that calls it and prints the result.
   If ambiguous, pick by the surrounding code (backend → logic, page → UI) and state the assumption.
3. **Find the context** with the graphs, not by browsing: `get_minimal_context_tool` and `graphify query` for the module the spike is for.
4. **Build in `SCRATCH/spike-<slug>/`** (`lfg run scratch`, this machine only), never in the repo or the run folder, which is committed. Trivial to run (one command or a double-click). In-memory state. No tests, no polish, no abstractions. Print or render the full state after each action.
5. **Run it** and record what happened. If the user is around, let them drive it; their "wait, that shouldn't happen" moments are the findings.
6. **Conclude** in `spike-<slug>.md`: verdict, evidence, and the lift-out (the pure logic or snippet worth keeping, quoted inline, short).
7. **Delete** `SCRATCH/spike-<slug>/` (only that folder) and confirm it's gone.

## Output

`<run>/spike-<slug>.md`:
```
# Spike: <question>
Verdict: yes / no / partly — <one line>
Shape: logic | ui | api
What we tried · What happened · Evidence (commands, outputs)
Keep: <the validated logic or decision, ≤ 40 lines>
Feeds: 02-design.md section / ticket id
```
If the verdict is a design decision, offer to record it as an ADR under `lfg repo docs`.

## Rules

- Throwaway from the start. Nothing lands in the repo; no new dependencies in the repo's manifests (a spike needing one says so and runs `/secure <pkg>` first).
- No persistence unless persistence is the question; then a scratch file named `PROTOTYPE-wipe-me`.
- Don't generalise. One question per spike.
- Delete only the scratch folder you created.
