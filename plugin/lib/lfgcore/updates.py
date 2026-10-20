"""`lfg update`: is there newer LFG code, and install it.

Three places code can be newer than what's installed in ~/.lfg: your fork (`origin`), the project you forked
(`upstream`), and commits in your checkout that were never installed. `check` asks git (fetch only, nothing
changes); `apply` brings the checkout's main up to date with both, runs the tests, pushes main to your fork and
installs it. Applying is yours: the guard keeps agents from running it.
"""
import json
import os
import subprocess
import sys
import time

from . import common as C

BRANCH = "main"


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


def _count(root, a, b):
    """Commits in b that a doesn't have."""
    cp = _git(root, "rev-list", "--count", "%s..%s" % (a, b))
    return int(cp.stdout.strip()) if cp.returncode == 0 and cp.stdout.strip().isdigit() else 0


def _log(root, a, b, n=8):
    cp = _git(root, "log", "--format=%h %s", "-n", str(n), "%s..%s" % (a, b))
    return [ln for ln in (cp.stdout or "").splitlines() if ln]


def _remote_url(root, name):
    return _git(root, "remote", "get-url", name).stdout.strip()


_CACHE = {"ts": 0, "data": None}


def check(max_age=600, fetch=True):
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
        ref = "%s/%s" % (r, BRANCH)
        out["remotes"][r] = {"url": _remote_url(root, r), "new": _count(root, BRANCH, ref),
                             "commits": _log(root, BRANCH, ref)}
    out["not_installed"] = _count(root, installed, BRANCH) if installed and head else 0
    out["not_installed_commits"] = _log(root, installed, BRANCH) if out["not_installed"] else []
    out["unpushed"] = _count(root, "origin/%s" % BRANCH, BRANCH) if "origin" in remotes else 0
    out["current_branch"] = _git(root, "branch", "--show-current").stdout.strip()
    out["dirty"] = bool(_git(root, "status", "--porcelain", "--untracked-files=no").stdout.strip())
    out["ready"] = bool(sum(v["new"] for v in out["remotes"].values()) or out["not_installed"])
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


def apply(log=print):
    """Update the checkout's main from your fork and the upstream project, test it, push it to your fork, install it.
    Stops, changing nothing further, at the first problem: uncommitted changes, another branch checked out, a merge
    that conflicts, failing tests."""
    root = source()
    steps = []
    j = {"status": "running", "pid": os.getpid(), "started": C.now_iso(), "steps": steps, "why": ""}

    def say(msg):
        steps.append(msg)
        C.write_json(_job_path(), j)
        log(msg)

    def fail(why):
        j.update(status="failed", why=why, ended=C.now_iso())
        C.write_json(_job_path(), j)
        log("stopped: " + why)
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
    if _remote_url(root, "upstream") and _count(root, BRANCH, "upstream/" + BRANCH):
        say("Merging the original project's new commits")
        cp = _git(root, "merge", "--no-edit", "-q", "upstream/" + BRANCH)
        if cp.returncode:
            _git(root, "merge", "--abort")
            return fail("the original project's changes conflict with yours; nothing was merged. Merge "
                        "upstream/main by hand in %s" % root)
    say("Running LFG's tests")
    t = C.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=root, timeout=900)
    if t.returncode:
        _git(root, "reset", "--keep", before)
        tail = ((t.stderr or "") + (t.stdout or "")).strip().splitlines()[-12:]
        return fail("tests failed, so the update was undone and nothing was installed:\n" + "\n".join(tail))
    if _remote_url(root, "origin") and _count(root, "origin/" + BRANCH, BRANCH):
        say("Saving it to your fork")
        if _git(root, "push", "-q", "origin", BRANCH, timeout=120).returncode:
            say("Couldn't push to your fork; installing anyway (push it later)")
    say("Installing")
    cp = C.run([sys.executable, os.path.join(root, "plugin", "bin", "lfg"), "setup", "--yes"], cwd=root, timeout=600)
    if cp.returncode:
        return fail("install failed: %s" % ((cp.stderr or cp.stdout).strip()[-400:]))
    _CACHE.update(ts=0, data=None)
    j.update(status="done", ended=C.now_iso(), from_head=before[:12],
             to_head=_git(root, "rev-parse", "HEAD").stdout.strip()[:12])
    say("Installed. LFG commands and the dashboard use it now; start a new Claude Code session for new skills")
    return j


def human(d):
    if not d.get("available"):
        print(d.get("why"))
        return
    for r, v in d["remotes"].items():
        print("%-9s %s new commit(s)  (%s)" % (r, v["new"], v["url"]))
        for c in v["commits"]:
            print("            " + c)
    if d["not_installed"]:
        print("checkout  %d commit(s) on %s not installed yet" % (d["not_installed"], BRANCH))
    for e in d["errors"]:
        print("!! " + e)
    print("update ready: run `lfg update apply`" if d["ready"] else "up to date")


def as_json(d):
    return json.dumps(d, separators=(",", ":"))
