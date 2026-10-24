---
name: note
description: >
  Saves something worth remembering to dev-graph (team decisions, gotchas, invariants,
  follow-ups for this repo) or your second-brain (personal preferences, insights, people,
  open questions), always asking which one first. Use when the user says "remember that…",
  "note this", "add to my second brain", "add to dev-graph", "save this decision",
  "I always want…" or "open question: …".
author: Varun Singh
phase: helper
lanes: [express, standard, full, hotfix]
reads: [dev-graph, second-brain]
writes: [dev-graph Decision/Learning/Invariant/Principle/Issue, second-brain Note/Person]
auto-trigger: true
---

## Step 0: preflight

No graph preflight: `/note` never touches code. `lfg rule remember` for the item format and the stored queries. Optionally `lfg run path` to link the item to the current run; carry on if there is none.

## Steps

1. **Distil** what the user said into one or two plain sentences in their words. Several facts become several items.
2. **Classify** each item and propose a graph (see the table in `lfg rule remember`):
   - **dev-graph** (team, this repo): `Decision` with its why, `Learning` (gotcha, root cause, landmine), `Invariant`, `Principle`, `Issue` (follow-up).
   - **second-brain** (personal, every project): `Note` with a `kind` (`preference`, `insight`, `question`, `idea`, `reflection`), or a `Person`.
3. **Check for secrets and others' personal data.** Refuse to store that part and say why.
4. **Ask before writing**, even when the user named a graph and it fits: show the `Remember?` block from the rule module (exact text, proposed graph and kind) and wait. The user can switch the graph, pick both, edit the text or skip.
5. **De-duplicate** in the chosen graph with LFG's keyword queries from `~/.lfg/plugin/omnigraph/*.gq` (`find_decisions`, `find_learnings`, `find_invariants`, `find_notes`; `people_all` for people). A near match becomes a proposal to update it; ask again.
6. **Write** with the Omnigraph MCP `mutate` tool to the graph the user picked: `record_decision`, `add_learning`, `create_issue`, `save_note` (LFG's, keeps the text and tags), `add_person`; for `Invariant`/`Principle` read `schema_get` and insert. Tags: repo, topic, run id. Link to the repo's `Component` (dev-graph) or `Project` (second-brain, `link_note_about_project`) when one exists.
7. Confirm in one line per item: graph, kind, text, node id.

## Output

The approved nodes, plus a one-line confirmation per item in chat. Nothing in the repo or the run folder (except "To remember" in `progress.md` when the graph is down).

## Rules

- Never write before the user picked the graph for that item.
- A `Principle` is enforced by `/review-coach`, so say that when proposing one.
- Never store secrets or credentials, even if asked.
- Store what the user said, not your elaboration of it.
