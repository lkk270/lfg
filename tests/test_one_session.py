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
        self.assertEqual(M.choices()[0]["label"], "Claude Code default")  # never names the settings model

    def test_shown_names_what_the_default_runs_on(self):
        from lfgcore import models as M
        self.assertEqual(M.shown("claude-haiku-5-5", "claude-sonnet-5-5"), "Haiku 5.5")  # a pick wins
        self.assertEqual(M.shown("", "claude-opus-5-5"), "Opus 5.5")  # the running model, not "default (...)"
        self.assertEqual(M.shown("", "claude-x-9"), "x 9")  # an unknown id, tidied
        self.assertEqual(M.shown("", ""), "Claude Code default")  # nothing known: the settings file is not trusted

    def test_note_says_what_the_default_runs_on(self):
        from lfgcore import models as M
        self.assertEqual(M.note("", "claude-opus-5-5"), "Running on Opus 5.5 (Claude Code's default)")
        self.assertEqual(M.note("", ""), "")
        self.assertEqual(M.note("claude-haiku-5-5", "claude-opus-5-5"), "")

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

    def test_live_set_model_default_waits_for_the_next_message(self):
        lv = self.live()
        lv._native_set_model = True  # even then: Claude Code's default has no name to send
        with mock.patch.object(self.CS, "_remember") as rem:
            lv.set_model("")
        self.assertEqual(rem.call_args.kwargs, {"model": None})
        self.assertEqual((lv.sent, lv.model, lv.model_pending), ([], None, True))

    def test_cs_set_model_default_on_a_running_studio(self):
        CS = self.CS
        lv = self.live()
        lv._native_set_model = True
        CS._LIVE[self.SID] = lv
        self.assertEqual(CS.set_model(self.SID, ""), {"id": self.SID, "model": ""})
        self.assertEqual((lv.model, lv.model_pending, lv.sent), (None, True, []))
        self.assertIsNone(CS._index()[self.SID]["model"])

    def test_session_action_sess_model(self):
        from lfgcore import settings as S
        from lfgcore import ui
        CS = self.CS
        CS._remember(self.SID, lfg=True, model="opus")
        self.assertEqual(ui.session_action("sess_model", {"id": self.SID, "model": ""}),
                         {"id": self.SID, "model": ""})
        self.assertIn("model", CS._index()[self.SID])
        self.assertIsNone(CS._index()[self.SID]["model"])  # Claude Code's default is stored as no model
        with self.assertRaises(S.Invalid) as cm:
            ui.session_action("sess_model", {"id": self.SID, "model": "nope"})
        self.assertEqual(str(cm.exception), "not a model")
        self.assertIsNone(CS._index()[self.SID]["model"])

    def test_session_action_sess_model_refused_while_working(self):
        from lfgcore import settings as S
        from lfgcore import ui
        self.CS._LIVE[self.SID] = self.live("working")
        with self.assertRaises(S.Invalid) as cm:
            ui.session_action("sess_model", {"id": self.SID, "model": "claude-haiku-5-5"})
        self.assertEqual(str(cm.exception), "Wait for the answer to finish, then change the model.")

    def test_set_model_needs_a_session_it_knows(self):
        CS = self.CS
        for sid in ("../x", "not-a-session", "22222222-2222-3333-4444-555555555555"):
            with self.assertRaises(CS.Invalid, msg=sid):
                CS.set_model(sid, "claude-haiku-5-5")
        self.assertEqual(CS._index(), {})  # nothing stored for them

    def test_detail_carries_the_chosen_model_its_label_and_the_list(self):
        CS = self.CS
        tr = os.path.join(CS.PROJECTS, "p")
        os.makedirs(tr)
        with open(os.path.join(tr, self.SID + ".jsonl"), "w") as f:
            f.write('{"type":"user","cwd":"%s","entrypoint":"cli","message":{"role":"user","content":"hi"}}\n'
                    % self.root)
            f.write('{"type":"assistant","cwd":"%s","message":{"model":"claude-sonnet-5-5","content":[]}}\n'
                    % self.root)
        d = CS.detail("r1", self.root, self.SID)
        self.assertEqual((d["model"], d["model_label"]), ("claude-sonnet-5-5", "Sonnet 5.5"))  # its last reply
        self.assertEqual([m["id"] for m in d["models"]], [""] + IDS)
        CS.set_model(self.SID, "opus")
        d = CS.detail("r1", self.root, self.SID)
        self.assertEqual((d["model"], d["model_label"]), ("opus", "Opus"))  # what you picked, for its next run
        CS.set_model(self.SID, "")
        d = CS.detail("r1", self.root, self.SID)
        self.assertEqual((d["model"], d["model_label"]), ("", "Sonnet 5.5"))  # what it ran on

    def test_where_carries_the_model_list(self):
        self.assertEqual([m["id"] for m in self.CS.where("r1", None)["models"]], [""] + IDS)


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

    def test_your_name_wins_over_the_claude_code_title(self):
        d = os.path.join(self.projects, self.repo1.replace("/", "-"))
        with open(os.path.join(d, self.A + ".jsonl"), "a") as f:
            f.write(self.json.dumps({"type": "custom-title", "customTitle": "cc title", "sessionId": self.A}) + "\n")
        self.assertEqual(self.rows(scope="all")[self.A]["title"], "cc title")
        self.SS.rename(self.A, "my name")
        self.SS.rename(self.B, "renamed studio")
        rows = self.rows(scope="all")
        self.assertEqual(rows[self.A]["title"], "my name")
        self.assertEqual(rows[self.B]["title"], "renamed studio")
        from lfgcore import claudesess as CS
        self.assertEqual(CS.detail("r1", self.repo1, self.A)["title"], "my name")

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

    def test_a_switch_shows_on_the_row(self):
        self.append(self.A, self.repo1, {"type": "assistant", "cwd": self.repo1, "message": {
            "model": "claude-sonnet-5-5", "content": []}})
        self.assertEqual(self.rows(scope="all")[self.A]["model_label"], "Sonnet 5.5")  # its last reply
        self.CS.set_model(self.A, "claude-haiku-5-5")  # for when it continues here
        self.assertEqual(self.rows(scope="all")[self.A]["model_label"], "Haiku 5.5")
        self.CS.set_model(self.A, "")
        self.assertEqual(self.rows(scope="all")[self.A]["model_label"], "Sonnet 5.5")
        settings = os.path.join(self.home, ".claude", "settings.json")
        with open(settings, "w") as f:
            f.write('{"model": "opus"}')
        self.CS.set_model(self.B, "")  # no reply yet: the settings model is never named
        self.assertEqual(self.rows(scope="all")[self.B]["model_label"], "Claude Code default")
        self.live[self.LIVE_ONLY] = self.stub(self.LIVE_ONLY, "working", "")
        self.assertEqual(self.rows()[self.LIVE_ONLY]["model_label"], "Claude Code default")

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

    def test_a_running_studio_cannot_go_to_the_trash(self):
        from lfgcore import settings as S
        from lfgcore import ui
        path = os.path.join(self.projects, self.repo1.replace("/", "-"), self.B + ".jsonl")
        os.utime(path, (1000000000, 1000000000))  # idle for years: only the running check can refuse it
        self.live[self.B] = self.stub(self.B, "idle")
        with self.assertRaises(S.Invalid) as cm:
            ui.save("session_trash", {"id": self.B})
        self.assertIn("End it first", str(cm.exception))
        self.assertTrue(os.path.exists(path))
        self.live[self.B].state = "ended"
        with mock.patch.object(self.SS.os, "rename") as mv:
            ui.save("session_trash", {"id": self.B})
        self.assertTrue(mv.called)

    def test_done_cleans_up_studios_and_background_runs_in_the_group(self):
        studio, run = "66666666-0000-0000-0000-000000000000", "77777777-0000-0000-0000-000000000000"
        wt = self.repo1 + ".worktrees/feat-z"  # gone already: the group and worktree come from the path
        self.write(studio, wt, "feat-z", "studio in a worktree", "sdk-cli")
        self.write(run, self.repo1, "feat-z", "Read only. Call list_teams", "sdk-cli")
        out = self.SS.group_cleanup(os.path.basename(self.repo1), "feat-z")
        self.assertEqual(set(out["sessions"]), {studio, run})
        self.assertEqual([w["path"] for w in out["worktrees"]], [wt])


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


