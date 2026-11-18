# One concept for studios and sessions: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One list for studio chats and terminal sessions (Studio's), every session action on every session, and a model choice for studios.

**Architecture:** A shared model list (new `models.py`) feeds Studio and reviews. `Live` gets `set_model` with a restart fallback. The Studio list request grows scope arguments and returns the Sessions page's rows plus live state. The dashboard gets one row and one action menu used by the list, the open session and "Where you left off"; `#sessions` and `#studio/all` redirect to `#studio`.

**Tech Stack:** Python 3 stdlib (`plugin/lib/lfgcore`), vanilla JS (`ui_assets/app.js`, `app.css`, `index.html`), `unittest`.

**Spec:** `docs/superpowers/specs/2026-11-16-one-session-concept-design.md` (read it first; the mockup is `.superpowers/brainstorm/49864-1794885855/content/merged-list-v3.html`, copies LFG's own CSS).

## Global Constraints

- Work in the worktree `/Users/leek/code/lfg.worktrees/merge-sessions-studios`, branch `merge-sessions-studios`. Never touch `~/code/lfg`'s checkout.
- Commit after each task. **No `Co-Authored-By` line and no "Generated with Claude Code" line. Never amend or force-push. Do not push and do not open a PR**; Lee says when.
- Never bump the version in `plugin/.claude-plugin/plugin.json`. Never edit `~/.lfg/plugin`.
- Tests never touch the real `~/.claude` or `~/.lfg`: patch `C.HOME`, `LFG_HOME` and any path fixed at import time.
- Old `~/.lfg/state/sessions.json` and `~/.lfg/sessions/index.json` read unchanged; no new keys.
- Model list, in this order: Claude Code default (id `""`, first and the starting choice), `claude-fable-5-2` "Fable 5.2", `claude-mythos-5-2` "Mythos 5.2", `claude-fable-5-1` "Fable 5.1", `claude-opus-5-5` "Opus 5.5", `claude-sonnet-5-5` "Sonnet 5.5", `claude-haiku-5-5` "Haiku 5.5". `settings.MODELS` (the per-agent aliases) is not changed.
- Row chips: kind (Studio, Terminal, Desktop app, Background), repo, model, working or idle, time. One **Open** button and a `...` menu. No other chips, no row of buttons, no blue "new" outlines.
- Menu order: Copy resume command, What it changed, Run a skill..., Rules, Remind it of my style; Rename, Change group (Add to a group... when none), Labels...; Hide (Show again), Delete. Star is its own button. Fork, Compact, Export, End stay on the open session.
- Dark and light themes, LFG's existing components. No new UI library. No em dashes in text you write.
- Plain words in UI text; say "group" and "label"; the page is titled "Studio".

## Review Focus

- A studio saved with the legacy model `opus` still resumes, and its row shows "Opus".
- A model id LFG doesn't know shows as written (tidied), and never breaks the row or the dropdown.
- Switching model while the studio is working or waiting for an answer is refused with a plain message.
- `#sessions?...` links saved by an older tab (scope, hidden) land on `#studio` with that scope kept.
- A live studio whose transcript isn't written yet still appears in the list, with kind Studio.
- Delete on a running studio is disabled ("End it first").
- All repos with hundreds of transcripts loads no slower than the Sessions page does on the same data.

---

### Task 1: Shared model list

**Files:**
- Create: `plugin/lib/lfgcore/models.py`, `tests/test_one_session.py`
- Modify: `plugin/lib/lfgcore/claudesess.py:32,911`, `plugin/lib/lfgcore/review.py:1102-1112`, `plugin/lib/lfgcore/settings.py:74`

**Interfaces:**
- Produces: `models.MODELS: list[tuple[str, str]]` (id, label; no default entry), `models.choices(own: str = "") -> list[dict]` (`{"id","label"}`, default first, labelled `Claude Code default (<own>)` when `own` is set), `models.label(model_id: str) -> str` ("" gives "Claude Code default"; `opus`/`sonnet`/`haiku` give "Opus"/"Sonnet"/"Haiku"; a known id gives its label; an unknown id gives the id with `claude-` dropped, dashes to spaces, tidied), `models.valid(model_id: str) -> bool` (known id or legacy alias; "" is valid).

- [ ] **Step 1: Write failing tests** in `tests/test_one_session.py::ModelsTest`: `label("")`, `label("opus") == "Opus"`, `label("claude-fable-5-2") == "Fable 5.2"`, `label("claude-x-9") == "x 9"`; `valid("opus")`, `valid("")`, `not valid("nope")`; `choices()[0] == {"id": "", "label": "Claude Code default"}` and `[m["id"] for m in choices()[1:]]` equals the six ids in order; `review.models()` and `models.choices()` give the same ids; `claudesess.start` keeps `claude-fable-5-2` as the stored model (patch `Live`, `C.which`, `_remember`) and drops an unknown one to `None`.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_one_session.ModelsTest -v`. Expected: FAIL (no module).
- [ ] **Step 3: Implement `models.py`** as above; make `review.MODELS` read `models.MODELS`, `review.models()` return `models.choices(own)`, `settings.py`'s review-model tuple build from `models.MODELS`, and `claudesess.start` validate with `models.valid` (store `None` for `""`). `claudesess.MODELS` is removed; its `listing` and `detail` payload key `models` becomes `models.choices(...)`.
- [ ] **Step 4: Run** `python3 -m unittest tests.test_one_session tests.test_core -v`. Expected: PASS.
- [ ] **Step 5: Commit** `Share one model list between Studio and reviews`.

### Task 2: Model switch on a running studio (tests first)

**Files:**
- Modify: `plugin/lib/lfgcore/claudesess.py` (`Live`, new module functions), `plugin/lib/lfgcore/dashboard.py:818` area (save action)
- Test: `tests/test_one_session.py::ModelSwitchTest`

**Interfaces:**
- Consumes: `models.valid`.
- Produces: `Live.set_model(model: str) -> None` (raises `Invalid("Wait for the answer to finish, then change the model.")` when `state` is `working`, `starting` or `needs-you`; raises `Invalid` for an invalid model; stores `self.model` and `_remember(self.sid, model=...)`), `Live.model_pending: bool`, `claudesess.set_model(sid: str, model: str) -> dict` (returns `{"id", "model"}`; for a saved session that is not live, only stores the model for the next resume), dashboard save action `sess_model {id, model}`.

- [ ] **Step 1: Write the failing tests first**, with `Live.__new__` and a recorded `_write`, as `test_questions_and_plans_are_answered_not_allowed` does:
  - `test_set_model_refused_while_working`: state `working`, expect `Invalid`, nothing written, `lv.model` unchanged.
  - `test_set_model_refused_when_waiting_for_you`: state `needs-you`.
  - `test_set_model_rejects_unknown`: `Invalid`.
  - `test_fallback_restarts_with_new_model_on_next_message`: `lv._native_set_model = False`; after `set_model("claude-haiku-5-5")` on an idle studio, `model_pending` is true and no control request was sent; the next `say("hi")` stops the old process and starts a new `Live` argv containing `["--model", "claude-haiku-5-5", "--resume", sid]` (patch `subprocess.Popen` and `C.which`, read `argv`).
  - `test_native_switch_sends_set_model_control_request`: `lv._native_set_model = True`; the written object is `{"type": "control_request", "request": {"subtype": "set_model", "model": "claude-haiku-5-5"}}` with a `request_id`, and `model_pending` stays false.
  - `test_saved_session_keeps_model_for_resume`: `claudesess.set_model` on a session with no `Live` stores it; `resume()` then passes it to `Live` (argv has `--model`).
- [ ] **Step 2: Run** `python3 -m unittest tests.test_one_session.ModelSwitchTest -v`. Expected: FAIL.
- [ ] **Step 3: Probe whether `set_model` is supported.** With the real `claude` (a throwaway session in a temp folder, `-p --input-format stream-json --output-format stream-json --verbose`), send a `control_request` `{"subtype": "set_model", "model": "claude-haiku-5-5"}` and then one message; record the response subtype and the `model` on the next assistant message. Write what you saw to `docs/superpowers/plans/2026-11-16-set-model-probe.md` (three lines). Set the class default `Live._native_set_model` to `True` only if the response succeeded and the reply used the new model; otherwise `False`.
- [ ] **Step 4: Implement** `Live.set_model`, the pending-restart path inside `Live.say` (stop the process, build the new argv with `--resume` and the stored model, keep `sid`, `title`, `mode`, `review`), `claudesess.set_model`, and `sess_model` in `dashboard.py` next to `sess_start`.
- [ ] **Step 5: Run** the class and the full file. Expected: PASS.
- [ ] **Step 6: Commit** `A running studio can change model`.

### Task 3: The merged list data

**Files:**
- Create: `plugin/lib/lfgcore/studiolist.py`
- Modify: `plugin/lib/lfgcore/ui.py:415-418` (the `studio` view), `plugin/lib/lfgcore/claudesess.py` (`listing` delegates)
- Test: `tests/test_one_session.py::StudioListTest`

**Interfaces:**
- Consumes: `sessions.listing(hidden, only, loose)`, `sessions.group_info()`, `claudesess._LIVE`, `claudesess._index()`, `models.label`.
- Produces: `studiolist.listing(rid: str, root: str, hidden: bool = False, scope: str = "repo") -> dict` where `scope` is `repo`, `all` or `loose`. Returns `{"sessions": [row], "group_info", "label_list", "models", "modes"}`. Each `row` is the Sessions page's row (all its keys: `id`, `name`, `title`, `repo`, `cwd`, `resume`, `starred`, `hidden`, `folder`, `via_pr`, `via_ticket`, `labels`, `branch`, `worktree`, `cost`, `modified`, `prompts`, `loose`, ...) plus `kind` (`studio|terminal|desktop|background`), `state` (`working|needs-you|idle|saved|ended`), `model` (id, "" if unknown), `model_label`, `live: bool`. A live studio with no transcript yet is included first, `kind` `studio`.

- [ ] **Step 1: Write failing tests**: a tmp `HOME` with two transcripts (one terminal-entry, one in the LFG index with `lfg: true`) and one `_LIVE` stub; assert `kind`, `state`, `model_label` for each (including legacy `opus` giving "Opus" and an unknown id), `scope="loose"` returns only sessions outside a repo, `scope="all"` returns both repos, `hidden=False` drops hidden rows and `True` keeps them, the live-without-transcript row is first, and `starred`, `folder`, `labels` come through.
- [ ] **Step 2: Run** `python3 -m unittest tests.test_one_session.StudioListTest -v`. Expected: FAIL.
- [ ] **Step 3: Implement `studiolist.listing`** by calling `sessions.listing` for the scope and joining live state and the LFG index by id; read the model from the index, else the live process, else the transcript summary (as `claudesess.listing` does from `meta["model"]`). `ui.py`'s `studio` view takes `scope`, `hidden` query args and calls it.
- [ ] **Step 4: Measure.** Time `studiolist.listing(scope="all")` against `sessions.listing()` on this computer's real data (read only, `LFG_HOME` unchanged) and put both numbers in the commit body; it must be no slower than +10%.
- [ ] **Step 5: Run** all tests. Expected: PASS.
- [ ] **Step 6: Commit** `One Studio list request for every session`.

### Task 4: The list page, addresses and redirects

**Files:**
- Modify: `plugin/lib/lfgcore/ui_assets/app.js` (`ssAll` ~6259, `wireSessions` ~3010-3320, `route`, `NAV`, `NAV_GROUPS`, `noticeGo` ~7307, `AUTO_REFRESH` ~7633), `plugin/lib/lfgcore/ui_assets/index.html` (the `top-sess` link), `plugin/lib/lfgcore/ui_assets/app.css`

**Interfaces:**
- Consumes: Task 3's rows. The existing `groupTree`, `treeHtml`, `labelFilterBar`, `scopeArgs`, `allRepos`, `sessionGroupDrawer`, the "Done with" drawer.
- Produces: `ssList(list, unlocked) -> string` (the page), `sessRow(s, ctx) -> string` (one row: star, title with `labelChips`, chips, Open, `...`), the hash scheme `#studio` (list), `#studio/new`, `#studio/<id>`. Old `#sessions...` and `#studio/all` redirect to `#studio`, keeping `loose=1`, `hidden` and repo scope. Per-page scope stored for `sessions` is read as the list's scope once.

- [ ] **Step 1: Build the page to match the mockup**: title "Studio" with **New studio** (goes to `#studio/new`), search, By group / By time, the tabs `<repo> / All repos / Outside a repo`, one line with the label filter, **Starred**, **Show hidden**, **New group...**, and the Yours / Background / All switch. Keep: group tree with counts and Manage on hover, the repo sections for sessions in no group, older-than-a-week sessions folded, the "Done" clean-up on a group, skill runs and background work lines (the `data-sess-work` fill and the 4-second refresh while a run is going), worktree, branch and cost in the row's meta, "its folder is gone".
- [ ] **Step 2: Redirects.** Router maps `sessions` and `studio/all` to `studio` (same scope args). Remove the Sessions entry from `NAV` and `NAV_GROUPS`; change `index.html`'s `<a class="top-sess" href="#sessions">` to `href="#studio"`; the sidebar's Studio entry points to `#studio`; `newStudio()` goes to `#studio/new`. `noticeGo` opens `#studio` and sets `state.goto = '[data-sid="<id>"]'`, which scrolls to and flashes the row. `AUTO_REFRESH` and the `location.hash.startsWith("#sessions")` timer use `studio`.
- [ ] **Step 3: Check** `node --check plugin/lib/lfgcore/ui_assets/app.js`. Expected: no output. Then run `plugin/bin/lfg ui` from the worktree on a spare port with `--no-open`, open it in a browser, and check each item in the Goals list of the spec; note anything unchecked in the commit body.
- [ ] **Step 4: Commit** `Studio is the one list; Sessions redirects to it`.

### Task 5: One action menu, on the row, the open session and "Where you left off"

**Files:**
- Modify: `plugin/lib/lfgcore/ui_assets/app.js` (`ssHead` ~6552, `ssDetail`, `ssAct`, `wireStudio`, the session panel ~3395-3420 on Where you left off, `wireSessions` handlers), `app.css`

**Interfaces:**
- Consumes: Task 4's `sessRow`. The existing save actions `session_star`, `session_name`, `session_folder`, `session_hide`, `session_trash`, `pref_remind`, `skill_run`, and the drawers behind "What it changed", "Run a skill...", "Rules", "Labels...", "Add to a group...".
- Produces: `sessMenu(s: object, ctx: object) -> string` (the menu HTML, ordered as in Global Constraints) and `wireSessMenu(root: Element, ctx: object) -> void` (all its handlers). Delete is disabled with the title "End it first" when `s.live` and `s.state` is not `saved`/`ended`.

- [ ] **Step 1: Write `sessMenu` and `wireSessMenu` once**, moving the handlers out of `wireSessions` and the Where-you-left-off panel; both now call them. The open session's header gets: model dropdown (Task 6), cost, a star, End (only while it runs) and `...`, whose menu is `sessMenu` plus Fork, Compact and Export. Remove the old `data-menu` entries that `sessMenu` replaces (Rename, Copy terminal command).
- [ ] **Step 2: Under the conversation of an open session**, replace the composer with the reply box: placeholder "Message this studio. / for skills, @ for files", attach, the Ask / Auto / Plan switch, **Send**. A saved terminal session keeps "Write to continue this session here" and **Continue here**. The where-it-works picker and "Start" appear only on `#studio/new`.
- [ ] **Step 3: Check** `node --check`, then in the browser: every menu item works from a list row, an open studio, an open terminal session and the Where-you-left-off panel; a studio started in the dashboard and a terminal session look the same except the kind chip.
- [ ] **Step 4: Commit** `Every session has the same actions`.

### Task 6: Model dropdowns

**Files:**
- Modify: `plugin/lib/lfgcore/ui_assets/app.js` (`ssHead`, `ssComposer` ~6284, `wireStudio`, `sess_start` call), `plugin/lib/lfgcore/dashboard.py:818`

**Interfaces:**
- Consumes: `models` from the Studio payload (`models.choices`), Task 2's `sess_model`.
- Produces: `#studio/new` screen "New studio" with a model select (default "Claude Code default (<own>)", remembered in `localStorage` key `lfg.ss.model`), passed as `model` to `sess_start`; the header model button (label from `model_label`) opening the list, disabled while the studio is working or waiting for you (title says why), calling `sess_model`; a model chip on rows.

- [ ] **Step 1: Build both dropdowns** to match the mockup (screens 2 and 3). A switch that the backend refuses shows its message in a toast and leaves the label as it was.
- [ ] **Step 2: Check** `node --check`; in the browser: start a studio on Mythos 5.2, see "Mythos 5.2" on its row and header, switch it to Haiku 5.5 between turns, send a message, and confirm the next reply used it (the header and row update); open an old studio saved with `opus` and see "Opus".
- [ ] **Step 3: Commit** `Choose the model for a studio`.

### Task 7: Notes, docs, final checks

**Files:**
- Create: `changes/merge-sessions-studios.json`
- Modify: `CONTRACT.md` (the `studio`/`sessions` views, `sess_model`, `sess_start`'s `model`, the model list, the addresses), `docs/dashboard.md` (merge the Sessions rows into Studio's; update Tabs and What's new rows that mention Sessions)

- [ ] **Step 1: Notes file.** `plugin/bin/lfg release note merge-sessions-studios --changed "Studio is now the one list of every session, studio chat or terminal, with every action on each; the Sessions page redirects to it" --added "Choose the model for a studio, in the new-studio box and in an open studio's header: Fable 5.2, Mythos 5.2, Fable 5.1, Opus 5.5, Sonnet 5.5, Haiku 5.5 or Claude Code's default" --fixed "The top-right Studio button now opens the Studio list" --whats-new "One list for studios and sessions" "Studio now lists every session, whether you chatted in the dashboard or started it in a terminal. Each row has Open and a ... menu with copy resume command, what it changed, run a skill, rules, rename, group, labels, hide and delete. A studio can now run on any model." --page studio --sel ".ss-allbox"`. Read the generated file; the `whats_new` entry must exist.
- [ ] **Step 2: Update `CONTRACT.md` and `docs/dashboard.md`** to describe the code as it is now.
- [ ] **Step 3: Run all checks**: `python3 -m unittest discover -s tests`, `uvx ruff check plugin/lib plugin/bin/lfg tests`, `plugin/bin/lfg doctor --selftest`, `node --check plugin/lib/lfgcore/ui_assets/app.js`. Expected: all pass. Report anything that did not run.
- [ ] **Step 4: Commit** `Notes and docs for one list of sessions`. Do not push.

## Self-review

- Spec coverage: one list (3, 4), nothing lost (4), every action (5), model setting (1, 2, 6), old addresses and top-right button (4), notes file and docs (7), tests for the switch fallback first (2).
- The fallback tests come before any switch code (Task 2 steps 1 to 3); the probe only chooses the default of `_native_set_model`.
