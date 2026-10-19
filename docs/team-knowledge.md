# Team knowledge: sharing a repo's LFG context

Status: built on branch `scope/team-knowledge`, not yet merged. Scoped and built 2026-10-18.

## The problem

Someone builds a feature with LFG, then a teammate takes it over. The teammate needs to know how it works: the business logic, the infra, the commands to run it, the decisions behind it and the gotchas found along the way. Until now all of that lived only on the builder's machine, in `~/.lfg/`, so the teammate's LFG started from nothing.

**Goal:** when someone takes over a feature, their LFG has the same knowledge of the repo the builder's had, without asking the builder, and what they add flows back the same way.

Personal context (second-brain) is out of scope and stays personal.

## Terms

| Term | Meaning |
|---|---|
| repo folder | The tracked `.lfg/` folder in each repo: runs, docs, commands and node files. |
| local state | What stays in `~/.lfg/` on one machine: tokens, `/build` and `/spike` scratch, sync state, logs. |
| node file | One markdown file in `.lfg/nodes/<Type>/<slug>.md` holding one dev-graph node: fields and links at the top, text below. |
| checkout branch | The dev-graph branch that indexes one checkout: `repo/<repo-id>` for the main checkout, `repo/<repo-id>--wt-<hash>` for each linked worktree. |
| sync | `lfg knowledge sync`: copies what agents saved in the checkout branch into node files, then rebuilds the branch from the files. |
| repo id | `<repo-dir-name>-<8 hex>`, the key LFG files everything under. Stored in `.lfg/repo-id`. |

## Decisions

### Knowledge lives in a tracked folder in the repo

Runs, docs and shared dev-graph nodes live in `.lfg/` in the repo, committed with the code. A feature's run lands on its feature branch and merges with its PR, so whoever checks out the branch gets that feature's context, and a pull brings teammates' additions.

Rejected:

- **A separate branch or repo for knowledge only.** Keeps code PRs clean, but it is a second thing to push and pull, people forget, and its history is not tied to the code's.
- **One hosted team dev-graph.** Someone has to host and secure it, it breaks LFG's local-only design, and most of the knowledge is files anyway.

This reverses an earlier LFG stance: `lfg enable` hid `.lfg/` through `.git/info/exclude`, `/lfg:grill` put ADRs "outside the repo", and `/lfg:note` wrote "nothing in the repo". None of those said why. All three changed.

### The files are the master copy; the graph is an index rebuilt from them

Each checkout's dev-graph branch is rebuilt from its node files. Agents still save through the dev-graph MCP, which is pinned to the checkout branch; sync then copies what they added or changed into node files, as unstaged changes the user commits (LFG never commits). Sync runs in the background at session start and at the end of every turn.

How sync decides, per node, against what it loaded last time:

| Graph | File | Result |
|---|---|---|
| new, never loaded | none | written as a new file (an agent saved it) |
| changed since last sync | as loaded | file rewritten (an agent edited it) |
| changed since last sync | also changed | conflict: the file wins, reported |
| unchanged | changed, new or deleted | the file wins (a pull, a merge, a deletion) |
| any | unreadable (bad merge, hand edit) | node left as it is until the file is fixed, reported |
| new, slug not safe as a filename | none | node kept in the graph, reported, no file |

Why files are the master: it turns the hard problem, two people editing the same knowledge, into an ordinary git merge in readable files. The alternative, graph as master with export and import by key, makes LFG work out deletions, conflicts and branch switches itself, and the graph knows nothing about git branches.

Why agents still write to the graph rather than to files: every skill and agent already saves through the MCP, and the MCP's writes are typed and checked against the schema. Changing every writer to produce files was more churn for no gain, since sync gets the same result.

Consequences: deleting knowledge is deleting a file. Checking out an old branch shows that branch's knowledge after the next sync. **A save made while dev-graph is down fails**, as before; nothing is written to a file in that case.

### What from a run is committed

| Committed | Stays local, and why |
|---|---|
| `01-brief.md`, `02-design.md`, `03-build-*.md`, `03-fix-*.md`, `04-qa.md`, `06-review.json`, `progress.md`, handoff note, `tasks.json`, `run.json` | `patches/`: copies of code already in git |
| glossary, ADRs, `commands.json`, `shipcheck.json` | `gate-logs/`: build and lint output, rerun anytime |
| | `/build` worktrees and `/spike` prototypes: in `lfg run scratch` (`~/.lfg/runs/<repo-id>/<run-id>/`), one machine only |
| | `ready.json`: contains `/Users/<name>/...` paths |
| | `05-secure.*`, `05-pentest.json`, `security-audit/`: security findings, never committed, because anyone who can read the repo can read them. `/secure audit` writes its full report to the scratch folder, outside the repo. A per-repo opt-in to commit them was considered and not built. |
| | `COMMIT_MSG.md`, `PR_BODY.md`: in git and on GitHub once the PR exists |
| | `CURRENT`: which run is current is per checkout |

