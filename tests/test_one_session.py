"""Tests for the one-session concept: the shared model list, and what builds on it."""
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


if __name__ == "__main__":
    unittest.main()
