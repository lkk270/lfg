# Changelog

All notable changes to LFG. The version lives in `plugin/.claude-plugin/plugin.json`.

## 0.3.0 (2026-10-20)

### Added
- **Docs page as a tree**: project docs at the top (LFG's Wiki, glossary, Decisions, docs you asked for), then one folder per branch. Claude writes docs you ask for to `lfg repo docs` (project-wide) or the new `lfg repo docs --branch` (this branch's work), never into the repo unless you name a path. The repo's own markdown and graphify's per-cluster pages ("plugin · re") are no longer listed.
- **LFG Dictate** (`lfg add dictate`, or Settings → Claude Code → Feature packs): hold Option+Space anywhere on the Mac to dictate, double-tap for hands-free, Esc or the shortcut again to finish. Text goes where the cursor is: pasted with your clipboard restored, or typed (`dictate.insert`), or left on the clipboard when no text field is focused. Transcription runs on-device with Cactus Compute's Whistle model through cactus-needle 3.2.8, which LFG always starts with its telemetry off and Hugging Face offline. **Clean up with Claude** (on by default, `lfg dictate cleanup off` to keep everything on the Mac) sends text only (never audio) to Claude and falls back to the raw text if that fails. No audio or transcript is kept. Ships dormant: nothing is downloaded, installed or asked for until turned on, and `lfg remove dictate` deletes everything through the change ledger. The shortcut can be changed (Right Option, Fn, Control+Space, Command+Shift+Space), with a warning when a known app also claims it. Dictate runs as its own small app, **LFG Dictate** (`~/.lfg/dictate/LFG Dictate.app`, built and signed locally), so macOS asks for Microphone and Accessibility permission by that name. A quiet pill at the bottom centre of the screen shows only voice-level bars while listening, dimmed bars while transcribing, and text only when it has something to say. Its options (shortcut, paste or type, Clean up) sit on the Dictate row in Settings → Claude Code and in `lfg dictate cleanup on|off`, `lfg dictate insert paste|type` and `lfg dictate shortcut <preset>`; these are user-only (the guard blocks agents from them). `lfg dictate status|restart` (status also says where the last dictation went and why, never the words). Everyone, on a fresh install or after an update, learns about Dictate once: while it's off, a **New: LFG Dictate** banner sits above every dashboard page (Turn it on / Take the tour / close) with a tour; once it's on, the tour is offered once (Start tour / Skip) unless it was already finished. The tour walks through every control (gestures and the listening pill, shortcut, paste or type, Clean up, Add or Turn off, terminal commands); the Dictate row shows its controls greyed while it's off so they can be pointed at. Both are remembered in `~/.lfg/state/tours.json` and can be replayed from "Take the tour" on the Dictate row. `lfg setup` prints "New in LFG 0.3.0" after an update.

### Fixed (Dictate)
- Dictation in Chrome, Electron apps (Slack, VS Code, Claude) and other apps that don't report their focused field was left on the clipboard ("Copied") instead of being pasted. Dictate now inserts unless macOS clearly says nothing editable has focus, and asks Electron apps to turn on their accessibility tree.
- **Commit approval** (`guard.allow_commits`, on by default; Settings → Claude Code → Safety): `git commit` becomes a Claude Code approval prompt instead of a hard block. Push, merge, rebase, amend, `--no-verify`, PRs, secret reads and deploys stay blocked. Hardened mode leaves out its `git commit` deny rule while this is on.

### Changed
- Pentest and Headroom are labelled **Experimental** in setup, `lfg packs`, the dashboard and the README, each with a one-line warning.
- LFG is macOS-only: `lfg setup` now refuses other systems, like `install.sh`.
- The promise is now "never pushes or deploys; commits only with your approval".

### Fixed
- The guard no longer treats a heredoc's text as commands (`cat > notes.md <<'EOF' ... git commit ... EOF` is a file write). A heredoc fed to a shell (`bash <<EOF`) is still checked, and so is `$(...)` in an unquoted heredoc.
- The guard allows `curl <api> | python3 -c "<parse>"`: inline code reads the download as data. Piping into a bare interpreter, or inline code that executes what it reads, is still blocked.

## 0.2.0 (2026-10-14)

LFG no longer changes Claude Code for every session on the machine. It is now installed off, turned on per repo, and every change it makes outside `~/.lfg` is recorded and reversible.

