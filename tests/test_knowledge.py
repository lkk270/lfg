"""Shared repo knowledge (lfgcore.knowledge): node files <-> the repo's dev-graph branch. The sync tests run the real
`omnigraph` CLI against a throwaway store (CI installs it the way the Knowledge pack does)."""
import importlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("LFG_HOME", tempfile.mkdtemp(prefix="lfg-test-home-"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "plugin", "lib"))

C = importlib.import_module("lfgcore.common")
K = importlib.import_module("lfgcore.teamknowledge")

OTHER = [t for t in K.ALL_TYPES if t not in ("Decision", "Learning", "Component", "Issue", "PR")]
SCHEMA = """
node Decision { slug: String @key
 title: String
 decision: String
 status: enum(proposed, accepted, rejected, superseded)
 createdAt: Date }
node Learning { slug: String @key
 title: String
 body: String? }
node Component { slug: String @key
 name: String }
node Issue { slug: String @key
 title: String }
node PR { slug: String @key
 title: String }
""" + "".join("node %s { slug: String @key }\n" % t for t in OTHER) + """
edge LearningAboutComponent: Learning -> Component
edge DecisionAppliesToComponent: Decision -> Component
edge DecisionEmergedFromIssue: Decision -> Issue
edge PrTouchesComponent: PR -> Component
"""


def dec(slug, title="Files are the master", links=()):
    return {"type": "Decision", "slug": slug, "links": sorted([list(x) for x in links]),
            "data": {"slug": slug, "title": title, "decision": "Rebuild the graph from files.\n\nSecond line.",
                     "status": "accepted", "createdAt": "2026-10-18"}}


