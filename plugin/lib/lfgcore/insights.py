"""Insights: where the code keeps breaking, and why a piece of it is there. Read-only git, nothing fetched.

Hotspots: files that change a lot and keep needing fixes, from git history (changes, fix commits, how many people
touch it, size, whether a test covers it), each with the reasons in plain words and whether fixes are rising.
Why: every commit that shaped a file or a few of its lines, newest first, with the PRs, issues and Linear tickets
each mentions turned into links.

Ported from upstream LFG (Varun Singh's hotspots_engine, history_engine and the parts of explain5_engine they use);
his "Your changes" review coach and test suggester stay upstream, since this fork's PR reviews cover them."""
import collections
import datetime
import os
import re

from . import common as C

SKIP = re.compile(r"(^|/)(node_modules|vendor|dist|build|\.venv|venv|__pycache__|\.git|docs?)/|"
                  r"(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|Cargo\.lock|go\.sum|uv\.lock)$|"
                  r"\.(md|mdx|txt|rst|json|ya?ml|toml|lock|svg|png|jpe?g|gif|ico|css|map|min\.js|csv)$", re.I)
TEST_FILE = re.compile(r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]+$|_test\.\w+$|\.(test|spec)\.\w+$")
ISSUE_RX = re.compile(r"(?<![\w/])#(\d{1,7})\b")
TICKET_RX = re.compile(r"\b([A-Z][A-Z0-9]{1,9}-\d{1,7})\b")
PR_MERGE_RX = re.compile(r"Merge pull request #(\d+)|\(#(\d+)\)\s*$", re.M)  # a squash merge's subject ends (#N)
# Files a tool writes: their "fixes" are regenerations, not bugs. By name, or a marker in the first lines.
GENERATED = re.compile(r"\.generated\.|(^|/)(generated|__generated__)/|\.gen\.\w+$|_pb2\.py$|\.pb\.go$|"
                       r"(^|/)(supabase|database)\.types\.ts$", re.I)
GENERATED_MARK = re.compile(rb"@generated|auto-?generated|code generated|do not edit", re.I)
NOT_TICKETS = re.compile(r"^(CVE|GHSA|UTF|ISO|RFC|SHA|HTTP|TLS)-")


class _FixDetector:
    """A commit subject that says it fixed something, not a release or version roll-up that only lists fixes."""
    START = re.compile(r"^\s*(\[?(fix|bug|hotfix|bugfix)\b|fix(es|ed)?\s*[:(])", re.I)
    ANY = re.compile(r"\b(fix(es|ed|ing)?|bugfix|hotfix|regression|crash(es|ed|ing)?|broken)\b", re.I)
    RELEASE = re.compile(r"^\s*(release|bump|merge|revert)\b|^\s*v?\d+\.\d+(\.\d+)?\b|^\s*[\w.-]+\s+v?\d+\.\d+(\.\d+)?"
                         r"\s*[:-]", re.I)

    def search(self, text):
        text = text or ""
        if self.RELEASE.search(text):
            return None
        return self.START.search(text) or self.ANY.search(text)


FIX_RX = _FixDetector()


def _git(root, *args, timeout=60):
    return C.run(["git"] + list(args), cwd=root, timeout=timeout)


def files(root):
    """Files git tracks, plus new ones it would track (not ignored)."""
    cp = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", timeout=20)
    return sorted(set(cp.stdout.splitlines())) if cp.returncode == 0 else []


def tracked(root, path):
    """`path` when git knows it as a file of this project, else ValueError: nothing else is ever read."""
    path = (path or "").strip()
    while path.startswith("./"):
        path = path[2:]
    if not path:
        raise ValueError("pick a file")
    if path not in set(files(root)):
        raise ValueError("%s isn't a file in this project (or git ignores it)" % path)
    return path


def related_tests(path, root, every=None):
    """Test files for this module: named after it (test_<name>, <name>_test, <name>.test/.spec) or importing it."""
    base = os.path.splitext(os.path.basename(path))[0]
    if not base or base == "__init__":
        base = os.path.basename(os.path.dirname(path))
    if not base:
        return []
    tests = [f for f in (every if every is not None else files(root)) if TEST_FILE.search(f) and f != path]
    if not tests:
        return []
    b = re.escape(base)
    named = {f for f in tests if re.search(r"(^|/)(test_)?%s([_.-](test|spec))?\.\w+$" % b, f)}
    imp = re.compile(r"^\s*(from\s+[\w.]*\b%s\b[\w.]*\s+import\b|import\s+[\w.]*\b%s\b"
                     r"|from\s+[\w.]+\s+import\s+.*\b%s\b)"
                     r"|from\s+['\"][^'\"]*\b%s['\"]|require\(\s*['\"][^'\"]*\b%s['\"]" % ((b,) * 5), re.M)
    g = _git(root, "grep", "--untracked", "-l", "-w", "-F", base, "--", *tests, timeout=20)  # cheap prefilter
    importing = set()
    for f in (g.stdout.splitlines() if g.returncode == 0 else []):
        try:
            with open(os.path.join(root, f), errors="replace") as fh:
                if imp.search(fh.read(400_000)):
                    importing.add(f)
        except OSError:
            pass
    return sorted(named | importing)[:10]


