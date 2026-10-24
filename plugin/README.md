# LFG plugin

LFG is an engineering pipeline for Claude Code. It takes an idea or a Linear issue from "what do we want?" to a change that is tested, security-checked, reviewed and ready for **you** to commit. It works from knowledge graphs of your code (code-review-graph, graphify, dev-graph), picks a lane (Express / Standard / Full / Hotfix) so small changes stay fast, never pushes or deploys, and commits only when you ask and approve each commit.

This folder is the Claude Code plugin **and** the `lfg` CLI it calls (`bin/`, `lib/`). Install it with the installer in the repository root, which also sets up the tools the CLI uses:

```bash
git clone https://github.com/varun-singhh/lfg.git && ./lfg/install.sh
```

The plugin is **off until you turn it on for a repo** (`lfg enable`). It ships with `defaultEnabled: false`, and its hooks do nothing in repos where LFG is off.

## Two commands to remember

```
/lfg:lfg <what you want>          # runs the pipeline, stops at the checkpoints where you decide
/lfg:wizard <idea or LIN-123>     # same pipeline, every stage, explained, fixing until all gates are green
```

Lost? Type `/lfg:which`. It looks at your repo and run folder and tells you the next skill.

Skills are namespaced by Claude Code as `/lfg:<name>`. When no other skill or command uses the same name, the short form (`/wizard`, `/which`) works too. If you already have a personal skill called `ship`, `health` or `learn`, typing `/ship` runs yours, and `/lfg:ship` runs LFG's.

## Skills

Talk → Plan → Build → Prove → Ship → Learn, plus helpers you can use any time. Each is `/lfg:<name>`.

| Phase | Skills |
|---|---|
| Run it all | `lfg`, `wizard` |
| Talk | `grill` |
| Plan | `plan` |
| Build | `build`, `fix` |
| Prove | `check`, `secure`, `pentest`, `review-coach` |
| Ship | `ship` |
| Learn | `learn` |
| Helpers | `explain`, `impact`, `spike`, `research`, `map`, `inbox`, `handoff`, `note`, `health`, `which` |

Trigger phrases, inputs and outputs for each: `lfg ui` → Skills, or the guide in `docs/guide.html`.

## What's in here

| Path | What |
|---|---|
| `skills/<name>/SKILL.md` | The skills |
| `agents/<role>.md` | Role subagents (product manager, architect, engineers, QA, security, reviewer, lane triage) |
| `rules/<name>.md` | Rule modules agents load with `lfg rule <name>` |
| `hooks/hooks.json` | Guard, graph freshness, secret-output warning, usage log |
| `.mcp.json` | code-review-graph, dev-graph, second-brain, Headroom: started by `lfg mcp <name>`, which serves an empty stub when a pack isn't set up |
| `bin/lfg`, `lib/lfgcore/` | The CLI and the dashboard (Python 3.9+ standard library only) |
| `omnigraph/` | Keyword queries for dev-graph and second-brain |
| `vendor/` | Cloudflare's security-audit skill, vendored unchanged |

## Where things go

- Every run writes numbered files to `~/.lfg/runs/<repo-id>/<run-id>/` (brief, design, build notes, QA, security, review, ship packet). Any skill can resume from them.
- Graphs live in the repo's main checkout, in `.code-review-graph/` and `graphify-out/`. They're ignored through `.git/info/exclude`, never committed, and shared by every branch and worktree. Apart from those and the code changes, which are left unstaged, nothing is written into your repo.
- Agents create worktrees next to the repo (`<repo>.worktrees/<branch>`, via `lfg worktree new`) when work needs another branch. Your checkout is never switched, and clean worktrees are removed after a day. See `lfg rule worktrees`.
- `lfg ui` opens the local dashboard at http://127.0.0.1:7777.

## What LFG never does

Push, merge, rebase, write to GitHub, read `.env` or key files, deploy, or `docker push`. Commits happen only when you ask, and Claude Code asks you to approve each one (Commit approval; turn it off in Settings to block commits too). Writes to Linear happen only after you approve the exact text. To do any of these, you do it yourself in your own terminal.

## Credits

LFG is created by Varun Singh (MIT).
Adapted skills (`grill`, `plan`, `build`, `fix`, `review-coach`, `learn`, `spike`, `research`, `map`, `inbox`, `handoff`, `health`) are adapted from [mattpocock/skills](https://github.com/mattpocock/skills), © 2026 Matt Pocock, MIT. Each one names its source in an `adapted-from:` line.
`secure`'s code review uses [cloudflare/security-audit-skill](https://github.com/cloudflare/security-audit-skill), © 2025-2026 Cloudflare, Inc., MIT, vendored unchanged in `vendor/cloudflare-security-audit/` (see its `UPSTREAM.md` and `LICENSE`).
