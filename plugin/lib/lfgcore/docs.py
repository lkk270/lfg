"""Generated docs and playbooks, all from the graphs, no model calls.

`lfg graphs docs`: graphify wiki + call-flow HTML, code-review-graph wiki, then playbooks.
`lfg playbooks`:   onboarding tour, landmines, test gaps (and incident runbooks when dev-graph has any)
                   in ~/.lfg/playbooks/<repo-id>/. "How to add X here" playbooks need judgement, so /learn
                   writes those into the same folder.

Everything is written under ~/.lfg, never into the repo. Author: Varun Singh.
"""
import collections
import json
import os
import re
import shutil
import sqlite3
import sys
import time

from . import common as C

PLAYBOOKS = ("onboarding.md", "landmines.md", "test-gaps.md", "incidents.md")


def gdir(rid):
    """LFG's bookkeeping for the repo (state.json, docs.json)."""
    return C.lfg_path("graphs", rid)


def data(rid, kind, *parts):
    """Path inside the repo's graph data (`crg` → .code-review-graph, `graphify` → graphify-out); "" if unknown."""
    from . import graphs as G
    d = G.data_dir(rid, kind)
    return os.path.join(d, *parts) if d else ""


def playbook_dir(rid):
    return C.lfg_path("playbooks", rid)


def docs_state(rid):
    return C.read_json(os.path.join(gdir(rid), "docs.json"), {}) or {}


# ---------------------------------------------------------------- graph readers (shared with the dashboard)

def crg_db(rid):
    """Read-only connection to code-review-graph's SQLite store, or None."""
    p = data(rid, "crg", "graph.db")
    if not p or not os.path.exists(p):
        return None
    try:
        db = sqlite3.connect("file:%s?mode=ro" % p, uri=True, timeout=5)
        db.execute("SELECT 1 FROM nodes LIMIT 1")
        return db
    except sqlite3.Error:
        try:  # read-only directory (no -shm allowed): fall back to an immutable snapshot read
            db = sqlite3.connect("file:%s?immutable=1" % p, uri=True)
            db.execute("SELECT 1 FROM nodes LIMIT 1")
            return db
        except sqlite3.Error:
            return None


_GJ_CACHE = {}


def graphify_graph(rid):
    """graphify graph.json, parsed once per file version (it can be tens of MB)."""
    p = data(rid, "graphify", "graph.json")
    try:
        mt = os.stat(p).st_mtime_ns
    except OSError:
        return None
    hit = _GJ_CACHE.get(rid)
    if hit and hit[0] == mt:
        return hit[1]
    g = C.read_json(p, None)
    if not isinstance(g, dict):
        return None
    deg = collections.Counter()
    for e in g.get("links", []):
        deg[e.get("source")] += 1
        deg[e.get("target")] += 1
    g["_degree"] = deg
    _GJ_CACHE.clear()  # keep one repo in memory at a time
    _GJ_CACHE[rid] = (mt, g)
    return g


DOC_EXT = re.compile(r"\.(md|mdx|markdown|rst|txt|adoc)$", re.I)
TEST_FILE = re.compile(r"(^|/)(tests?|__tests__|testdata|spec)/|_test\.(go|py)$|(^|/)test_[^/]*\.py$|"
                       r"\.(test|spec)\.[jt]sx?$|(^|/)tests?\.rs$|Tests?\.(java|kt|cs|swift)$")


THIRD_PARTY = re.compile(r"(^|/)(vendor|vendored|third[_-]party|node_modules|external)/", re.I)  # not the team's own


def is_test(path):
    return bool(TEST_FILE.search(path or ""))


GENERIC_DIRS = {"src", "lib", "app", "pkg", "internal", "core", "main", "java", "go", "ts", "js", "packages",
                "microservices", "services", "modules", "source"}


