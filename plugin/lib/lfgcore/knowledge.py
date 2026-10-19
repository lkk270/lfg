"""The repo's shared dev-graph knowledge (docs/team-knowledge.md).

The master copy is one markdown file per node in <checkout>/.lfg/nodes/<Type>/<slug>.md, committed with the code.
Each person's dev-graph keeps a checkout on its own branch, `repo/<repo-id>` for the main checkout and
`repo/<repo-id>--wt-<hash>` for each linked worktree (each holds its own git branch's files), which `sync` rebuilds from
the files. Agents keep writing through the dev-graph MCP (pinned to that branch); `sync` copies what they added or
changed back into files first, by comparing both sides against what it loaded last time
(~/.lfg/graphs/<repo-id>/knowledge*.json):

  in the graph only, never loaded   -> new from an agent: write its file
  changed in the graph, file not    -> edited by an agent: rewrite its file
  changed on both sides             -> conflict: the file wins, reported
  anything else                     -> the file wins (a pull, a merge, a deleted file)

Shared: the repo's knowledge that nothing else holds. Not shared: Issues linked to Linear (Linear is the master), PR,
Commit, Release, Deployment (GitHub is), Actor (email addresses), Comment. Those stay on the branch untouched.
"""
import datetime
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

from . import common as C

SHARED = ("Decision", "Learning", "Invariant", "Principle", "Gap", "Assumption", "ExternalBlocker", "Component",
          "Capability", "SpecFile", "Incident", "Issue")
# Every node type in the dev-graph schema: a new branch starts as a copy of main, so it is emptied of all of them.
ALL_TYPES = SHARED + ("Epic", "Repo", "PR", "Release", "Actor", "Gate", "Label", "Commit", "Deployment", "Comment")
# The long text of each type goes below the header, where it reads (and diffs) like prose.
BODY = {"Decision": "decision", "Learning": "body", "SpecFile": "body", "Issue": "description",
        "Incident": "summary", "Component": "summary", "Capability": "summary", "Principle": "rationale"}
SKIP_FIELDS = {"embedding"}
SLUG_RX = re.compile(r"^[a-z0-9][a-z0-9._-]{0,120}$")
GRAPH = "dev-graph"


def branch(rid):
    """The main checkout's branch; the dashboard, which only knows the repo id, shows this one."""
    return "repo/" + rid


def branch_for(root):
    """This checkout's branch: a linked worktree has its own, so two git branches never share one index."""
    rid, main = C.repo_id(root), C.main_root(root)
    if os.path.realpath(root) == os.path.realpath(main):
        return branch(rid)
    # a sibling name: Omnigraph refuses a branch nested under another live branch's name
    return "%s--wt-%s" % (branch(rid), hashlib.sha1(os.path.realpath(root).encode()).hexdigest()[:8])


def shared(rtype, slug):
    """Issues without a Linear ticket have free-text keys (iss-...); the rest mirror Linear."""
    return rtype in SHARED and (rtype != "Issue" or slug.startswith("iss-"))


# ---------------------------------------------------------------- node files

def nodes_dir(root, create=False):
    return os.path.join(C.knowledge_dir(root, create), "nodes")


def render(rec):
    """A node record {type, slug, data, links} as its markdown file."""
    body_key = BODY.get(rec["type"])
    lines = ["---", "type: " + json.dumps(rec["type"])]
    for k in sorted(rec["data"]):
        if k != body_key:
            lines.append("%s: %s" % (k, json.dumps(rec["data"][k], ensure_ascii=False)))
    if rec["links"]:
        lines.append("links:")
        lines += ["- %s %s" % tuple(link) for link in rec["links"]]
    lines.append("---")
    body = rec["data"].get(body_key) if body_key else None
    return "\n".join(lines) + "\n" + (body + "\n" if body else "")


def parse(text):
    """The inverse of render. Raises ValueError on a file that isn't one."""
    if not text.startswith("---\n"):
        raise ValueError("no header")
    head, sep, body = (text if text.endswith("\n") else text + "\n")[4:].partition("\n---\n")
    if not sep:
        raise ValueError("header not closed")
    data, links, rtype, in_links = {}, [], None, False
    for line in head.splitlines():
        if in_links and line.startswith("- "):
            parts = line[2:].split()
            if len(parts) != 2:
                raise ValueError("bad link: %s" % line)
            links.append(parts)
            continue
        in_links = False
        key, colon, val = line.partition(": ")
        if line == "links:":
            in_links = True
        elif not colon:
            raise ValueError("bad line: %s" % line)
        elif key == "type":
            rtype = json.loads(val)
        else:
            data[key] = json.loads(val)
    if rtype not in SHARED:
        raise ValueError("not a shared type: %r" % rtype)
    body = body.rstrip("\n")
    if body and BODY.get(rtype):
        data[BODY[rtype]] = body
    return {"type": rtype, "slug": data.get("slug"), "data": data, "links": sorted(links)}


