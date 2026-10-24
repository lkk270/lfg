"""`lfg worktree`: git worktrees for working on another branch without touching the user's checkout.

Worktrees go next to the main checkout, in `<parent>/<repo>.worktrees/<branch-slug>`, so they are outside both the
repo and ~/.lfg. They share the main checkout's graphs (one graph per repo, see graphs.py). LFG never commits in a
worktree, never uses `--force`, and only removes worktrees it created that have no uncommitted changes.
Author: Varun Singh."""
import os
import re

from . import common as C


def base_dir(root):
    main = C.main_root(root)
    return os.path.join(os.path.dirname(main), os.path.basename(main) + ".worktrees")


def slug(branch):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", branch).strip("-.") or "wt"


def _git(root, *args, timeout=60):
    return C.run(["git", *args], cwd=root, timeout=timeout)


def listing(root):
    """Every worktree of the repo: [{path, branch, head, lfg}], `lfg` true for the ones under base_dir()."""
    cp = _git(root, "worktree", "list", "--porcelain")
    mine = os.path.realpath(base_dir(root))
    out, cur = [], {}
    for line in (cp.stdout or "").splitlines() + [""]:
        if not line:
            if cur:
                out.append(cur)
            cur = {}
            continue
        k, _, v = line.partition(" ")
        if k == "worktree":
            cur = {"path": v, "branch": "", "head": "", "lfg": os.path.dirname(os.path.realpath(v)) == mine}
        elif k == "branch":
            cur["branch"] = v.replace("refs/heads/", "", 1)
        elif k == "HEAD":
            cur["head"] = v[:12]
    return out


def new(root, branch, base=None):
    """Check `branch` out in a new worktree (create it from `base`, default HEAD, if it doesn't exist)."""
    if not branch or branch.startswith("-") or _git(root, "check-ref-format", "--branch", branch).returncode:
        raise ValueError("not a valid branch name: %r" % branch)
    path = os.path.join(base_dir(root), slug(branch))
    if os.path.exists(path):
        raise ValueError("%s already exists" % path)
    exists = _git(root, "show-ref", "--verify", "--quiet", "refs/heads/" + branch).returncode == 0
    if exists and base:
        raise ValueError("branch %s already exists; --from only applies to a new branch" % branch)
    os.makedirs(base_dir(root), exist_ok=True)
    args = ["worktree", "add", path, branch] if exists else \
        ["worktree", "add", "-b", branch, path] + ([base] if base else [])
    fork = None if exists else (base or C.git_branch(root))  # the branch it was forked from, to merge back into
    cp = _git(root, *args, timeout=300)
    if cp.returncode:
        raise RuntimeError((cp.stderr or cp.stdout).strip())
    if fork and not fork.startswith("detached@"):
        _git(root, "config", "branch.%s.lfgBase" % branch, fork.replace("origin/", "", 1))
    return {"path": path, "branch": branch, "created_branch": not exists, "base": fork}


def remove(root, name):
    """Remove an LFG worktree by folder name or branch. Refuses one with uncommitted or untracked changes."""
    hit = [w for w in listing(root) if w["lfg"] and name in (os.path.basename(w["path"]), w["branch"])]
    if not hit:
        raise ValueError("no LFG worktree named %r (see `lfg worktree list`)" % name)
    path = hit[0]["path"]
    dirty = _git(path, "status", "--porcelain").stdout.strip()
    if dirty:
        raise RuntimeError("%s has uncommitted changes; commit or move them first (LFG never forces):\n%s"
                           % (path, dirty[:1500]))
    cp = _git(root, "worktree", "remove", path)
    if cp.returncode:
        raise RuntimeError((cp.stderr or cp.stdout).strip())
    try:
        os.rmdir(base_dir(root))  # only when empty
    except OSError:
        pass
    return {"path": path, "branch": hit[0]["branch"]}


def _last_used(path):
    """Newest of the worktree folder and its git admin files (index/HEAD change on any git use there)."""
    admin = _git(path, "rev-parse", "--absolute-git-dir").stdout.strip()
    paths = [path] + ([os.path.join(admin, f) for f in ("index", "HEAD")] if admin else [])
    return max((os.path.getmtime(p) for p in paths if os.path.exists(p)), default=0)


def prune(root, idle_s=86400):
    """Remove LFG worktrees that are clean and unused for `idle_s` (run by SessionStart, so nobody has to).
    Worktrees with any change are kept; the branch is always kept. Returns the removed paths."""
    import time
    gone = []
    for w in listing(root):
        if not w["lfg"] or time.time() - _last_used(w["path"]) < idle_s:
            continue
        if os.path.basename(w["path"]).startswith("review-pr-"):
            continue  # a PR review from the dashboard: removed from its Reviews page when the reviewer is done
        if not os.path.isdir(w["path"]):
            continue  # folder deleted by hand: `git worktree prune` territory, not ours
        try:
            gone.append(remove(root, os.path.basename(w["path"]))["path"])
        except (ValueError, RuntimeError):
            pass  # has changes (the user's work) or git refused: leave it
    return gone


# ---------------------------------------------------------------- where each worktree stands, and merging it back

