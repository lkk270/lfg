Rule module: git-guard · LFG · author Varun Singh · adapted from mattpocock/skills/git-guardrails-claude-code (MIT)

# git-guard: read-only git and GitHub

Agents read git and GitHub; the human writes. Every change is left **unstaged** with `COMMIT_MSG.md` and `PR_BODY.md` in the run folder, and the human commits, pushes and opens the PR in their own terminal. This holds even when the user asks in chat.

## Allowed

- git: `status`, `diff`, `log`, `show`, `blame`, `rev-parse`, `merge-base`, `ls-files`, `branch` (list), `remote -v`; `worktree add/remove` and `apply --3way` for the patch-based `/build`.
- gh: `auth status`, `pr view/list/checks/diff`, `run list/view` (incl. `--log-failed`), `issue view/list`, `repo view`, `api` with GET only.

## Blocked (guard rules 1–3)

**Rule 1, git writes:** `git commit`, `push` (any form, incl. `--force`), `merge`, `rebase`, `tag`, `stash drop`, `reset --hard`, `clean -f` / `-fd`, `branch -D`, and `checkout --` / `checkout .` / `restore` over uncommitted work.

**Rule 2, GitHub writes:** `gh pr create/merge/close/comment/review`, `gh issue create/edit/close/comment`, `gh release …`, `gh repo create/delete/edit`, `gh secret …`, `gh variable …`, `gh workflow run`, `gh api` with any method other than GET (`-X POST/PUT/PATCH/DELETE`, `-f`/`-F` fields that imply POST).

**Rule 3, bypasses:** `--no-verify`, `-c core.hooksPath=…`, `SKIP=…` env tricks, disabling CI jobs or workflow steps.

Wrapping doesn't change the verdict: `cd x && git push`, `sh -c`, `bash -lc`, `eval`, `xargs`, aliases, variables and subshells are parsed by `lfg-guard` and blocked the same way.

If the user's Preferences are switched on (`lfg prefs status` says hooks: true), they decide `git commit`, `git push` (including force-push and amend), `gh pr create` and `gh pr merge`, and their own check runs before each command: follow `lfg-preferences.md` and any rules changed for this session, including committing or pushing without being asked when they say so. Everything else in rules 1 to 3 still holds.

If `guard.allow_commit` is `true` in `~/.lfg/config.json`, `git commit` (not `--amend`) is allowed and you commit when the user asks. Everything else in rule 1, and rules 2 and 3, still holds.

## When blocked

The guard exits 2 with: `Blocked by LFG rule <N>: <why>. A human must do this in their own terminal.`

1. Don't retry with a variant.
2. Tell the user the exact command to run themselves, with paths filled in, e.g.
   `git commit -F .lfg/runs/<run-id>/COMMIT_MSG.md`
   `gh pr create --body-file .lfg/runs/<run-id>/PR_BODY.md`
3. Carry on with the read-only work that remains.

## Why two layers

Prefix-based `permissions.deny` rules catch the plain forms; `lfg-guard` parses the full command and catches the wrapped ones. `lfg doctor --selftest` proves both block every item above.