def _key(rec):
    return "%s/%s" % (rec["type"], rec["slug"])


def digest(rec):
    return hashlib.sha256(json.dumps([rec["data"], rec["links"]], sort_keys=True).encode()).hexdigest()[:16]


def read_files(root, unreadable=None):
    """{key: record} from the checkout's node files, plus [problems] for files that don't parse. Keys of files that
    exist but can't be read go into `unreadable` (a set), so sync leaves those nodes alone until they're fixed."""
    out, bad = {}, []
    base = nodes_dir(root)
    for rtype in SHARED:
        d = os.path.join(base, rtype)
        for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
            if not name.endswith(".md"):
                continue
            try:
                rec = parse(C.read_text(os.path.join(d, name)))
            except (ValueError, json.JSONDecodeError) as e:
                bad.append("%s/%s: %s" % (rtype, name, e))
                if unreadable is not None:
                    unreadable.add("%s/%s" % (rtype, name[:-3]))
                continue
            if rec["type"] != rtype or rec["slug"] != name[:-3]:
                bad.append("%s/%s: its type or slug does not match where it is" % (rtype, name))
                if unreadable is not None:
                    unreadable.add("%s/%s" % (rtype, name[:-3]))
                continue
            out[_key(rec)] = rec
    return out, bad


def write_file(root, rec):
    if not SLUG_RX.match(rec["slug"] or ""):
        raise ValueError("unsafe slug %r" % rec["slug"])
    C.write_text(os.path.join(nodes_dir(root, True), rec["type"], rec["slug"] + ".md"), render(rec))


# ---------------------------------------------------------------- the graph (omnigraph CLI)

def _scope():
    """--store <uri> for tests (LFG_KNOWLEDGE_STORE), else this machine's dev-graph server with the writer token."""
    store = os.environ.get("LFG_KNOWLEDGE_STORE")
    if store:
        return ["--store", store], {}
    from . import omnigraph as OG
    return ["--server", OG.url(GRAPH), "--graph", OG.cfg()["graphs"][GRAPH]["graph"]], \
        {"OMNIGRAPH_BEARER_TOKEN": OG.tokens()["act-writer"], "OMNIGRAPH_TOKEN": ""}


def _og(args, timeout=120):
    from . import omnigraph as OG
    exe = OG._which("omnigraph")
    if not exe:
        raise RuntimeError("omnigraph not found (Knowledge pack: `lfg add knowledge`)")
    scope, env = _scope()
    cp = C.run([exe] + args[:1] + scope + args[1:] + ["--quiet"], timeout=timeout, env=env)
    if cp.returncode:
        raise RuntimeError("omnigraph %s: %s" % (args[0], (cp.stderr or cp.stdout).strip()[-400:]))
    return cp.stdout


def branches():
    return json.loads(_og(["branch", "list", "--json"]) or "{}").get("branches", [])


def export(name):
    """(nodes {key: record} of every type, edges [[edge, from, to]]) on a branch."""
    nodes, edges = {}, []
    for line in _og(["export", "--branch", name]).splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if "edge" in row:
            edges.append([row["edge"], row["from"], row["to"]])
        else:
            data = {k: v for k, v in (row.get("data") or {}).items() if v is not None and k not in SKIP_FIELDS}
            nodes["%s/%s" % (row["type"], row["id"])] = {"type": row["type"], "slug": row["id"], "data": data,
                                                         "links": []}
    return nodes, edges


def _mutate(name, statements, params):
    if statements:
        decl = ", ".join("$%s: String" % p for p in params)
        _og(["mutate", "--branch", name, "-e", "query w(%s) {\n%s\n}" % (decl, "\n".join(statements)),
             "--params", json.dumps(params), "--json"])


def _load(name, rows):
    if not rows:
        return
    fd, path = tempfile.mkstemp(suffix=".jsonl", prefix="lfg-knowledge-")
    try:
        with os.fdopen(fd, "w") as f:
            f.write("".join(json.dumps(r) + "\n" for r in rows))
        _og(["load", "--branch", name, "--mode", "merge", "--data", path])
    finally:
        os.remove(path)