`.lfg/.gitignore` holds those lines. LFG adds any line a newer version knows and leaves lines someone else added.

### Which dev-graph nodes are shared

| Shared | Not shared, and why |
|---|---|
| Decision, Learning, Invariant, Principle, Gap, Assumption, ExternalBlocker, Component, Capability, SpecFile, Incident | Issues linked to Linear: Linear is the master, each person's LFG already mirrors it, and status changes every stage, so committing them churns and conflicts |
| Issues with no Linear ticket (`iss-...`) | PR, Commit, Release, Deployment: GitHub is the master |
| | Actor: holds email addresses |
| | Comment: nothing in LFG writes these today |
| | Epic, Repo, Gate, Label: nothing in LFG writes these today |

Free-text issue keys used to come from the title alone ("fix login" became `iss-fix-login`), so two people's "fix login" would have merged into one issue once shared. A new free-text issue now gets a short random suffix (`iss-fix-login-3f2a`); a title already in use finds its existing issue. With dev-graph down, a title gets a fresh suffixed key.

### Smaller calls

Lee delegated these; they are Claude's recommendations, open to change.

- **One node file per node**, named by its key. Separate files make it rare for two people to touch the same one, and they read fine on GitHub.
- **The repo id is stored in `.lfg/repo-id`** and committed, so every clone and every teammate uses the same id. It used to be derived from the `origin` URL, so adding or changing a remote orphaned existing state.
- **Moving old state is on request**, not automatic: session start points at `lfg knowledge migrate --dry-run`, and the user runs the move. If the current run is still in the old place, session start says so and tells the agent not to start a new run. Migration merges a run found under two ids (newer file wins), takes back the `.lfg/` line older versions put in `.git/info/exclude`, and backs up the originals in `~/.lfg/backups/`.
- **Each checkout has its own dev-graph branch.** A linked worktree holds a different git branch, so it must not share an index with the main checkout. Found in review: with one shared branch, a worktree's sync wrote the main checkout's new knowledge into the worktree's files.
- **A teammate without LFG** sees readable markdown and nothing breaks.
- **Taking over a run**: at session start LFG offers the unfinished runs whose `run.json` branch matches the checkout; `lfg run use <run-id>` picks one.
- **The guard protects `.lfg/repo-id` and `.lfg/.gitignore`** from agent edits, and blocks a recursive delete of a repo's `.lfg/`. An agent changing the id would point the repo at another repo's knowledge; changing the ignore file could commit security reports.
- **Secrets**: the existing rule (never saved, `rules/remember.md`) holds. The green gate's gitleaks scan covers untracked `.lfg/` files.

## Verified facts

Checked 2026-10-18 on Lee's machine, Omnigraph 0.13.0.

| Fact | How checked | Answer |
|---|---|---|
| Omnigraph can export | `omnigraph export --help` | Yes: full branch snapshot as JSONL, filterable by `--type`. An earlier session said no export existed; that was wrong. |
| Omnigraph can upsert by key | `omnigraph load --help`, MCP instructions | `load --mode merge` upserts on `@key`. |
| dev-graph was one graph for all repos | `common.py` `DEFAULT_CONFIG` | Yes: graph `dev`, port 47182, every repo on `main`. Nodes carry no repo field, so nodes already on `main` can't be assigned to a repo automatically. |
| Vectors | dev-graph `schema_get`, cookbook README | 13 `Vector(3072)` columns, all empty because LFG configures no embedding provider. Nothing to lose today. |
| Repo-id orphaning has happened | `ls ~/.lfg/runs`, the run's `run.json` | Run `20261017-1518-init-go-module-repo-layout-makefile` exists under both `osi-06b219e9` and `osi-d5df47b4`. The copy under `osi-d5df47b4` has a `run.json` saying `repo_id: osi-06b219e9` and holds the later files. Consistent with a remote being added mid-run; the cause is not proven. A second osi run exists only under `osi-d5df47b4`. |
| Runs in a repo with no commits recorded branch `detached@` | test against `git rev-parse --abbrev-ref HEAD` | Yes, the osi run shows it. Fixed: `git symbolic-ref` first. |

