# Share LFG with your team

LFG is open source (MIT). Everyone installs it from the repository, and each person decides which repos it runs in. It ships as one folder: the **Claude Code plugin** (skills, agents, hooks, MCP servers) with the **`lfg` CLI** inside it (`plugin/bin`, `plugin/lib`). The plugin's skills and hooks call the CLI, so install with `install.sh` (which runs `lfg setup`) rather than adding the plugin to Claude Code on its own.

## Install

```bash
git clone https://github.com/varun-singhh/lfg.git && ./lfg/install.sh
```

`lfg setup` first looks at the machine (read-only), then prints its plan and asks before changing anything. What it does by default:

- copies LFG to `~/.lfg` and links `~/.local/bin/lfg`
- installs Core's tools if they're missing: `uv`, `gh`, `code-review-graph`, `graphify`
- registers LFG's local marketplace with Claude Code and installs the plugin **turned off** (`defaultEnabled: false`)
- if an older LFG changed Claude Code machine-wide, offers to undo exactly those changes

It does not touch your Claude Code settings, hooks, skills, MCP servers, `CLAUDE.md`, global git config or API endpoint. Every change outside `~/.lfg` is recorded: `lfg changes` lists them, and `lfg uninstall` undoes them.

Got LFG as a zip instead? Unzip it, then from that folder run `xattr -dr com.apple.quarantine . && ./install.sh`. The `xattr` step clears the macOS quarantine flag that files from chat or mail get.

## Turn it on where you want it

```bash
cd your-repo && lfg enable
```

This switches the plugin on for that one repo, using Claude Code's own per-repo setting (`enabledPlugins` in `.claude/settings.local.json`, which git ignores). It also keeps LFG's graph folders out of `git status` through `.git/info/exclude`, but not `.lfg/`, which holds the repo's shared knowledge (below). In every other repo, Claude Code behaves as if LFG weren't installed. `lfg disable` undoes exactly what `enable` did. You can do both from `lfg ui` → Settings → Claude Code.

## Feature packs

Core is all LFG needs. Add the rest when you want them, from the dashboard or with `lfg add <pack>`:

| Pack | Installs | For |
|---|---|---|
| `security` | gitleaks, semgrep, osv-scanner, trivy, hadolint, actionlint, zizmor, picklescan | `/lfg:secure`, the green gate |
| `shipcheck` | Docker Desktop (or bring your own Docker / Colima) | `lfg shipcheck` |
| `pentest` (experimental) | Ollama, LuLu, Strix (its installer is a `curl \| bash` script, so LFG asks first and never runs it from the dashboard) | `/lfg:pentest` |
| `knowledge` | Omnigraph + two local servers under launchd | dev-graph, second-brain |
| `linear` | the Linear MCP server (reuses yours if you have one) | `/lfg:inbox`, issue reads |
| `headroom` | headroom-ai + a local proxy (experimental) | context compression, LFG repos only unless you choose everywhere |
| `dictate` | a private environment in `~/.lfg/dictate` with the Whistle model (about 90 MB) and a login helper | LFG Dictate: hold Option+Space anywhere to dictate, on-device; asks for Microphone and Accessibility permission |

`lfg remove <pack>` stops what a pack runs. Its tools stay installed because other things may use them.

## What each person needs

- **macOS** (Apple silicon or Intel). Linux and Windows aren't supported yet.
- **Python 3.9+** (`xcode-select --install` provides it) and **Claude Code**, signed in.
- **Homebrew** for tools that aren't installed yet.
- Disk space: Core needs a few hundred MB. The Pentest pack needs about 10 GB (a local model and sandbox images).

## First-run checklist

1. `lfg doctor`: fix anything marked `ERR` (it says how).
2. `gh auth login`: LFG uses GitHub read-only (PR and CI status).
3. `cd your-repo && lfg enable`, then start `claude` there and approve the MCP servers it asks about.
4. With the Linear pack, run `/mcp` and sign in to **Linear**. With the Pentest pack, open **LuLu** once and approve its system extension.
5. `lfg ui` opens the dashboard at http://127.0.0.1:7777. Help explains every page.
6. Try `/lfg:which` (what to do next) or `/lfg:wizard <idea>` (a guided run).

## Share a repo's knowledge

What LFG learns about a repo lives in the repo, in `.lfg/`, and is committed with the work: each feature's run (brief,
design, build notes, QA, review, progress), the glossary and ADRs, the lint/test/build commands, and the team's
dev-graph knowledge (decisions, gotchas, invariants, principles) as one markdown file per item in `.lfg/nodes/`. Whoever
checks out a branch gets that branch's context; a pull brings in teammates' additions.

- **You commit it.** LFG writes into `.lfg/` and leaves the changes unstaged, like any other change. Commit them with
  the feature.
- **What stays on your machine:** which run is current, patches, gate logs, worktrees, commit and PR text, and
  security and pentest reports (`.lfg/.gitignore`). Your second-brain is personal and never leaves your machine.
- **Taking over a teammate's feature:** check out their branch and start Claude Code. LFG offers the unfinished run on
  that branch; `lfg run use <run-id>` picks it up.
- **dev-graph** keeps each repo on its own branch and rebuilds it from `.lfg/nodes/` at the start of every session. If
  you and a teammate edit the same item, git shows a conflict in that one file; resolve it like code.
- **Upgrading from 0.2:** runs and docs were in `~/.lfg`. `lfg knowledge migrate --dry-run` shows what would move into
  the repo; drop `--dry-run` to move it (originals are backed up in `~/.lfg/backups/`).
- A repo that can't hold LFG's folder isn't supported yet.

## Team settings worth agreeing on

Each person's `~/.lfg/config.json` is theirs, but these work best when everyone uses the same values:

- `linear.team`: your Linear team key, so `/lfg:inbox` pulls the right issues.
- `linear.workspace`: your Linear workspace slug, so the dashboard links issues to Linear.
- `graphs.docs`: keep `true` so wikis and playbooks regenerate automatically.

## Update

```bash
cd lfg && git pull && ./install.sh
```

Your edits to skills and rules (made in the dashboard) are kept.

## Uninstall

```bash
lfg uninstall --dry-run   # shows what it would undo
lfg uninstall
```

This undoes every recorded change: the plugin in each repo, the marketplace, the PATH link, launchd agents, Headroom routing and the Linear MCP server LFG added. It also cleans up what older versions changed, and removes `~/.lfg`. A value you changed yourself after LFG set it is left as it is and reported. Tools installed with Homebrew or uv, and the graph folders inside your repos, are listed so you can remove them if you like.
