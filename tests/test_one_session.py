"""Tests for the one-session concept: the shared model list, and what builds on it."""
import collections
import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("LFG_HOME", tempfile.mkdtemp(prefix="lfg-test-home-"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugin", "lib"))

IDS = ["claude-fable-5-2", "claude-mythos-5-2", "claude-fable-5-1", "claude-opus-5-5", "claude-sonnet-5-5",
       "claude-haiku-5-5"]


class ModelsTest(unittest.TestCase):
    def setUp(self):
        home = tempfile.mkdtemp(prefix="lfg-one-home-")
        from lfgcore import common as C
        p = mock.patch.object(C, "HOME", home)
        p.start()
        self.addCleanup(p.stop)

    def test_label(self):
        from lfgcore import models as M
        self.assertEqual(M.label(""), "Claude Code default")
        self.assertEqual(M.label("opus"), "Opus")
        self.assertEqual(M.label("claude-fable-5-2"), "Fable 5.2")
        self.assertEqual(M.label("claude-x-9"), "x 9")

    def test_valid(self):
        from lfgcore import models as M
        self.assertTrue(M.valid("opus"))
        self.assertTrue(M.valid(""))
        self.assertTrue(M.valid("claude-haiku-5-5"))
        self.assertFalse(M.valid("nope"))

    def test_choices(self):
        from lfgcore import models as M
        self.assertEqual(M.choices()[0], {"id": "", "label": "Claude Code default"})
        self.assertEqual([m["id"] for m in M.choices()[1:]], IDS)
        self.assertEqual(M.choices("opus")[0]["label"], "Claude Code default (opus)")

    def test_review_uses_the_same_list(self):
        from lfgcore import models as M
        from lfgcore import review as R
        self.assertEqual([m["id"] for m in R.models()], [m["id"] for m in M.choices()])

    def test_start_keeps_a_known_model_and_drops_an_unknown_one(self):
        from lfgcore import claudesess as CS
        root = tempfile.mkdtemp(prefix="lfg-one-root-")
        for given, stored in (("claude-fable-5-2", "claude-fable-5-2"), ("nope", None), ("", None)):
            with mock.patch.object(CS, "Live") as live, mock.patch.object(CS.C, "which", return_value="/bin/claude"), \
                    mock.patch.object(CS, "_remember") as rem, mock.patch.object(CS, "_LIVE", {}):
                CS.start("r1", root, "hello", model=given)
            self.assertEqual(live.call_args.args[3], stored, given)
            self.assertEqual(rem.call_args.kwargs["model"], stored, given)


class ModelSwitchTest(unittest.TestCase):
    SID = "11111111-2222-3333-4444-555555555555"

    def setUp(self):
        from lfgcore import claudesess as CS
        self.CS = CS
        home = tempfile.mkdtemp(prefix="lfg-one-home-")
        lfg = tempfile.mkdtemp(prefix="lfg-one-lfg-")
        for p in (mock.patch.object(CS.C, "HOME", home), mock.patch.object(CS.C, "LFG_HOME", lfg),
                  mock.patch.object(CS, "PROJECTS", os.path.join(home, ".claude", "projects")),
                  mock.patch.object(CS, "_LIVE", {})):
            p.start()
            self.addCleanup(p.stop)
        self.root = tempfile.mkdtemp(prefix="lfg-one-root-")

    def live(self, state="idle"):
        CS = self.CS
        lv = CS.Live.__new__(CS.Live)
        lv.sent = []
        lv._write = lambda obj: lv.sent.append(obj) or True
        lv.sid, lv.rid, lv.root, lv.title, lv.mode, lv.model = self.SID, "r1", self.root, "T", "default", "opus"
        lv.pending, lv.queued, lv._qmeta, lv._turns, lv.review = {}, [], [], collections.deque(), None
        lv.state, lv.error, lv.model_pending = state, None, False
        lv.proc = mock.MagicMock()
        return lv

    def test_set_model_refused_while_working(self):
        for state in ("working", "starting"):
            lv = self.live(state)
            with self.assertRaises(self.CS.Invalid) as cm:
                lv.set_model("claude-haiku-5-5")
            self.assertEqual(str(cm.exception), "Wait for the answer to finish, then change the model.")
            self.assertEqual((lv.sent, lv.model), ([], "opus"))

    def test_set_model_refused_when_waiting_for_you(self):
        lv = self.live("needs-you")
        with self.assertRaises(self.CS.Invalid) as cm:
            lv.set_model("claude-haiku-5-5")
        self.assertEqual(str(cm.exception), "Wait for the answer to finish, then change the model.")
        self.assertEqual((lv.sent, lv.model), ([], "opus"))

    def test_set_model_rejects_unknown(self):
        lv = self.live()
        with self.assertRaises(self.CS.Invalid):
            lv.set_model("nope")
        self.assertEqual((lv.sent, lv.model, lv.model_pending), ([], "opus", False))

    def test_fallback_restarts_with_new_model_on_next_message(self):
        CS = self.CS
        lv = self.live()
        lv._native_set_model = False
        CS._LIVE[self.SID] = lv
        with mock.patch.object(CS, "_remember") as rem:
            lv.set_model("claude-haiku-5-5")
        self.assertEqual(rem.call_args.kwargs, {"model": "claude-haiku-5-5"})
        self.assertTrue(lv.model_pending)
        self.assertEqual(lv.sent, [])  # no control request
        old_proc = lv.proc
        with mock.patch.object(CS.subprocess, "Popen") as popen, \
                mock.patch.object(CS.C, "which", return_value="/bin/claude"), \
                mock.patch.object(CS.threading, "Thread"), \
                mock.patch("lfgcore.prreview._child_env", return_value=({}, None)):
            self.assertEqual(lv.say("hi"), "sent")
        old_proc.stdin.close.assert_called()
        argv = popen.call_args.args[0]
        i = argv.index("--model")
        self.assertEqual(argv[i:i + 4], ["--model", "claude-haiku-5-5", "--resume", self.SID])
        new = CS._LIVE[self.SID]
        self.assertIsNot(new, lv)
        self.assertEqual((new.sid, new.title, new.mode, new.model, new.model_pending),
                         (self.SID, "T", "default", "claude-haiku-5-5", False))

    def test_native_switch_sends_set_model_control_request(self):
        lv = self.live()
        lv._native_set_model = True
        with mock.patch.object(self.CS, "_remember"):
            lv.set_model("claude-haiku-5-5")
        self.assertEqual(len(lv.sent), 1)
        obj = dict(lv.sent[0])
        self.assertTrue(obj.pop("request_id"))
        self.assertEqual(obj, {"type": "control_request", "request": {"subtype": "set_model",
                                                                      "model": "claude-haiku-5-5"}})
        self.assertEqual((lv.model, lv.model_pending), ("claude-haiku-5-5", False))

    def test_saved_session_keeps_model_for_resume(self):
        CS = self.CS
        CS._remember(self.SID, lfg=True, model="opus")
        self.assertEqual(CS.set_model(self.SID, "claude-haiku-5-5"), {"id": self.SID, "model": "claude-haiku-5-5"})
        self.assertEqual(CS._index()[self.SID]["model"], "claude-haiku-5-5")
        with self.assertRaises(CS.Invalid):
            CS.set_model(self.SID, "nope")
        tr = os.path.join(CS.PROJECTS, "p")
        os.makedirs(tr)
        with open(os.path.join(tr, self.SID + ".jsonl"), "w") as f:
            f.write('{"type":"user","cwd":"%s","message":{"role":"user","content":"hi"}}\n' % self.root)
        with mock.patch.object(CS.subprocess, "Popen") as popen, \
                mock.patch.object(CS.C, "which", return_value="/bin/claude"), \
                mock.patch.object(CS.threading, "Thread"), \
                mock.patch("lfgcore.prreview._child_env", return_value=({}, None)):
            CS.resume("r1", self.root, self.SID)
        argv = popen.call_args.args[0]
        self.assertEqual(argv[argv.index("--model") + 1], "claude-haiku-5-5")


class StudioListTest(unittest.TestCase):
    A, B, C_, D = ("%08d-0000-0000-0000-000000000000" % i for i in (1, 2, 3, 4))
    LIVE_ONLY = "99999999-0000-0000-0000-000000000000"

    def setUp(self):
        import json
        from lfgcore import claudesess as CS
        from lfgcore import sessions as SS
        self.CS, self.SS, self.json = CS, SS, json
        self.home = tempfile.mkdtemp(prefix="lfg-sl-home-")
        self.lfg = tempfile.mkdtemp(prefix="lfg-sl-lfg-")
        self.projects = os.path.join(self.home, ".claude", "projects")
        self.live = {}
        for p in (mock.patch.object(CS.C, "HOME", self.home), mock.patch.object(CS.C, "LFG_HOME", self.lfg),
                  mock.patch.object(CS, "PROJECTS", self.projects), mock.patch.object(SS, "PROJECTS", self.projects),
                  mock.patch.object(CS, "_LIVE", self.live)):
            p.start()
            self.addCleanup(p.stop)
        self.repo1, self.repo2, self.loose = (os.path.realpath(tempfile.mkdtemp(prefix="lfg-sl-r-")) for _ in range(3))
        for r in (self.repo1, self.repo2):
            os.makedirs(os.path.join(r, ".git"))
        self.write(self.A, self.repo1, "feat-a", "terminal prompt", "cli")
        self.write(self.B, self.repo1, "feat-b", "studio prompt", "sdk-cli")
        self.write(self.C_, self.repo2, "main", "other repo prompt", "claude-desktop")
        self.write(self.D, self.loose, "", "loose prompt", "cli")
        idx = {self.B: {"lfg": True, "model": "opus", "title": "Studio chat"}}
        os.makedirs(os.path.join(self.lfg, "sessions"), exist_ok=True)
        with open(os.path.join(self.lfg, "sessions", "index.json"), "w") as f:
            f.write(json.dumps(idx))

    def write(self, sid, cwd, branch, prompt, entry):
        d = os.path.join(self.projects, cwd.replace("/", "-"))
        os.makedirs(d, exist_ok=True)
        ev = {"type": "user", "cwd": cwd, "gitBranch": branch, "entrypoint": entry,
              "timestamp": "2026-10-19T10:00:00Z", "message": {"role": "user", "content": prompt}}
        with open(os.path.join(d, sid + ".jsonl"), "w") as f:
            f.write(self.json.dumps(ev) + "\n")

    def stub(self, sid, state="idle", model="claude-x-9", rid="r1"):
        return mock.MagicMock(sid=sid, rid=rid, state=state, model=model, mode="default", title="Fresh chat",
                              branch="main", started=1.0)

    def rows(self, **kw):
        from lfgcore import studiolist as SL
        return {r["id"]: r for r in SL.listing("r1", self.repo1, **kw)["sessions"]}

    def test_kind_and_model_and_old_keys(self):
        rows = self.rows(scope="all")
        self.assertEqual(rows[self.A]["kind"], "terminal")
        self.assertEqual(rows[self.B]["kind"], "studio")
        self.assertEqual(rows[self.C_]["kind"], "desktop")
        self.assertEqual((rows[self.B]["model"], rows[self.B]["model_label"]), ("opus", "Opus"))
        self.assertEqual(rows[self.A]["state"], "saved")
        self.assertFalse(rows[self.A]["live"])
        self.assertEqual(rows[self.B]["title"], "Studio chat")
        for k in ("id", "name", "repo", "cwd", "resume", "starred", "hidden", "folder", "via_pr", "via_ticket",
                  "labels", "branch", "worktree", "modified", "prompts", "loose", "source", "skills", "issues"):
            self.assertIn(k, rows[self.B], k)
        self.assertEqual(rows[self.B]["source"], "lfg")
        self.assertEqual(rows[self.A]["source"], "terminal")

    def test_live_state_and_unknown_model(self):
        self.live[self.A] = self.stub(self.A, "needs-you", "claude-x-9")
        self.live[self.B] = self.stub(self.B, "starting", "")
        rows = self.rows(scope="all")
        self.assertEqual((rows[self.A]["state"], rows[self.A]["live"]), ("needs-you", True))
        self.assertEqual(rows[self.A]["model_label"], "x 9")
        self.assertEqual(rows[self.B]["state"], "working")
        self.assertEqual(rows[self.B]["model"], "opus")  # the index wins

    def test_scopes(self):
        self.assertEqual(set(self.rows()), {self.A, self.B})
        self.assertEqual(set(self.rows(scope="repo")), {self.A, self.B})
        self.assertEqual(set(self.rows(scope="all")), {self.A, self.B, self.C_, self.D})
        self.assertEqual(set(self.rows(scope="loose")), {self.D})

    def test_hidden(self):
        os.makedirs(os.path.join(self.lfg, "state"), exist_ok=True)
        with open(os.path.join(self.lfg, "state", "sessions.json"), "w") as f:
            f.write(self.json.dumps({"hidden": [self.A], "starred": [self.B], "folders": {"Epic": [self.B]},
                                     "labels": {self.B: ["bug"]}}))
        self.assertNotIn(self.A, self.rows(scope="all"))
        rows = self.rows(scope="all", hidden=True)
        self.assertTrue(rows[self.A]["hidden"])
        self.assertTrue(rows[self.B]["starred"])
        self.assertEqual(rows[self.B]["folder"], "Epic")
        self.assertEqual([x["name"] for x in rows[self.B]["labels"]], ["bug"])

    def test_live_studio_without_a_transcript_comes_first(self):
        from lfgcore import studiolist as SL
        self.live[self.LIVE_ONLY] = self.stub(self.LIVE_ONLY, "working")
        self.live["other"] = self.stub("other", "idle", rid="r2")
        out = SL.listing("r1", self.repo1)["sessions"]
        self.assertEqual(out[0]["id"], self.LIVE_ONLY)
        self.assertEqual((out[0]["kind"], out[0]["state"], out[0]["live"]), ("studio", "working", True))
        self.assertEqual(out[0]["model_label"], "x 9")
        self.assertNotIn("other", [r["id"] for r in out])

    def test_payload_keeps_the_old_keys(self):
        from lfgcore import studiolist as SL
        d = SL.listing("r1", self.repo1)
        for k in ("sessions", "group_info", "label_list", "models", "modes"):
            self.assertIn(k, d)

    def append(self, sid, cwd, *events):
        path = os.path.join(self.projects, cwd.replace("/", "-"), sid + ".jsonl")
        with open(path, "a") as f:
            f.write("\n".join(self.json.dumps(e) for e in events) + "\n")

    def test_model_skills_files_and_issues_come_from_a_fresh_transcript(self):
        self.append(self.A, self.repo1, {"type": "assistant", "cwd": self.repo1, "message": {
            "model": "claude-sonnet-5-5", "content": [
                {"type": "tool_use", "id": "t1", "name": "Edit", "input": {"file_path": self.repo1 + "/a.py"}},
                {"type": "tool_use", "id": "t2", "name": "Edit", "input": {"file_path": self.repo1 + "/b.py"}}]}},
                    {"type": "user", "cwd": self.repo1, "message": {"role": "user", "content": [
                        {"type": "tool_result", "tool_use_id": "t1", "content": "ok"},
                        {"type": "tool_result", "tool_use_id": "t2", "content": "ok"}]}})
        row = self.rows(scope="all")[self.A]
        self.assertEqual((row["model"], row["model_label"]), ("claude-sonnet-5-5", "Sonnet 5.5"))
        self.assertEqual(row["files"], 2)
        for k in ("skills", "issues"):
            self.assertIn(k, row)
        self.append(self.A, self.repo1, {"type": "assistant", "cwd": self.repo1, "message": {
            "model": "claude-haiku-5-5", "content": []}})
        self.assertEqual(self.rows(scope="all")[self.A]["model"], "claude-haiku-5-5")  # a changed file is re-read

    def test_a_scripted_session_is_background(self):
        sid = "55555555-0000-0000-0000-000000000000"
        self.write(sid, self.repo1, "main", "Read only. Call list_teams", "sdk-cli")
        row = self.rows(scope="all")[sid]
        self.assertEqual((row["kind"], row["source"]), ("background", "background"))

    def test_background_rows_are_capped_to_the_newest(self):
        from lfgcore import studiolist as SL
        ids = []
        for i in range(SL.BACKGROUND_ROWS + 5):
            sid = "%08d-1111-0000-0000-000000000000" % i
            self.write(sid, self.repo1, "main", "Read only. Call list_teams", "sdk-cli")
            path = os.path.join(self.projects, self.repo1.replace("/", "-"), sid + ".jsonl")
            os.utime(path, (2000000000 + i, 2000000000 + i))
            ids.append(sid)
        rows = self.rows(scope="all")
        background = [r for r in rows.values() if r["kind"] == "background"]
        self.assertEqual(len(background), SL.BACKGROUND_ROWS)
        self.assertEqual({r["id"] for r in background}, set(ids[5:]))  # the five oldest are dropped
        for sid in (self.A, self.B, self.C_, self.D):
            self.assertIn(sid, rows)


class ListPageTest(unittest.TestCase):
    """The Studio list page's row, menu and old addresses, run as the real app.js code in Node."""

    def run_js(self, start, end, script):
        import json
        import shutil
        import subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("node isn't installed")
        here = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugin", "lib", "lfgcore")
        with open(os.path.join(here, "ui_assets", "app.js")) as f:
            js = f.read()
        block = js[js.index(start):js.index(end)]
        out = subprocess.run([node, "-e", block + "\n" + script], capture_output=True, text=True, check=True).stdout
        return json.loads(out)

    def test_old_addresses_land_on_the_list_with_their_scope(self):
        script = """
const store = {}, localStorage = { getItem: k => store[k] ?? null, setItem: (k, v) => { store[k] = String(v); } };
const state = { repo: "r1" }, location = { hash: "" }, history = { replaceState: (a, b, h) => { location.hash = h; } };
const go = h => { location.hash = h; ssRedirect(); return [location.hash, store[SS_SCOPE_KEY], !!state.showHidden]; };
const out = {};
store["lfg.sessions.loose"] = "1"; out.stored = go("#sessions");          // the Sessions page's choice, read once
store["lfg.sessions.loose"] = ""; out.again = go("#sessions");             // already moved over: kept
out.all = go("#sessions/all");
out.hidden = go("#sessions?loose=1&hidden=1");
state.showHidden = false; out.studioAll = go("#studio/all");
out.open = go("#studio/0b1c");                                             // an open session is left alone
state.repo = ""; store[SS_SCOPE_KEY] = "repo"; out.norepo = ssScope();
console.log(JSON.stringify(out));
"""
        out = self.run_js("/* The Studio list's scope", "/* The Studio list: every session", script)
        self.assertEqual(out["stored"], ["#studio", "loose", False])
        self.assertEqual(out["again"], ["#studio", "loose", False])
        self.assertEqual(out["all"], ["#studio", "all", False])
        self.assertEqual(out["hidden"], ["#studio", "loose", True])
        self.assertEqual(out["studioAll"], ["#studio", "loose", False])
        self.assertEqual(out["open"], ["#studio/0b1c", "loose", False])
        self.assertEqual(out["norepo"], "all")

    def test_a_row_has_its_chips_open_and_the_menu_in_order(self):
        script = r"""
const esc = s => String(s ?? ""), icon = k => "", dot = t => "", ago = () => "now", homePath = p => p;
const money = v => "$" + v, groupPath = g => g, labelChips = () => "", skillRuns = () => "";
const unlockCmd = () => "lfg ui --unlock";
const strip = h => h.replace(/<[^>]+>/g, "|").split("|").map(x => x.trim()).filter(Boolean);
const menu = h => strip(h.slice(h.indexOf('<div class="sess-menu"')));
const chips = h => strip(h.slice(0, h.indexOf('<span class="sess-menu-wrap')));
const base = { id: "a", title: "Fix it", repo: "api", modified: "2020-01-01T00:00:00Z", resume: "claude -r a" };
const dflt = { model: "", model_label: "Claude Code default" };
const studio = sessRow({ ...base, ...dflt, kind: "studio", state: "working", live: true, folder: "Epic" },
  { unlocked: true });
const term = sessRow({ ...base, ...dflt, kind: "terminal", state: "saved", worktree: "fix", branch: "lee/fix",
  cost: 2, folder_exists: false }, { unlocked: true });
const ended = sessRow({ ...base, kind: "studio", state: "ended", live: true, model: "claude-opus-5-5",
  model_label: "Opus 5.5" }, { unlocked: false });
console.log(JSON.stringify({ studio: chips(studio), menu: menu(studio), term: chips(term), termMenu: menu(term),
  busyDelete: /data-sess-trash="a" disabled title="End it first"/.test(studio),
  termDelete: /data-sess-trash="a" title=/.test(term),
  lockedDelete: /data-sess-trash="a" disabled title="Locked/.test(ended), sid: /data-sid="a"/.test(studio),
  openHref: /href="#studio\/a">Open</.test(studio) }));
"""
        out = self.run_js("/* One session as a row", "/* The menu opens beside its button", script)
        self.assertEqual(out["studio"], ["☆", "Fix it", "Studio", "api", "Claude Code default", "working", "now",
                                         "Open"])
        self.assertEqual(out["menu"], ["Copy resume command", "What it changed", "Run a skill…", "Rules",
                                       "Remind it of my style", "Rename", "Change group", "Labels…", "Hide", "Delete"])
        # a terminal session with no known model has no model chip; worktree, branch, cost and a gone folder are meta
        self.assertEqual(out["term"], ["☆", "Fix it", "Terminal", "api", "idle", "now", "worktree", "fix", "·",
                                       "lee/fix", "· $2 ·", "its folder is gone", "Open"])
        self.assertIn("Add to a group…", out["termMenu"])
        self.assertTrue(out["busyDelete"])
        self.assertTrue(out["termDelete"])
        self.assertTrue(out["lockedDelete"])
        self.assertTrue(out["sid"])
        self.assertTrue(out["openHref"])


if __name__ == "__main__":
    unittest.main()
