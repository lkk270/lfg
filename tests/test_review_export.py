"""Download a PR review as Markdown: the text, what it leaves out, and the file name (app.js code, run in Node)."""
import json
import os
import shutil
import subprocess
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ReviewExportTest(unittest.TestCase):
    def run_js(self, script):
        node = shutil.which("node")
        if not node:
            self.skipTest("node isn't installed")
        with open(os.path.join(HERE, "plugin", "lib", "lfgcore", "ui_assets", "app.js")) as f:
            js = f.read()
        block = js[js.index("const copyMsg = "):js.index("async function prImport(")]
        stubs = ("const PRIOR = {}, DELIVERS = {}, ABOUT = {};\n")
        out = subprocess.run([node, "-e", stubs + block + "\n" + script], capture_output=True, text=True,
                             check=True).stdout
        return json.loads(out)

    REC = ('const rec = {repo: "lkk270/lfg", number: 12, title: "T", url: "u", passes: []};\n'
           'const mk = (id, title, status) => ({id, title, severity: "major", status, file: "a.py", line: 3});\n')

    def test_export_leaves_out_dropped_findings(self):
        text = self.run_js(self.REC + 'const p = {n: 1, head_sha: "abc", findings: [mk("1.1", "Keep me", "keep"), '
                           'mk("1.2", "Drop me", "drop")]}; rec.passes = [p];\n'
                           "console.log(JSON.stringify(prExportText(rec, p)));")
        self.assertIn("Keep me", text)
        self.assertNotIn("Drop me", text)

    def test_export_with_every_finding_dropped_says_none_open(self):
        text = self.run_js(self.REC + 'const p = {n: 1, head_sha: "abc", findings: [mk("1.1", "Drop me", "drop")]}; '
                           "rec.passes = [p];\nconsole.log(JSON.stringify(prExportText(rec, p)));")
        self.assertIn("No open findings.", text)

    def test_export_file_name(self):
        name = self.run_js(self.REC + "console.log(JSON.stringify(prExportName(rec, {n: 2})));")
        self.assertEqual(name, "lkk270-lfg-12-review-pass2.md")


if __name__ == "__main__":
    unittest.main()