def area_name(paths):
    """A readable name for a group of files: their shared folder, minus filler like src/ ("security-controls/steps"),
    or the file names when they share nothing. Used instead of graphify's "Community 12"."""
    paths = [p for p in paths if p]
    if not paths:
        return ""
    dirs = [os.path.dirname(p).split("/") for p in paths]
    common = []
    for parts in zip(*dirs):
        if len(set(parts)) != 1:
            break
        common.append(parts[0])
    if not common:  # no shared folder: the most common one
        top = collections.Counter("/".join(d) for d in dirs).most_common(1)[0][0]
        common = top.split("/") if top else []
    keep = [x for x in common if x and x.lower() not in GENERIC_DIRS][-3:]
    if keep:
        return "/".join(keep)
    stems = []
    for p in paths:
        s = re.sub(r"\.\w{1,5}$", "", os.path.basename(p))
        if s not in stems:
            stems.append(s)
    return ", ".join(stems[:3]) + (" and more" if len(stems) > 3 else "")


def wiki_pages(rid):
    """graphify wiki pages, classified. kind: `doc` (every source is documentation: README, runbooks, guides),
    `code` (a community of code) or `node` (a single god-node page). Sorted most useful first."""
    d = data(rid, "graphify", "wiki")
    if not d or not os.path.isdir(d):
        return []
    out = []
    for name in os.listdir(d):
        if not name.endswith(".md") or name == "index.md":
            continue
        text = C.read_text(os.path.join(d, name))
        head = re.search(r"^# (.+)$", text, re.M)
        size = re.search(r"^> (\d+) nodes", text, re.M)
        srcs = re.findall(r"^- `([^`]+)`", text.split("## Source Files", 1)[1], re.M) if "## Source Files" in text \
            else []
        doc = bool(srcs) and all(DOC_EXT.search(x) for x in srcs)
        title = (head.group(1).strip() if head else name[:-3])[:120]
        lead = re.search(r"^- \*\*(.+?)\*\*", text, re.M)
        if re.match(r"^Community \d+$", title):  # graphify's placeholder name: say what's in it instead
            key = re.findall(r"^- \*\*.*?\*\* \(.*?\) — `([^`]+)`", text, re.M)
            title = area_name([x for x in key + srcs if not is_test(x)] or key + srcs) or title
            heading = re.sub(r"^\d+\.\s*", "", lead.group(1)).strip()[:120] if lead else ""
            if srcs and all(DOC_EXT.search(x) for x in srcs) and " " in heading:  # docs cluster: its heading
                title = heading
        if doc and DOC_EXT.search(title) and len(srcs) == 1:  # "linux.mdx" -> "runbooks · linux"
            parent = os.path.basename(os.path.dirname(srcs[0]))
            stem = DOC_EXT.sub("", os.path.basename(srcs[0]))
            title = "%s · %s" % (parent, stem) if parent and parent not in ("docs", "content") else stem
        elif size and re.search(r"\.\w{1,5}$", title):  # graphify names an area after its top node's file
            dirs = collections.Counter(os.path.dirname(x) for x in srcs if not is_test(x) and not DOC_EXT.search(x))
            if dirs and dirs.most_common(1)[0][0]:
                top = dirs.most_common(1)[0][0]
                stem = re.sub(r"\.\w{1,5}$", "", title)
                title = top if is_test(title) or os.path.basename(top) in title or stem in ("__init__", "index", "mod",
                                                                                              "main") \
                    else "%s · %s" % (top, title)
        out.append({"path": name, "title": title, "nodes": int(size.group(1)) if size else 0, "sources": srcs,
                    "lead": re.sub(r"\.\w{1,5}$|\(\)$", "", lead.group(1)) if lead else "",
                    "kind": "doc" if doc else ("code" if size else "node"),
                    "runbook": any(re.search(r"runbook|playbook|operations|troubleshoot", x, re.I) for x in srcs),
                    "tests": bool(srcs) and sum(map(is_test, srcs)) * 2 >= len(srcs)})  # mostly test files
    order = {"doc": 0, "code": 1, "node": 2}
    out.sort(key=lambda p: (order[p["kind"]], not p["runbook"], p["tests"], -p["nodes"], p["title"].lower()))
    return out


