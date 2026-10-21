# Standing decisions about upstream

How this fork takes changes from varun-singhh/lfg. Fix with Claude in the dashboard follows these when it finishes an update, and stops to ask when an upstream change overlaps something this fork does and nothing here covers it. Add one line per decision.

- Never take upstream's Commit approval (`guard.allow_commits`, the approval prompt for `git commit`): Preferences (Git → Commits) decide when Claude commits, and the guard keeps blocking commits on its own.
- A repo's LFG knowledge lives in the repo, in `<checkout>/.lfg/` (docs, ADRs, runs, nodes, commands.json, shipcheck.json), not in `~/.lfg/repos/<repo-id>/`. Upstream features that store per-repo files in `~/.lfg` get moved into `.lfg/` here.
- The guard blocks through `_block()` so a rule lifted in Preferences → Safety rules stops blocking; upstream's `raise Block(...)` becomes `_block(...)`, and LFG's own files keep `hard=True`.
- Keep this fork's own features whole when upstream touches the same code: Preferences (prefs.py and its hooks), Sessions, PR reviews, Usage, the update banner (Keep / Later / Skip), and the back and forward arrows.