def ensure_branch(name):
    """Create branch `name` empty. A new branch starts as a copy of main, which holds every repo's old nodes, so it is
    cleared before anyone may read it: callers hold the repo's knowledge lock, and a branch that could not be cleared
    is deleted again rather than left full."""
    if name in branches():
        return False
    _og(["branch", "create", name])
    try:
        _mutate(name, ['delete %s where slug != ""' % t for t in ALL_TYPES], {})
    except RuntimeError:
        _og(["branch", "delete", name])
        raise
    return True


def _lock(root):
    from . import graphs as G
    return G.Lock(C.repo_id(root), ".knowledge.lock")


def ensure_locked(root, timeout=20):
    """ensure_branch for the MCP launcher, which starts beside SessionStart's sync."""
    lock = _lock(root)
    if not lock.acquire(timeout=timeout):
        raise RuntimeError("another knowledge sync held the lock for %ss" % timeout)
    try:
        return ensure_branch(branch_for(root))
    finally:
        lock.release()


# ---------------------------------------------------------------- sync

def _state_path(root):
    rid = C.repo_id(root)
    suffix = branch_for(root)[len(branch(rid)):]  # "" for the main checkout, "--wt-<hash>" for a worktree
    return C.lfg_path("graphs", rid, "knowledge%s.json" % suffix)


def _shared_records(nodes, edges):
    """{key: record} of the shared nodes in an export, each with its outgoing edges as sorted links."""
    graph = {k: r for k, r in nodes.items() if shared(r["type"], r["slug"])}
    by_slug = {r["slug"]: r for r in graph.values()}
    for e, src, dst in edges:
        if src in by_slug:
            by_slug[src]["links"].append([e, dst])
    for r in graph.values():
        r["links"].sort()
    return graph


def sync(root):
    """Bring the files and this checkout's branch level: agents' additions into files, then the files into the graph.
    """
    unreadable = set()
    files, bad = read_files(root, unreadable)
    name = branch_for(root)
    created = ensure_branch(name)
    nodes, edges = export(name)
    graph = _shared_records(nodes, edges)
    loaded = {} if created else (C.read_json(_state_path(root), {}) or {}).get("loaded", {})
    keep = {}  # in the graph but with no usable file: loaded again as they are, never deleted
    written, conflicts = [], []
    for k, rec in sorted(graph.items()):
        g, seen, f = digest(rec), loaded.get(k), files.get(k)
        fd = digest(f) if f else None
        if k in unreadable:  # a bad merge or a hand edit: leave the node until the file is fixed
            keep[k] = rec
            continue
        if g == seen or fd == g:
            continue  # untouched in the graph since the last sync (the file wins), or already level
        if f is not None and fd != seen:
            conflicts.append(k)  # changed on both sides: the file wins
            continue
        try:  # new from an agent, or edited by one while the file stayed as loaded
            write_file(root, rec)
        except ValueError as e:
            bad.append("%s: %s" % (k, e))
            keep[k] = rec
            continue
        files[k] = rec
        written.append(k)
    level = dict(files, **keep)
    changed = sorted((set(level) ^ set(graph)) |
                     {k for k in level if k in graph and digest(level[k]) != digest(graph[k])})
    if changed:
        _rebuild(name, level, nodes, edges, graph)
    C.write_json(_state_path(root), {"loaded": dict({k: digest(r) for k, r in files.items()},
                                                    **{k: loaded[k] for k in keep if k in loaded}),
                                     "synced_at": C.now_iso(), "root": root, "branch": name})
    return {"branch": name, "files": len(files), "written": written, "conflicts": conflicts, "bad": bad,
            "rebuilt": bool(changed), "changed": len(changed)}


def _rebuild(name, files, nodes, edges, graph):
    """Replace the branch's shared nodes with the files' (deleting a node drops its edges), then put back the edges
    from nodes that aren't shared (a PR touching a Component) whose ends still exist."""
    stmts, params = [], {}
    for t in SHARED:
        if t != "Issue":
            stmts.append('delete %s where slug != ""' % t)
    for i, k in enumerate(sorted(k for k in graph if k.startswith("Issue/"))):
        params["s%d" % i] = graph[k]["slug"]
        stmts.append("delete Issue where slug = $s%d" % i)
    _mutate(name, stmts, params)
    kept = {r["slug"] for k, r in nodes.items() if not shared(r["type"], r["slug"])}
    loaded = {r["slug"] for r in files.values()}
    rows = [{"type": r["type"], "data": r["data"]} for _k, r in sorted(files.items())]
    links = {(e, r["slug"], dst) for r in files.values() for e, dst in r["links"] if dst in kept | loaded}
    # edges into a deleted shared node from a kept one went with it; edges between kept nodes never left
    links |= {(e, s, d) for e, s, d in edges if s in kept and d in loaded and d not in kept}
    _load(name, rows + [{"edge": e, "from": s, "to": d} for e, s, d in sorted(links)])