def report_sections(rid):
    """GRAPH_REPORT.md split into {heading: markdown body} for the top-level (##) sections."""
    text = C.read_text(data(rid, "graphify", "GRAPH_REPORT.md")) if data(rid, "graphify") else ""
    out, cur = {}, None
    for line in text.splitlines():
        if line.startswith("## "):
            cur = line[3:].strip()
            out[cur] = []
        elif cur:
            out[cur].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def section(sections, prefix):
    for k, v in sections.items():
        if k.lower().startswith(prefix.lower()):
            return v
    return ""


def _short(path, root):
    if root and path.startswith(root.rstrip("/") + "/"):
        return path[len(root.rstrip("/")) + 1:]
    return path


def _qual(q, root):
    """crg qualified name `/abs/path/file.ts::Class.fn` → (`file.ts`, `Class.fn`)."""
    f, _, sym = q.partition("::")
    return _short(f, root), sym or os.path.basename(f)


# ---------------------------------------------------------------- tool docs

def _run(rid, cmd, root, cwd=None, timeout=600):
    from . import graphs as G
    return G._run_tool(rid, cmd, root, timeout, cwd=cwd)


def generate(root, rid):
    """Regenerate both wikis, the call-flow view and the playbooks. Returns docs.json content."""
    from . import graphs as G
    lock = G.Lock(rid)
    if not lock.acquire(blocking=True, timeout=900):
        return {"status": "busy", "message": "a graph sync is running; try again shortly"}
    t0, errors, made = time.time(), [], {}
    try:
        gd = gdir(rid)
        root = C.main_root(root)
        gout, crgd = G.data_dir(rid, "graphify", root), G.data_dir(rid, "crg", root)
        gj = os.path.join(gout, "graph.json")
        gfy = C.which("graphify")
        if gfy and os.path.exists(gj):
            shutil.rmtree(os.path.join(gout, "wiki"), ignore_errors=True)
            cp = _run(rid, [gfy, "export", "wiki", "--graph", gj], root, gout)
            made["graphify_wiki"] = cp.returncode == 0
            if cp.returncode:
                errors.append("graphify export wiki: %s" % (cp.stderr or cp.stdout)[-300:].strip())
            cf = os.path.join(gout, "callflow.html")
            cp = _run(rid, [gfy, "export", "callflow-html", "--graph", gj, "--output", cf], root, gout)
            made["callflow"] = cp.returncode == 0
            if cp.returncode:
                errors.append("graphify export callflow-html: %s" % (cp.stderr or cp.stdout)[-300:].strip())
        crg = C.which("code-review-graph")
        if crg and os.path.exists(os.path.join(crgd, "graph.db")):
            shutil.rmtree(os.path.join(crgd, "wiki"), ignore_errors=True)
            cp = _run(rid, [crg, "wiki", "--repo", root, "--data-dir", crgd, "--force"], root)
            made["crg_wiki"] = cp.returncode == 0
            if cp.returncode:
                errors.append("code-review-graph wiki: %s" % (cp.stderr or cp.stdout)[-300:].strip())
    finally:
        lock.release()
    try:
        made["playbooks"] = playbooks(root, rid)
    except Exception as e:  # playbooks are best effort; the wikis above are still useful
        errors.append("playbooks: %s: %s" % (type(e).__name__, e))
    st = {"generated_at": C.now_iso(), "seconds": round(time.time() - t0, 2), "made": made,
          "fingerprint": (C.read_json(os.path.join(gd, "state.json"), {}) or {}).get("fingerprint"),
          "errors": errors}
    C.write_json(os.path.join(gd, "docs.json"), st)
    return dict(st, status="ok" if not errors else "partial")


def due(rid):
    """True when the graphs changed since the docs were last generated."""
    if not C.config()["graphs"].get("docs", True):
        return False
    fp = (C.read_json(os.path.join(gdir(rid), "state.json"), {}) or {}).get("fingerprint")
    return bool(fp) and docs_state(rid).get("fingerprint") != fp


def spawn_background(root):
    import subprocess
    lfg = C.lfg_bin()
    if not os.path.exists(lfg):
        lfg = os.path.abspath(sys.argv[0])
    with open(os.devnull, "wb") as dn:
        subprocess.Popen([sys.executable, lfg, "graphs", "docs", "--quiet"], cwd=root, stdout=dn, stderr=dn,
                         stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True)


