# Spec: PR reviews for your own PRs, and "How Claude talks to you" in Preferences

Two independent changes, shipped as two PRs, part 2 first (it is smaller). Agreed with Lee on 2026-10-20.

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