### Spike results

Run 2026-10-18 on throwaway graphs initialized from the dev-graph schema, never the live dev-graph unless stated.

| Question | Answer |
|---|---|
| Can one graph keep repos apart without a schema change? | Yes: one Omnigraph branch per checkout. Nodes loaded on a branch are invisible on `main` and on other branches. |
| Branch naming | Omnigraph refuses a branch nested under a live branch's name (`repo/x/wt-1` beside `repo/x`), so worktree branches are siblings: `repo/x--wt-<hash>`. |
| A new branch is a copy of `main` | Yes, so a new checkout branch is cleared of every type right after creation, under the repo's sync lock. A branch that can't be cleared is deleted again: otherwise sync would read other repos' old nodes as an agent's and write them into this repo's files (reproduced in review). |
| Round trip | Exported a branch, loaded the export into a fresh branch, exported again: identical apart from edge ids. Export writes `Date` as ISO; load accepts ISO or integer days. Edges by key survive. |
| Rebuild cost | Clearing and loading 2,000 Learning nodes takes about 0.1s on the direct store. |
| Served path | Ran against the live server with a throwaway repo: sync loaded a file, an MCP insert on the checkout branch came back as a node file, a second sync changed nothing. The test branch was deleted after. |
| Can agents be pinned to the branch? | Yes: the MCP bridge (`@modernrelay/omnigraph-mcp@0.13.0`) reads `OMNIGRAPH_DEFAULT_BRANCH`; `lfg omnigraph mcp dev-graph` sets it. |
| Does the writer role allow it? | Yes: `graph.policy.yaml` gives writers branch create, delete and merge and `change` on any branch. Only `main` is protected. |

## Where it lives in the code

- `common.py`: `repo_id`, `knowledge_dir`, `runs_dir`, `current_run`, `scratch_dir`, `KNOWLEDGE_IGNORE`.
- `knowledge.py`: node files, sync, the checkout branch, migration, taking over a run.
- `omnigraph.py`: `repo_branch` and the MCP pin; `read`, `invoke` and `mutate` take a branch.
- `tracker.py`: `resolve`, the suffixed free-text keys.
- `hooks.py`: background sync at session start and Stop, the session-start notices.
- `dash.py`, `docs.py`: read runs from every checkout and dev-graph from the repo's branch.
- `setup.py`, `claudecfg.py`: `lfg enable` no longer hides `.lfg/`; `lines_take_back`.
- `guard.py`: `PROTECTED_IN_REPO`.

## Cases walked

| Case | What happens |
|---|---|
| Two people add knowledge on different branches | Separate node files, git merges them |
| Two people edit the same node | Git conflict in one markdown file, resolved like code; until it is, the node stays as it was in the graph |
| Sync run twice | Second run changes nothing (tested) |
| Sync interrupted halfway | Next sync starts over from the files; the graph is only an index |
| Two syncs at once (session start and Stop) | The second skips; the MCP launcher waits for the lock before creating a branch |
| dev-graph down | Saves fail as before; sync and session-start notices log to `~/.lfg/graphs/<repo-id>/knowledge.log` and never block a session |
| Remote URL changes | Id read from `.lfg/repo-id`, so nothing moves |
| A cloned repo's `.lfg/repo-id` names another repo's id | Migration only takes ids derived from this checkout's own remote and path, so it can't pull another repo's old runs in (security review) |
| State from before this feature | Moved on request with `lfg knowledge migrate`; nodes on `main` copied into a repo only with `--take-main-nodes`, in the repos the user picks |
| Main checkout and a worktree, different branches | Separate dev-graph branches and sync state (tested) |
| Branch switch mid-session | Index catches up at the end of the turn (Stop hook) |
| A node's key is renamed | Reads as delete plus add; links to the old key are dropped. Not supported |

## Open questions

1. **Company repos that cannot hold the folder.** Not known yet what blocks it there: a policy against non-code files, reviewers, or the repo being shared outside the team. The hedge discussed, a config option pointing the folder elsewhere, **was not built**; `docs/sharing.md` says such repos aren't supported yet.
2. **CI installs Omnigraph unpinned** from the `ModernRelay/tap` Homebrew tap, so the sync tests run in CI. Pinning it (formula version or a checksum-checked download) retires the caveat from the security review.
3. **Renaming a node's key.** Whether keys are ever renamed, and if so how links are kept.
