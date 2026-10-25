
# LFG

**An engineering pipeline for Claude Code.** LFG takes an idea or a Linear issue to a change that is tested, security-checked, reviewed and ready for **you** to commit. It works from knowledge graphs of your code, picks a lane so small changes stay fast, and never commits, pushes or deploys on its own.

[![CI](https://github.com/lkk270/lfg/actions/workflows/ci.yml/badge.svg)](https://github.com/lkk270/lfg/actions/workflows/ci.yml)
![macOS](https://img.shields.io/badge/platform-macOS-lightgrey)
![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

https://github.com/user-attachments/assets/bcc10777-99ec-4f32-9b55-19702dbade8f

```
grill → plan → build → check ∥ secure ∥ pentest → expert review → ship packet → you commit
```

## Install

```bash
git clone https://github.com/varun-singhh/lfg.git && ./lfg/install.sh
```

The installer looks at your machine first, shows exactly what it would change, and asks before doing anything. Then turn LFG on in the repos where you want it:

```bash
cd your-repo && lfg enable
```

Start Claude Code there and type `/lfg:wizard <your idea>` for a guided run, or `/lfg:which` to see what to do next.

## A guest on your machine

LFG is built so that installing it can't disturb how you already use Claude Code:

- **Off until you turn it on.** The plugin installs disabled. `lfg enable` switches it on for one repo, using Claude Code's own per-repo setting. In every other repo, Claude Code works as if LFG weren't there: no skills, hooks or MCP servers.
- **Your setup is left alone.** Your `settings.json`, hooks, skills, MCP servers, `CLAUDE.md`, API endpoint and global git config aren't touched. Your own skills keep their names, and LFG's are `/lfg:<name>`.
- **Every change is recorded and reversible.** Anything LFG changes outside `~/.lfg` goes into a change ledger with a backup. `lfg changes` lists the changes, `lfg changes undo <id>` reverts one, and `lfg uninstall` reverts them all. A value you changed afterwards is never overwritten.
- **Only what you need.** Core is a few small tools. Security scanners, Docker, the pentest stack, knowledge graphs, Linear and the Headroom proxy are optional packs you add when you want them.
- **Upgrading from an older LFG?** `lfg setup --migrate` finds what earlier versions changed machine-wide and offers to undo exactly that. Plain `lfg setup` leaves it alone.

## What you get

| | |
|---|---|
| **Skills** (`/lfg:<name>`) | `lfg`, `wizard` (whole pipeline) · `grill` · `plan` · `build`, `fix` · `check`, `secure`, `pentest`, `expert` · `ship` · `learn` · helpers: `which`, `explain`, `impact`, `spike`, `research`, `map`, `inbox`, `handoff`, `note`, `health` |
| **Agents** | product manager, architecture designer, software engineer, AI engineer, QA, security analyst, expert reviewer, lane triage. They hand work to each other through run-folder files, never chat history |
| **Graphs** | [code-review-graph](https://pypi.org/project/code-review-graph/) and [graphify](https://pypi.org/project/graphifyy/) for code; Omnigraph **dev-graph** (decisions, issues, learnings) and **second-brain** (your notes) |
| **Guard** | A PreToolUse hook that parses whole shell commands and blocks commits, pushes, GitHub writes, secret reads, env dumps, deploys and more (18 rules, self-tested with `lfg doctor --selftest`) |
| **Gates** | Lint, types, tests, build, CI replay, secret scan, security vetting, an offline pentest with a local model, expert review and a Docker ship check, all from exit codes, never an agent's claim |
| **Dashboard** | `lfg ui`: runs, issues, checks, code maps, docs and playbooks, usage and cost, **every skill on your machine** (with name clashes and context cost), and **Settings → Claude Code**, where you choose where LFG is on, add packs, and undo any change |

## Feature packs

```bash
lfg packs                 # what's on, what's missing
lfg add security          # gitleaks, semgrep, osv-scanner, trivy, hadolint, actionlint, zizmor
lfg add shipcheck         # Docker, for the container ship check
lfg add pentest           # experimental: Ollama + Strix + LuLu (~10 GB), offline pentests; asks before any curl | bash
lfg add knowledge         # dev-graph and second-brain (local Omnigraph servers)
lfg add linear            # Linear MCP (reuses yours if you have one)
lfg add headroom          # experimental: third-party proxy that rewrites context to compress it; LFG repos only by default
lfg add dictate           # LFG Dictate: hold Option+Space anywhere on your Mac to dictate (on-device)
```

Or use the dashboard: **Settings → Claude Code → Feature packs**.

## LFG Dictate

Hold **Option+Space** anywhere on your Mac, in any app, speak, and let go: the words appear where your cursor is. Double-tap for hands-free dictation until you press the shortcut again or Esc.

- **Off until you turn it on:** nothing is downloaded or asked for until `lfg add dictate` (or Settings → Claude Code → Feature packs). It then fetches Cactus Compute's on-device [Whistle](https://cactuscompute.com/blog/whistle) model (17 MB) into `~/.lfg/dictate` and asks macOS for Microphone and Accessibility permission.
- **On-device:** audio never leaves the Mac, usage telemetry is switched off, and no audio or transcript is kept. **Clean up with Claude** is on by default: it sends the text (never audio) to Claude, with your Claude Code sign-in, to remove filler words, apply spoken corrections and fix punctuation. Turn it off (`lfg dictate cleanup off` or the Dictate row) to keep everything on the Mac.
- **Both, every time:** the text is put where your cursor is and also left on your clipboard, so you can paste it again anywhere. Pasting is the default; choose **Type instead** for apps that block pasting.
- While it listens, a small pill at the bottom of the screen shows bars that move with your voice; that's all.
- Change the shortcut, paste/type and Clean up on the Dictate row in Settings → Claude Code, or with `lfg dictate shortcut right_option`, `lfg dictate insert type`, `lfg dictate cleanup on|off`. macOS lists it as **LFG Dictate** under Privacy & Security. `lfg remove dictate` deletes it all.

## Requirements

macOS only (Apple silicon or Intel), Python 3.9+, [Claude Code](https://claude.com/claude-code), and Homebrew for any tools you don't have yet. Linux support is on the roadmap.

## Everyday commands

```bash
lfg doctor        # is everything working? (says how to fix what isn't)
lfg ui            # the dashboard at http://127.0.0.1:7777
lfg enable        # turn LFG on in this repo (lfg disable to turn it off)
lfg changes       # what LFG changed outside ~/.lfg
lfg uninstall     # undo all of it
```

## Docs

- [docs/guide.html](docs/guide.html): the user guide (also in `lfg ui` → Help)
- [docs/sharing.md](docs/sharing.md): rolling LFG out to a team
- [docs/dashboard.md](docs/dashboard.md): every dashboard page
- [CONTRACT.md](CONTRACT.md): CLI reference, file layout, and exactly what LFG may change
- [plugin/README.md](plugin/README.md): the skills and agents

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md). Report security problems (for example, a way around the guard) privately, as described in [SECURITY.md](SECURITY.md).

```bash
python3 -m unittest discover -s tests            # unit + install-flow tests (sandboxed, fake claude)
uvx ruff check plugin/lib plugin/bin/lfg tests
plugin/bin/lfg doctor --selftest                  # guard self-test
```

## License and credits

MIT © Varun Singh. See [LICENSE](LICENSE).

Several skills are adapted from [mattpocock/skills](https://github.com/mattpocock/skills) (MIT, © 2026 Matt Pocock), and `/lfg:secure` vendors [cloudflare/security-audit-skill](https://github.com/cloudflare/security-audit-skill) (MIT, © 2025-2026 Cloudflare, Inc.). Each adapted file names its source.