# ---------------------------------------------------------------- playbooks

def _md_table(cols, rows):
    if not rows:
        return "_None found._\n"
    def esc(v):
        return str(v if v is not None else "").replace("|", "\\|").replace("\n", " ")
    return "| %s |\n|%s|\n%s\n" % (" | ".join(cols), "|".join("---" for _ in cols),
                                  "\n".join("| %s |" % " | ".join(esc(c) for c in r) for r in rows))


def _churn(root, days=90):
    cp = C.run(["git", "log", "--since=%d.days" % days, "--name-only", "--pretty=format:"], cwd=root, timeout=60)
    return collections.Counter(ln for ln in cp.stdout.splitlines() if ln.strip())


def _header(title, rid, why):
    return "# %s\n\n> Generated by `lfg playbooks` from the code graphs on %s for `%s`. %s\n\n" % (
        title, C.now_iso()[:10], rid, why)


def _glance(g):
    nodes = g.get("nodes", [])
    files = {n.get("source_file") for n in nodes if n.get("file_type") == "code" and n.get("source_file")}
    areas = {n.get("community_name") for n in nodes}
    return "%d code files, %d symbols and %d links between them, in %d areas." % (
        len(files), len(nodes), len(g.get("links", [])), len(areas))


def _area_names(g):
    """graphify's area labels ("Community 12", or its top symbol) → the shared folder of the area's non-test files."""
    files = collections.defaultdict(list)
    for n in g.get("nodes", []):
        files[n.get("community_name")].append(n.get("source_file"))
    out = {}
    for name, paths in files.items():
        out[name] = area_name([x for x in paths if x and not is_test(x)] or paths) or name
    return out


def _onboarding(rid, root, g, sections, db):
    out = [_header("Onboarding tour", rid, "Read top to bottom: core abstractions, then the areas, then the "
                                             "flows that matter, then the surprises.")]
    out.append("## 1. The codebase at a glance\n\n%s\n\n" % (_glance(g) if g else "_No code map yet._"))
    guides = [p for p in wiki_pages(rid)
              if p["kind"] == "doc" and not all(THIRD_PARTY.search(x) for x in p["sources"])][:20]
    if guides:
        out.append("## Runbooks and guides (from your docs)\n\nWhat the team already wrote down, as graphify read it. "
                   "Start with the runbooks.\n\n")
        out.append("".join("- [%s](lfgdoc:guides/%s)%s, from `%s`\n" % (
            p["title"], p["path"], " **(runbook)**" if p["runbook"] else "", "`, `".join(p["sources"][:2]))
            for p in guides))
        out.append("\nThe originals are in the repo; the code map is in `lfg ui` → Code.\n\n")
    if g:
        deg = g["_degree"]
        nodes = {n["id"]: n for n in g.get("nodes", [])}
        top = [nodes[i] for i, _ in deg.most_common(200) if i in nodes and nodes[i].get("file_type") == "code"
               and nodes[i].get("source_file") and not is_test(nodes[i]["source_file"])][:15]
        names = _area_names(g)
        out.append("## 2. Core abstractions (god nodes)\n\nThe most connected symbols. Change these with care; "
                   "learn these first.\n\n")
        out.append(_md_table(["Symbol", "Connections", "Defined in"],
                             [("`%s`" % n["label"], deg[n["id"]], "`%s`" % n.get("source_file", "")) for n in top]))
        comm = collections.defaultdict(list)
        for n in g.get("nodes", []):
            comm[n.get("community_name") or "?"].append(n)
        areas = sorted(((k, v) for k, v in comm.items()
                        if sum(is_test(n.get("source_file")) for n in v) * 2 < len(v)),  # skip test-only areas
                       key=lambda kv: -len(kv[1]))[:15]
        out.append("\n## 3. Main areas\n\n")
        rows = []
        for name, ns in areas:
            files = collections.Counter(n.get("source_file") for n in ns if n.get("source_file"))
            rows.append(("**%s**" % (names.get(name) or name), len(ns),
                         ", ".join("`%s`" % f for f, _ in files.most_common(3))))
        out.append(_md_table(["Area", "Symbols", "Key files"], rows))
    if db:
        rows = db.execute("SELECT c.name, c.size, COALESCE(s.purpose, ''), c.dominant_language, "
                          "COALESCE(s.key_symbols, '[]') FROM communities c LEFT JOIN community_summaries s "
                          "ON s.community_id = c.id ORDER BY c.size DESC LIMIT 15").fetchall()
        out.append("\n## 4. Modules\n\n")
        out.append(_md_table(["Module", "Size", "Purpose", "Language", "Key symbols"],
                             [(r[0], r[1], r[2], r[3], ", ".join(json.loads(r[4] or "[]")[:5])) for r in rows]))
        flows = db.execute("SELECT f.name, f.node_count, f.file_count, f.criticality, n.file_path FROM flows f "
                           "LEFT JOIN nodes n ON n.id = f.entry_point_id ORDER BY f.criticality DESC LIMIT 12"
                           ).fetchall()
        out.append("\n## 5. Critical execution flows\n\nEntry points whose call chains touch the most code. "
                   "Trace one end to end before changing it.\n\n")
        out.append(_md_table(["Flow", "Criticality", "Nodes", "Files", "Entry point"],
                             [("`%s`" % f[0], "%.2f" % f[3], f[1], f[2], "`%s`" % _short(f[4] or "", root))
                              for f in flows]))
    surprising = section(sections, "Surprising")
    out.append("\n## 6. Surprising connections\n\n%s\n" % (surprising or "_None reported._"))
    out.append("\n## Next\n\n- Explore the code map in `lfg ui` → Code; ask Claude to write a doc on anything that "
               "isn't covered (it lands in `lfg ui` → Docs).\n"
               "- Ask the graph: `graphify query \"<question>\"` from the repo root (from a worktree add "
               "`--graph \"$(lfg repo graph)\"`).\n")
    return "".join(out)


