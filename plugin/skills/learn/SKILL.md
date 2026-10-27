---
name: learn
description: >
  Retro on a run (or a week of runs): turns what happened into dev-graph Learning and Principle
  nodes, repo playbooks, personal second-brain notes, and proposed reviewer-rule tweaks. Use
  when the user says "retro", "what did we learn?", "make a playbook", or after a merge.
author: Varun Singh
phase: learn
lanes: [express, standard, full, hotfix]
reads: [run folder, 06-review.json, feedback store, usage.db, audit.log]
writes: [08-learn.md, dev-graph Learning/Principle, ~/.lfg/playbooks/<repo-id>/, second-brain]
auto-trigger: false
preflight: graphs
adapted-from: mattpocock/skills/retro + writing-for-agents (MIT, © 2026 Matt Pocock)
---

# /learn: make the next run better

## Step 0: preflight

1. `lfg graphs ensure`. Non-zero exit: stop and show its output. Continue on a stale graph only if the user typed `--allow-stale`.
2. `lfg run path`. Exit 1: `lfg run list` and ask which run (or "the week") to look back on.
3. `lfg rule agent-writing`: every rule, playbook or note you draft follows it.

## Steps

1. **Read the primary sources** for the run (or each run this week): `01-brief.md` … `07-shipcheck.json`, `progress.md`, `tasks.json`; `lfg usage --json` (tokens and time per stage); `~/.lfg/audit.log` entries for the run (blocked actions); the accept/reject verdicts in `~/.lfg/feedback/` for its findings. Note what went wrong, what was slow, and what was expensive.
2. **Find candidates** in each category; a category with nothing real stays empty.
   - **Navigation:** the agent searched long for something the graph should have pointed to → a graphify rationale gap, a missing `Component` link, or a playbook entry.
   - **Automated checks:** a mistake a check could have caught. Read the repo's own lint/test/CI wiring first; an existing check left unwired is the finding. A repo with no guardrail at all is a finding.
   - **Reviewer rules:** from the feedback store. Rejected findings → loosen or drop the rule that produced them. Bugs `/review-coach` missed → a new rule. Classify first: **mechanical** (banned API, import shape, file location) → a linter rule or CI job; **judgement** → a `Principle` or a `CODING_STANDARDS.md` line.
   - **Steering no-ops:** lines in rule modules, skills or CLAUDE.md that changed nothing this run.
   - **Tool economy:** stages that burned tokens or time out of line with their job (from `usage.db`).
   - **Information access:** something the agent needed but could not see (logs, read-only service access).
   - **Guard blocks:** repeated blocks in `audit.log` mean a prompt or skill is steering toward a forbidden action; name it.
3. **Present candidates by severity**, each with the evidence (file, stage, finding id) and the proposed change. Wait for the user to pick.
4. **Write what was agreed:**
   - dev-graph `Learning` per lesson, linked to the `Component` (and `Incident` for Hotfix). Write Learnings directly.
   - dev-graph `Principle` for each agreed judgement rule; only after the user's yes, since `/review-coach` enforces Principles.
   - **Playbooks** in `~/.lfg/playbooks/<repo-id>/<slug>.md` ("how to add X here", landmines): only from a pattern with 3+ instances found via `graphify query`, citing the reference files.
   - **Second-brain notes** for personal insights and preferences the user chooses to keep.
   - **Skill candidates:** a repeated, error-prone procedure → propose it as a skill; create nothing unless the user confirms.
   - Repo changes (a lint rule, a CI job) are proposed as a ticket or a follow-up `/build`, never edited in from here. Linear writes only after a yes on the exact text.

## Output

`08-learn.md` in the run folder:

```markdown
# Learn: <run-id or week>
| # | Category | Evidence | Change | Status (written / proposed / declined) |
## Written: Learning ids, Principle ids, playbook paths, second-brain notes
## Proposed reviewer-rule tweaks (rule, from → to, evidence)
```

Reply with the top three lessons, what was written where, and the open proposals.

## Rules

- Evidence over impressions: every candidate cites where it came from.
- Lessons describe the system and the process, not the person.
- No secrets, code blocks with credentials, or exploit details in any node, playbook or note.