class OneMenuTest(unittest.TestCase):
    """Task 5: the open session's header, its reply box and Where you left off's panel use the list row's menu."""

    BLOCKS = [("/* One session as a row", "/* The menu opens beside its button"),
              ("/* The panel for one session", "PAGES.continue = async arg"),
              ("/* Under an open session: a plain reply box", "/* Where a new session works"),
              ("/* The open session as the shared menu sees it", "function ssDetail(d)")]
    STUBS = r"""
const esc = s => String(s ?? ""), icon = k => "", dot = t => "", ago = () => "now", homePath = p => p;
const money = v => "$" + v, groupPath = g => g, labelChips = () => "", skillRuns = () => "";
const unlockCmd = () => "lfg ui --unlock", ssTagList = () => "", ssCtxHtml = () => "";
const ssWherePicker = () => "<select id=ss-where></select>";
const ssLive = st => ["working", "needs-you", "starting", "idle"].includes(st);
const SS_MODES = [["default", "Ask first", ""], ["acceptEdits", "Accept edits", ""], ["plan", "Plan only", ""]];
const store = {}, localStorage = { getItem: k => store[k] ?? null, setItem: (k, v) => { store[k] = String(v); } };
const state = { sess: { unlocked: true }, navSess: [] };
const strip = h => h.replace(/<[^>]+>/g, "|").split("|").map(x => x.trim()).filter(Boolean);
const menu = h => strip(h.slice(h.indexOf('<div class="sess-menu"'), h.indexOf("</div></span>")));
const ph = h => (h.match(/placeholder="([^"]*)"/) || [])[1];
const btn = h => (h.match(/id="ss-send">([^<]*)</) || [])[1];
"""

    def run_js(self, script):
        import json
        import shutil
        import subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("node isn't installed")
        here = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugin", "lib", "lfgcore")
        with open(os.path.join(here, "ui_assets", "app.js")) as f:
            js = f.read()
        code = "\n".join(js[js.index(a):js.index(b)] for a, b in self.BLOCKS)
        out = subprocess.run([node, "-e", self.STUBS + code + "\n" + script], capture_output=True, text=True,
                             check=True).stdout
        return json.loads(out)

    SHARED = ["Copy resume command", "What it changed", "Run a skill…", "Rules", "Remind it of my style", "Rename",
              "Change group", "Labels…", "Hide", "Delete"]

    def test_header_has_star_end_and_the_shared_menu_after_fork_compact_export(self):
        out = self.run_js(r"""
const studio = { id: "a", title: "Chat", source: "lfg", state: "working", cost: 1,
  row: { resume: "cd x && claude --resume a", folder: "Epic", starred: true } };
const term = { id: "b", title: "Term", source: "terminal", state: "saved", row: { resume: "r" } };
const h = ssHead(studio), t = ssHead(term);
state.sess.unlocked = false; const locked = ssHead(term);
console.log(JSON.stringify({ menu: menu(h), termMenu: menu(t),
  star: /class="star on"/.test(h), end: /data-ss-end/.test(h), termEnd: /data-ss-end/.test(t),
  busyDelete: /data-sess-trash="a" disabled title="End it first"/.test(h),
  termDelete: /data-sess-trash="b" title=/.test(t),
  oldMenu: /data-menu="(rename|resume)"|class="ss-menu"|data-ss-more/.test(h + t),
  rename: /data-ss-rename/.test(h), lockedRename: /data-ss-rename/.test(locked),
  live: studio.row.live, kind: studio.row.kind, termLive: term.row.live, kept: studio.row.starred,
  order: [h.indexOf("ss-cost"), h.indexOf('class="star'), h.indexOf("data-ss-end"), h.indexOf("data-sess-menu")] }));
""")
        self.assertEqual(out["menu"], ["Fork session", "Compact conversation", "Export as Markdown"] + self.SHARED)
        self.assertEqual(out["termMenu"][3:], self.SHARED[:6] + ["Add to a group…"] + self.SHARED[7:])
        self.assertTrue(out["star"])
        self.assertTrue(out["end"])
        self.assertFalse(out["termEnd"])
        self.assertTrue(out["busyDelete"])
        self.assertTrue(out["termDelete"])
        self.assertFalse(out["oldMenu"])
        self.assertTrue(out["rename"])
        self.assertFalse(out["lockedRename"])
        self.assertEqual([out["live"], out["kind"], out["termLive"], out["kept"]], [True, "studio", False, True])
        self.assertEqual(out["order"], sorted(out["order"]))  # cost, star, End, then the menu
        self.assertNotIn(-1, out["order"])

    def test_reply_box_per_state(self):
        out = self.run_js(r"""
const c = o => { const h = ssComposer(o); return [ph(h), btn(h), /data-seg="mode"/.test(h), /ss-where/.test(h)]; };
console.log(JSON.stringify({ live: c({ live: true, studio: true }), livetTerm: c({ live: true }),
  savedStudio: c({ studio: true }), savedTerm: c({}), fresh: c({ isNew: true }),
  fork: c({ live: true, studio: true, fork: { at: "", label: "" } }) }));
""")
        msg = "Message this studio. / for skills, @ for files"
        self.assertEqual(out["live"], [msg, "Send", True, False])
        self.assertEqual(out["livetTerm"], [msg, "Send", True, False])
        self.assertEqual(out["savedStudio"], [msg, "Send", True, False])
        self.assertEqual(out["savedTerm"], ["Write to continue this session here", "Continue here", False, False])
        self.assertEqual(out["fresh"], ["Describe the task. / for skills, @ for files and folders", "Start", True,
                                        True])
        self.assertEqual(out["fork"][:2], ["What should the new session do?", "Start fork"])
        self.assertFalse(out["fork"][3])

    MODELS = r"""
const MODELS = [{ id: "", label: "Claude Code default" }, { id: "claude-fable-5-2", label: "Fable 5.2" },
  { id: "claude-mythos-5-2", label: "Mythos 5.2" }, { id: "claude-haiku-5-5", label: "Haiku 5.5" }];
"""

    def test_header_model_button(self):
        out = self.run_js(self.MODELS + r"""
const pick = h => {
  const b = (h.match(/<button[^>]*data-ss-model[^>]*>/) || [""])[0];
  const list = h.slice(h.indexOf('class="sess-menu ss-model-menu"'));
  const opts = [...list.matchAll(/data-model="([^"]*)"[^>]*>([^<]*)</g)].map(m => m[2]);
  const cur = [...list.matchAll(/class="cur"[^>]*data-model="([^"]*)"/g)].map(m => m[1]);
  return { label: (h.match(/data-ss-model[^>]*>([^<]*)</) || [])[1], off: / disabled/.test(b),
    title: (b.match(/title="([^"]*)"/) || [])[1], opts, cur };
};
const one = (o, more) => ssHead(Object.assign({ id: "a", title: "Chat", source: "lfg", state: "idle", cost: 1,
  model: "claude-fable-5-2", model_label: "Fable 5.2", models: MODELS, row: { resume: "r" } }, o));
const h = one({});
const out = { idle: pick(h), order: [h.indexOf("data-ss-model"), h.indexOf("ss-cost")],
  working: pick(one({ state: "working" })), starting: pick(one({ state: "starting" })),
  needs: pick(one({ state: "needs-you" })), asking: pick(one({ pending: [{ id: "p" }] })),
  dflt: pick(one({ model: "", model_label: "Opus 5.5", model_note: "Running on Opus 5.5 (Claude Code's default)" })),
  dfltNone: pick(one({ model: "", model_label: "Claude Code default", model_note: "" })),
  legacy: pick(one({ model: "opus", model_label: "Opus" })),
  term: pick(one({ source: "terminal", state: "saved", model: "claude-haiku-5-5", model_label: "Haiku 5.5" })),
  none: /data-ss-model/.test(one({ models: undefined })) };
state.sess.unlocked = false; out.locked = pick(one({}));
console.log(JSON.stringify(out));
""")
        busy = "Wait for the answer to finish, then change the model."
        labels = ["Claude Code default", "Fable 5.2", "Mythos 5.2", "Haiku 5.5"]
        self.assertEqual(out["idle"]["label"], "Fable 5.2 ▾")
        self.assertFalse(out["idle"]["off"])
        self.assertEqual(out["idle"]["opts"], labels)
        self.assertEqual(out["idle"]["cur"], ["claude-fable-5-2"])
        self.assertNotIn(-1, out["order"])
        self.assertLess(out["order"][0], out["order"][1])  # just left of the cost
        for k in ("working", "starting", "needs", "asking"):
            self.assertTrue(out[k]["off"], k)
            self.assertEqual(out[k]["title"], busy, k)
        # the same words as the row: what the default runs on, never just "Default"
        self.assertEqual((out["dflt"]["label"], out["dflt"]["cur"]), ("Opus 5.5 ▾", [""]))
        self.assertIn("Running on Opus 5.5 (Claude Code's default)", out["dflt"]["title"])
        self.assertEqual(out["dfltNone"]["label"], "Claude Code default ▾")
        self.assertNotIn("Running on", out["dfltNone"]["title"])
        # an older alias names the button and matches no option; the list is still whole
        self.assertEqual((out["legacy"]["label"], out["legacy"]["cur"], out["legacy"]["opts"]), ("Opus ▾", [], labels))
        self.assertFalse(out["term"]["off"])
        self.assertIn("continue", out["term"]["title"])
        self.assertTrue(out["locked"]["off"])
        self.assertTrue(out["locked"]["title"].startswith("Locked"))
        self.assertFalse(out["none"])

    def test_new_studio_model_select(self):
        out = self.run_js(self.MODELS + r"""
const sel = h => { const s = (h.match(/<select[^>]*id="ss-model"[\s\S]*?<\/select>/) || [""])[0];
  return { opts: [...s.matchAll(/<option value="([^"]*)"[^>]*>([^<]*)</g)].map(m => [m[1], m[2]]),
    on: (s.match(/value="([^"]*)" selected/) || [null, null])[1] }; };
const out = { fresh: sel(ssComposer({ isNew: true, models: MODELS })) };
store["lfg.ss.model"] = "claude-haiku-5-5"; out.kept = sel(ssComposer({ isNew: true, models: MODELS }));
store["lfg.ss.model"] = "claude-gone-1"; out.gone = sel(ssComposer({ isNew: true, models: MODELS }));
out.reply = /id="ss-model"/.test(ssComposer({ live: true, studio: true, models: MODELS }));
const h = ssComposer({ isNew: true, models: MODELS });
out.order = [h.indexOf('data-seg="mode"'), h.indexOf('id="ss-model"'), h.indexOf('id="ss-send"')];
console.log(JSON.stringify(out));
""")
        self.assertEqual(out["fresh"]["opts"], [["", "Claude Code default"], ["claude-fable-5-2", "Fable 5.2"],
                                                ["claude-mythos-5-2", "Mythos 5.2"], ["claude-haiku-5-5", "Haiku 5.5"]])
        self.assertEqual(out["fresh"]["on"], "")
        self.assertEqual(out["kept"]["on"], "claude-haiku-5-5")
        self.assertEqual(out["gone"]["on"], "")  # a remembered model no longer listed falls back to the default
        self.assertFalse(out["reply"])
        self.assertEqual(out["order"], sorted(out["order"]))  # next to Ask / Auto / Plan, before Start
        self.assertNotIn(-1, out["order"])

    def test_where_you_left_off_panel_uses_the_shared_menu(self):
        out = self.run_js(r"""
const s = { id: "c", name: "Fix it", activity: "working", modified: "", resume: "r", folder: "Epic", via_ticket: true };
state.navSess = [{ id: "c", kind: "studio", live: true, state: "working" }];
const h = contPanel(s, true);
console.log(JSON.stringify({ menu: menu(h), loose: (h.match(/class="btn small"[^>]*data-sess-/g) || []).length,
  open: /href="#studio\/c"[^>]*>Open</.test(h), star: /data-sess-star/.test(h), group: /in Epic \(via ticket\)/.test(h),
  busyDelete: /data-sess-trash="c" disabled title="End it first"/.test(h) }));
""")
        self.assertEqual(out["menu"], self.SHARED)
        self.assertEqual(out["loose"], 0)
        self.assertTrue(out["open"])
        self.assertTrue(out["star"])
        self.assertTrue(out["group"])
        self.assertTrue(out["busyDelete"])


