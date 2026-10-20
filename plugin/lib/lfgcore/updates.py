"""`lfg update`: is there newer LFG code, and install it.

Three places code can be newer than what's installed in ~/.lfg: your fork (`origin`), the project you forked
(`upstream`), and commits in your checkout that were never installed. `check` asks git (fetch only, nothing
changes); `apply` brings the checkout's main up to date with both, runs the tests, pushes main to your fork and
installs it. Applying is yours: the guard keeps agents from running it.

The upstream merge never happens on main: it runs on an `lfg-update/...` branch in its own worktree, and main only
fast-forwards to that branch once it is merged and tested. A merge that conflicts stays there, half done, for you
(or Claude) to finish; the next apply picks it up from that branch.
"""
import json
import os
import subprocess
import sys
import time

from . import common as C
from . import worktree as W

BRANCH = "main"
HELD = "lfg-update/"  # branches where an upstream merge is in progress or waiting to be installed
TESTS = [sys.executable, "-m", "unittest", "discover", "-s", "tests"]


def _state_path():
    return C.lfg_path("state", "source.json")


def remember_source(root):
    """Called by `lfg setup`: the checkout this install came from, so the installed copy can find it again."""
    if os.path.exists(os.path.join(root, ".git")):
        C.ensure_dir(os.path.dirname(_state_path()))
        C.write_json(_state_path(), {"path": os.path.realpath(root), "installed_at": C.now_iso(),
                                     "installed_head": _git(root, "rev-parse", "HEAD").stdout.strip()})


def source():
    p = (C.read_json(_state_path(), {}) or {}).get("path")
    if p and os.path.exists(os.path.join(p, ".git")):
        return p
    if os.path.exists(os.path.join(C.LFG_ROOT, ".git")):
        return C.LFG_ROOT
    return None


def _git(root, *args, timeout=60):
    return C.run(["git", *args], cwd=root, timeout=timeout)


def _count(root, a, b, *also):
    """Commits in b that a (and every ref in also) doesn't have."""
    cp = _git(root, "rev-list", "--count", b, "^" + a, *["^" + x for x in also])
    return int(cp.stdout.strip()) if cp.returncode == 0 and cp.stdout.strip().isdigit() else 0


def _log(root, a, b, *also, n=8):
    cp = _git(root, "log", "--format=%h %s", "-n", str(n), b, "^" + a, *["^" + x for x in also])
    return _lines(cp)


def _lines(cp):
    return [ln for ln in (cp.stdout or "").splitlines() if ln]


def _remote_url(root, name):
    return _git(root, "remote", "get-url", name).stdout.strip()


def _repo_name(url):
    """owner/repo from a GitHub-style URL (https or ssh), else the URL."""
    url = url.rstrip("/")
    tail = (url[:-4] if url.endswith(".git") else url).replace(":", "/").split("/")
    return "/".join(tail[-2:]) if len(tail) >= 2 and tail[-2] else url


def _held_all(root):
    """Every lfg-update/ branch, newest first: {branch, worktree, state, files, prompt, ahead}. state is "conflict"
    (a merge in progress), "uncommitted" (fixed but not committed) or "ready"; ahead is commits main doesn't have."""
    trees = {w["branch"]: w["path"] for w in W.listing(root) if os.path.isdir(w["path"])}
    for b in _lines(_git(root, "for-each-ref", "--sort=-committerdate", "--format=%(refname:short)",
                         "refs/heads/" + HELD)):
        wt = trees.get(b, "")
        h = {"branch": b, "worktree": wt, "state": "ready", "files": [], "prompt": "", "ahead": _count(root, BRANCH, b)}
        unmerged = _lines(_git(wt, "diff", "--name-only", "--diff-filter=U")) if wt else []
        if unmerged:
            h.update(state="conflict", files=unmerged)
        elif wt and (_git(wt, "rev-parse", "-q", "--verify", "MERGE_HEAD").returncode == 0
                     or _git(wt, "status", "--porcelain", "--untracked-files=no").stdout.strip()):
            h.update(state="uncommitted", files=_lines(_git(wt, "diff", "--name-only", "HEAD")))
        if h["state"] != "ready":
            h["prompt"] = fix_prompt(h, _repo_name(_remote_url(root, "upstream")) or "the original LFG")
        yield h