def _landmines(rid, root, g, sections, db, churn):
    out = [_header("Landmines", rid, "The places most likely to bite: notes left in the code, risky code "
                                     "without tests, import cycles, and files that change a lot.")]
    if g:
        rat = [n for n in g.get("nodes", []) if n.get("file_type") == "rationale"]
        order = {"HACK": 0, "FIXME": 1, "XXX": 2, "WARNING": 3, "WHY": 4, "NOTE": 5, "TODO": 6}
        rat.sort(key=lambda n: (order.get(re.split(r"[:(\s]", n.get("label", "") + " ")[0].upper(), 9),
                                n.get("source_file", "")))
        out.append("## 1. Notes left in the code (HACK / FIXME / WHY / NOTE / TODO)\n\n")
        out.append(_md_table(["Note", "Where"], [(n.get("label", ""), "`%s%s`" % (
            n.get("source_file", ""), ":" + str(n["source_location"]) if n.get("source_location") else ""))
            for n in rat[:80]]))
    if db:
        rows = db.execute("SELECT qualified_name, risk_score, caller_count FROM risk_index WHERE "
                          "test_coverage = 'untested' AND security_relevant = 1 ORDER BY risk_score DESC, "
                          "caller_count DESC LIMIT 25").fetchall()
        out.append("\n## 2. Security-relevant code with no tests\n\nHigh risk score, flagged security-relevant "
                   "by code-review-graph, and no `TESTED_BY` edge. Add a test before changing these.\n\n")
        out.append(_md_table(["Symbol", "File", "Risk", "Callers"],
                             [("`%s`" % _qual(q, root)[1], "`%s`" % _qual(q, root)[0], "%.2f" % r, c)
                              for q, r, c in rows]))
    cycles = section(sections, "Import Cycles")
    out.append("\n## 3. Import cycles\n\n%s\n" % (cycles or "_None reported._"))
    if churn and db:
        untested = collections.Counter()
        for q, in db.execute("SELECT qualified_name FROM risk_index WHERE test_coverage = 'untested'"):
            untested[_qual(q, root)[0]] += 1
        hot = [(f, n, untested[f]) for f, n in churn.most_common(400) if untested.get(f)][:20]
        out.append("\n## 4. Churn hotspots with untested code (last 90 days)\n\nFiles changed often that still "
                   "hold untested symbols: regressions are likeliest here.\n\n")
        out.append(_md_table(["File", "Commits touching it", "Untested symbols"],
                             [("`%s`" % f, n, u) for f, n, u in hot]))
    return "".join(out)


