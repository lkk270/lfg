# Spec: own-PR reviews, "How Claude talks to you" in Preferences, and Usage page costs

Three independent changes, one PR each: part 2 first (it is smaller), then part 1; part 3 in any order. Agreed with Lee on 2026-10-20.

## Part 2 (ship first): PR reviews page

### What is wrong today

- **You cannot see your own PRs.** lfg ui → PR reviews → "Waiting on you" lists only PRs where GitHub names you as
  a requested reviewer (`review.queue()`, `plugin/lib/lfgcore/review.py`, `gh search prs --review-requested=@me`).
  GitHub never names you on your own PR, so a PR you want to self-review never shows. The review engine itself
  already handles your own PRs (`review.py` computes `"mine"` around line 490); only the list leaves them out.
- **The repo picker at the top is ignored.** That search covers every repo you have access to, whatever repo is
  picked.

### What to build

| Change | Detail |
|---|---|
| New section "Your open PRs" | `gh search prs --author=@me --state=open`, same columns and buttons as "Waiting on you" (Review / Re-review / Import / Open), same GitHub status tag, same 120 s cache pattern as `queue()`. |
| Filter by the picked repo | Both sections show only PRs whose `owner/repo` is the picked repo's GitHub remote (`gh repo view --json nameWithOwner` in that repo's root, as `review.py:40` does). A "Show all repos" link turns the filter off. A repo with no GitHub remote shows everything, with a one-line note. |
| Your own PR: Comment only | On a PR you authored, the detail page shows only "Comment only". GitHub rejects Approve and Request changes on your own PR. Enforce it in `review.post()` too, not only by hiding buttons. |

Where: `review.py` (`queue`, `dashboard`, `post`), `ui.py` (the `prreviews` API, pass the repo through),
`ui_assets/app.js` (`PAGES.prs`, `prDetail`).

### Tests (in `tests/test_core.py`, next to the existing review tests; mock `gh_json`)

- Your own open PRs appear under "Your open PRs" and not under "Waiting on you".
- With a repo picked, PRs from other repos are left out of both sections; with "all", they are back.
- `post()` on your own PR with `approve` or `request-changes` raises a clear error; `comment` works.

## Part 1 (ship second): "How Claude talks to you" in Preferences

### What it is

A new built-in group in `BUILTIN` (`plugin/lib/lfgcore/prefs.py`), shown on lfg ui → Preferences like Git and
GitHub. Global default plus per-session changes in Sessions → Rules, both of which already exist and need no new
code. These are instructions to Claude, not enforced (`"enforce": False`, so the page tags them "Claude is asked").

Source of the rule text: Lee's `~/.claude/CLAUDE.md` (sections "Lead with the answer" through "Tables earn their
place"). Condense each to one or two sentences for `text`, and write a plain `about` saying what the user will see.
Do not copy the long examples, and do not import stack facts (the Supabase / ClickHouse SQL targets become generic
"system and environment").

| id | Title | Kind | Default |
|---|---|---|---|
| `style_answer_first` | Lead with the answer: 2-3 sentences that are the answer; who, what, where, when; old vs new for a fix | switch | off |
| `style_breaks_first` | Say what breaks for a person before how it works | switch | off |
| `style_point_words` | Point length: no limit / 20 words / 40 words | choice | no limit |
| `style_paste_blocks` | Anything to paste goes in a code block between `--- PASTE START ---` and `--- PASTE END ---`, nothing else inside, and say where it goes | switch | **on** |
| `style_risky_blocks` | SQL and destructive commands: the marker names the target (system, environment) and READ ONLY or WRITE - kinds; say the row count, add RETURNING or a check, name preconditions, offer a dry run | switch | off |
| `style_steps` | Steps the user runs (commands, queries, secrets, clicks): show the outline once, then one step per message with a one-line status ("step 2 of 5: ..."), the step in paste markers, what to report back, then wait | switch | off |
| `style_handoff_prompts` | Prompts for another session open with what the session is, then the task, then branch and base | switch | off |
| `style_labels` | Re-name a label every time it is used again; no code identifiers or jargon when explaining | switch | off |
| `style_hold_position` | A question is not a correction: re-check and answer on the evidence; say what is proven and what is not | switch | off |
| `style_one_note` | At most one trailing note, and only if it changes what the user does next | switch | off |
| `style_recommend` | Give a recommendation, not a menu; no padding or unasked follow-ups | switch | off |
| `style_no_em_dash` | No em dashes anywhere | switch | off |
| `style_us_spelling` | US spelling, in code and prose | switch | off |
| `style_tables` | Tables only when comparing several things across the same dimensions | switch | off |

`style_paste_blocks` is the only one on by default, for every LFG user. Lee turns the rest on globally himself.

Check `render()` output stays readable: the group heading is "How Claude talks to you" in `lfg-preferences.md`.

### Reprompt button ("Remind it of my style")

When a session drifts from the style, the user wants to push the rules back in.

- lfg ui → Sessions: each row gets a "Remind it of my style" button next to "Rules" (`app.js`, around
  `data-sess-rules`). It needs the edit key like the other buttons.