def held(root):
    """The newest lfg-update/ branch with work main doesn't have: a merge to finish, or one ready to install."""
    return next((h for h in _held_all(root) if h["state"] != "ready" or h["ahead"]), None)


def fix_prompt(h, upstream):
    """One line to hand Claude: finish the merge on the held branch. Claude can commit there; it never merges."""
    files = ", ".join(h["files"][:20]) or "the files git status lists"
    where = "In %s (branch %s), LFG's update is part way through merging %s's main (upstream/main)" % (
        h["worktree"], h["branch"], upstream)
    todo = ("and these files conflict: %s. Resolve each conflict keeping both sides' changes, run" % files
            if h["state"] == "conflict" else "and the conflicts look resolved but aren't committed. Check them, run")
    return ("%s %s `python3 -m unittest discover -s tests` there until it passes, then `git add` the files and "
            "`git commit --no-edit` to finish the merge. Don't run git merge, rebase or push, and don't touch main; "
            "I'll finish the update after." % (where, todo))


_CACHE = {"ts": 0, "data": None}


def check(max_age=60, fetch=True):
    """What's newer than the installed copy. Cached for max_age seconds; fetch=False skips asking GitHub."""
    if _CACHE["data"] and time.time() - _CACHE["ts"] < max_age:
        return _CACHE["data"]
    root = source()
    if not root:
        return {"available": False, "why": "LFG wasn't installed from a git checkout, so there is nothing to compare"}
    out = {"available": True, "source": root, "remotes": {}, "errors": []}
    remotes = [r for r in ("origin", "upstream") if _remote_url(root, r)]
    if fetch:
        for r in remotes:
            cp = _git(root, "fetch", "-q", r, BRANCH, timeout=60)
            if cp.returncode:
                out["errors"].append("couldn't reach %s: %s" % (r, (cp.stderr or "").strip()[-200:]))
    installed = (C.read_json(_state_path(), {}) or {}).get("installed_head") or ""
    head = _git(root, "rev-parse", BRANCH).stdout.strip()
    for r in remotes:
        # Each commit counts once: upstream's are the ones your fork doesn't have yet either, so an upstream merge
        # already made on the fork shows as the fork's, not as both.
        ref = "%s/%s" % (r, BRANCH)
        also = ["origin/" + BRANCH] if r == "upstream" and "origin" in remotes else []
        url = _remote_url(root, r)
        out["remotes"][r] = {"url": url, "name": _repo_name(url), "new": _count(root, BRANCH, ref, *also),
                             "commits": _log(root, BRANCH, ref, *also)}
    out["sources"] = [r for r in ("upstream", "origin") if r in remotes and out["remotes"][r]["new"]]
    out["held"] = held(root)
    out["not_installed"] = _count(root, installed, BRANCH) if installed and head else 0
    out["not_installed_commits"] = _log(root, installed, BRANCH) if out["not_installed"] else []
    out["unpushed"] = _count(root, "origin/%s" % BRANCH, BRANCH) if "origin" in remotes else 0
    out["current_branch"] = _git(root, "branch", "--show-current").stdout.strip()
    out["dirty"] = bool(_git(root, "status", "--porcelain", "--untracked-files=no").stdout.strip())
    out["ready"] = bool(out["sources"] or out["not_installed"] or (out["held"] or {}).get("state") == "ready")
    out["checked_at"] = C.now_iso()
    out["job"] = job()
    _CACHE.update(ts=time.time(), data=out)
    return out


# ---------------------------------------------------------------- applying (user-only)

def _job_path():
    return C.lfg_path("state", "update-job.json")


