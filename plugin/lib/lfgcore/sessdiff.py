"""What a session's work actually changed, from git and GitHub rather than from its transcript.

The transcript only records Claude's Edit and Write tools. A session that changes files by shell (a Python script,
sed -i, a formatter, a codegen) leaves no diff there, so a page built from it can show 4 files for a PR of 31. This
finds the checkout the session worked in (where its edits and `cd`s went, else its own folder) and shows:

- the branch's pull request, as GitHub has it: `git diff <merge-base>..<PR head>` of the PR fetched into LFG's own refs,
  the same diff a review reads (prdiff.py);
- with no PR yet, the branch against the branch it was made from, including uncommitted and new files.

On the default branch with no PR there is nothing to compare against, so the caller falls back to the transcript."""
import collections
import os
import re

from . import common as C

CD = re.compile(r"(?:^|[;&|(]\s*)cd\s+(\"[^\"]+\"|'[^']+'|[^\s;&|)]+)")


def _git(cwd, *args, timeout=60):
    return C.run(["git", *args], cwd=cwd, timeout=timeout)


def _dir(p):
    d = p if os.path.isdir(p) else os.path.dirname(p)
    while d and d != "/" and not os.path.isdir(d):
        d = os.path.dirname(d)
    return d if d and os.path.isdir(d) else ""


def _top(d, memo):
    if d not in memo:
        cp = _git(d, "rev-parse", "--show-toplevel", "--git-common-dir", timeout=10) if d else None
        out = cp.stdout.split("\n") if cp is not None and cp.returncode == 0 else []
        memo[d] = (out[0], os.path.realpath(os.path.join(d, out[1]))) if len(out) > 1 and out[0] else ("", "")
    return memo[d]


def checkout(cwd, edited=(), commands=()):
    """The checkout (a repo's folder or one of its worktrees) the session worked in: where most of its file edits and
    `cd`s went, among checkouts of the session's own repo; else the session's own folder. "" when none is a repo."""
    memo, votes = {}, collections.Counter()
    home_top, home_repo = _top(_dir(cwd), memo) if cwd else ("", "")
    paths = [p for p in edited if os.path.isabs(str(p))]
    for c in commands:
        for m in CD.finditer(str(c or "")):
            t = os.path.expanduser(m.group(1).strip("\"'"))
            if os.path.isabs(t):
                paths.append(t)
    for p in paths:
        top, repo = _top(_dir(p), memo)
        if top and (not home_repo or repo == home_repo):
            votes[top] += 1
    return votes.most_common(1)[0][0] if votes else home_top


def _pr(rid, top, branch):
    """The branch's pull request number (open, merged or closed; the newest), from the saved list, else gh."""
    try:
        from . import dash
        hit = dash.pr_states(rid)[1].get(branch)
        if hit:
            return int(hit["number"])
    except Exception:
        pass
    if not C.which("gh") or _git(top, "remote", "get-url", "origin").returncode:
        return None
    cp = C.run(["gh", "pr", "view", branch, "--json", "number"], cwd=top, timeout=30)
    try:
        import json
        return int(json.loads(cp.stdout)["number"]) if cp.returncode == 0 else None
    except (ValueError, KeyError, TypeError):
        return None


def _untracked(top):
    files = [f for f in _git(top, "ls-files", "--others", "--exclude-standard", "-z").stdout.split("\0") if f]
    return "".join(_git(top, "diff", "--no-color", "--no-ext-diff", "--no-index", "--src-prefix=a/",
                        "--dst-prefix=b/", "--", "/dev/null", f).stdout for f in files[:500]
                   if os.path.isfile(os.path.join(top, f)))


def _local(top):
    """What's in the checkout and not on GitHub yet: uncommitted files and commits not pushed."""
    dirty = len([x for x in _git(top, "status", "--porcelain").stdout.splitlines() if x.strip()])
    cp = _git(top, "rev-list", "--count", "@{upstream}..HEAD")
    return {"uncommitted": dirty, "unpushed": int(cp.stdout.strip() or 0) if cp.returncode == 0 else None}


def actual(cwd, edited=(), commands=(), rid=None):
    """The diff of the session's branch: {files, additions, deletions, source}, or None when there is no branch to
    compare (not a repo, a detached head, the default branch with no PR). Raises nothing: a git or GitHub failure
    is None too, with the reason in source when there is one."""
    from . import prdiff as PD
    from . import prreview as PR
    from . import worktree as W
    top = checkout(cwd, edited, commands)
    if not top:
        return None
    branch = _git(top, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if not branch or branch == "HEAD":
        return None
    rid = rid or C.repo_id(top)
    main = W.default_branch(top)
    n = _pr(rid, top, branch) if branch != main else None
    wt = "" if os.path.realpath(top) == os.path.realpath(C.main_root(top) or top) else os.path.basename(top)
    if n:
        try:
            pr = PR._pr_view(top, n)
            head, mb = PR._fetch(top, n, pr["baseRefName"], pr.get("baseRefOid"))
            files = PD._files(rid, top, n, head, mb)
        except Exception:
            return None
        source = {"kind": "pr", "number": n, "url": pr.get("url") or "", "title": pr.get("title") or "",
                  "base": pr["baseRefName"], "branch": branch, "head": head,
                  "local": _local(top)}
    elif branch != main:
        base = W.base_of(top, branch) or main
        ref = next((r for r in ("origin/" + base, base)
                    if _git(top, "rev-parse", "--verify", "-q", r).returncode == 0), "")
        mb = _git(top, "merge-base", ref, "HEAD").stdout.strip() if ref else ""
        if not mb:
            return None
        cp = _git(top, "diff", "--no-color", "--no-ext-diff", "--src-prefix=a/", "--dst-prefix=b/", "-M", "-U3", mb,
                  timeout=300)
        if cp.returncode:
            return None
        files = PD._parse(cp.stdout + _untracked(top))
        source = {"kind": "branch", "branch": branch, "base": base}
    else:
        return None
    for f in files:
        f["full"], f["worktree"], f["outside"] = os.path.join(top, f["path"]), wt, False
    source.update(checkout=top, worktree=wt)
    return {"files": files, "additions": sum(f["additions"] for f in files),
            "deletions": sum(f["deletions"] for f in files), "source": source}
