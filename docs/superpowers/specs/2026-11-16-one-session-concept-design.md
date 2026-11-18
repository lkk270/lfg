# One concept for studios and sessions

Project 4 of 4 (groups and labels, "where you left off" and tab fixes are shipped or separate). Status: draft, waiting for
Lee's approval. Mockup: `.superpowers/brainstorm/49864-1794885855/content/merged-list-v3.html` (not committed; three screens:
the list, an open studio with the model dropdown, and the new-studio box).

## Why

A studio chat and a terminal session are the same thing underneath: a Claude Code transcript, keyed by session id. LFG still
shows them as two things on two pages with different buttons. The Sessions page has star, copy resume command, what it
changed, run a skill, rules, remind me of my style, rename, hide and delete; Studio's list has only group and labels, and an
open studio has fork, compact, export, copy command and rename. Studio also offers only `opus`, `sonnet` and `haiku`, so a
studio can't run on Fable 5.2 or Mythos 5.2, which every other part of LFG already offers.

What Lee wants: one list, every action on every session, and a model setting for studios. A studio is a session you can also
chat with in the dashboard.

## Goals

1. **One list.** Studio's "All sessions" becomes the only list. The Sessions page goes away.
2. **Nothing the Sessions page does today is lost** in the merged list: the group tree, labels bar and label filter, the repo /
   All repos / Outside a repo views, search, Starred, show hidden, older sessions folded away, skill runs and background work
   on a session, delete to the Trash, worktree, branch and cost on a row, and a group's **Done** clean-up (hide its sessions,
   remove the worktrees they used). There is no multi-select or bulk action on the Sessions page, so none is added.