def run_app_js(test, blocks, script, pre=""):
    """Runs `pre`, then slices of app.js (each from its start marker to its end marker), then `script` in Node;
    returns the JSON the script prints."""
    import json
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        test.skipTest("node isn't installed")
    here = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugin", "lib", "lfgcore")
    with open(os.path.join(here, "ui_assets", "app.js")) as f:
        js = f.read()
    code = "\n".join(js[js.index(a):js.index(b, js.index(a))] for a, b in blocks)
    cp = subprocess.run([node, "-e", pre + "\n" + code + "\n" + script], capture_output=True, text=True)
    if cp.returncode:
        test.fail(cp.stderr[-2000:])
    return json.loads(cp.stdout)


class ListRedrawTest(unittest.TestCase):
    """The Studio list redraws without asking the server for more than it needs."""

    def test_search_filters_without_the_server_and_the_drawn_list_does_not_depend_on_it(self):
        out = run_app_js(self, [("/* The Studio list: every session", '/* "Done" on a ticket')], r"""
const state = {}, store = {}, localStorage = { getItem: k => store[k] ?? null, setItem: (k, v) => { store[k] = v; } };
const esc = s => String(s ?? ""), plural = (k, w) => k + " " + w, n = x => x, ago = () => "now", homePath = p => p;
const ssScope = () => "repo", repoName = () => "api", unlockCmd = () => "", empty = (a, b) => a;
const liveLabelFilter = () => [], labelHit = () => true, sessStarredOn = () => false, sessStarredCount = () => 0;
const sessShown = (all, hit) => all.filter(hit), groupTree = () => [], treeHtml = () => "", groupTags = () => "";
const labelFilterChips = () => "", ssLive = () => false, sessBusy = () => false, sessRow = s => `<row ${s.id}>`;
const sessEmptyText = () => ["none", ""];
const now = new Date().toISOString();
const list = { sessions: [
  { id: "a", title: "Fix the export", repo: "api", branch: "lee/ato-1-export", modified: now },
  { id: "b", title: "Rename things", repo: "api", branch: "main", ticket: "ATO-2", modified: now }] };
const plain = ssList(list, true, {});
state.ssFind = "export"; const searched = ssList(list, true, {});
const noBox = h => h.replace(/id="ss-find"[^>]*>/, "");  // the box itself carries what was typed
console.log(JSON.stringify({ same: noBox(plain) === noBox(searched), rows: (plain.match(/<row /g) || []).length,
  hits: list.sessions.filter(s => ssMatch(s, "export")).map(s => s.id),
  words: list.sessions.filter(s => ssMatch(s, "ato-2 RENAME")).map(s => s.id),
  all: list.sessions.filter(s => ssMatch(s, "  ")).map(s => s.id),
  count: /data-ss-count/.test(plain), nomatch: /data-ss-nomatch[^>]*hidden/.test(plain) }));
""")
        self.assertTrue(out["same"])  # typing redraws nothing: the rows are filtered where they are
        self.assertEqual(out["rows"], 2)
        self.assertEqual(out["hits"], ["a"])
        self.assertEqual(out["words"], ["b"])
        self.assertEqual(out["all"], ["a", "b"])
        self.assertTrue(out["count"])
        self.assertTrue(out["nomatch"])

    def test_a_soft_redraw_keeps_the_worktrees_it_read(self):
        out = run_app_js(self, [("PAGES.studio = async", "/* tags: one look")], pre="const PAGES = {};", script=r"""
const state = { repo: "r1" }, calls = [];
const api = async what => {
  calls.push(what);
  if (what === "studio") return { sessions: [] };
  return what === "skillruns" ? { runs: [] } : { branch: "main", n: calls.length };
};
const ssScope = () => "repo", isUnlocked = async () => true, ssList = () => "", ssWorktrees = () => "";
const pageTimer = () => {}, location = { hash: "#studio" };
const ssRunsBySession = () => ({}), ssRunsBusy = () => false, ssRunsTick = () => {};
let ssWhereStale = false;
(async () => {
  const out = {};
  const where = async soft => {
    calls.length = 0; await PAGES.studio("", { soft });
    return calls.filter(c => c === "studio_where").length;
  };
  out.first = await where(false);
  out.soft = await where(true);
  const kept = state.sess.where;
  out.again = await where(true);
  out.kept = state.sess.where === kept;
  state.fresh = true; out.fresh = await where(true); state.fresh = false;  // Refresh, or the 10-minute refresh
  ssWhereStale = true; out.stale = await where(true);                      // after a merge or a removed worktree
  out.staleAfter = await where(true);
  state.repo = "r2"; out.otherRepo = await where(true);
  out.button = await where(false);
  console.log(JSON.stringify(out));
})();
""")
        self.assertEqual(out, {"first": 1, "soft": 0, "again": 0, "kept": True, "fresh": 1, "stale": 1,
                               "staleAfter": 0, "otherRepo": 1, "button": 1})