class FileFormatTest(unittest.TestCase):
    def test_round_trip_keeps_fields_body_and_links(self):
        rec = dec("dec-a", title="Ünïcode: \"quoted\"", links=[("DecisionAppliesToComponent", "cmp-core")])
        text = K.render(rec)
        self.assertIn("\n---\nRebuild the graph from files.\n\nSecond line.\n", text)  # the body reads as prose
        self.assertEqual(K.parse(text), rec)
        self.assertEqual(K.parse(text.rstrip("\n") + "\n"), rec)

    def test_rejects_what_is_not_a_node_file(self):
        for bad in ("no header", "---\ntype: \"Decision\"\n", "---\ntype: \"Actor\"\nslug: \"a\"\n---\n",
                    "---\ntype: \"Decision\"\nslug \"x\"\n---\n"):
            with self.assertRaises(ValueError):
                K.parse(bad)

    def test_only_free_text_issues_are_shared(self):
        self.assertTrue(K.shared("Issue", "iss-fix-login-3f2a"))
        self.assertFalse(K.shared("Issue", "acme-123"))
        self.assertFalse(K.shared("Actor", "lee"))
        self.assertTrue(K.shared("Learning", "lrn-x"))

    def test_unsafe_slug_is_never_a_path(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        with self.assertRaises(ValueError):
            K.write_file(root, dec("../../x"))


class MigrateTest(unittest.TestCase):
    """The osi case: one run started before the repo had a remote and finished after, so it sits under two ids."""

    def setUp(self):
        # a `.lfg/` line in the user's own global gitignore would look like the old exclude line
        env = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": os.devnull})
        env.start()
        self.addCleanup(env.stop)
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="osi-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        subprocess.run(["git", "init", "-q", "-b", "main", self.root], check=True)
        self.no_remote = C.repo_id(self.root)
        subprocess.run(["git", "remote", "add", "origin", "https://example.com/osi.git"], cwd=self.root, check=True)
        self.with_remote = C.repo_id(self.root)
        self.assertNotEqual(self.no_remote, self.with_remote)
        for rid in (self.no_remote, self.with_remote):
            self.addCleanup(shutil.rmtree, C.lfg_path("runs", rid), True)
            self.addCleanup(shutil.rmtree, C.lfg_path("repos", rid), True)
        run = "20261017-1518-init"
        old = C.lfg_path("runs", self.no_remote, run)
        new = C.lfg_path("runs", self.with_remote, run)
        C.write_json(os.path.join(old, "run.json"), {"run_id": run, "repo_id": self.no_remote, "stage": "plan"})
        C.write_text(os.path.join(old, "01-brief.md"), "brief")
        C.write_json(os.path.join(new, "run.json"), {"run_id": run, "repo_id": self.no_remote, "stage": "done"})
        C.write_text(os.path.join(new, "PR_BODY.md"), "body")
        os.utime(os.path.join(old, "run.json"), (1, 1))  # the copy under the old id is the older one
        C.write_text(C.lfg_path("runs", self.with_remote, "CURRENT"), run + "\n")
        C.write_text(C.lfg_path("repos", self.no_remote, "docs", "GLOSSARY.md"), "old terms")
        C.write_text(C.lfg_path("repos", self.with_remote, "docs", "GLOSSARY.md"), "new terms")
        C.write_json(C.lfg_path("repos", self.with_remote, "commands.json"), {"test": "go test ./..."})
        C.write_json(C.lfg_path("repos", self.with_remote, "shipcheck-history.json"), {"size": 1})
        self.run_id = run

    def test_session_start_says_the_current_run_is_still_in_the_old_place(self):
        from lfgcore import hooks as H
        self.assertEqual(K.legacy_current(self.root), self.run_id)
        with mock.patch.object(K, "spawn_background", return_value=False):
            lines = " ".join(H._knowledge_lines(self.root, C.repo_id(self.root), None))
        self.assertIn("STOP before starting a new run", lines)
        self.assertIn(self.run_id, lines)
        K.migrate(self.root)
        self.assertIsNone(K.legacy_current(self.root))
        with mock.patch.object(K, "spawn_background", return_value=False):
            self.assertEqual(H._knowledge_lines(self.root, C.repo_id(self.root), C.current_run(self.root)), [])

    def test_an_old_exclude_line_is_reported(self):
        self.assertFalse(K.hidden_by_exclude(self.root))
        with open(os.path.join(self.root, ".git", "info", "exclude"), "a") as f:
            f.write(".lfg/\n")
        self.assertTrue(K.hidden_by_exclude(self.root))

    def test_dry_run_moves_nothing(self):
        res = K.migrate(self.root, dry_run=True)
        self.assertEqual(res["from"], sorted([self.no_remote, self.with_remote]))
        self.assertEqual(res["runs"], [self.run_id])
        self.assertFalse(os.path.exists(os.path.join(self.root, ".lfg")))

    def test_merges_the_split_run_and_keeps_what_belongs_to_the_machine(self):
        res = K.migrate(self.root)
        run = os.path.join(self.root, ".lfg", "runs", self.run_id)
        self.assertEqual(C.read_text(os.path.join(run, "01-brief.md")), "brief")
        self.assertEqual(C.read_text(os.path.join(run, "PR_BODY.md")), "body")
        meta = C.read_json(os.path.join(run, "run.json"))
        self.assertEqual((meta["stage"], meta["repo_id"]), ("done", self.with_remote))  # newer copy, one id
        self.assertEqual(C.current_run(self.root), run)
        docs = os.path.join(self.root, ".lfg", "docs")
        self.assertEqual(sorted(os.listdir(docs)), ["GLOSSARY.from-%s.md" % self.no_remote, "GLOSSARY.md"])
        self.assertEqual(res["kept_both"], [os.path.join(docs, "GLOSSARY.from-%s.md" % self.no_remote)])
        self.assertTrue(os.path.isfile(os.path.join(self.root, ".lfg", "commands.json")))
        self.assertEqual(C.read_text(os.path.join(self.root, ".lfg", "repo-id")).strip(), self.with_remote)
        self.assertTrue(os.path.isfile(C.lfg_path("repos", self.with_remote, "shipcheck-history.json")))
        self.assertFalse(os.path.exists(C.lfg_path("runs", self.no_remote, self.run_id)))
        self.assertTrue(os.path.isfile(os.path.join(res["backup"], "runs", self.no_remote, self.run_id, "01-brief.md")))
        self.assertEqual(K.legacy(self.root), {})
        self.assertEqual(K.migrate(self.root)["from"], [])  # running it again finds nothing

    def test_a_stored_id_from_the_clone_never_pulls_in_another_repos_runs(self):
        other = "victim-0badc0de"
        self.addCleanup(shutil.rmtree, C.lfg_path("runs", other), True)
        C.write_json(C.lfg_path("runs", other, "20260101-0000-secret", "run.json"), {"run_id": "x"})
        C.write_text(os.path.join(self.root, ".lfg", "repo-id"), other + "\n")  # committed by whoever made the repo
        self.assertEqual(C.repo_id(self.root), other)
        self.assertNotIn(other, K.legacy(self.root))
        self.assertNotIn("20260101-0000-secret", K.migrate(self.root, dry_run=True)["runs"])

    def test_a_run_with_live_build_worktrees_is_copied_but_left(self):
        C.write_text(C.lfg_path("runs", self.with_remote, self.run_id, "wt", "t1", "a.py"), "x")
        res = K.migrate(self.root)
        self.assertEqual(res["left"], [C.lfg_path("runs", self.with_remote, self.run_id)])
        self.assertFalse(os.path.exists(os.path.join(self.root, ".lfg", "runs", self.run_id, "wt")))


class TakeOverTest(unittest.TestCase):
    def test_offers_unfinished_runs_on_this_branch_and_run_use_picks_one(self):
        from lfgcore import cli
        root = os.path.realpath(tempfile.mkdtemp(prefix="lfg-take-"))
        self.addCleanup(shutil.rmtree, root, True)
        subprocess.run(["git", "init", "-q", "-b", "feat", root], check=True)
        mine = C.new_run(root, "teammate work")
        done = C.new_run(root, "finished")
        C.write_json(os.path.join(done, "run.json"), dict(C.read_json(os.path.join(done, "run.json")), stage="done"))
        C.new_run(root, "other branch", branch="main")
        os.remove(os.path.join(root, ".lfg", "runs", "CURRENT"))  # a fresh clone: CURRENT is never committed
        self.assertEqual(K.unfinished_runs(root), [os.path.basename(mine)])
        with mock.patch.object(C, "need_repo", return_value=(root, C.repo_id(root))):
            self.assertEqual(cli.main(["run", "use", os.path.basename(mine)]), 0)
            with self.assertRaises(SystemExit):
                cli.main(["run", "use", "../../etc"])
        self.assertEqual(C.current_run(root), mine)
        self.assertEqual(K.unfinished_runs(root), [])

    def test_session_start_offers_a_teammates_run(self):
        from lfgcore import hooks as H
        root = os.path.realpath(tempfile.mkdtemp(prefix="lfg-take-"))
        self.addCleanup(shutil.rmtree, root, True)
        subprocess.run(["git", "init", "-q", "-b", "feat", root], check=True)
        theirs = os.path.basename(C.new_run(root, "their work"))
        os.remove(os.path.join(root, ".lfg", "runs", "CURRENT"))
        with mock.patch.object(K, "spawn_background", return_value=False):
            lines = " ".join(H._knowledge_lines(root, C.repo_id(root), None))
        self.assertIn(theirs, lines)
        self.assertIn("lfg run use", lines)

    def test_the_ignore_list_gains_new_lines_and_keeps_yours(self):
        root = os.path.realpath(tempfile.mkdtemp(prefix="lfg-ign-"))
        self.addCleanup(shutil.rmtree, root, True)
        subprocess.run(["git", "init", "-q", root], check=True)
        C.write_text(os.path.join(root, ".lfg", ".gitignore"), "runs/CURRENT\nmine/")  # an older LFG, plus a line
        C.knowledge_dir(root)
        lines = C.read_text(os.path.join(root, ".lfg", ".gitignore")).splitlines()
        self.assertEqual(lines[:2], ["runs/CURRENT", "mine/"])
        self.assertIn("runs/**/security-audit/", lines)
        self.assertEqual(len(lines), len(set(lines)))


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="lfg-knowledge-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        with open(os.path.join(self.tmp, "schema.pg"), "w") as fh:
            fh.write(SCHEMA)
        store = os.path.join(self.tmp, "g")
        subprocess.run(["omnigraph", "init", "--schema", os.path.join(self.tmp, "schema.pg"), store],
                       check=True, capture_output=True)
        env = mock.patch.dict(os.environ, {"LFG_KNOWLEDGE_STORE": "file://" + store})
        env.start()
        self.addCleanup(env.stop)
        self.root = os.path.join(self.tmp, "repo")
        subprocess.run(["git", "init", "-q", "-b", "main", self.root], check=True)
        self.rid = C.repo_id(self.root)
        self.addCleanup(shutil.rmtree, C.lfg_path("graphs", self.rid), True)
        self.name = K.branch_for(self.root)

    def graph(self):
        nodes, edges = K.export(self.name)
        return nodes, sorted(edges)

    def agent_writes(self, rows):
        K._load(self.name, rows)

    def test_new_branch_starts_empty_even_when_main_has_other_repos_nodes(self):
        K._load("main", [{"type": "Learning", "data": {"slug": "lrn-other-repo", "title": "elsewhere"}}])
        K.sync(self.root)
        self.assertEqual(self.graph(), ({}, []))
        self.assertIn("Learning/lrn-other-repo", K.export("main")[0])  # main is left as it was

    def test_files_load_and_agent_additions_come_back_as_files(self):
        K.write_file(self.root, {"type": "Component", "slug": "cmp-core", "links": [],
                                 "data": {"slug": "cmp-core", "name": "core"}})
        K.write_file(self.root, dec("dec-a", links=[("DecisionAppliesToComponent", "cmp-core")]))
        res = K.sync(self.root)
        self.assertEqual((res["files"], res["rebuilt"], res["written"]), (2, True, []))
        nodes, edges = self.graph()
        self.assertEqual(set(nodes), {"Component/cmp-core", "Decision/dec-a"})
        self.assertEqual([e[0] for e in edges], ["DecisionAppliesToComponent"])
        # an agent saves a Learning through the MCP, plus a Linear-mirrored Issue and a PR that touches a Component
        self.agent_writes([{"type": "Learning", "data": {"slug": "lrn-b", "title": "gotcha", "body": "why"}},
                           {"type": "Issue", "data": {"slug": "acme-1", "title": "from Linear"}},
                           {"type": "PR", "data": {"slug": "pr-1", "title": "pr"}},
                           {"edge": "LearningAboutComponent", "from": "lrn-b", "to": "cmp-core"},
                           {"edge": "PrTouchesComponent", "from": "pr-1", "to": "cmp-core"}])
        res = K.sync(self.root)
        self.assertEqual(res["written"], ["Learning/lrn-b"])
        text = C.read_text(os.path.join(self.root, ".lfg", "nodes", "Learning", "lrn-b.md"))
        self.assertIn("- LearningAboutComponent cmp-core", text)
        self.assertFalse(os.path.exists(os.path.join(self.root, ".lfg", "nodes", "Issue")))  # Linear's, not ours
        self.assertFalse(res["rebuilt"])  # nothing left to load
        # a teammate's pull edits the Component's file: the rebuild keeps the PR's edge and the Linear issue
        K.write_file(self.root, {"type": "Component", "slug": "cmp-core", "links": [],
                                 "data": {"slug": "cmp-core", "name": "core v2"}})
        self.assertTrue(K.sync(self.root)["rebuilt"])
        nodes, edges = self.graph()
        self.assertEqual(nodes["Component/cmp-core"]["data"]["name"], "core v2")
        self.assertIn("Issue/acme-1", nodes)
        self.assertEqual(sorted(e[0] for e in edges),
                         ["DecisionAppliesToComponent", "LearningAboutComponent", "PrTouchesComponent"])
        # running it again changes nothing
        res = K.sync(self.root)
        self.assertEqual((res["rebuilt"], res["written"], res["conflicts"]), (False, [], []))
        self.assertEqual(len(self.graph()[1]), 3)

    def test_a_link_to_a_node_not_on_the_branch_stays_in_the_file(self):
        rec = dec("dec-a", links=[("DecisionEmergedFromIssue", "lee-56")])  # a Linear issue not mirrored here
        K.write_file(self.root, rec)
        path = os.path.join(self.root, ".lfg", "nodes", "Decision", "dec-a.md")
        for _ in range(3):
            res = K.sync(self.root)
            self.assertEqual(res["written"], [])
            self.assertIn("- DecisionEmergedFromIssue lee-56", C.read_text(path))
        self.agent_writes([{"type": "Decision", "data": dict(rec["data"], title="agent edit")}])
        K.sync(self.root)  # an agent's edit keeps the link the graph couldn't hold
        self.assertIn("agent edit", C.read_text(path))
        self.assertIn("- DecisionEmergedFromIssue lee-56", C.read_text(path))
        self.agent_writes([{"type": "Issue", "data": {"slug": "lee-56", "title": "from Linear"}}])
        K.sync(self.root)  # once the issue is on the branch, the edge is loaded
        self.assertIn(["DecisionEmergedFromIssue", "dec-a", "lee-56"], self.graph()[1])
        self.assertEqual(K.sync(self.root)["written"], [])

    def test_deleted_file_removes_the_node(self):
        K.write_file(self.root, dec("dec-a"))
        K.sync(self.root)
        os.remove(os.path.join(self.root, ".lfg", "nodes", "Decision", "dec-a.md"))
        self.assertTrue(K.sync(self.root)["rebuilt"])
        self.assertEqual(self.graph(), ({}, []))
        self.assertFalse(os.path.exists(os.path.join(self.root, ".lfg", "nodes", "Decision", "dec-a.md")))

    def test_agent_edit_reaches_the_file_and_both_sides_edited_keeps_the_file(self):
        K.write_file(self.root, dec("dec-a"))
        K.sync(self.root)
        self.agent_writes([{"type": "Decision", "data": dict(dec("dec-a", title="edited by an agent")["data"])}])
        self.assertEqual(K.sync(self.root)["written"], ["Decision/dec-a"])
        self.assertIn("edited by an agent", C.read_text(os.path.join(self.root, ".lfg", "nodes", "Decision",
                                                                     "dec-a.md")))
        self.agent_writes([{"type": "Decision", "data": dict(dec("dec-a", title="agent again")["data"])}])
        K.write_file(self.root, dec("dec-a", title="teammate"))
        res = K.sync(self.root)
        self.assertEqual(res["conflicts"], ["Decision/dec-a"])
        self.assertEqual(self.graph()[0]["Decision/dec-a"]["data"]["title"], "teammate")

    def test_broken_file_is_reported_not_loaded(self):
        C.write_text(os.path.join(self.root, ".lfg", "nodes", "Decision", "dec-x.md"), "not a node\n")
        res = K.sync(self.root)
        self.assertEqual(res["files"], 0)
        self.assertEqual(len(res["bad"]), 1)

    def test_a_bad_merge_leaves_the_node_in_the_graph_until_the_file_is_fixed(self):
        K.write_file(self.root, dec("dec-a"))
        K.sync(self.root)
        path = os.path.join(self.root, ".lfg", "nodes", "Decision", "dec-a.md")
        good = C.read_text(path)
        C.write_text(path, "<<<<<<< HEAD\n" + good + "=======\n>>>>>>> theirs\n")
        for _ in range(2):  # and on the sync after that
            res = K.sync(self.root)
            self.assertIn("Decision/dec-a", self.graph()[0])
            self.assertEqual(len(res["bad"]), 1)
        C.write_text(path, good.replace("Files are the master", "fixed"))
        K.sync(self.root)
        self.assertEqual(self.graph()[0]["Decision/dec-a"]["data"]["title"], "fixed")

    def test_an_agent_node_whose_file_cannot_be_written_stays_in_the_graph(self):
        K.sync(self.root)
        self.agent_writes([{"type": "Learning", "data": {"slug": "Lrn-Upper", "title": "x"}}])
        for _ in range(2):
            res = K.sync(self.root)
            self.assertIn("Learning/Lrn-Upper", self.graph()[0])
            self.assertTrue(any("unsafe slug" in b for b in res["bad"]))

    def test_each_checkout_has_its_own_branch(self):
        wt = os.path.join(self.tmp, "wt")
        subprocess.run(["git", "-C", self.root, "-c", "user.email=t@e", "-c", "user.name=t", "commit", "-q",
                        "--allow-empty", "-m", "base"], check=True)
        subprocess.run(["git", "-C", self.root, "worktree", "add", "-q", "-b", "feat", wt], check=True)
        self.assertEqual(C.repo_id(wt), self.rid)
        self.assertNotEqual(K.branch_for(wt), self.name)
        K.write_file(self.root, dec("dec-main"))
        K.write_file(wt, dec("dec-feat"))
        K.sync(self.root)
        K.sync(wt)
        self.agent_writes([{"type": "Learning", "data": {"slug": "lrn-main", "title": "saved in main"}}])
        K.sync(wt)  # the worktree's Stop hook runs first
        K.sync(self.root)
        self.assertEqual(set(self.graph()[0]), {"Decision/dec-main", "Learning/lrn-main"})
        self.assertEqual(set(K.export(K.branch_for(wt))[0]), {"Decision/dec-feat"})
        self.assertFalse(os.path.exists(os.path.join(wt, ".lfg", "nodes", "Learning")))

    def test_a_branch_that_cannot_be_cleared_is_removed_not_left_full(self):
        K._load("main", [{"type": "Decision", "data": dict(dec("dec-other-repo")["data"])}])
        real = K._mutate
        with mock.patch.object(K, "_mutate", side_effect=RuntimeError("server went away")):
            with self.assertRaises(RuntimeError):
                K.sync(self.root)
        self.assertNotIn(self.name, K.branches())
        K._mutate = real
        K.sync(self.root)
        self.assertEqual(self.graph(), ({}, []))
        self.assertFalse(os.path.exists(os.path.join(self.root, ".lfg", "nodes", "Decision")))

    def test_take_main_nodes_copies_only_shared_nodes_once(self):
        K._load("main", [{"type": "Decision", "data": dict(dec("dec-old")["data"])},
                         {"type": "Issue", "data": {"slug": "acme-1", "title": "linear"}},
                         {"type": "Issue", "data": {"slug": "iss-idea-1a2b", "title": "idea"}}])
        self.assertEqual(K.take_main_nodes(self.root), ["Decision/dec-old", "Issue/iss-idea-1a2b"])
        self.assertEqual(K.take_main_nodes(self.root), [])


class McpPinTest(unittest.TestCase):
    def test_dev_graph_mcp_is_pinned_to_this_checkouts_branch(self):
        from lfgcore import omnigraph as OG
        root = os.path.realpath(tempfile.mkdtemp(prefix="lfg-mcp-"))
        self.addCleanup(shutil.rmtree, root, True)
        subprocess.run(["git", "init", "-q", root], check=True)
        with mock.patch.object(C, "repo_root", return_value=root), mock.patch.object(OG, "_which",
                                                                                      return_value="/bin/npx"), \
                mock.patch.object(K, "ensure_locked") as ens, mock.patch.object(OG, "_exec") as ex:
            OG.mcp("dev-graph")
            self.assertEqual(ex.call_args[0][1]["OMNIGRAPH_DEFAULT_BRANCH"], K.branch_for(root))
            ens.assert_called_once_with(root)
            OG.mcp("second-brain")
            self.assertNotIn("OMNIGRAPH_DEFAULT_BRANCH", ex.call_args[0][1])


if __name__ == "__main__":
    unittest.main()
