"""Stacked PRs and the epic they belong to, for the dashboard. Read only: GitHub through `gh` (PRs, their checks, how
far behind their parent each is), local git (branches built on another branch before any PR stacks them: a
"preview" stack) and dev-graph's copy of Linear (the epic, its tickets, which blocks which). Nothing is written to
GitHub, Linear or dev-graph."""
import concurrent.futures
import re
import time
import urllib.parse

from . import common as C
from . import review as R

TERMINAL = {"done", "canceled", "duplicate"}
SKIP = re.compile(r"^(review/|pr-\d+$|dependabot/|renovate/)")  # review checkouts, bots: never your stack
LANDED = {"merged_main"}
GONE = {"merged_main", "merged_parent", "closed"}
PASS = {"SUCCESS", "NEUTRAL", "SKIPPED"}
FAIL = {"FAILURE", "ERROR", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE"}


# ---------------------------------------------------------------- one PR

def _checks(roll):
    """(CI, CodeRabbit) from a PR's statusCheckRollup: "pass", "fail", "pending", or None when there is none."""
    ci, rabbit = [], []
    for c in roll or []:
        name = str(c.get("name") or c.get("context") or "")
        if c.get("__typename") == "CheckRun" and (c.get("status") or "COMPLETED") != "COMPLETED":
            res = "pending"
        else:
            v = str(c.get("conclusion") or c.get("state") or "").upper()
            res = "pass" if v in PASS else "fail" if v in FAIL else "pending"
        (rabbit if "coderabbit" in name.lower() else ci).append(res)

    def one(xs):
        return None if not xs else "fail" if "fail" in xs else "pending" if "pending" in xs else "pass"
    return one(ci), one(rabbit)


def summarize(p, default):
    """One PR as the stack shows it. state: draft, open, approved, changes, merged_parent (merged into the branch
    below it, not main yet), merged_main or closed."""
    base = p.get("baseRefName") or ""
    if p.get("state") == "MERGED":
        state = "merged_main" if base == default else "merged_parent"
    elif p.get("state") == "CLOSED":
        state = "closed"
    elif p.get("isDraft"):
        state = "draft"
    else:
        state = {"APPROVED": "approved", "CHANGES_REQUESTED": "changes"}.get(p.get("reviewDecision") or "", "open")
    ci, rabbit = _checks(p.get("statusCheckRollup"))
    branch = p.get("headRefName") or ""
    return {"number": p.get("number"), "title": p.get("title") or "", "url": p.get("url") or "", "branch": branch,
            "base": base, "parent": base, "state": state, "ci": ci, "coderabbit": rabbit, "inferred": False,
            "author": (p.get("author") or {}).get("login", ""),
            "ticket": R.ticket_of(p.get("title"), p.get("body"), branch)}


def _no_pr(branch, parent):
    return {"number": None, "title": "", "url": "", "branch": branch, "base": parent, "parent": parent,
            "state": "no_pr", "ci": None, "coderabbit": None, "inferred": True, "author": "",
            "ticket": R.ticket_of(branch=branch)}


# ---------------------------------------------------------------- stacks

def _by_head(rows, default):
    """{head branch: its PR}: an open PR over a merged one, then the newest. Closed-unmerged PRs are left out."""
    out = {}
    for p in sorted(rows or [], key=lambda p: (p.get("state") == "OPEN", p.get("number") or 0)):
        if p.get("state") != "CLOSED" and p.get("headRefName"):
            out[p["headRefName"]] = summarize(p, default)
    return out


def chains(rows, default, preview=None):
    """Stacks of PRs, bottom (nearest main) first. GitHub's own: a PR whose base is another PR's branch. A preview
    stack also has links `preview` inferred from local git ({branch: the branch it is built on}), for a branch with no
    PR yet or a PR still aimed at main. Only stacks of two or more with something still open are kept."""
    nodes = _by_head(rows, default)
    for b, parent in (preview or {}).items():
        n = nodes.get(b)
        if n is None:
            nodes[b] = _no_pr(b, parent)
        elif n["state"] not in GONE and n["base"] == default:
            n.update(parent=parent, inferred=True)
    for parent in set((preview or {}).values()) - set(nodes) - {default}:  # built on a branch with no PR either
        nodes[parent] = _no_pr(parent, default)
    kids = {}
    for b, n in nodes.items():
        if n["parent"] != default and n["parent"] in nodes and n["parent"] != b:
            kids.setdefault(n["parent"], []).append(b)
    out = []
    for b, n in sorted(nodes.items(), key=lambda x: x[1]["number"] or 10 ** 9):
        if n["parent"] in nodes and n["parent"] != default:
            continue  # not a root
        order, seen, todo = [], set(), [(b, 0)]
        while todo:  # depth first, lowest PR number first
            x, depth = todo.pop()
            if x in seen:
                continue
            seen.add(x)
            order.append(dict(nodes[x], depth=depth))
            todo += [(k, depth + 1) for k in sorted(kids.get(x, []), key=lambda k: nodes[k]["number"] or 10 ** 9,
                                                    reverse=True)]
        if len(order) > 1 and any(p["state"] not in GONE for p in order):
            out.append({"kind": "preview" if any(p["inferred"] for p in order) else "github",
                        "base": n["parent"], "prs": order})
    return out


def _git(root, *a):
    cp = C.run(["git"] + list(a), cwd=root, timeout=15)
    return cp.stdout.split("\n") if cp.returncode == 0 else []


def _skip(branch):
    return bool(SKIP.match(branch))


def infer_parents(root, rows, default, days=30, limit=25):
    """{branch: the branch it is built on}, for recent local branches with no PR yet and open PRs aimed at
    `default`: the nearest open PR branch or unmerged local branch whose tip it contains."""
    if not root:
        return {}
    cut = time.time() - days * 86400
    local = []
    for line in _git(root, "for-each-ref", "--sort=-committerdate", "--format=%(refname:short) %(committerdate:unix)",
                     "refs/heads"):
        name, _, ts = line.rpartition(" ")
        if name and name != default and not _skip(name) and ts.isdigit() and int(ts) >= cut:
            local.append(name)
    have = set(_git(root, "for-each-ref", "--format=%(refname:short)", "refs/heads", "refs/remotes/origin"))
    base = "origin/" + default if "origin/" + default in have else default if default in have else None
    if not base:  # origin's copy first: a stale local main makes every branch look built on old work
        return {}
    merged = {x.strip() for x in _git(root, "branch", "--merged", base, "--format=%(refname:short)")}
    local = [b for b in local if b not in merged][:limit]
    open_ = {p["headRefName"]: p for p in rows or [] if p.get("state") == "OPEN" and p.get("headRefName")
             and not _skip(p["headRefName"])}
    done = {p["headRefName"] for p in rows or [] if p.get("state") != "OPEN"} - set(open_)

    def ref(b):
        return b if b in have else "origin/" + b if "origin/" + b in have else None
    names = set(b for b in list(open_) + local if b not in done and ref(b))
    ahead = {}

    def count(b):  # commits on b that the default branch doesn't have
        if b not in ahead:
            n = (_git(root, "rev-list", "--count", "%s..%s" % (base, ref(b))) or ["0"])[0]
            ahead[b] = int(n) if n.isdigit() else 0
        return ahead[b]
    out = {}
    for b in local:  # your own recent branches: no PR yet, or a PR still aimed at the default branch
        pr = open_.get(b)
        if b not in names or pr and pr.get("baseRefName") != default:
            continue  # GitHub already stacks it
        tips = _git(root, "for-each-ref", "--merged", ref(b), "--format=%(refname:short)", "refs/heads",
                    "refs/remotes/origin")
        under = {t[7:] if t.startswith("origin/") else t for t in tips if t} & names - {b}
        under = [p for p in under if 0 < count(p) < count(b)]
        if under:
            out[b] = max(under, key=count)
    return out


# ---------------------------------------------------------------- how far behind

_BEHIND = {}


def behind(gh_repo, base, head, max_age=300):
    """Commits on `base` (the branch below) that `head` doesn't have yet, from GitHub's compare; None when unknown."""
    key = (gh_repo, base, head)
    hit = _BEHIND.get(key)
    if hit and time.time() - hit[0] < max_age:
        return hit[1]
    try:
        j = R.gh_json(["api", "repos/%s/compare/%s...%s" % (gh_repo, urllib.parse.quote(base, safe="/"),
                                                            urllib.parse.quote(head, safe="/"))])
        n = j.get("behind_by") if isinstance(j, dict) else None
    except R.ReviewError:
        n = None
    _BEHIND[key] = (time.time(), n)
    return n


def _behind_local(root, base, head):
    n = (_git(root, "rev-list", "--count", "%s..%s" % (head, base)) or [""])[0] if root else ""
    return int(n) if n.isdigit() else None


# ---------------------------------------------------------------- the epic

def _num(key):
    m = re.search(r"(\d+)$", key or "")
    return int(m.group(1)) if m else 10 ** 9


def _pr_for(rows, default):
    """{ticket: the PR for it}: an open one first, then one merged into main, then the newest."""
    rank = {"merged_main": 1, "merged_parent": 2, "closed": 3}
    out = {}
    for p in rows or []:
        s = summarize(p, default)
        t = s["ticket"]
        if t and (t not in out or (rank.get(s["state"], 0), -(s["number"] or 0)) <
                  (rank.get(out[t]["state"], 0), -(out[t]["number"] or 0))):
            out[t] = s
    return out


def epic_items(issues, blocks, stacks, rows, default, runs, here=None):
    """The epic's tickets in build order: a ticket after any it is blocked by, then landed ones first, then by where
    its PR sits in a stack, then by ticket number. Each with its PR, its place in the stack, its LFG run, whether it
    is done (Linear says so or its PR merged into main), `here` (the work in front of you) and `next`."""
    prs = _pr_for(rows, default)
    place = {}
    for si, s in enumerate(stacks or []):
        for pi, p in enumerate(s["prs"]):
            if p["number"]:
                place[p["number"]] = (si, pi, len(s["prs"]))
    items = {}
    for i in issues:
        k = i["key"]
        pr = prs.get(k)
        pos = place.get(pr["number"]) if pr else None
        done = str(i.get("status") or "") in TERMINAL or bool(pr and pr["state"] in LANDED)
        items[k] = dict(i, pr=pr, position=[pos[1] + 1, pos[2]] if pos else None, stack=pos[0] if pos else None,
                        run=(runs or {}).get(k), done=done, here=k == here, next=False)
    waits = {k: set() for k in items}
    for a, b in blocks or []:
        if a in items and b in items and a != b:
            waits[b].add(a)

    def rank(k):
        x = items[k]
        return (not x["done"], x["stack"] if x["stack"] is not None else 10 ** 6,
                x["position"][0] if x["position"] else 0, _num(k))
    order, left = [], set(items)
    while left:
        free = [k for k in left if not waits[k] & left] or list(left)  # a loop of blockers: fall back to rank
        k = min(free, key=rank)
        order.append(items[k])
        left.discard(k)
    at = next((n for n, x in enumerate(order) if x["here"]), -1)
    nxt = next((x for x in order[at + 1:] if not x["done"] and not x["here"]), None) or \
        next((x for x in order if not x["done"] and not x["here"]), None)
    if nxt:
        nxt["next"] = True
    return order


def _key(slug, ref=None):
    for v in (ref, re.sub(r"^(iss|epc)-", "", slug or "")):
        if v and re.fullmatch(r"[A-Za-z][A-Za-z0-9]+-\d+", v):
            return v.upper()
    return ""


def _graph(rid):
    """dev-graph's copy of Linear: issues, epics, which epic or parent issue holds which issue, and which blocks
    which, on main and this repo's branch. Cached briefly."""
    from . import dash

    def read():
        branches = [None] + ([dash._dev_branch(rid)] if rid else [])
        issues, groups, blocks = {}, {}, set()
        for br in branches:
            for i in dash._rows(dash._list("dev-graph", "Issue", ["slug", "title", "status", "legacyRef"], None, 1000,
                                           br)):
                k = _key(i.get("slug"), i.get("legacyRef"))
                if k:
                    issues[k] = {"key": k, "title": i.get("title") or "", "status": i.get("status") or ""}
            for e in dash._rows(dash._list("dev-graph", "Epic", ["slug", "title", "legacyRef"], None, 200, br)):
                k = _key(e.get("slug"), e.get("legacyRef"))
                if k:
                    groups.setdefault(k, {"key": k, "title": e.get("title") or "", "kind": "epic", "members": set()})
            for edge, src in (("epicContainsIssue", "Epic"), ("epicParentChildIssue", "Epic"),
                              ("issueParentChildIssue", "Issue"), ("issueBlocksIssue", "Issue")):
                q = ("query l() { match { $a: %s $a %s $b $b: Issue } return { $a.slug as a, $a.legacyRef as ar, "
                     "$b.slug as b, $b.legacyRef as br } limit 2000 }" % (src, edge))
                for r in dash._rows(dash._og(lambda OG, q=q, br=br: OG.read("dev-graph", q, "l", branch=br))):
                    a, b = _key(r.get("a"), r.get("ar")), _key(r.get("b"), r.get("br"))
                    if not a or not b:
                        continue
                    if edge == "issueBlocksIssue":
                        blocks.add((a, b))
                    else:
                        g = groups.setdefault(a, {"key": a, "title": "", "kind": "epic" if src == "Epic" else
                                                  "parent", "members": set()})
                        g["members"].add(b)
        for k, g in groups.items():
            g["title"] = g["title"] or (issues.get(k) or {}).get("title", "")
        return {"issues": issues, "groups": groups, "blocks": sorted(blocks)}
    return dash.cached("stack-graph:%s" % rid, 120, read)


def epic_for(rid, ticket):
    """The epic (or parent issue) holding `ticket`: the parent issue when there is one, it is closer; else its epic.
    A ticket that is itself an epic or parent is its own. None when dev-graph doesn't know."""
    g = _graph(rid)
    t = (ticket or "").upper()
    if t in g["groups"] and g["groups"][t]["members"]:
        return g["groups"][t]
    holding = [x for x in g["groups"].values() if t in x["members"]]
    holding.sort(key=lambda x: (x["kind"] != "parent", len(x["members"])))
    return holding[0] if holding else None


# ---------------------------------------------------------------- the view

_ROWS = {}


def _pr_rows(gh_repo, max_age=120):
    hit = _ROWS.get(gh_repo)
    if hit and time.time() - hit[0] < max_age:
        return hit[1]
    rows = R.gh_json(["pr", "list", "-R", gh_repo, "--state", "all", "--limit", "150", "--json",
                      "number,title,url,headRefName,baseRefName,state,isDraft,reviewDecision,statusCheckRollup,"
                      "author,body"], timeout=90)
    for p in rows or []:
        p["body"] = (p.get("body") or "")[:4000]
    _ROWS[gh_repo] = (time.time(), rows or [])
    return rows or []


def _default_branch(gh_repo, root):
    from . import dash
    gb = dash.git_branches(root) if root else None
    if gb and gb.get("default"):
        return gb["default"]

    def ask():
        try:
            return (R.gh_json(["repo", "view", gh_repo, "--json", "defaultBranchRef"]).get("defaultBranchRef") or
                    {}).get("name") or "main"
        except R.ReviewError:
            return "main"
    return dash.cached("default-branch:" + gh_repo, 3600, ask)


def _origin(root):
    url = "\n".join(_git(root, "remote", "get-url", "origin")).strip() if root else ""
    m = R.REMOTE.search(url)
    return m.group(1) if m else ""


def _root_for(gh_repo):
    from . import dash
    for r in dash.repos()["repos"]:
        if gh_repo.lower() in R.github_names(r["root"]):
            return r["id"], r["root"]
    return None, None


def _runs_by_ticket(rid):
    from . import dash
    out = {}
    if not rid:
        return out
    keys = [k for k, _, _ in dash.STAGES]
    for r in dash.runs(rid)["runs"]:
        t = (r.get("ticket") or "").upper()
        if t and t not in out:  # newest first
            # counted as the run page counts (runPlace): done or done outside LFG, out of the steps not skipped
            st, skip, outside = r.get("stages") or {}, r.get("skipped") or {}, r.get("outside") or {}
            out[t] = {"run": r["run"], "done": sum(1 for k in keys if st.get(k) or outside.get(k)),
                      "total": sum(1 for k in keys if k not in skip),
                      "branch": r.get("branch") or "", "current": bool(r.get("current"))}
    return out


def view(rid=None, gh=None, pr=None, run=None, ticket=None):
    """What the stack strip and the epic view show. Focus (the "you are here"): `pr`, else `run`, else `ticket`, else
    the repo's current run, else its checked-out branch. Returns the focused stack, every stack in the repo, and
    the epic holding the focused ticket."""
    from . import dash
    root = dash.repo_root(rid) if rid else None
    if gh and (not root or gh.lower() not in R.github_names(root)):  # a PR page of a repo other than the picked one
        rid, root = _root_for(gh)
    gh = gh or _origin(root)
    if not gh:
        return {"available": False, "why": "This repo has no GitHub remote, so there are no PRs to stack."}
    try:
        rows = _pr_rows(gh)
    except R.ReviewError as e:
        return {"available": False, "why": str(e)}
    default = _default_branch(gh, root)
    preview = dash.cached("stack-preview:%s" % root, 120, lambda: infer_parents(root, rows, default)) if root else {}
    stacks = chains(rows, default, preview)
    runs = _runs_by_ticket(rid)
    here = {"pr": None, "branch": "", "ticket": (ticket or "").upper(), "run": run or ""}
    if pr:
        p = next((x for x in rows if str(x.get("number")) == str(pr)), None)
        if p:
            s = summarize(p, default)
            here.update(pr=s["number"], branch=s["branch"], ticket=s["ticket"])
    elif run and rid:
        d = dash._run_dir(rid, run)
        if d:
            s = dash._run_summary(d)
            here.update(branch=s.get("branch") or "", ticket=(s.get("ticket") or "").upper())
    elif not ticket and root:
        cur = next((r for r in runs.values() if r["current"]), None)
        here.update(branch=(cur or {}).get("branch") or C.git_branch(root) or "",
                    run=(cur or {}).get("run", ""))
    if here["branch"] and not here["ticket"]:
        here["ticket"] = R.ticket_of(branch=here["branch"])
    if here["branch"] and not here["pr"]:
        p = next((x for x in rows if x.get("headRefName") == here["branch"] and x.get("state") == "OPEN"), None)
        here["pr"] = p["number"] if p else None

    def has(s):
        return any((here["pr"] and p["number"] == here["pr"]) or (here["branch"] and p["branch"] == here["branch"])
                   for p in s["prs"])
    focus = next((s for s in stacks if has(s)), None)
    every = [p for s in stacks for p in s["prs"]]
    for s in stacks:
        for p in s["prs"]:
            p["here"] = bool(focus is s and ((here["pr"] and p["number"] == here["pr"]) or
                                             (here["branch"] and p["branch"] == here["branch"])))
            p["run"] = runs.get(p["ticket"]) if p["ticket"] else None

    def lag(p):
        if p["state"] in GONE:
            return None
        if p["number"] and not p["inferred"]:
            return behind(gh, p["parent"], p["branch"])
        return _behind_local(root, p["parent"], p["branch"])
    with concurrent.futures.ThreadPoolExecutor(8) as pool:  # one GitHub compare each: side by side
        for p, n in zip(every, pool.map(lag, every)):
            p["behind"] = n
    epic = None
    why = None
    if here["ticket"]:
        try:
            g = epic_for(rid, here["ticket"])
        except Exception as e:  # dev-graph down: the stacks still show
            g, why = None, "dev-graph: %s" % e
        if g:
            gr = _graph(rid)
            issues = [gr["issues"].get(k) or {"key": k, "title": "", "status": ""} for k in g["members"]]
            epic = {"key": g["key"], "title": g["title"], "kind": g["kind"],
                    "items": epic_items(issues, gr["blocks"], stacks, rows, default, runs, here["ticket"]),
                    "ordered_by_blocks": any(a in g["members"] and b in g["members"] for a, b in gr["blocks"])}
    if not why:
        why = dash.og_access("dev-graph") if here["ticket"] and not epic else None
    return {"available": True, "gh_repo": gh, "default": default, "here": here, "stack": focus, "stacks": stacks,
            "epic": epic, "epic_why": why,
            "linear_workspace": (C.config()["linear"].get("workspace") or "")}