### Added
- `lfg setup`: looks at the machine (read-only), prints a plan, and applies it only after a yes. A failed step rolls back that run's changes. `install.sh` is now a thin wrapper around it.
- `lfg enable` / `lfg disable`: turn LFG on or off for one repo, using Claude Code's per-repo plugin setting (`.claude/settings.local.json`). `--everywhere` is available but not the default.
- Change ledger (`~/.lfg/state/ledger.json`, `claudecfg.py`): every outside change is backed up, written with compare-and-swap, and undoable. Added `lfg changes [undo <id>]`.
- `lfg uninstall [--dry-run] [--keep-data]`: undoes everything, including what older versions did, and lists the tools and repo graph folders it leaves.
- Feature packs (`lfg packs`, `lfg add`, `lfg remove`): security, shipcheck, pentest, knowledge, linear, headroom. Core installs only uv, gh, code-review-graph and graphify.
- Dashboard **Skills** page: every skill from every source, with name clashes, context cost and an auto-invoke switch.
- Dashboard **Settings → Claude Code**: where LFG is on, packs (installed in the background), hardened mode, Headroom scope, MCP status, your setup (read-only), leftovers from older versions, and every change with Undo.
- Migration from older installs. `lfg setup`, the dashboard and `lfg uninstall` detect the old global deny rules, the `CLAUDE.md` block (only if unedited), the user-scope MCP servers, global Headroom routing and the plugin being on everywhere, and offer to remove exactly those.
- Hardened mode: Claude Code deny rules behind the guard, written per repo, never to user settings.
- `lfg mcp <name>`: the plugin's own MCP servers, with a no-tools stub when a pack isn't set up.
- Open-source project files: CI, contributing guide, security policy, code of conduct, issue templates.

### Changed
- `bin/` and `lib/` moved into `plugin/`, so the plugin is self-contained. Hooks call `${CLAUDE_PLUGIN_ROOT}/bin/lfg`.
- Plugin manifest: `defaultEnabled: false`, plus homepage and repository fields. MCP servers moved from user scope into `plugin/.mcp.json`, so agent tool names are now `mcp__plugin_lfg_<server>__*`.
- Hooks exit at once in repos where LFG is off, match only the tools they inspect, and start Python with `-S`. Measured with Anaconda Python, an off-repo hook dropped from about 196 ms to 64 ms. SessionStart caches `gh auth status` for an hour, and Stop reads only the new part of the transcript.
- Headroom is opt-in and scoped (`headroom.scope`: off / repos / everywhere), and refused on Bedrock, Vertex and Foundry.
- The guidance that used to be appended to `~/.claude/CLAUDE.md` is now session context, and only in LFG repos.
- Skill edits from the dashboard no longer write into Claude Code's plugin cache, because the local marketplace loads the plugin in place.
- The guard blocks agents from running `lfg setup|enable|disable|uninstall|add|remove|changes undo|headroom setup|off` and from editing `~/.lfg/state` or `enabled.json`.
- Skills are documented as `/lfg:<name>`, and `/lfg:which` recommends namespaced names.
- Ignore entries go in each repo's `.git/info/exclude` instead of the global gitignore.

### Dashboard
- New look: a calm, document-style workspace in the spirit of Notion. It has warm neutral colours, system fonts, a sidebar with icons and project and branch switchers, a breadcrumb bar, large page titles, lists and tables on light dividers instead of boxes, tinted status labels, coloured callouts for what needs you, expandable toggles, a side panel for files, and a full dark theme. It fits at phone width with no sideways scrolling.
- Data fixes found by checking every page against seeded runs, real code graphs and usage:
  - The ship check's checklist was never shown ("0 of 0 checks passed"). It is now counted and listed, including items left for you to do and items that don't apply.
  - Review feedback is matched to the run it was given on (finding IDs like R-1 repeat across runs).
  - A run's "next step" names what is blocking it first, most serious first (failing checks, then a blocked review, a security problem, review changes, then the ship check), instead of the next missing file. Progress counts only the steps actually done, so a review-only run no longer shows "8 of 10".
  - A pentest that didn't run is flagged. Run documents are listed in pipeline order.
  - Home's "needs your attention" only nags about packs you added and says what to do ("GitHub CLI isn't signed in: run `gh auth login`"). The issues tile no longer shows 0 when dev-graph is unreachable, and a dev-graph that refuses LFG's token is explained with a fix.
  - Home and Usage count tokens the same way.
  - Code: test functions are left out of "where changes are riskiest", areas get readable folder names instead of `__init__.py`, and docstrings are labelled as what they are, with locations as `file:line`.
  - Docs: vendored third-party files are no longer listed as your team's docs.
  - Usage shows this project's tokens per run.
  - Skill names are shown as `/lfg:<name>` throughout.

### Removed
- Global `permissions.deny` rules, the global `CLAUDE.md` block, user-scope MCP registration, global gitignore and `core.excludesFile` changes, and routing all Claude Code traffic through Headroom by default.
- References to design documents that weren't in the repository.

## 0.1.0

First version.
