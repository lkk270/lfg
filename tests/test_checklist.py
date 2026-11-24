"""Studio notes and the pinned checklist (lfgcore.checklist): storage, the `lfg checklist` command, dashboard views."""
import contextlib
import io
import os
import sys
import tempfile
import unittest

os.environ.setdefault("LFG_HOME", tempfile.mkdtemp(prefix="lfg-test-home-"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugin", "lib"))

SID = "aaaaaaaa-1111-2222-3333-444444444444"
CL = C = None


def _load():
    """lfgcore, imported when a test runs: test_core sets LFG_HOME by then, whatever order the files load in."""
    global CL, C
    from lfgcore import checklist as CL_
    from lfgcore import common as C_
    CL, C = CL_, C_


class StoreTest(unittest.TestCase):
    def setUp(self):
        _load()
        self.home = tempfile.mkdtemp(prefix="lfg-cl-")
        self.old = C.LFG_HOME
        C.LFG_HOME = self.home

    def tearDown(self):
        C.LFG_HOME = self.old

    def test_empty_session_reads_empty(self):
        d = CL.get(SID)
        self.assertEqual(d["notes"], "")
        self.assertEqual(d["checklist"]["items"], [])

    def test_set_items_numbers_them_c1_to_cn(self):
        d = CL.set_items(SID, ["a", "b", "c"], title="Before merge")
        self.assertEqual([i["id"] for i in d["checklist"]["items"]], ["c1", "c2", "c3"])
        self.assertEqual(d["checklist"]["title"], "Before merge")

    def test_mark_by_id_and_by_position(self):
        CL.set_items(SID, ["a", "b"])
        CL.mark(SID, "c1", True, "you")
        d = CL.mark(SID, "2", True, "claude")
        done = {i["id"]: (i["done"], i["by"]) for i in d["checklist"]["items"]}
        self.assertEqual(done, {"c1": (True, "you"), "c2": (True, "claude")})

    def test_unknown_item_raises_value_error(self):
        CL.set_items(SID, ["a"])
        with self.assertRaises(ValueError) as cm:
            CL.mark(SID, "99", True, "you")
        self.assertIn("No item 99", str(cm.exception))

    def test_added_ids_are_not_reused_after_remove(self):
        CL.set_items(SID, ["a", "b"])
        CL.remove(SID, "c2")
        d = CL.add(SID, "c", "you")
        self.assertEqual([i["id"] for i in d["checklist"]["items"]], ["c1", "c3"])

    def test_two_writers_keep_both_changes(self):
        CL.set_items(SID, ["a", "b"])
        CL.mark(SID, "c1", True, "you")
        d = CL.add(SID, "c", "claude")
        self.assertTrue(d["checklist"]["items"][0]["done"])
        self.assertEqual(len(d["checklist"]["items"]), 3)

    def test_notes_round_trip(self):
        CL.set_notes(SID, "remember this")
        self.assertEqual(CL.get(SID)["notes"], "remember this")

    def test_edit_move_and_clear_done(self):
        CL.set_items(SID, ["a", "b", "c"])
        CL.edit(SID, "c1", "A", "you")
        CL.mark(SID, "c2", True, "you")
        CL.move(SID, "c3", 0)
        d = CL.clear_done(SID)
        self.assertEqual([i["text"] for i in d["checklist"]["items"]], ["c", "A"])

    def test_limits(self):
        with self.assertRaises(ValueError):
            CL.set_items(SID, ["x" * 501])
        with self.assertRaises(ValueError):
            CL.set_items(SID, ["x"] * 201)


if __name__ == "__main__":
    unittest.main()


class CliTest(unittest.TestCase):
    def setUp(self):
        _load()
        self.old = (C.LFG_HOME, os.environ.pop("LFG_SESSION_ID", None))
        C.LFG_HOME = tempfile.mkdtemp(prefix="lfg-cl-")

    def tearDown(self):
        C.LFG_HOME = self.old[0]
        os.environ.pop("LFG_SESSION_ID", None)
        if self.old[1]:
            os.environ["LFG_SESSION_ID"] = self.old[1]

    def run_cli(self, *argv):
        from lfgcore import cli
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(["checklist", *argv])
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def test_cli_set_then_done_prints_the_list(self):
        os.environ["LFG_SESSION_ID"] = SID
        self.assertEqual(self.run_cli("set", "first", "second")[0], 0)
        code, out, _ = self.run_cli("done", "1")
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "[x] 1. first\n[ ] 2. second")
        self.assertEqual(CL.get(SID)["checklist"]["items"][0]["by"], "claude")

    def test_cli_without_session_exits_1_with_message(self):
        code, _, err = self.run_cli("show")
        self.assertEqual(code, 1)
        self.assertIn("No session", err)

    def test_cli_done_unknown_item_exits_1_and_changes_nothing(self):
        CL.set_items(SID, ["a"])
        code, _, err = self.run_cli("done", "99", "--session", SID)
        self.assertEqual(code, 1)
        self.assertIn("No item 99", err)
        self.assertFalse(CL.get(SID)["checklist"]["items"][0]["done"])

    def test_studio_child_gets_the_session_id_and_the_hint(self):
        env = {}
        extra = CL.setup(env, SID)
        self.assertEqual(env["LFG_SESSION_ID"], SID)
        self.assertEqual(extra[0], "--append-system-prompt")
        self.assertIn("checklist set", extra[1])


class DashboardTest(unittest.TestCase):
    def setUp(self):
        _load()
        self.old = C.LFG_HOME
        C.LFG_HOME = tempfile.mkdtemp(prefix="lfg-cl-")

    def tearDown(self):
        C.LFG_HOME = self.old

    def test_view_returns_empty_for_new_session(self):
        from lfgcore import ui
        d = ui.api("session_notes", {"id": [SID]})
        self.assertEqual(d["checklist"]["items"], [])

    def test_save_done_then_view_shows_it_ticked_by_you(self):
        from lfgcore import ui
        ui.save("checklist_set", {"id": SID, "items": ["a", "b"]})
        ui.save("checklist_done", {"id": SID, "item": "c2", "on": True})
        items = ui.api("session_notes", {"id": [SID]})["checklist"]["items"]
        self.assertEqual([(i["done"], i["by"]) for i in items], [(False, "you"), (True, "you")])

    def test_bad_item_is_refused_with_a_message(self):
        from lfgcore import settings as S
        from lfgcore import ui
        with self.assertRaises(S.Invalid) as cm:
            ui.save("checklist_done", {"id": SID, "item": "c9"})
        self.assertIn("No item c9", str(cm.exception))


class SidebarHtmlTest(unittest.TestCase):
    """The sidebar's markup, run as the real app.js code in Node."""

    def run_js(self, script):
        import json
        import shutil
        import subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("node isn't installed")
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, "plugin", "lib", "lfgcore", "ui_assets", "app.js")) as f:
            js = f.read()
        block = js[js.index("/* The Studio sidebar"):js.index("function ssDetail(")]
        stubs = "const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/\"/g, '&quot;');\n"
        out = subprocess.run([node, "-e", stubs + block + "\n" + script], capture_output=True, text=True,
                             check=True).stdout
        return json.loads(out)

    def test_side_html_shows_progress_and_ticked_items(self):
        html = self.run_js('const c = {notes: "n", checklist: {items: [{id: "c1", text: "a", done: true}, '
                           '{id: "c2", text: "b", done: false}, {id: "c3", text: "c", done: false}]}};\n'
                           "console.log(JSON.stringify(ssSideHtml(c)));")
        self.assertIn("1 of 3", html)
        self.assertRegex(html, r'data-ck="c1"[^>]*checked')
        self.assertNotRegex(html, r'data-ck="c2"[^>]*checked')

    def test_side_html_empty_has_add_box_and_notes(self):
        html = self.run_js("console.log(JSON.stringify(ssSideHtml({notes: '', checklist: {items: []}})));")
        self.assertIn("data-ck-add", html)
        self.assertIn("data-notes", html)
        self.assertNotIn("of 0", html)

    def test_side_html_escapes_text(self):
        html = self.run_js('console.log(JSON.stringify(ssSideHtml({notes: "<b>x</b>", checklist: {items: '
                           '[{id: "c1", text: "<i>a</i>", done: false}]}})));')
        self.assertNotIn("<i>a</i>", html)
        self.assertNotIn("<b>x</b>", html)
