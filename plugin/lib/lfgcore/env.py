"""The Environment page: every repo and worktree on this machine, and what LFG runs in the background.

Repos are found from three places: the folders your Claude Code sessions ran in, the repos LFG knows, and the git
repos directly under the folders those live in (e.g. ~/code). Each worktree gets its branch, uncommitted files,
commits no remote has, when it was last touched and when a session last ran there. Only git is read; the one change
it makes is `git worktree prune`, which drops git's records of worktree folders that are already gone.
"""
import concurrent.futures
import os
import time

from . import common as C
from . import sessions as SS


def _git(cwd, *args, timeout=20):
    return C.run(["git", *args], cwd=cwd, timeout=timeout)


def _roots():
    """Main checkouts: from sessions, LFG's own list, and sibling repos of those."""
    seen, parents = set(), set()
    for s in SS.listing(hidden=True)["sessions"]:
        if s.get("root"):
            seen.add(os.path.realpath(s["root"]))
    seen |= {os.path.realpath(r) for r in C.enabled_state()["repos"]}
    for r in list(seen):
        parents.add(os.path.dirname(r))
    for p in parents:
        try:
            names = os.listdir(p)
        except OSError:
            continue
        for n in names:
            d = os.path.join(p, n)
            if os.path.isdir(os.path.join(d, ".git")):
                seen.add(os.path.realpath(d))
    return sorted(r for r in seen if os.path.isdir(os.path.join(r, ".git")))


def _worktrees(root):
    cp = _git(root, "worktree", "list", "--porcelain")
    out, cur = [], None
    for line in (cp.stdout or "").splitlines() + [""]:
        if not line:
            if cur:
                out.append(cur)
            cur = None
            continue
        k, _, v = line.partition(" ")
        if k == "worktree":
            cur = {"path": v, "branch": "", "head": "", "detached": False, "missing": False, "locked": False}
        elif cur is None:
            continue
        elif k == "branch":
            cur["branch"] = v.replace("refs/heads/", "", 1)
        elif k == "HEAD":
            cur["head"] = v[:9]
        elif k == "detached":
            cur["detached"] = True
        elif k == "prunable":
            cur["missing"] = True
        elif k == "locked":
            cur["locked"] = True
    return out


def _detail(w, main):
    p = w["path"]
    w["main"] = os.path.realpath(p) == os.path.realpath(main)
    if w["missing"] or not os.path.isdir(p):
        w.update(missing=True, dirty=0, unpushed=0, touched=None)
        return w
    st = _git(p, "status", "--porcelain")
    w["dirty"] = len([ln for ln in (st.stdout or "").splitlines() if ln.strip()])
    up = _git(p, "rev-list", "--count", "HEAD", "--not", "--remotes")
    w["unpushed"] = int(up.stdout.strip()) if up.returncode == 0 and up.stdout.strip().isdigit() else 0
    last = _git(p, "log", "-1", "--format=%cI %s")
    w["last_commit"], _, w["last_subject"] = (last.stdout or "").strip().partition(" ")
    try:
        w["touched"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(p)))
    except OSError:
        w["touched"] = None
    w["ticket"] = SS._ticket(w["branch"])
    return w


def snapshot():
    """Every repo with its worktrees, and LFG's background pieces."""
    last_session, count = {}, {}
    for s in SS.listing(hidden=True)["sessions"]:
        k = os.path.realpath(s["cwd"]) if s.get("cwd") else ""
        count[k] = count.get(k, 0) + 1
        if s["modified"] > last_session.get(k, ""):
            last_session[k] = s["modified"]
    repos, jobs = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for root in _roots():
            wts = _worktrees(root)
            repos.append({"name": os.path.basename(root), "root": root, "worktrees": wts,
                          "enabled": C.is_enabled(root)})
            jobs += [pool.submit(_detail, w, root) for w in wts]
        for j in jobs:
            j.result()
    for r in repos:
        for w in r["worktrees"]:
            k = os.path.realpath(w["path"])
            w["last_session"] = last_session.get(k)
            w["sessions"] = count.get(k, 0)
            w["safe_to_delete"] = (not w["main"] and not w["missing"] and not w["locked"] and not w["dirty"]
                                   and not w["unpushed"])
        r["worktrees"].sort(key=lambda w: (not w["main"], -(_ts(w.get("last_session") or w.get("touched")))))
    return {"repos": repos, "services": services(), "checked_at": C.now_iso()}


def only(snap, root):
    """The snapshot with just root's repo and its worktrees (root None: all of them)."""
    if not root or not snap.get("repos"):
        return snap
    want = os.path.realpath(root)
    return dict(snap, repos=[r for r in snap["repos"] if os.path.realpath(r["root"]) == want])


def _ts(s):
    try:
        return time.mktime(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S"))
    except (TypeError, ValueError):
        return 0


def _du(path):
    cp = C.run(["du", "-sk", path], timeout=30)
    try:
        return int(cp.stdout.split()[0]) * 1024
    except (IndexError, ValueError):
        return None


def services():
    from . import headroom as HR
    from . import omnigraph as OG
    from . import updates as U
    up = U.check(fetch=False)
    rows = [
        {"name": "Headroom proxy", "ok": HR.live(timeout=1),
         "detail": "every Claude Code session goes through it" if HR.routed() else "running, but Claude Code "
                   "doesn't go through it" if HR.live(timeout=1) else "not running",
         "fix": "launchctl kickstart -k gui/$(id -u)/dev.lfg.headroom"},
    ]
    for name in ("dev-graph", "second-brain"):
        ok = OG.ready(name, timeout=1)
        rows.append({"name": name, "ok": ok, "detail": "saved decisions and learnings" if name == "dev-graph"
                     else "your notes", "fix": "lfg omnigraph restart %s" % name})
    rows.append({"name": "LFG %s" % C.VERSION, "ok": not up.get("ready"),
                 "detail": "update ready" if up.get("ready") else "up to date (as of the last check)",
                 "fix": "lfg update apply"})
    disk = [{"what": "LFG's data (~/.lfg)", "bytes": _du(C.LFG_HOME)},
            {"what": "Claude Code sessions (~/.claude/projects)", "bytes": _du(SS.PROJECTS)}]
    return {"rows": rows, "disk": disk}


def prune(root):
    """`git worktree prune` for one repo: forgets worktrees whose folders are already gone. Touches no files."""
    if not os.path.isdir(os.path.join(root, ".git")):
        raise ValueError("not a main checkout: %s" % root)
    before = sum(1 for w in _worktrees(root) if w["missing"])
    cp = _git(root, "worktree", "prune")
    if cp.returncode:
        raise ValueError((cp.stderr or cp.stdout).strip())
    return {"root": root, "forgot": before}