- The UI cannot type into a terminal session, so the button sets a flag for that session id in prefs state.
- In `prefs.hook("prompt")`, if the flag is set: add every style rule that is on for that session (rendered with
  `render(..., only=<style ids>)`) to `additionalContext` with a line like "The user asked you to follow these
  again; your recent replies drifted from them." Then clear the flag. One message only.
- CLI: `lfg prefs remind <session-id>` does the same (wire it in `cli.py` next to `prefs set`). An agent may run
  it; it only adds instructions, it loosens nothing.

### Tests

- Each style switch appears in `render()` when on and disappears when off; `style_point_words` renders its number.
- A session change overrides the default (existing mechanism, one test for a style id).
- The remind flag adds the style rules to exactly one prompt hook output, then clears; with no flag, nothing is
  added.
- `test_the_preferences_page_and_list_show_them` style: the group shows in `ui.api("prefs")`.

### After part 1 merges (Lee does this, not the agent)

Lee removes the same sections from `~/.claude/CLAUDE.md` (it is in his claude-personal repo, outside this repo;
LFG blocks agents from editing it). The agent's final message lists exactly which headings to cut.

## Rules for the agent building this

- Branch from `main` for each part, one PR each. Commit and push follow the user's Preferences
  (`~/.claude/lfg-preferences.md`).
- Before each commit: `python3 -m unittest discover -s tests` and `uvx ruff check plugin/lib plugin/bin/lfg tests`
  (CI runs `pipx run ruff`; same checks). Lines are at most 120 characters.
- Match the surrounding code: dense one-line docstrings, plain-English UI copy, no em dashes, US spelling.
- `gh pr create` is blocked unless Preferences → GitHub → "Opening PRs" is on. If it is off, give the user the exact
  command in paste markers: `gh pr create --repo lkk270/lfg --fill` (this repo has two remotes, so `--repo` is
  required).

## Part 3 (independent of parts 1 and 2): Usage page costs

The Usage page in `lfg ui` shows what Claude Code costs at API prices, worked out from every session's transcript
under ~/.claude/projects. A review found four real problems and one decision to write down. Fix them on a new branch
`fix/usage-costs` off `main` (base: main). Create its worktree with `lfg worktree new fix/usage-costs`; don't switch
the main checkout.

The code is in `plugin/lib/lfgcore/sessions.py` (`PRICES`, `cost()`, `_file_usage()`, `usage()`),
`plugin/lib/lfgcore/dash.py` (`usage()`, around lines 990-1040), `plugin/lib/lfgcore/ui_assets/app.js` (the Usage
page), and `docs/dashboard.md` (line 16).

1. Two prices are wrong. Look up the published prices with the claude-api skill rather than trusting these notes or
   memory.
   - Claude Fable 5 (`claude-fable-5`) cache reads are $1.00 per million tokens, not $0.25. ($0.25 is right for
     Fable 5.1 and Mythos 5.1.)
   - Claude Haiku 5.5 costs $0.10 / $0.50 per million tokens when the prompt is 100K tokens or fewer, and $0.50 /
     $2.50 above that. The code only has the lower price. The tier depends on each request's prompt size (input +
     cache read + cache write), so it has to be decided per request in `_file_usage()`, not on the daily totals.
     Check what the cache-read and cache-write prices are above 100K.
   - While you're there, confirm the other cache-read prices. Opus 5.5 at $0.20 is correct and deliberate (5% of
     input). Opus 5 $0.50, Sonnet 5 $0.20 and Haiku 5.5 $0.01 have not been checked.
   - If what the usage index stores per file changes, bump its version (`"v"` in `usage()`) so old indexes are read
     again.
2. Models with no price count as $0 and the page never says so. `usage()` already returns `unpriced`. Show it on the
   Usage page, e.g. "Not priced: <models>", so the total is not silently low.
3. With the 90-day range selected, the "30d" spend figure covers 90 days, because it sums everything since the range
   start. Make "30d" mean the last 30 days whatever the range. If the page needs a total for the selected range,
   return it under its own name.
4. `docs/dashboard.md`, Usage row: it still says costs come from `tokensave cost`. Rewrite it to say they come from
   Claude Code's own session transcripts at API list prices. Add what Headroom's detail view shows (the `headroom`
   API view: savings per day and per hour today, from ~/.headroom/savings_events.jsonl).
5. Not a bug, just write it down. The page counts every Claude Code session on this computer, including repos where
   LFG is off. Say so in the same docs row.

Write a failing test first for 1, 2 and 3 in `tests/test_core.py`, class `SessionsTest`, next to
`test_usage_counts_each_reply_once_and_prices_it`. Run `python3 -m unittest discover -s tests` until it passes. Then
open `lfg ui` and check the Usage page on the 30-day and 90-day ranges.

Commit one logical change at a time and push each commit to `fix/usage-costs`. Open a PR against main on origin
(lkk270/lfg). Don't merge it. No em dashes, US spelling.