class OpenSessionPollTest(unittest.TestCase):
    """The open session's poll: a poll still in flight when the page was drawn again does nothing."""

    def test_a_poll_from_a_replaced_page_does_not_touch_the_header(self):
        import json
        import shutil
        import subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("node isn't installed")
        here = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugin", "lib", "lfgcore")
        with open(os.path.join(here, "ui_assets", "app.js")) as f:
            js = f.read()
        start = js.index("  async function refresh() {\n    clearTimeout(ssPoll);")
        body = js[start:js.index("  if (ssLive(d.state)) ssPoll = setTimeout(refresh, 1200);", start)]
        script = r"""
let ssPoll = null, sig = "old", heads = [];
const location = { hash: "#studio/a" }, setTimeout = () => 0, clearTimeout = () => {};
const conv = { classList: { toggle() {} }, scrollTop: 0, scrollHeight: 0 }, head = {}, send = null;
const morph = (el, html) => { if (el === head) heads.push(html); }, ssConv = () => "", ssHead = x => x.row.group;
const wireConv = () => {}, wireHead = () => {}, wireOut = () => {}, loadCtx = () => {}, drawAct = () => {};
const atBottom = () => false, busyBg = () => false, ssLive = () => false, ssSendLabel = () => "";
const sigOf = n => n.state;
let answer; const api = () => new Promise(r => { answer = r; });
const d = { state: "idle", row: { group: "old group" } }, S = { id: "a", d };
const state = { sess: S };
""" + body + r"""
(async () => {
  const p = refresh();
  state.sess = { id: "a", d: { state: "idle", row: { group: "new group" } } };  // Change group soft-routed meanwhile
  answer({ state: "working" }); await p;
  const out = { replaced: heads.slice(), oldRow: d.row.group, oldState: d.state };
  state.sess = S; heads = []; const q = refresh(); answer({ state: "ended" }); await q;
  out.same = heads.slice();
  console.log(JSON.stringify(out));
})();
"""
        out = json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(out["replaced"], [])  # no stale header drawn
        self.assertEqual((out["oldRow"], out["oldState"]), ("old group", "idle"))
        self.assertEqual(out["same"], ["old group"])  # a poll for the page still shown draws as before