def sync_locked(root):
    """sync, unless another one is already running for this repo (SessionStart and Stop can overlap)."""
    lock = _lock(root)
    if not lock.acquire(blocking=False):
        return {"skipped": "another sync is running"}
    try:
        return sync(root)
    finally:
        lock.release()


def spawn_background(root):
    """`lfg knowledge sync --quiet` detached, from the hooks. Only with the Knowledge pack on."""
    from . import graphs as G
    from . import setup as SU
    if not SU.pack_on("knowledge"):
        return False
    lfg = C.lfg_bin() if os.path.exists(C.lfg_bin()) else os.path.abspath(sys.argv[0])
    with open(os.devnull, "wb") as dn, open(os.path.join(G.gdir(C.repo_id(root)), "knowledge.log"), "ab") as log:
        subprocess.Popen([sys.executable, lfg, "knowledge", "sync", "--quiet"], cwd=root, stdout=dn, stderr=log,
                         stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    return True


def log(root, line):
    """One line in ~/.lfg/graphs/<repo-id>/knowledge.log, for failures the hooks must swallow."""
    try:
        from . import graphs as G
        with open(os.path.join(G.gdir(C.repo_id(root)), "knowledge.log"), "a") as f:
            f.write("%s %s\n" % (C.now_iso(), line))
    except Exception:
        pass


def legacy_current(root, found=None):
    """The run CURRENT names under an old id in ~/.lfg, if it hasn't moved into this checkout yet."""
    for rid in found if found is not None else legacy(root):
        name = C.read_text(C.lfg_path("runs", rid, "CURRENT")).strip()
        if name and os.path.isfile(C.lfg_path("runs", rid, name, "run.json")):
            return name
    return None


def last_sync(root):
    return C.read_json(_state_path(root), {}) or {}


# ---------------------------------------------------------------- taking over a run

def unfinished_runs(root):
    """Runs in this checkout on the checked-out branch that aren't done and aren't current: a teammate's, or this
    person's from another clone, to offer at session start."""
    runs, cur = C.runs_dir(root, create=False), os.path.basename(C.current_run(root) or "")
    now = C.git_branch(root)
    out = []
    for name in sorted(os.listdir(runs), reverse=True) if os.path.isdir(runs) else []:
        meta = C.read_json(os.path.join(runs, name, "run.json"), None)
        if isinstance(meta, dict) and name != cur and meta.get("branch") == now and meta.get("stage") != "done":
            out.append(name)
    return out


# ---------------------------------------------------------------- moving state from before 0.3 into the repo

def legacy(root):
    """What ~/.lfg still holds for this repo under any id it had: {id: {"runs": [...], "docs": [...], "files": [...]}}.
    Only ids derived from this checkout's own remote and path: the stored .lfg/repo-id came with the clone, so a repo
    could name another repo's id in it and have that repo's old runs copied in here."""
    out = {}
    for rid in C.legacy_repo_ids(root):
        runs = [d for d in sorted(glob.glob(C.lfg_path("runs", rid, "*")))
                if os.path.isfile(os.path.join(d, "run.json"))]
        docs_dir = C.lfg_path("repos", rid, "docs")
        docs = sorted(glob.glob(os.path.join(docs_dir, "GLOSSARY.md")) + glob.glob(os.path.join(docs_dir, "adr", "*")))
        files = [p for p in (C.lfg_path("repos", rid, n) for n in ("commands.json", "shipcheck.json"))
                 if os.path.isfile(p)]
        if runs or docs or files:
            out[rid] = {"runs": runs, "docs": docs, "files": files}
    return out


def _place(src, dst, report, label):
    """Copy src to dst. A different file already there stays; src goes beside it as <name>.from-<id><ext>."""
    if os.path.isfile(dst):
        if C.read_text(dst) == C.read_text(src):
            return
        stem, ext = os.path.splitext(dst)
        dst = "%s.from-%s%s" % (stem, label, ext)
        report["kept_both"].append(dst)
    C.ensure_dir(os.path.dirname(dst))
    shutil.copy2(src, dst)
    report["copied"].append(dst)


def migrate(root, dry_run=False):
    """Move runs, glossary, ADRs and commands from ~/.lfg into <checkout>/.lfg. A run folder found under two ids is
    merged file by file (the newer file wins). The originals go to ~/.lfg/backups/migrate-<time>/, never deleted.
    A run folder still holding live /build worktrees (wt/) is copied but left in place."""
    found = legacy(root)
    report = {"from": sorted(found), "to": C.knowledge_dir(root, create=False), "copied": [], "kept_both": [],
              "left": [], "dry_run": dry_run,
              "runs": sorted({os.path.basename(d) for w in found.values() for d in w["runs"]})}
    if dry_run or not found:
        return report
    kdir, me = C.knowledge_dir(root), C.repo_id(root)
    backup = C.lfg_path("backups", "migrate-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    # the current id first: where a glossary or ADR differs, its copy keeps the name and the others go beside it
    for rid, what in sorted(found.items(), key=lambda kv: kv[0] != me):
        for d in what["runs"]:
            target = os.path.join(kdir, "runs", os.path.basename(d))
            for base, dirs, names in os.walk(d):
                dirs[:] = [x for x in dirs if not (base == d and x == "wt")]
                for n in names:
                    src = os.path.join(base, n)
                    dst = os.path.join(target, os.path.relpath(src, d))
                    if not os.path.isfile(dst) or os.path.getmtime(src) > os.path.getmtime(dst):
                        C.ensure_dir(os.path.dirname(dst))
                        shutil.copy2(src, dst)
                        report["copied"].append(dst)
        for p in what["docs"]:
            _place(p, os.path.join(kdir, "docs", os.path.relpath(p, C.lfg_path("repos", rid, "docs"))), report, rid)
        for p in what["files"]:
            _place(p, os.path.join(kdir, os.path.basename(p)), report, rid)
        cur = C.read_text(C.lfg_path("runs", rid, "CURRENT")).strip()
        if cur and not C.current_run(root) and os.path.isdir(os.path.join(kdir, "runs", cur)):
            C.write_text(os.path.join(kdir, "runs", "CURRENT"), cur + "\n")
        moved = [d for d in what["runs"] if not (os.path.isdir(os.path.join(d, "wt")) and
                                                 os.listdir(os.path.join(d, "wt")))]
        report["left"] += sorted(set(what["runs"]) - set(moved))
        moved += [p for p in (C.lfg_path("runs", rid, "CURRENT"), C.lfg_path("repos", rid, "docs"))
                  if os.path.exists(p)] + what["files"]
        for p in moved:  # what stays: shipcheck history and live worktrees, which belong to this machine
            dst = os.path.join(backup, os.path.relpath(p, C.LFG_HOME))
            C.ensure_dir(os.path.dirname(dst))
            shutil.move(p, dst)
    for name in report["runs"]:  # only after every copy: rewriting it earlier makes a stale copy look newest
        p = os.path.join(kdir, "runs", name, "run.json")
        meta = C.read_json(p, {}) or {}
        if meta.get("repo_id") != me:
            meta["repo_id"] = me
            C.write_json(p, meta)
    report["backup"] = backup
    report["unhidden"] = unhide(root)
    C.audit("knowledge-migrate", {"root": root, "from": report["from"], "copied": len(report["copied"])})
    return report


def hidden_by_exclude(root):
    """True when git ignores the folder through the `.lfg/` line older `lfg enable`s put in .git/info/exclude."""
    probe = os.path.join(".lfg", "runs", "x", "01-brief.md")
    return C.run(["git", "check-ignore", "-q", "--no-index", probe], cwd=root, timeout=10).returncode == 0


def unhide(root):
    """Take back that line, through the change ledger (only if LFG added it). Run on the user's word: migrate."""
    from . import claudecfg as CC
    from . import setup as SU
    main = os.path.realpath(C.main_root(root))
    return CC.lines_take_back(os.path.join(main, ".git", "info", "exclude"), SU.SHARED_DIR_LINE, tag="exclude",
                              repo=main)


def take_main_nodes(root):
    """Copy every shared node on dev-graph's main (where LFG kept every repo's nodes before 0.3) into this checkout's
    files. Main can't say which repo a node came from, so the user picks the repos this runs in."""
    graph = _shared_records(*export("main"))
    files, _bad = read_files(root)
    taken = []
    for k, rec in sorted(graph.items()):
        if k not in files and SLUG_RX.match(rec["slug"]):
            write_file(root, rec)
            taken.append(k)
    return taken
