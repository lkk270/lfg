---
name: plan
description: >
  Turns the approved brief into a graph-scoped design, a spec and tracer-bullet tickets
  with blocking edges, owner roles and pre-agreed test seams in tasks.json, and suggests
  the lane. Proposes matching Linear issues (written only after an explicit yes). Use when
  the user says "plan this", "break it down", "write a spec", "make tickets", "design this",
  or when a run has an approved 01-brief.md but no 02-design.md.
author: Varun Singh
phase: plan
lanes: [standard, full]
reads: [01-brief.md, GLOSSARY.md, adr/, code-review-graph, graphify, dev-graph]
writes: [02-design.md, tasks.json, progress.md]
auto-trigger: true
preflight: graphs
adapted-from: mattpocock/skills/to-spec + to-tickets + codebase-design (MIT, © 2026 Matt Pocock)
---

## Step 0: preflight

1. Run `lfg graphs ensure`. If it exits non-zero, stop and show its output (only `--allow-stale` from the user overrides).
2. Run `lfg run path` → `RUN`. If there is no run or no `RUN/01-brief.md`, stop and suggest `/grill`. Run `lfg run doing design` and `lfg run doing tasks`.
3. Run `lfg repo docs` → `DOCS`; read `DOCS/GLOSSARY.md` and ADRs touching this area. Use glossary terms everywhere.
4. Load `lfg rule slice-rules` and `lfg rule module-design`.

## Steps

1. **Scope from the graph, not the repo.** For the brief's nouns: `get_minimal_context_tool` → `get_impact_radius_tool` → `get_architecture_overview_tool` / `get_bridge_nodes_tool` if more than one community is involved → `graphify explain/path` for rationale → dev-graph `Principle`/`Invariant`/`Gap`/`Decision` for touched `Component`s. Read only files the graph points to.
2. **Design** (`module-design`): which modules change, their interfaces, data flow, and where the seams sit. Prefer existing seams and deepening an existing module over new shallow ones. Look for a prefactor that makes the change easy. In Full lane, if an interface shape is genuinely open, sketch 2–3 distinct options and recommend one.
3. **Test seams.** Pick the highest seam(s) that observe each acceptance criterion; fewest seams wins. Each seam gets one line: what it catches, what it misses. Use existing test prior art (`query_graph_tool` `tests_for`).
4. **Tickets** (`slice-rules`): tracer-bullet vertical slices, prefactor first, each sized for one fresh context, each with `depends_on`. Wide mechanical refactors use expand → migrate batches → contract. Assign `owner_role` (`software-engineer`, or `ai-engineer` for prompts/RAG/model calls/evals) and a `parallel_group` (same letter = no edge between them, can run together).
5. **Lane.** Run `lfg lane --json` and combine it with the radius, communities, new dependencies and touched auth/crypto/PII/payments/migrations/infra. Suggest the higher lane when in doubt; record reasons. Never lower a lane a human set.
6. **Write** `RUN/02-design.md` and `RUN/tasks.json`; update `RUN/progress.md` (lane, ticket count, next: `/build`). Mirror tickets to dev-graph with `lfg issue sync-tasks` (one `Issue` per ticket, carrying its description, steps and verification; never hand-write a stub), then add `IssueBlocksIssue` edges for `depends_on`.
7. **Checkpoint 2:** show a short summary: lane + reasons, components, risks, numbered tickets (title · blocked by · what it delivers · seams). Ask: granularity right? edges right? merge/split any? Iterate until approved, then run `lfg run done design` and `lfg run done tasks`.
8. **Linear (checkpoint 7, only if asked).** Never create Linear issues on your own. Ask once whether the user wants a Linear issue per ticket; only on yes, show one issue per ticket, blockers first, as exact text (title, what to build, acceptance criteria, `file:symbol` refs; no code blocks, secrets or internal hosts), as sub-issues when the run came from a Linear issue, with native blocking relations. Write only after an explicit yes; then store each Linear id on its ticket. Never modify the parent issue.

## Output

`RUN/02-design.md`: Problem · Solution · Components touched (`file:symbol`, community) · Data flow (+ Mermaid) · Interfaces & decisions · Test seams · Risks (Principles/Invariants hit) · Lane + reasons · Out of scope. No code snippets except a decision-rich type/schema shape.

`RUN/tasks.json` (global CLAUDE.md schema + LFG fields):

```json
[{ "id": "csv-001", "description": "Prefactor: extract exporter interface from PDF export",
   "priority": 1, "lane": "standard", "owner_role": "software-engineer",
   "graph_scope": ["billing/export.PdfExporter"], "depends_on": [], "parallel_group": "A",
   "test_seams": [{ "seam": "Exporter.export(invoice)", "catches": "format output", "misses": "HTTP layer" }],
   "steps": ["..."], "verification": "Given/When/Then from 01-brief.md #1 passes at the seam",
   "acceptance": [1], "linear_id": null, "passes": false, "notes": "" }]
```

Every acceptance criterion maps to at least one ticket (`acceptance`) and one seam. `passes` always starts `false`.

## Rules

- Synthesize; don't re-interview. Ask only for decisions the brief leaves open.
- Never weaken or delete existing `tasks.json` entries; append or supersede with a note.
- No code changes in this stage. Linear writes only after an explicit yes on the exact text.