def _test_gaps(rid, root, db):
    out = [_header("Test gaps", rid, "Untested symbols ranked by how much depends on them (code-review-graph "
                                     "risk index). Use it to pick what to cover first.")]
    tot = dict(db.execute("SELECT test_coverage, count(*) FROM risk_index GROUP BY 1").fetchall())
    n = sum(tot.values()) or 1
    out.append("**Coverage by symbol:** %d tested, %d untested (%.0f%% tested).\n\n" % (
        tot.get("tested", 0), tot.get("untested", 0), 100.0 * tot.get("tested", 0) / n))
    rows = db.execute("SELECT qualified_name, risk_score, caller_count, security_relevant FROM risk_index "
                      "WHERE test_coverage = 'untested' ORDER BY caller_count DESC, risk_score DESC LIMIT 40"
                      ).fetchall()
    out.append("## Most depended-on untested symbols\n\n")
    out.append(_md_table(["Symbol", "File", "Callers", "Risk", "Security"],
                         [("`%s`" % _qual(q, root)[1], "`%s`" % _qual(q, root)[0], c, "%.2f" % r,
                           "yes" if s else "") for q, r, c, s in rows]))
    by_file = collections.Counter(_qual(q, root)[0] for q, in db.execute(
        "SELECT qualified_name FROM risk_index WHERE test_coverage = 'untested'"))
    out.append("\n## Files with the most untested symbols\n\n")
    out.append(_md_table(["File", "Untested symbols"], [("`%s`" % f, c) for f, c in by_file.most_common(20)]))
    return "".join(out)


def _incidents(rid):
    from . import teamknowledge as K
    from . import omnigraph as OG
    br = K.branch(rid)  # this repo's incidents: generated for the main checkout, whose branch this is
    try:
        inc = OG.read("dev-graph", "query incidents() { match { $i: Incident } return { $i.slug, $i.title, "
                                   "$i.severity, $i.status, $i.summary, $i.startedAt } order { $i.startedAt desc } "
                                   "limit 50 }", "incidents", branch=br)
    except Exception:
        return None
    if not inc:
        return None
    out = [_header("Incident runbooks", rid, "Past incidents from dev-graph, each with its root cause, "
                                             "affected components and learnings.")]
    for i in inc:
        slug = i.get("slug")
        out.append("## %s (%s, %s)\n\n%s\n\n" % (i.get("title") or slug, i.get("severity") or "?",
                                                 i.get("status") or "?", i.get("summary") or ""))
        for name, title in (("incident_root_cause", "Root cause"), ("incident_components", "Components"),
                            ("learnings_for_incident", "Learnings")):
            try:
                rows = OG.invoke("dev-graph", name, {"incident": slug}, branch=br)
            except Exception:
                rows = []
            if rows:
                out.append("**%s:**\n\n%s\n" % (title, "\n".join("- " + " · ".join(
                    str(v) for v in r.values() if v not in (None, "")) for r in rows)))
    return "".join(out)


def playbooks(root, rid):
    """Write the deterministic playbooks. Returns the list of files written."""
    d = C.ensure_dir(playbook_dir(rid))
    g, sections, db = graphify_graph(rid), report_sections(rid), crg_db(rid)
    written = []

    def put(name, text):
        if text:
            C.write_text(os.path.join(d, name), text)
            written.append(name)

    try:
        put("onboarding.md", _onboarding(rid, root, g, sections, db))
        put("landmines.md", _landmines(rid, root, g, sections, db, _churn(root) if root else None))
        if db:
            put("test-gaps.md", _test_gaps(rid, root, db))
    finally:
        if db:
            db.close()
    put("incidents.md", _incidents(rid))
    return written