def default_branch(root):
    ref = _git(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").stdout.strip()
    if ref.startswith("origin/"):
        return ref[7:]
    return next((b for b in ("main", "master", "develop")
                 if _git(root, "show-ref", "--verify", "--quiet", "refs/heads/" + b).returncode == 0), "main")


def base_of(root, branch):
    """The branch `branch` was forked from: recorded when LFG made it (git config branch.<b>.lfgBase), else the
    repo's default branch."""
    if not branch:
        return None
    got = _git(root, "config", "--get", "branch.%s.lfgBase" % branch).stdout.strip()
    return got or default_branch(root)


def _kind(root, w):
    if os.path.realpath(w["path"]) == os.path.realpath(C.main_root(root)):
        return "main"
    if os.path.basename(w["path"]).startswith("review-pr-"):
        return "review"
    return "lfg" if w["lfg"] else "yours"


def status(root):
    """Every worktree of the repo: its branch, the branch it merges back into, uncommitted changes, commits ahead
    and behind that base, and what kind it is (main checkout, an LFG worktree, one of yours, a PR review's)."""
    out = []
    for w in listing(root):
        kind, br = _kind(root, w), w["branch"]
        row = dict(w, kind=kind, name=os.path.basename(w["path"]), base=None, dirty=0, ahead=0, behind=0,
                   exists=os.path.isdir(w["path"]))
        if row["exists"]:
            row["dirty"] = len([x for x in _git(w["path"], "status", "--porcelain").stdout.splitlines() if x])
        if br and kind in ("lfg", "yours"):
            row["base"] = base_of(root, br)
            if row["base"] and row["base"] != br:
                cp = _git(root, "rev-list", "--left-right", "--count", "%s...%s" % (row["base"], br))
                if cp.returncode == 0 and cp.stdout.split():
                    row["behind"], row["ahead"] = (int(x) for x in cp.stdout.split()[:2])
        out.append(row)
    return out


class NeedsMergeCommit(RuntimeError):
    pass


def _find(root, name):
    hit = [w for w in status(root) if w["kind"] in ("lfg", "yours") and name in (w["name"], w["branch"])]
    if not hit:
        raise ValueError("no worktree named %r to merge (see `lfg worktree list`)" % name)
    return hit[0]


def merge(root, name, into=None, remove_after=False, merge_commit=False):
    """Merge a worktree's branch into the branch it was forked from (or `into`). Only committed work moves: a
    worktree with uncommitted changes is refused (LFG never commits for you). A fast-forward when possible; when
    the base has moved on, a merge commit only with `merge_commit` (the user said yes). Conflicts abort the merge
    and are listed. `remove_after` then removes the worktree (LFG's own, clean) and deletes the branch if merged."""
    w = _find(root, name)
    br, base = w["branch"], into or w["base"]
    if not br or not base or br == base:
        raise ValueError("%s has no branch to merge into %s" % (w["name"], base or "its base"))
    if w["dirty"]:
        raise RuntimeError("%s has %d uncommitted change%s: commit them in that worktree first, then merge (LFG "
                           "never commits for you)" % (w["name"], w["dirty"], "" if w["dirty"] == 1 else "s"))
    ahead = int(_git(root, "rev-list", "--count", "%s..%s" % (base, br)).stdout.strip() or 0)
    how = "nothing to merge"
    if ahead:
        there = next((x for x in listing(root) if x["branch"] == base), None)
        if there:  # the base is checked out somewhere: merge there, never on top of someone's changes
            if _git(there["path"], "status", "--porcelain").stdout.strip():
                raise RuntimeError("%s, where %s is checked out, has uncommitted changes: commit or stash them first"
                                   % (there["path"], base))
            cp = _git(there["path"], "merge", "--ff-only", br, timeout=300)
            how = "fast-forward"
            if cp.returncode:
                if not merge_commit:
                    raise NeedsMergeCommit("%s has moved on since %s was forked, so it can't fast-forward. Merge with "
                                           "a merge commit?" % (base, br))
                cp = _git(there["path"], "merge", "--no-ff", "--no-edit", br, timeout=300)
                how = "merge commit"
                if cp.returncode:
                    files = _git(there["path"], "diff", "--name-only", "--diff-filter=U").stdout.split()
                    _git(there["path"], "merge", "--abort")
                    raise RuntimeError("merging %s into %s conflicts in %s; nothing was changed. Resolve it by hand "
                                       "(or rebase %s on %s) and try again" % (br, base, ", ".join(files[:8]) or
                                                                              "some files", br, base))
        else:  # not checked out anywhere: move the branch only when that's a fast-forward
            cp = _git(root, "fetch", ".", "%s:%s" % (br, base))
            how = "fast-forward"
            if cp.returncode:
                raise RuntimeError("%s has moved on and isn't checked out anywhere: check it out, then merge %s there "
                                   "(or rebase %s on %s)" % (base, br, br, base))
    out = {"name": w["name"], "branch": br, "into": base, "commits": ahead, "how": how, "removed": False}
    if remove_after:
        if w["kind"] != "lfg":
            raise RuntimeError("merged; %s isn't a worktree LFG made, so LFG leaves removing it to you" % w["name"])
        remove(root, w["name"])
        _git(root, "branch", "-d", br)  # only deletes a fully merged branch
        _git(root, "config", "--unset", "branch.%s.lfgBase" % br)
        out["removed"] = True
    return out


def merge_all(root, into, remove_after=True, merge_commit=False):
    """Merge every LFG worktree forked from `into` back into it (and remove them), one by one; stops at the first
    that can't merge, so nothing is left half done."""
    done = []
    for w in [w for w in status(root) if w["kind"] == "lfg" and w["base"] == into]:
        done.append(merge(root, w["name"], into, remove_after, merge_commit))
    return done