class SessionRowOfTest(unittest.TestCase):
    """The open session's header reads its list settings once, from sessions.row_of."""

    SID = "00000042-0000-0000-0000-000000000000"

    def setUp(self):
        import json
        from lfgcore import claudesess as CS
        from lfgcore import sessions as SS
        self.CS, self.SS = CS, SS
        home, lfg = tempfile.mkdtemp(prefix="lfg-ro-home-"), tempfile.mkdtemp(prefix="lfg-ro-lfg-")
        projects = os.path.join(home, ".claude", "projects")
        for p in (mock.patch.object(CS.C, "HOME", home), mock.patch.object(CS.C, "LFG_HOME", lfg),
                  mock.patch.object(CS, "PROJECTS", projects), mock.patch.object(SS, "PROJECTS", projects),
                  mock.patch.object(CS, "_LIVE", {})):
            p.start()
            self.addCleanup(p.stop)
        self.repo = os.path.realpath(tempfile.mkdtemp(prefix="lfg-ro-r-"))
        os.makedirs(os.path.join(self.repo, ".git"))
        d = os.path.join(projects, self.repo.replace("/", "-"))
        os.makedirs(d)
        ev = {"type": "user", "cwd": self.repo, "gitBranch": "feat", "entrypoint": "cli",
              "timestamp": "2026-10-19T10:00:00Z", "message": {"role": "user", "content": "fix the export"}}
        with open(os.path.join(d, self.SID + ".jsonl"), "w") as f:
            f.write(json.dumps(ev) + "\n")

    def test_row_carries_star_group_labels_and_resume_only_when_asked(self):
        self.SS.star(self.SID)
        self.SS.make_group("Epic")
        self.SS.file_into(self.SID, "Epic")
        self.SS.set_labels(self.SID, ["urgent"])
        d = self.CS.detail("r1", self.repo, self.SID, row=True)
        row = d["row"]
        self.assertTrue(row["starred"])
        self.assertFalse(row["hidden"])
        self.assertEqual(row["folder"], "Epic")
        self.assertEqual([x["name"] for x in row["labels"]], ["urgent"])
        self.assertIn("claude --resume " + self.SID, row["resume"])
        self.assertIn("Epic", d["group_info"])
        self.assertEqual([x["name"] for x in d["label_list"]], ["urgent"])
        self.assertNotIn("row", self.CS.detail("r1", self.repo, self.SID))  # a refresh does not pay for it

    def test_no_transcript_yet(self):
        row = self.SS.row_of("00000043-0000-0000-0000-000000000000")
        self.assertEqual((row["resume"], row["folder"], row["starred"]), ("", "", False))


if __name__ == "__main__":
    unittest.main()
