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


if __name__ == "__main__":
    unittest.main()