3. **Every session has every action**, studio or terminal, in one place (the `...` menu on a row, and the `...` menu in an open
   session's header): Copy resume command, What it changed, Run a skill, Rules, Remind it of my style, Rename, Change group,
   Labels, Hide, Delete. Star is its own button on both. Fork, Compact and Export stay on the open session.
4. **A model setting for studios.** A model dropdown in the new-studio box and one in an open studio's header. Same list as
   Settings, "Model for reviews", from one shared list in the code: Claude Code default (first, and the starting choice),
   Fable 5.2, Mythos 5.2, Fable 5.1, Opus 5.5, Sonnet 5.5, Haiku 5.5. The current model shows on the row and in the header.
5. **Old addresses keep working.** `#sessions` (with or without a scope) lands on the merged list. Links from "Where you left
   off", notices (a skill run finished) and open tabs land on the right row or studio.

## Non-goals

- Changing what is on disk, how `/resume` works, or how groups and labels are stored.
- The PR review chat (it already uses a studio underneath and keeps its page).
- Tab behaviour (project 3) and "where you left off" content (project 2). Only their links into sessions change.
- A new price table or new models. Adding a future model stays one list plus the spend price table.

## Anti-goals

- A row must stay calm. No row of buttons, no extra chips beyond those below.
- A studio chat and a terminal session must not look like two kinds of thing. A small chip says which it is, nothing more.
- The merged list must not be slower to load than the Sessions page is now.

## What it looks like

- **A row:** star, one-line title with its label chips, then small chips: kind (Studio, Terminal, Desktop app or Background,
  with a small icon), repo, model, working or idle, time. One **Open** button and a `...` menu.
- **The list page:** title "Studio" with **New studio**, search and By group / By time; below, the tabs
  **<current repo> / All repos / Outside a repo**; below that, one line with the labels filter, **Starred** and **New group...**.
  Manage on a group shows on hover. The existing Yours / Background / All switch stays.
- **An open session:** the header gets the model dropdown (left of the cost), a star, End (only while it runs) and `...`. Under
  the conversation is a plain reply box, "Message this studio", with `/` for skills and `@` for files, the Ask / Auto / Plan
  switch and **Send**. A terminal session opens the same way; its box says it continues the session here (existing behaviour).
- **New studio:** its own screen from the **New studio** button (and the `+` menu, and the sidebar): description box, where it
  works, Ask / Auto / Plan, the model dropdown, **Start**.

## Approaches

- **A. Studio list grows into the merged list (picked).** Studio already shows groups, labels and the open-session view. It
  gains the Sessions page's views and its row actions. One list, one row, one menu.
- **B. Keep two pages and share one row.** Less change, but two places to learn and two lists to keep in step; Lee did not want it.
- **C. Sessions page gains a Chat button.** The Sessions page already has more of what is wanted, but a chat view would then
  live in two places. Rejected.

## Decisions (as Lee decided them)

- Studio is the list; the Sessions page's group tree, labels, All repos view and filters all exist in it.
- `#sessions` still works and takes you to the merged list.
- Model dropdown in both the new-studio box and the open studio's header, from the same list as Settings, with Claude Code's
  default as the starting choice and the current model shown on the row or header.
- A row is calm: Open plus a `...` menu. The reply box under an open studio is a plain reply box.
- New studio is its own screen.

## Decisions I made (Lee can override)

- **Addresses.** `#studio` is the list (it is a new-studio box today), `#studio/new` is the new-studio screen, and
  `#studio/<id>` is an open session, as now. The old `#studio/all` and `#sessions` both go to `#studio`. The sidebar's
  Studio entry and the top-right Studio button go to the list; **New studio** (button, `+` menu, sidebar) goes to `#studio/new`.
- **Opening costs nothing.** Studio's list already reads every transcript of the repo and its worktrees, terminal and
  desktop ones included, and marks the ones LFG started. Opening a session only reads its transcript. A Claude Code process
  starts only when you press Send or Continue here (`resume()`), as now.
- **One list in the code.** One Studio list request with scope arguments (repo, all repos, outside a repo, hidden), built from
  the transcripts the way the Sessions page's listing is, with Studio's live state, model and "started by LFG" added on the
  server. It must load no slower than the Sessions page does now; the builder measures both. The old `sessions` request
  stays: the PR page's "Link a session" drawer and "Where you left off" use it. Stored per-page scope choices for Sessions
  carry over to the list.
- **Kind chip.** Started in the dashboard, or continued there, is **Studio**; otherwise **Terminal**, **Desktop app** or
  **Background**. A terminal session you continue here becomes a Studio from then on (`resume()` already records it).
- **Model storage.** "Claude Code default" is stored as no model. New studios store the full id; a legacy `opus`, `sonnet` or
  `haiku` shows as "Opus", "Sonnet", "Haiku" with no version and still resumes. A model picked on a terminal session is kept
  only once you continue it there. `settings.MODELS` (the per-agent aliases) is left alone; only the review model list and
  Studio's list share the new one.
- **Switching while busy.** The model dropdown is disabled while the studio is working or waiting for your answer, and
  switches between turns.
- **One action menu, one definition.** The list row, the open session header and the "Where you left off" session panel all
  use the same menu code, so they cannot drift again. That panel today carries its own copy of these buttons.
- **Rename, Hide and Delete on an open, running studio:** Delete is disabled while it runs ("End it first"); the rest work.
- **Model on a terminal session:** its row shows the model its last reply used. Choosing another one in an open terminal
  session applies to the studio continuation only; it never touches the terminal's own process.
- **Models.** The shared list lives in one module; `claudesess.MODELS`, `review.MODELS` and `settings.py`'s list read it. A
  stored legacy value (`opus`, `sonnet`, `haiku`) still resumes. A model id LFG doesn't know shows as it is, tidied.
- **Switching model mid-conversation.** Preferred: Claude Code's `set_model` control request, the way Mode uses
  `set_permission_mode`. **Not verified yet.** If it is not supported, the switch restarts the process with `--resume` and the
  new `--model` at the next message, which `Live` already does for resume. The builder tests this first and picks.
- **The sidebar's Sessions entry is removed.** The top-right Studio button's link is `#sessions` in `index.html` (checked),
  which is why it seemed to go to Sessions; it now points to `#studio`.
- **Skill runs and background work** (now inside a Sessions row) show on the open session under its header, one line each,
  and as a small "working" chip on the row. Their current 4-second refresh while a run is going stays.
- **Notices.** "A skill run finished" opens the list scrolled to that row (highlighted), as it does on the Sessions page now.

## Constraints

- Follow `CLAUDE.md`: `changes/<branch>.json` with a `whats_new` entry, `CONTRACT.md` and `docs/dashboard.md` updated (the
  Sessions rows are merged into Studio's), tests that patch `C.HOME` and `LFG_HOME`, `python3 -m unittest discover -s tests`,
  `uvx ruff check plugin/lib plugin/bin/lfg tests`, `plugin/bin/lfg doctor --selftest`, `node --check` on `app.js`.
- Old `~/.lfg/state/sessions.json` and `~/.lfg/sessions/index.json` read unchanged. No new keys are needed.
- Dark and light themes, LFG's own components and spacing (the mockup copies `app.css` as it is). No new UI library.
- One PR, its own branch and worktree off `origin/main`. It is large; the builder may split it into two commits (list and
  actions; model) but it ships as one release, 0.8.0.

## Left to the builder

Exact menu component, how the `...` menu closes and positions near the window edge, the row's loading and empty states, the
label for unknown models, scroll-to-row details, keyboard behaviour, and the test split.

## Open items this settles

- The top-right Studio button going to Sessions: explained above (its link is `#sessions`); not a bug in the router.
- The malloc message when running `lfg ui` is unrelated and still waits on Lee's `printenv` output.