# ---------------------------------------------------------------- hotspots

def _log(root, days):
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    cp = _git(root, "log", "--no-merges", "--since=%s" % since, "--name-only", "--no-renames",
              "--format=%x01%H%x02%an%x02%ad%x02%s", "--date=short")
    commits = []
    for block in cp.stdout.split("\x01") if cp.returncode == 0 else []:
        head, _, rest = block.partition("\n")
        parts = head.split("\x02")
        if len(parts) == 4:
            commits.append({"sha": parts[0], "author": parts[1], "date": parts[2], "subject": parts[3],
                            "files": [f for f in rest.splitlines() if f.strip()]})
    return commits


def _lines(root, path):
    try:
        with open(os.path.join(root, path), "rb") as fh:
            return fh.read(2_000_000).count(b"\n")
    except OSError:
        return 0


def _generated(root, path):
    if GENERATED.search(path):
        return True
    try:
        with open(os.path.join(root, path), "rb") as fh:
            return bool(GENERATED_MARK.search(fh.read(600)))
    except OSError:
        return False


def _trend(recent, earlier):
    if recent >= 2 and recent > earlier:
        return "rising"
    return "falling" if earlier >= 2 and recent < earlier else "steady"


def hotspots(root, days=180, limit=25):
    """Generated files (by name, or a "do not edit" mark) are left out of the ranking.
    {files, areas, rising, commits, days}. Each file: path, changes, fixes, authors, lines, tests, last, level
    (high | watch), reasons (plain sentences), recent_fixes, trend (fixes in the recent half vs the half before)."""
    commits = _log(root, days)
    half = (datetime.date.today() - datetime.timedelta(days=days // 2)).isoformat()
    every = files(root)
    known = set(every)
    per = collections.defaultdict(lambda: {"changes": 0, "fixes": 0, "recent": 0, "authors": set(), "last": "",
                                           "fix_list": []})
    for c in commits:
        is_fix = bool(FIX_RX.search(c["subject"]))
        for f in c["files"]:
            if f not in known or SKIP.search(f) or TEST_FILE.search(f):
                continue
            p = per[f]
            p["changes"] += 1
            p["authors"].add(c["author"])
            p["last"] = max(p["last"], c["date"])
            if is_fix:
                p["fixes"] += 1
                p["recent"] += c["date"] >= half
                if len(p["fix_list"]) < 5:
                    p["fix_list"].append({"sha": c["sha"][:12], "date": c["date"], "subject": c["subject"][:140]})
    ranked = sorted(per.items(), key=lambda kv: (kv[1]["fixes"] * 3 + kv[1]["changes"], kv[1]["last"]), reverse=True)
    ranked = [kv for kv in ranked[:limit * 3] if not _generated(root, kv[0])]
    out = []
    for path, p in ranked[:limit]:
        if p["changes"] < 2:
            continue
        tests, lines = related_tests(path, root, every), _lines(root, path)
        earlier = p["fixes"] - p["recent"]
        trend = _trend(p["recent"], earlier)
        reasons = (["needed %d fix%s in %d days" % (p["fixes"], "es" if p["fixes"] != 1 else "", days)]
                   if p["fixes"] else []) + ["changed %d time%s" % (p["changes"], "s" if p["changes"] != 1 else "")]
        if trend == "rising":
            reasons.append("fixes rising: %d in the last %d days, %d before" % (p["recent"], days // 2, earlier))
        if len(p["authors"]) >= 4:
            reasons.append("%d people change it" % len(p["authors"]))
        if lines >= 800:
            reasons.append("%d lines long" % lines)
        if not tests:
            reasons.append("no test file covers it")
        high = (p["fixes"] >= 3 and p["changes"] >= 6) or (p["fixes"] >= 2 and not tests) or \
            (p["changes"] >= 12 and not tests)
        out.append({"path": path, "area": os.path.dirname(path) or ".", "changes": p["changes"], "fixes": p["fixes"],
                    "authors": len(p["authors"]), "lines": lines, "tests": tests, "last": p["last"],
                    "level": "high" if high else "watch", "reasons": reasons, "recent_fixes": p["fix_list"],
                    "trend": trend, "fixes_recent": p["recent"], "fixes_earlier": earlier})
    areas = collections.defaultdict(lambda: {"changes": 0, "fixes": 0, "files": 0, "high": 0, "fixes_recent": 0})
    for path, p in per.items():
        a = areas[os.path.dirname(path) or "."]
        a["changes"] += p["changes"]
        a["fixes"] += p["fixes"]
        a["fixes_recent"] += p["recent"]
        a["files"] += 1
    for a in areas.values():
        a["fixes_earlier"] = a["fixes"] - a["fixes_recent"]
        a["trend"] = _trend(a["fixes_recent"], a["fixes_earlier"])
    for f in out:
        areas[f["area"]]["high"] += f["level"] == "high"
    area_list = sorted(({"area": k, **v} for k, v in areas.items() if v["changes"] >= 3),
                       key=lambda a: a["fixes"] * 3 + a["changes"], reverse=True)[:8]
    return {"days": days, "half": days // 2, "commits": len(commits), "files": out, "areas": area_list,
            "rising": [a["area"] for a in area_list if a["trend"] == "rising"]}


# ---------------------------------------------------------------- why is this here

def _web_base(root):
    """https://github.com/owner/repo (or GitLab/Bitbucket) from the origin URL, or ""."""
    url = _git(root, "remote", "get-url", "origin", timeout=10).stdout.strip()
    m = re.match(r"^(?:git@|ssh://git@|https?://)([\w.-]+)[:/]([\w.-]+/[\w.-]+?)(?:\.git)?/?$", url)
    return "https://%s/%s" % (m.group(1), m.group(2)) if m else ""


def refs(text, web="", linear=""):
    """PR and issue numbers and tracker keys a commit message mentions, as [{label, url}] (url may be "")."""
    out, seen = [], set()
    gh = "github.com" in web
    for m in PR_MERGE_RX.finditer(text):
        n = m.group(1) or m.group(2)
        if n and "#" + n not in seen:
            seen.add("#" + n)
            out.append({"label": "PR #%s" % n, "url": "%s/pull/%s" % (web, n) if gh else ""})
    for n in ISSUE_RX.findall(text):
        if "#" + n not in seen:
            seen.add("#" + n)
            out.append({"label": "#%s" % n, "url": "%s/issues/%s" % (web, n) if gh else ""})
    for k in TICKET_RX.findall(text):
        if k not in seen and not NOT_TICKETS.match(k):
            seen.add(k)
            out.append({"label": k, "url": "https://linear.app/%s/issue/%s" % (linear, k) if linear else ""})
    return out


def why(root, path, start=None, end=None, limit=15):
    """Commits that changed `path` (or only its lines start..end), newest first:
    {path, start, end, commits: [{sha, author, date, subject, body, fix, refs, url}], authors, fixes}."""
    fmt = "--format=%x01%H%x02%an%x02%ad%x02%s%x02%b"
    if start:
        n = max(1, _lines(root, path))
        start = min(int(start), n)
        end = min(max(int(end or n), start), n)  # no end: to the end of the file
        cmd = ["log", "-L", "%d,%d:%s" % (start, end, path), "--no-patch", fmt, "--date=short", "-n", str(limit)]
    else:
        cmd = ["log", "--follow", fmt, "--date=short", "-n", str(limit), "--", path]
    cp = _git(root, *cmd)
    web = _web_base(root)
    linear = ((C.config().get("linear") or {}).get("workspace") or "").strip()
    commits = []
    for block in cp.stdout.split("\x01") if cp.returncode == 0 else []:
        parts = block.strip("\n").split("\x02")
        if len(parts) < 4:
            continue
        subject, body = parts[3], (parts[4] if len(parts) > 4 else "").strip()
        body = "\n".join(x for x in body.splitlines() if not re.match(r"^(Co-Authored-By|Signed-off-by):", x, re.I))
        commits.append({"sha": parts[0][:12], "author": parts[1], "date": parts[2], "subject": subject,
                        "body": body[:1200], "fix": bool(FIX_RX.search(subject)),
                        "refs": refs(subject + "\n" + body, web, linear),
                        "url": "%s/commit/%s" % (web, parts[0]) if "github.com" in web else ""})
    return {"path": path, "start": start, "end": end, "commits": commits,
            "authors": len({c["author"] for c in commits}), "fixes": sum(c["fix"] for c in commits)}
