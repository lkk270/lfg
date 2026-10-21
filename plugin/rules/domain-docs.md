Rule module: domain-docs · LFG · author Varun Singh · adapted from mattpocock/skills/grill-with-docs + domain-modeling (MIT, © 2026 Matt Pocock)

# Domain docs: glossary and ADRs

## Location

- Run `lfg repo docs` and use the printed dir (`DOCS`). Glossary: `DOCS/GLOSSARY.md`. ADRs: `DOCS/adr/NNNN-<slug>.md`.
- Write only to `DOCS` (the repo's `.lfg/docs/`, committed with the repo's knowledge). If the repo already has its own `GLOSSARY.md` or `docs/adr/`, read them as input but write to `DOCS`.
- Create files lazily: only when the first term or decision is resolved.
- **Docs the user asks for** (explainers, guides, design write-ups, notes), when they don't name a path in the repo: Markdown starting with `# <Title>`, a short kebab-case file name. About the whole project → `DOCS/<name>.md` (subfolders for a set of related docs). About the work on the current branch (its design, decisions, migration notes, hand-off) → the dir `lfg repo docs --branch` prints. Update an existing doc rather than writing a second one on the same subject. The dashboard's Docs page shows project docs at the top and one folder per branch.
- Multiple bounded contexts: `DOCS/GLOSSARY-MAP.md` lists each context, its code area, and how contexts relate; each context gets `DOCS/<context>/GLOSSARY.md`. Infer the context from the topic; ask if unclear.

## Glossary format

```md
# <Context name>

<One or two sentences: what this context is and why it exists.>

## Language

**Invoice**:
A request for payment sent to a customer after delivery.
_Avoid_: bill, payment request
```

- Be opinionated: pick one word per concept; list the rest under `_Avoid_`.
- One or two sentences; define what it IS, not what it does.
- Only project-specific terms; no general programming concepts.
- No implementation detail: the glossary is not a spec or scratch pad.
- Group under subheadings when clusters emerge.
- Write a term the moment it is resolved; don't batch.

## ADR format

```md
# <Short title of the decision>

<1–3 sentences: context, what we decided, why.>
```

Optional, only when they add value: `Status` (proposed | accepted | deprecated | superseded by ADR-NNNN), Considered options, Consequences.

- Number: highest existing number in `DOCS/adr/` + 1, four digits.
- After writing, link it as a dev-graph `Decision` node on the touched `Component`.

## When to offer an ADR (all three must hold)

1. Hard to reverse.
2. Surprising without context: a future reader would ask "why on earth?".
3. A real trade-off between genuine alternatives.

Good candidates: architectural shape, integration patterns between contexts, technology with lock-in, ownership/boundary decisions (the explicit no's too), deliberate deviations from the obvious path, constraints not visible in code, non-obvious rejected alternatives.

## During a conversation

- Call out a term that conflicts with the glossary immediately.
- Replace vague or overloaded words with one canonical term.
- Probe boundaries with concrete edge-case scenarios.
- If a claim contradicts the code, show the `file:symbol` and ask which is right.