def job():
    j = C.read_json(_job_path(), None)
    if j and j.get("status") == "running":
        try:
            os.kill(int(j.get("pid")), 0)
        except (OSError, TypeError, ValueError):
            j.update(status="failed", why="the update stopped without finishing")
    return j


def start():
    """Run `lfg update apply` detached (the dashboard's Update button)."""
    j = job()
    if j and j.get("status") == "running":
        return {"started": False, "note": "An update is already running."}
    with open(os.devnull, "wb") as dn:
        subprocess.Popen([sys.executable, os.path.join(C.PLUGIN_ROOT, "bin", "lfg"), "update", "apply"],
                         stdout=dn, stderr=dn, stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    return {"started": True}


def _tidy(root, branch):
    """Drop a held branch main already has, and its worktree if it is clean. Never forces."""
    try:
        W.remove(root, branch)
    except (ValueError, RuntimeError):
        pass
    _git(root, "branch", "-d", branch)


def apply(log=print):
    """Bring the checkout's main up to date with your fork, then with the upstream project, test it, push it to your
    fork, install it. In that order, so what gets installed always has both. The upstream merge runs on a held branch
    in its own worktree; main moves only once that is merged and tested. Stops at the first problem: uncommitted
    changes, another branch checked out, a merge that conflicts (left on the held branch), failing tests."""
    root = source()
    steps = []
    j = {"status": "running", "pid": os.getpid(), "started": C.now_iso(), "steps": steps, "why": ""}

    def say(msg):
        steps.append(msg)
        C.write_json(_job_path(), j)
        log(msg)

    def fail(why, conflict=None):
        j.update(status="failed", why=why, ended=C.now_iso(), conflict=conflict)
        C.write_json(_job_path(), j)
        log("stopped: " + why)
        if conflict:
            log("conflicting files: " + ", ".join(conflict["files"]))
            log("hand this to Claude to fix it:\n" + conflict["prompt"])
        _CACHE.update(ts=0, data=None)
        return j

    C.ensure_dir(os.path.dirname(_job_path()))
    if not root:
        return fail("LFG wasn't installed from a git checkout")
    say("Checking %s" % root)
    if _git(root, "branch", "--show-current").stdout.strip() != BRANCH:
        return fail("%s has another branch checked out; switch it to %s first" % (root, BRANCH))
    if _git(root, "status", "--porcelain", "--untracked-files=no").stdout.strip():
        return fail("%s has uncommitted changes; commit or stash them first" % root)
    before = _git(root, "rev-parse", "HEAD").stdout.strip()
    was_installed = (C.read_json(_state_path(), {}) or {}).get("installed_head") or before
    has_up = bool(_remote_url(root, "upstream"))
    up_name = _repo_name(_remote_url(root, "upstream")) if has_up else ""
    for r in ("origin", "upstream"):
        if not _remote_url(root, r):
            continue
        say("Getting %s's latest" % r)
        if _git(root, "fetch", "-q", r, BRANCH, timeout=120).returncode:
            return fail("couldn't reach %s" % r)
    if _remote_url(root, "origin") and _count(root, BRANCH, "origin/" + BRANCH):
        say("Bringing in your fork's new commits")
        if _git(root, "merge", "--ff-only", "-q", "origin/" + BRANCH).returncode:
            return fail("your checkout and your fork have both moved on; merge them by hand once")
    for x in list(_held_all(root)):
        if x["state"] == "ready" and not x["ahead"]:
            _tidy(root, x["branch"])  # main already has it
    h = held(root)
    if h and h["state"] != "ready":
        return fail("the merge of %s's changes on %s isn't finished yet (%s)" % (up_name, h["branch"], h["state"]), h)
    wt, branch, made = "", "", False
    if h or (has_up and _count(root, BRANCH, "upstream/" + BRANCH)):
        if h:
            branch = h["branch"]
            say("Picking up %s" % branch)
            wt = h["worktree"] or W.new(root, branch)["path"]
        else:
            sha = _git(root, "rev-parse", "--short=7", "upstream/" + BRANCH).stdout.strip()
            branch, made = HELD + "upstream-" + sha, True
            say("Merging %s's new commits on %s, away from main" % (up_name, branch))
            try:
                wt = W.new(root, branch, base=BRANCH)["path"]
            except (ValueError, RuntimeError) as e:
                return fail("couldn't make a worktree for the merge: %s" % e)
        for ref in [BRANCH] + (["upstream/" + BRANCH] if has_up else []):
            if _count(root, branch, ref) and _git(wt, "merge", "--no-edit", "-q", ref).returncode:
                h = held(root)
                if not h or h["state"] == "ready":  # git refused for another reason (it would overwrite a file)
                    return fail("merging %s into %s failed; nothing changed on main" % (ref, branch))
                return fail("%s's changes conflict with yours in %d file(s). Nothing changed on main or was "
                            "installed; the half-done merge is on %s in %s" % (up_name, len(h["files"]), branch, wt),
                            h)
    say("Running LFG's tests")
    t = C.run(TESTS, cwd=wt or root, timeout=900)
    if t.returncode:
        _git(root, "reset", "--keep", before)
        if made:
            _tidy(root, branch)
            _git(root, "branch", "-D", branch)  # only the merge we just made, nothing of yours
        tail = ((t.stderr or "") + (t.stdout or "")).strip().splitlines()[-12:]
        return fail("tests failed%s, so the update was undone and nothing was installed:\n%s"
                    % (" on %s" % branch if branch and not made else "", "\n".join(tail)))
    if branch:
        if _git(root, "merge", "--ff-only", "-q", branch).returncode:
            return fail("couldn't move main to %s; nothing was installed" % branch)
        _tidy(root, branch)
    if _remote_url(root, "origin") and _count(root, "origin/" + BRANCH, BRANCH):
        say("Saving it to your fork")
        if _git(root, "push", "-q", "origin", BRANCH, timeout=120).returncode:
            say("Couldn't push to your fork; installing anyway (push it later)")
    say("Installing")
    cp = C.run([sys.executable, os.path.join(root, "plugin", "bin", "lfg"), "setup", "--yes"], cwd=root, timeout=600)
    if cp.returncode:
        return fail("install failed: %s" % ((cp.stderr or cp.stdout).strip()[-400:]))
    _CACHE.update(ts=0, data=None)
    after = _git(root, "rev-parse", "HEAD").stdout.strip()
    j.update(status="done", ended=C.now_iso(), from_head=was_installed[:12], to_head=after[:12],
             changes=_log(root, was_installed, after, n=30))
    say("Installed. LFG commands and the dashboard use it now; start a new Claude Code session for new skills")
    return j


SOURCE_LABEL = {"upstream": "the original LFG", "origin": "your fork"}


def human(d):
    if not d.get("available"):
        print(d.get("why"))
        return
    R = d["remotes"]
    if d.get("sources"):
        print("new from: " + " and ".join("%s (%s)" % (SOURCE_LABEL[r], R[r]["name"]) for r in d["sources"]))
    for r, v in R.items():
        print("%-9s %s new commit(s)  (%s)" % (r, v["new"], v["url"]))
        for c in v["commits"]:
            print("            " + c)
    if d["not_installed"]:
        print("checkout  %d commit(s) on %s not installed yet" % (d["not_installed"], BRANCH))
    h = d.get("held")
    if h and h["state"] != "ready":
        print("\nmerge not finished on %s (%s), in %s" % (h["branch"], h["state"], h["worktree"]))
        for f in h["files"]:
            print("  conflict  " + f)
        print("\nHand this to Claude to fix it, then run `lfg update apply`:\n\n" + h["prompt"])
    elif h:
        print("merged and committed on %s: `lfg update apply` finishes from it" % h["branch"])
    for e in d["errors"]:
        print("!! " + e)
    if not (h and h["state"] != "ready"):
        print("update ready: run `lfg update apply`" if d["ready"] else "up to date")


def as_json(d):
    return json.dumps(d, separators=(",", ":"))
