"""PR reviews, of other people's work or your own open PRs: the review record, triage, posting and re-review state.
Stdlib only.

One record per PR in ~/.lfg/reviews/<owner>__<repo>/<number>.json. Each review of the PR is a pass that remembers the
commit it read, so a re-review can tell what changed since. Findings keep the GitHub comment id they were posted as,
so a re-review can tell which ones were fixed, answered or ignored.

Posting (`lfg review post`) writes to GitHub, so the guard keeps it for the user (terminal or dashboard)."""
import glob
import json
import os
import re
import time

from . import common as C

SEVERITIES = ("blocker", "major", "minor", "nitpick", "note")
ORIGINS = ("introduced", "exposed", "pre-existing")      # who the bug belongs to
SINCE = ("first", "new", "missed")                      # re-review: in new commits, or missed by an earlier pass
PRIOR_STATES = ("fixed", "replied", "ignored", "resolved-unchanged", "open", "withdrawn")
STATUSES = ("pending", "keep", "drop")
EVENTS = {"approve": "APPROVE", "request-changes": "REQUEST_CHANGES", "comment": "COMMENT"}
PR_URL = re.compile(r"^https://github\.com/([\w.-]+/[\w.-]+)/pull/(\d+)")
PR_REF = re.compile(r"^([\w.-]+/[\w.-]+)#(\d+)$")
MAX_BODY = 20_000


class ReviewError(Exception):
    pass


# ---------------------------------------------------------------- PR identity and GitHub reads

def parse_pr(ref, cwd=None):
    """`owner/repo#12`, a PR URL, or a bare number (repo from the checkout in cwd) -> ("owner/repo", 12)."""
    ref = (ref or "").strip()
    m = PR_URL.match(ref) or PR_REF.match(ref)
    if m:
        return m.group(1), int(m.group(2))
    if ref.lstrip("#").isdigit():
        cp = C.run(["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"], cwd=cwd, timeout=30)
        if cp.returncode or not cp.stdout.strip():
            raise ReviewError("can't tell which repo PR %s is in: run this inside its checkout or use owner/repo#%s"
                              % (ref, ref.lstrip("#")))
        return cp.stdout.strip(), int(ref.lstrip("#"))
    raise ReviewError("not a PR: %r (use a number, owner/repo#12 or a PR URL)" % ref)


def gh_json(args, stdin=None, timeout=60):
    cp = _gh(args, stdin, timeout)
    if cp.returncode:
        raise ReviewError("gh %s: %s" % (" ".join(args[:3]), (cp.stderr or cp.stdout).strip()[-500:]))
    return json.loads(cp.stdout or "null")


def _gh(args, stdin=None, timeout=60):
    import subprocess
    try:
        return subprocess.run(["gh"] + args, input=stdin, text=True, capture_output=True, timeout=timeout)
    except FileNotFoundError:
        raise ReviewError("gh is not installed") from None
    except subprocess.TimeoutExpired:
        raise ReviewError("gh %s timed out" % " ".join(args[:3])) from None


def pr_meta(repo, number):
    j = gh_json(["pr", "view", str(number), "-R", repo, "--json",
                 "number,title,url,author,headRefOid,baseRefName,headRefName,state,isDraft"])
    return {"title": j["title"], "url": j["url"], "author": (j.get("author") or {}).get("login", ""),
            "head_sha": j["headRefOid"], "base": j["baseRefName"], "branch": j["headRefName"], "state": j["state"]}


_STATUS = {}


def gh_status(repo, number, max_age=300):
    """Where the PR stands on GitHub: open/merged, approved or changes asked for, each reviewer's latest verdict,
    who still has to review, and checks. Cached for max_age seconds."""
    key = (repo, number)
    hit = _STATUS.get(key)
    if hit and time.time() - hit[0] < max_age:
        return hit[1]
    try:
        j = gh_json(["pr", "view", str(number), "-R", repo, "--json",
                     "state,isDraft,reviewDecision,mergeable,reviews,reviewRequests,statusCheckRollup,headRefOid,"
                     "headRefName"])
    except ReviewError as e:
        return {"available": False, "why": str(e)}
    latest = {}
    for r in j.get("reviews") or []:
        who = (r.get("author") or {}).get("login") or "?"
        if r.get("state") in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED") or who not in latest:
            latest[who] = {"who": who, "state": r.get("state"), "at": r.get("submittedAt")}
    checks = {}
    for c in j.get("statusCheckRollup") or []:
        k = (c.get("conclusion") or c.get("state") or "PENDING").upper()
        checks[k] = checks.get(k, 0) + 1
    out = {"available": True, "state": j.get("state"), "draft": j.get("isDraft"),
           "decision": j.get("reviewDecision") or "", "mergeable": j.get("mergeable"),
           "reviewers": sorted(latest.values(), key=lambda r: r["at"] or ""),
           "waiting_on": [(r.get("login") or r.get("name") or "") for r in j.get("reviewRequests") or []],
           "checks": checks, "head_sha": j.get("headRefOid"), "branch": j.get("headRefName") or "", "me": me()}
    _STATUS[key] = (time.time(), out)
    return out


REWRITE = ("Rewrite this code review comment as asked. Keep it accurate to the finding, in the same voice. Reply "
           "with only the new comment, no preamble.\n\nWhat was asked: %s\n\nThe finding (for context, not "
           "posted):\n%s\n\nThe comment as it is now:\n%s")


def rewrite(repo, number, fid, instruction):
    """Ask Claude, with no tools, to change one comment ("shorter", "less blunt", "add the line number"). Returns the
    new text without saving it: you look at it, then save it like any edit."""
    import subprocess
    if not str(instruction or "").strip():
        raise ReviewError("say how to change it, e.g. \"make it two sentences\"")
    if not C.which("claude"):
        raise ReviewError("Claude Code (`claude`) is not on PATH")
    f = find(need(repo, number), fid)
    ctx = "\n".join(x for x in ("Title: " + (f.get("title") or ""), "Issue: " + (f.get("issue") or ""),
                                 "Fix: " + (f.get("fix") or ""), "Where: %s:%s" % (f.get("file") or "-", f.get("line")
                                                                                   or "-")) if x)
    cp = subprocess.run(["claude", "-p", "--output-format", "json", "--permission-mode", "dontAsk", "--tools", ""],
                        input=REWRITE % (_text(instruction, "instruction", 2000), ctx, f["body"]),
                        capture_output=True, text=True, timeout=300)
    try:
        text = (json.loads(cp.stdout).get("result") or "").strip()
    except ValueError:
        text = ""
    if not text:
        raise ReviewError("Claude didn't return a comment: %s" % (cp.stderr or cp.stdout or "")[-300:].strip())
    return {"id": fid, "body": re.sub(r"^```\w*\n|\n```$", "", text)}


def me():
    cp = _gh(["api", "user", "-q", ".login"], timeout=30)
    return cp.stdout.strip() if cp.returncode == 0 else ""


def diff_lines(repo, base, head):
    """{path: set(right-side line numbers GitHub accepts a comment on)} for the PR diff as of `head`."""
    j = gh_json(["api", "repos/%s/compare/%s...%s" % (repo, base, head)], timeout=120)
    out = {}
    for f in j.get("files") or []:
        out[f["filename"]] = commentable(f.get("patch") or "")
    return out


def commentable(patch):
    lines, new = set(), 0
    for ln in patch.splitlines():
        m = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", ln)
        if m:
            new = int(m.group(1))
            continue
        if ln.startswith("-") or ln.startswith("\\"):
            continue
        lines.add(new)
        new += 1
    return lines


# ---------------------------------------------------------------- the record

def reviews_dir():
    return C.lfg_path("reviews")


def record_path(repo, number):
    return os.path.join(reviews_dir(), repo.replace("/", "__"), "%d.json" % number)


def load(repo, number):
    return C.read_json(record_path(repo, number))


def store(rec):
    rec["updated"] = C.now_iso()
    C.write_json(record_path(rec["repo"], rec["number"]), rec)


def need(repo, number):
    rec = load(repo, number)
    if not rec or not rec.get("passes"):
        raise ReviewError("no review saved for %s#%d yet" % (repo, number))
    return rec


def all_records():
    out = []
    for p in sorted(glob.glob(os.path.join(reviews_dir(), "*", "*.json"))):
        r = C.read_json(p)
        if r and r.get("passes"):
            out.append(r)
    return sorted(out, key=lambda r: r.get("updated", ""), reverse=True)


def findings(rec):
    return [f for p in rec["passes"] for f in p["findings"]]


def find(rec, fid):
    for f in findings(rec):
        if f["id"] == fid:
            return f
    raise ReviewError("no finding %s on %s#%d" % (fid, rec["repo"], rec["number"]))


def _text(v, name, limit=MAX_BODY):
    v = "" if v is None else str(v)
    if len(v) > limit:
        raise ReviewError("%s is longer than %d characters" % (name, limit))
    return v


def _clean_finding(f, i):
    if not isinstance(f, dict):
        raise ReviewError("finding %d is not an object" % i)
    sev = str(f.get("severity", "")).lower()
    if sev not in SEVERITIES:
        raise ReviewError("finding %d: severity must be one of %s" % (i, ", ".join(SEVERITIES)))
    body = _text(f.get("body"), "finding %d body" % i)
    if not body.strip():
        raise ReviewError("finding %d has no body (the comment the author will read)" % i)
    line = f.get("line")
    if line is not None and (not isinstance(line, int) or line < 1):
        raise ReviewError("finding %d: line must be a positive integer or null" % i)
    origin = f.get("origin") or "introduced"
    since = f.get("since") or "first"
    if origin not in ORIGINS or since not in SINCE:
        raise ReviewError("finding %d: origin is one of %s; since is one of %s"
                          % (i, ", ".join(ORIGINS), ", ".join(SINCE)))
    return {"title": _text(f.get("title"), "title", 200), "severity": sev, "file": f.get("file") or None,
            "line": line, "issue": _text(f.get("issue"), "issue", 1000), "fix": _text(f.get("fix"), "fix", 1000),
            "detail": _text(f.get("detail"), "detail"), "body": body, "origin": origin, "since": since,
            "echoes": _echoes(f.get("echoes"), i), "status": "pending", "comment_id": None, "comment_url": None}


def _echoes(raw, i):
    """Other reviewers (people, CodeRabbit, other bots) who already raised this: [{who, url, said, bot}]."""
    if raw in (None, []):
        return []
    if not isinstance(raw, list):
        raise ReviewError("finding %d: echoes is a list of {who, url, said}" % i)
    out = []
    for e in raw[:10]:
        if not isinstance(e, dict) or not str(e.get("who") or "").strip():
            raise ReviewError("finding %d: each echo needs who (their GitHub login)" % i)
        url = str(e.get("url") or "")
        out.append({"who": str(e["who"]).strip().lstrip("@")[:80],
                    "url": url if url.startswith("https://github.com/") else "",
                    "said": _text(e.get("said"), "echo", 600), "bot": bool(e.get("bot"))})
    return out


def others(repo, number):
    """What other reviewers already said on a PR: inline comments (with file and line), review summaries and
    conversation comments, from people and bots (CodeRabbit, Sonar, other agents). LFG's own posted comments are
    left out. Read-only."""
    rec = load(repo, number) or {}
    mine = {f.get("comment_id") for f in findings(rec) if f.get("comment_id")} if rec.get("passes") else set()
    out = []

    def add(c, kind, file=None, line=None):
        u = c.get("user") or {}
        body = (c.get("body") or "").strip()
        if not body or c.get("id") in mine:
            return
        out.append({"who": u.get("login") or "", "bot": u.get("type") == "Bot" or (u.get("login") or "").endswith(
            "[bot]"), "kind": kind, "file": file, "line": line, "said": body[:1500], "url": c.get("html_url") or "",
            "at": c.get("submitted_at") or c.get("created_at") or ""})
    for c in gh_json(["api", "--paginate", "repos/%s/pulls/%d/comments" % (repo, number)], timeout=120) or []:
        add(c, "inline", c.get("path"), c.get("line") or c.get("original_line"))
    for c in gh_json(["api", "--paginate", "repos/%s/pulls/%d/reviews" % (repo, number)], timeout=120) or []:
        add(c, "review")
    for c in gh_json(["api", "--paginate", "repos/%s/issues/%d/comments" % (repo, number)], timeout=120) or []:
        add(c, "comment")
    return out


NEAR = 3  # lines: another reviewer's inline comment this close to a finding is about the same spot


def mark_echoes(repo, number, said=None):
    """Tag the latest review's findings with other reviewers' inline comments on the same file within NEAR lines,
    on top of the ones the review itself named. Never fails a review: if GitHub can't be asked, nothing changes."""
    rec = load(repo, number)
    if not rec or not rec.get("passes"):
        return 0
    try:
        said = others(repo, number) if said is None else said
    except ReviewError:
        return 0
    n = 0
    for f in rec["passes"][-1]["findings"]:
        have = {e["url"] for e in f.get("echoes") or [] if e.get("url")} | {e["who"] for e in f.get("echoes") or []}
        for c in said:
            if c["kind"] != "inline" or not f.get("file") or c["file"] != f["file"] or not f.get("line") \
                    or not c.get("line") or abs(int(c["line"]) - int(f["line"])) > NEAR:
                continue
            if c["url"] in have or c["who"] in have:
                continue
            f.setdefault("echoes", []).append({"who": c["who"], "url": c["url"], "said": c["said"][:600],
                                               "bot": c["bot"], "near": True})
            have |= {c["url"], c["who"]}
            n += 1
    if n:
        store(rec)
    return n


def save(repo, number, data, ticket=None, meta=None):
    """Add a pass from the agent's JSON: {summary, score, approach_notes, findings: [...], prior: [...]}.
    `meta` is pr_meta() (passed in tests); `head_sha` in data wins over the PR's current head."""
    if not isinstance(data, dict) or not isinstance(data.get("findings"), list):
        raise ReviewError("expected a JSON object with a findings list")
    meta = meta or pr_meta(repo, number)
    rec = load(repo, number) or {"repo": repo, "number": number, "created": C.now_iso(), "passes": []}
    rec.update({k: meta[k] for k in ("title", "url", "author", "base", "branch", "state")})
    if ticket:
        rec["ticket"] = ticket
    n = len(rec["passes"]) + 1
    found = [_clean_finding(f, i) for i, f in enumerate(data["findings"], 1)]
    for i, f in enumerate(found, 1):
        f["id"] = "%d.%d" % (n, i)
    known = {f["id"] for f in findings(rec)}
    prior = []
    for p in data.get("prior") or []:
        if p.get("id") not in known or p.get("state") not in PRIOR_STATES:
            raise ReviewError("prior entries need an earlier finding id (%s) and a state in %s"
                              % (", ".join(sorted(known)) or "none yet", ", ".join(PRIOR_STATES)))
        prior.append({"id": p["id"], "state": p["state"], "note": _text(p.get("note"), "prior note", 2000)})
    score = data.get("score")
    if score is not None and not (isinstance(score, int) and 0 <= score <= 100):
        raise ReviewError("score must be an integer 0-100 or null")
    rec["passes"].append({
        "n": n, "kind": "first" if n == 1 else "re-review", "ts": C.now_iso(), "reviewer": data.get("reviewer") or "",
        "head_sha": data.get("head_sha") or meta["head_sha"], "base": meta["base"],
        "summary": _text(data.get("summary"), "summary"), "score": score,
        "approach_notes": [_text(x, "approach note", 4000) for x in data.get("approach_notes") or []],
        "findings": found, "prior": prior, "posted": None})
    store(rec)
    C.audit("review_save", {"pr": "%s#%d" % (repo, number), "pass": n, "findings": len(found)})
    return rec


def discard(repo, number, n):
    """Throw away one review pass that was never posted. Only the latest can go, so later passes never point at a
    missing one; discarding the only pass removes the record."""
    rec = need(repo, number)
    last = rec["passes"][-1]
    if int(n) != last["n"]:
        raise ReviewError("only the latest review (%d) can be discarded" % last["n"])
    if last.get("posted"):
        raise ReviewError("review %d is already on GitHub; it can't be discarded here" % last["n"])
    rec["passes"].pop()
    if rec["passes"]:
        store(rec)
    else:
        os.remove(record_path(repo, number))
    C.audit("review_discard", {"pr": "%s#%d" % (repo, number), "pass": int(n)})
    return {"discarded": int(n), "left": len(rec["passes"])}


def mark(repo, number, ids, status=None, body=None):
    if status is not None and status not in STATUSES:
        raise ReviewError("status must be one of %s" % ", ".join(STATUSES))
    rec = need(repo, number)
    for fid in ids:
        f = find(rec, fid)
        if f.get("comment_id") and (status == "drop" or body is not None):
            raise ReviewError("%s is already posted on GitHub; change it there" % fid)
        if status:
            f["status"] = status
        if body is not None:
            if not body.strip():
                raise ReviewError("the comment can't be empty")
            f["body"] = _text(body, "comment")
    store(rec)
    return rec


# ---------------------------------------------------------------- posting (user-only: the guard blocks agents)

def plan_post(rec, event, body="", lines=None):
    """What `post` would send: kept, unposted findings of the latest pass. Findings whose line GitHub can't take a
    comment on (outside the diff, or no line) go into the review body with their file:line instead."""
    if event not in EVENTS:
        raise ReviewError("event must be one of %s" % ", ".join(EVENTS))
    p = rec["passes"][-1]
    if p.get("posted"):
        raise ReviewError("pass %d was already posted (%s); run a re-review first" % (p["n"], p["posted"]["url"]))
    pending = [f for f in p["findings"] if f["status"] == "pending"]
    if pending:
        raise ReviewError("decide keep or drop first: %s" % ", ".join(f["id"] for f in pending))
    kept = [f for f in p["findings"] if f["status"] == "keep" and not f["comment_id"]]
    if lines is None:
        lines = diff_lines(rec["repo"], rec["base"], p["head_sha"]) if any(f["file"] for f in kept) else {}
    inline, general = [], []
    for f in kept:
        if f["file"] and f["line"] and f["line"] in lines.get(f["file"], ()):
            inline.append({"id": f["id"], "path": f["file"], "line": f["line"], "side": "RIGHT", "body": f["body"]})
        else:
            general.append(f)
    parts = [body.strip()] if body.strip() else []
    for f in general:
        where = "`%s%s`: " % (f["file"], ":%d" % f["line"] if f["line"] else "") if f["file"] else ""
        parts.append(where + f["body"])
    if event == "request-changes" and not inline and not parts:
        raise ReviewError("request changes needs at least one kept finding or a body")
    return {"pass": p["n"], "event": EVENTS[event], "commit_id": p["head_sha"], "body": "\n\n".join(parts),
            "comments": inline, "in_body": [f["id"] for f in general]}


def post(repo, number, event, body="", dry_run=False):
    rec = need(repo, number)
    if event != "comment" and rec.get("author") and rec["author"] == me():
        raise ReviewError("this is your own PR: GitHub only takes a comment on it, not approve or request changes")
    plan = plan_post(rec, event, body)
    if dry_run:
        return dict(plan, dry_run=True)
    payload = {"commit_id": plan["commit_id"], "event": plan["event"], "body": plan["body"],
               "comments": [{k: c[k] for k in ("path", "line", "side", "body")} for c in plan["comments"]]}
    out = gh_json(["api", "-X", "POST", "repos/%s/pulls/%d/reviews" % (repo, number), "--input", "-"],
                  stdin=json.dumps(payload), timeout=120)
    posted = gh_json(["api", "--paginate", "repos/%s/pulls/%d/reviews/%d/comments" % (repo, number, out["id"])])
    p = rec["passes"][plan["pass"] - 1]
    for c, g in match_comments(plan["comments"], posted or []):
        f = find(rec, c["id"])
        f["comment_id"], f["comment_url"] = (g["id"], g["html_url"]) if g else (None, out.get("html_url"))
    for fid in plan["in_body"]:
        find(rec, fid)["comment_url"] = out.get("html_url")
    p["posted"] = {"review_id": out["id"], "event": plan["event"], "url": out.get("html_url"), "ts": C.now_iso()}
    store(rec)
    C.audit("review_post", {"pr": "%s#%d" % (repo, number), "event": plan["event"], "comments": len(plan["comments"])})
    return dict(plan, posted=p["posted"])


def match_comments(sent, posted):
    """Pair each comment we sent with the one GitHub created: same file and text, else same file and line (GitHub
    may normalise whitespace). Unmatched ones pair with None."""
    left, out = list(posted), []
    for c in sent:
        g = next((x for x in left if x["path"] == c["path"] and x["body"].strip() == c["body"].strip()), None) \
            or next((x for x in left if x["path"] == c["path"] and x.get("line") == c["line"]), None)
        if g:
            left.remove(g)
        out.append((c, g))
    return out


# ---------------------------------------------------------------- re-review inputs

THREADS_Q = """query($o:String!,$r:String!,$n:Int!,$c:String){repository(owner:$o,name:$r){pullRequest(number:$n){
reviewThreads(first:100,after:$c){pageInfo{hasNextPage endCursor}nodes{isResolved isOutdated path line
comments(first:50){nodes{databaseId author{login} body createdAt}}}}}}}"""


def _threads(repo, number):
    o, r = repo.split("/", 1)
    out, cursor = [], None
    while True:
        args = ["api", "graphql", "-f", "query=" + THREADS_Q, "-F", "o=" + o, "-F", "r=" + r, "-F", "n=%d" % number]
        if cursor:
            args += ["-F", "c=" + cursor]
        page = gh_json(args)["data"]["repository"]["pullRequest"]["reviewThreads"]
        out += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            return out
        cursor = page["pageInfo"]["endCursor"]


def threads(repo, number):
    """For each posted finding: resolved, outdated, the author's replies, and whether its file changed since the
    pass that posted it. Plus the commits since the last pass. Read-only; the agent judges what it means."""
    rec = need(repo, number)
    meta = pr_meta(repo, number)
    last = rec["passes"][-1]
    by_comment = {}
    for t in _threads(repo, number):
        nodes = t["comments"]["nodes"]
        if nodes:
            by_comment[nodes[0]["databaseId"]] = t
    changed = {}
    for p in rec["passes"]:
        if p["head_sha"] != meta["head_sha"]:
            try:
                j = gh_json(["api", "repos/%s/compare/%s...%s" % (repo, p["head_sha"], meta["head_sha"])],
                            timeout=120)
                changed[p["n"]] = {f["filename"] for f in j.get("files") or []}
            except ReviewError:
                changed[p["n"]] = None      # force-pushed away: the old commit is gone
    rows = []
    for p in rec["passes"]:
        for f in p["findings"]:
            if f["status"] != "keep" or not f.get("comment_url"):
                continue
            t = by_comment.get(f["comment_id"]) if f["comment_id"] else None
            files = changed.get(p["n"], set())
            replies = [{"by": (c.get("author") or {}).get("login", ""), "body": c["body"][:1500], "at": c["createdAt"]}
                       for c in (t["comments"]["nodes"][1:] if t else [])]
            rows.append({"id": f["id"], "title": f["title"], "file": f["file"], "line": f["line"],
                         "inline": bool(t), "resolved": bool(t and t["isResolved"]),
                         "outdated": bool(t and t["isOutdated"]), "replies": replies,
                         "file_changed": None if files is None else (f["file"] in files if f["file"] else None)})
    return {"repo": repo, "number": number, "head_sha": meta["head_sha"], "last_reviewed_sha": last["head_sha"],
            "new_commits": meta["head_sha"] != last["head_sha"], "posted": rows}


# ---------------------------------------------------------------- what the review reads

def _expand(path):
    path = os.path.expanduser(path)
    if os.path.isdir(path):
        return sorted(glob.glob(os.path.join(path, "**", "*.md"), recursive=True))
    return [path] if os.path.isfile(path) else []


def default_dir():
    return os.path.join(C.PLUGIN_ROOT, "review")


def override_dir():
    return C.lfg_path("overrides", "review")


def sources():
    """Method and knowledge files, in the order to read them. `review.sources` in config.json replaces the shipped
    defaults (point it at your own skill and references, read in place); ~/.lfg/overrides/review/ always comes last
    and wins on conflict."""
    cfg = C.config().get("review") or {}
    base = cfg.get("sources") or [default_dir()]
    out, missing = [], []
    for s in base:
        got = _expand(s)
        (out.extend(got) if got else missing.append(s))
    out += _expand(override_dir())
    return {"files": out, "missing": missing, "own": bool(cfg.get("sources"))}


def method():
    """What the Review method section shows: the files and folders a review reads, in order, each with whether it is
    there and how many files it holds; then your overrides, read last."""
    cfg = C.config().get("review") or {}
    own = list(cfg.get("sources") or [])
    rows = [{"path": x, "found": len(_expand(x)), "missing": not _expand(x)} for x in own or [default_dir()]]
    return {"own": bool(own), "sources": rows, "builtin": default_dir(), "overrides": override_dir(),
            "override_files": _expand(override_dir())}


def set_sources(paths):
    """Your review method: the files and folders /lfg:review reads instead of LFG's built-in one, in order (later
    ones win). An empty list goes back to the built-in method. Each must exist."""
    from . import settings as ST
    if not isinstance(paths, list) or not all(isinstance(x, str) for x in paths):
        raise ReviewError("expected a list of paths")
    clean = []
    for x in (p.strip() for p in paths):
        if x and x not in clean:
            if not _expand(x):
                raise ReviewError("%s isn't a file or a folder with Markdown in it" % x)
            clean.append(x)
    path = C.lfg_path("config.json")
    raw = C.read_json(path, {}) or {}
    if not isinstance(raw, dict):
        raise ReviewError("%s is not valid JSON; fix it by hand first" % path)
    ST._backup(path, "config")
    rv = dict(raw.get("review") or {})
    if clean:
        rv["sources"] = clean
    else:
        rv.pop("sources", None)
    if rv:
        raw["review"] = rv
    else:
        raw.pop("review", None)
    C.write_json(path, raw)
    return method()


def agents_md(repo, head_sha, files):
    """AGENTS.md files as of the PR's head that govern the changed files: the root one plus any in a folder above a
    changed file."""
    tree = gh_json(["api", "repos/%s/git/trees/%s?recursive=1" % (repo, head_sha)], timeout=120)
    have = {t["path"] for t in tree.get("tree") or [] if os.path.basename(t["path"]) in ("AGENTS.md", "CLAUDE.md")}
    want = set()
    for f in files:
        d = os.path.dirname(f)
        while True:
            for name in ("AGENTS.md", "CLAUDE.md"):
                p = os.path.join(d, name) if d else name
                if p in have:
                    want.add(p)
            if not d:
                break
            d = os.path.dirname(d)
    return sorted(want, key=lambda p: (p.count("/"), p))


def context(repo, number):
    meta = pr_meta(repo, number)
    files = [f["path"] for f in gh_json(["pr", "view", str(number), "-R", repo, "--json", "files"])["files"]]
    rec = load(repo, number)
    src = sources()
    return {"repo": repo, "number": number, "head_sha": meta["head_sha"], "author": meta["author"],
            "mine": meta["author"] == me(), "re_review": bool(rec and rec.get("passes")),
            "last_pass": rec["passes"][-1]["n"] if rec and rec.get("passes") else None,
            "record": record_path(repo, number), "sources": src["files"], "missing_sources": src["missing"],
            "agents_md": agents_md(repo, meta["head_sha"], files),
            "read_agents_md": "gh api repos/%s/contents/<path>?ref=%s -H 'Accept: application/vnd.github.raw'"
                              % (repo, meta["head_sha"]),
            "changed_files": len(files)}


# ---------------------------------------------------------------- the dashboard: queue, checkouts, background runs

_QUEUE = {}
SEARCHES = {"requested": "--review-requested=@me", "mine": "--author=@me"}


def queue(max_age=120, which="requested"):
    """Open PRs where GitHub has you as a requested reviewer ("requested") or that you opened ("mine"), each search
    cached for max_age seconds. GitHub never asks you to review your own PR, so "mine" is the only way to see them."""
    import time
    hit = _QUEUE.get(which)
    if hit and time.time() - hit[0] < max_age:
        return hit[1]
    data = _search([SEARCHES[which]], 50)
    _QUEUE[which] = (time.time(), data)
    return data


def _search(terms, limit):
    rows = gh_json(["search", "prs"] + terms + ["--state=open", "--limit", str(limit),
                    "--json", "repository,number,title,author,url,updatedAt,isDraft,body"])
    return [{"repo": r["repository"]["nameWithOwner"], "number": r["number"], "title": r["title"],
             "author": (r.get("author") or {}).get("login", ""), "url": r["url"], "updated": r["updatedAt"],
             "draft": r.get("isDraft", False), "ticket": ticket_of(r.get("title"), r.get("body"))}
            for r in rows or []]


# ---------------------------------------------------------------- Linear tickets a PR belongs to
# Read from the PR's branch (Linear's "lee/ato-4223-..."), title or description. Look-alikes that aren't tickets:
NOT_TICKETS = {"cve", "cwe", "iso", "utf", "sha", "rfc", "nist", "sp", "cmmc", "http", "tls", "aes", "rsa", "gpt",
               "fips", "pr", "v", "rc", "release", "hotfix", "bump", "python", "node", "es", "ie", "win", "x"}


def ticket_of(title="", body="", branch=""):
    """The Linear ticket id a PR is for ("ATO-4223"), or "": the branch's, else the title's (any case), else the
    description's when it names only one (a sync PR's lists many). Only config linear.team's prefix when set."""
    team = (C.config()["linear"].get("team") or "").upper()

    def ok(ids):
        return list(dict.fromkeys(t.upper() for t in ids if (t.split("-")[0].upper() == team if team else
                                                              t.split("-")[0].lower() not in NOT_TICKETS)))
    in_branch = r"(?:^|[/_-])([a-z][a-z0-9]{1,9}-\d{1,6})(?=$|[-_/])"
    for ids in (ok(re.findall(in_branch, str(branch or "").lower())),
                ok(re.findall(r"(?<![\w-])([A-Za-z][A-Za-z0-9]{1,9}-\d{1,6})(?![\w-])", str(title or ""))),
                ok(re.findall(in_branch, str(title or "").lower().split(" ")[0]))):  # titled by its branch name
        if ids:
            return ids[0]
    ids = ok(re.findall(r"\b([A-Z][A-Z0-9]{1,9}-\d{1,6})\b", str(body or "")[:4000]))
    return ids[0] if len(ids) == 1 else ""


def ticket_prs(ticket):
    """Every open PR on a ticket, in any repo you can see: GitHub's search for its id, kept when the PR names it."""
    t = str(ticket or "").strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9]{1,9}-\d{1,6}", t):
        raise ReviewError("a Linear ticket id looks like ATO-4223")
    return [x for x in _search([t], 30) if x["ticket"] == t]


REMOTE = re.compile(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?/?$")


def github_names(root):
    """owner/repo of every GitHub remote of the checkout at root, lowercased. All remotes, not `gh repo view`: in a
    fork gh picks upstream, which would leave out your own PRs on the fork."""
    names = set()
    for line in C.run(["git", "remote", "-v"], cwd=root, timeout=5).stdout.splitlines():
        m = REMOTE.search(line.split()[1] if len(line.split()) > 1 else "")
        if m:
            names.add(m.group(1).lower())
    return names


def local_checkout(repo):
    """A checkout of owner/repo on this machine: the repos LFG knows, and their sibling folders."""
    roots = set((C.enabled_state()["repos"] or {}).keys())
    for st in glob.glob(C.lfg_path("graphs", "*", "state.json")):
        r = (C.read_json(st, {}) or {}).get("repo_root")
        if r:
            roots.add(r)
    cand = []
    for r in sorted(roots):
        cand.append(r)
        parent = os.path.dirname(r.rstrip("/"))
        try:
            cand += sorted(os.path.join(parent, d) for d in os.listdir(parent))
        except OSError:
            continue
    seen = set()
    for d in cand:
        if d in seen or not os.path.isdir(os.path.join(d, ".git")):
            continue
        seen.add(d)
        url = C.run(["git", "config", "--get", "remote.origin.url"], cwd=d, timeout=5).stdout.strip()
        m = REMOTE.search(url)
        if m and m.group(1).lower() == repo.lower():
            return d
    return None


# Unattended runs may read anything and run only these. Writes to GitHub are denied on top of the guard, which only
# runs in repos where LFG is on.
RUN_ALLOW = ["Read", "Grep", "Glob", "Bash(lfg review context *)", "Bash(lfg review save *)",
             "Bash(lfg review others *)",
             "Bash(lfg review show *)", "Bash(lfg review threads *)", "Bash(lfg graphs *)", "Bash(lfg rule *)",
             "Bash(gh pr view *)", "Bash(gh pr diff *)", "Bash(gh search prs *)", "Bash(gh api repos/*)",
             "Bash(git fetch *)", "Bash(git show *)", "Bash(git diff *)", "Bash(git log *)", "Bash(git blame *)",
             "Bash(git grep *)", "mcp__linear__get_issue", "mcp__linear__list_comments",
             "mcp__plugin_lfg_code-review-graph"]
RUN_DENY = ["Bash(gh api * -X *)", "Bash(gh api * --method *)", "Bash(gh api * -f *)", "Bash(gh api * -F *)",
            "Bash(gh api * --field *)", "Bash(gh api * --raw-field *)", "Bash(gh api * --input *)",
            "Bash(gh api -X *)", "Bash(gh api --method *)", "Bash(lfg review post *)", "Edit", "Write", "NotebookEdit"]


def together(p):
    """The other PRs' reviews from the same session as pass p (reviewed together): what each PR's page shows so the
    whole review reads in one place."""
    run_ = p.get("run") or {}
    out = []
    for other in run_.get("with") or []:
        try:
            rec = load(*parse_pr(other))
        except ReviewError:
            rec = None
        q = next((x for x in reversed((rec or {}).get("passes") or [])
                  if run_.get("session_id") and (x.get("run") or {}).get("session_id") == run_["session_id"]), None)
        out.append({"pr": other, "title": (rec or {}).get("title") or "", "url": (rec or {}).get("url") or "",
                    "author": (rec or {}).get("author") or "",
                    "pass": q, "live": bool(q) and q is rec["passes"][-1] and not q.get("posted")})
    return out


def job_path(repo, number):
    return os.path.join(reviews_dir(), "jobs", "%s__%d.json" % (repo.replace("/", "__"), number))


def job(repo, number):
    j = C.read_json(job_path(repo, number))
    if j and j.get("status") == "running" and not _alive(j.get("pid")):
        j["status"] = "failed"
        j["why"] = "the review stopped without finishing"
    return j


def _alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def start(repo, number, ticket=None, fresh=False, together=()):
    """Start `lfg review run` detached (the dashboard's Review / Re-review / Review together buttons). together: more
    (repo, number) PRs to review in the same session."""
    import subprocess
    import sys
    prs = [(repo, number)] + [tuple(x) for x in together if tuple(x) != (repo, number)]
    busy = [ref(*x) for x in prs if (job(*x) or {}).get("status") == "running"]
    if busy:
        return {"started": False, "note": "A review of %s is already running." % ", ".join(busy)}
    args = [sys.executable, os.path.join(C.PLUGIN_ROOT, "bin", "lfg"), "review", "run", ref(repo, number)]
    for x in prs[1:]:
        args += ["--with", ref(*x)]
    args += ["--ticket", ticket] if ticket else []
    args += ["--fresh"] if fresh else []
    with open(os.devnull, "wb") as dn:
        subprocess.Popen(args, stdout=dn, stderr=dn, stdin=subprocess.DEVNULL, start_new_session=True,
                         close_fds=True)
    return {"started": True}


def ref(repo, number):
    return "%s#%d" % (repo, number)


def _passes(repo, number):
    return len((load(repo, number) or {}).get("passes") or [])


def run(repo, number, ticket=None, fresh=False, together=()):
    """Review one PR with Claude Code in print mode, on your own login, and wait for it. together: more PRs reviewed
    in the same session as one change (a backend and the frontend that calls it): each gets its own review, and the
    session also checks they agree with each other. Every review it saves remembers the session, so you can resume it,
    and its log, so the page can show what it did."""
    import shutil
    import subprocess
    if not C.which("claude"):
        raise ReviewError("Claude Code (`claude`) is not on PATH")
    prs = [(repo, number)] + [tuple(x) for x in together if tuple(x) != (repo, number)]
    before = {x: _passes(*x) for x in prs}
    cwd = local_checkout(repo) or C.ensure_dir(reviews_dir())
    log = job_path(repo, number)[:-5] + ".log"
    refs = [ref(*x) for x in prs]
    for x in prs:
        C.write_json(job_path(*x), {
            "repo": x[0], "number": x[1], "status": "running", "pid": os.getpid(), "started": C.now_iso(),
            "cwd": cwd, "log": log, "re_review": before[x] > 0 and not fresh, "fresh": bool(fresh),
            "with": [r for r in refs if r != ref(*x)], "ticket": ticket or ""})
    skill = os.path.join(C.PLUGIN_ROOT, "skills", "review", "SKILL.md")
    if len(prs) == 1:
        what = "to review %s" % refs[0]
        out = "end your last message with the Output JSON in one ```json block"
    else:
        what = ("to review these PRs together, as one change: %s. They are meant to work together (for example a "
                "backend and the frontend that calls it). Review each one as the skill says, and also check that they "
                "agree with each other (API shapes, field names, error cases, which has to ship first); put a problem "
                "between them on the PR whose code should change, and say in each summary how it fits the others"
                % ", ".join(refs))
        out = ("end your last message with one ```json block {\"reviews\": [{\"pr\": \"owner/repo#number\", ...the "
               "Output JSON for that PR}]}, one entry per PR")
    prompt = ("Read %s and follow it %s%s. You are running unattended from the LFG dashboard: nobody can answer "
              "questions, so put anything you would have asked in the summary. Run each shell command on its own, "
              "never chained with ; or &&. Don't run `lfg review save` and don't write files: %s, and LFG saves it. "
              "Skip the steps after saving (showing the table, triage, the post command).%s"
              % (skill, what, " (Linear ticket %s)" % ticket if ticket else "", out,
                 " Do a full first review of the whole PR, as if there were no earlier reviews: no prior list, every "
                 "finding since \"first\"." if fresh else ""))
    cmd = ["claude", "-p", prompt, "--permission-mode", "dontAsk", "--output-format", "stream-json", "--verbose",
           "--allowedTools", ",".join(RUN_ALLOW), "--disallowedTools", ",".join(RUN_DENY)]
    fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        # this code's own `lfg` first on PATH, so the session saves with the same version that started it
        env = dict(os.environ, PATH=os.path.join(C.PLUGIN_ROOT, "bin") + os.pathsep + os.environ.get("PATH", ""))
        cp = subprocess.run(cmd, cwd=cwd, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env)
    sid = session_id(log)
    first = None
    for x in prs:
        why = ""
        if _passes(*x) == before[x]:
            why = _save_from_log(x[0], x[1], log, ticket, many=len(prs) > 1)
        ok = _passes(*x) > before[x]
        if ok:
            mark_echoes(*x)
            rec = load(*x)
            p = rec["passes"][-1]
            kept = record_path(*x)[:-5] + ".pass%d.log" % p["n"]
            shutil.copyfile(log, kept)
            p["run"] = {"session_id": sid, "cwd": cwd, "log": kept, "with": [r for r in refs if r != ref(*x)]}
            store(rec)
        j = dict(job(*x) or {}, status="done" if ok else "failed", exit=cp.returncode, ended=C.now_iso(),
                 why="" if ok else why)
        C.write_json(job_path(*x), j)
        C.audit("review_run", {"pr": ref(*x), "status": j["status"], "with": len(prs) - 1})
        first = first or j
    for i, x in enumerate(refs):
        for y in refs[i + 1:]:
            link(x, y)
    rec = load(repo, number) or {}
    p = (rec.get("passes") or [{}])[-1]
    done = first["status"] == "done"
    score = " · score %s" % p["score"] if p.get("score") is not None else ""
    notify(ref(repo, number), "Review %s: %s" % ("done" if done else "failed", rec.get("title") or ref(repo, number)),
           "%s · %d findings%s" % (", ".join(refs), len(p.get("findings") or []), score) if done
           else first.get("why") or "see the log", ok=done)
    return first


# ---------------------------------------------------------------- notices: a review finished

NOTICES_KEEP = 50
SEEN_FOR = 90  # seconds: a dashboard tab that asked this recently shows the notice itself


def notices_path():
    return os.path.join(reviews_dir(), "notices.json")


def notify(pr, title, body, ok=True):
    """Tell you a review (or a fix) finished. Every open dashboard tab shows it as a desktop notification that opens
    the review; with no tab open, macOS shows a plain one instead."""
    import subprocess
    d = C.read_json(notices_path(), {}) or {}
    items = (d.get("items") or [])[-(NOTICES_KEEP - 1):]
    n = max([x["n"] for x in items] or [0]) + 1
    items.append({"n": n, "pr": pr, "title": title[:200], "body": str(body)[:400], "ok": bool(ok), "at": C.now_iso()})
    C.write_json(notices_path(), dict(d, items=items))
    if time.time() - float(d.get("seen") or 0) > SEEN_FOR and C.which("osascript"):
        script = "display notification %s with title %s" % (json.dumps(str(body)[:200]),
                                                             json.dumps("LFG: " + title[:150]))
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)


def notices(since):
    """Notices after number `since` (0: none, just the latest number to start from), and note a dashboard is open."""
    d = C.read_json(notices_path(), {}) or {}
    items = d.get("items") or []
    C.write_json(notices_path(), dict(d, seen=time.time()))
    last = max([x["n"] for x in items] or [0])
    return {"last": last, "items": [x for x in items if x["n"] > since] if since else []}


def session_id(log):
    """The Claude Code session a stream-json log came from (every event carries it)."""
    for ln in C.read_text(log).splitlines()[:50]:
        try:
            ev = json.loads(ln)
        except ValueError:
            continue
        if isinstance(ev, dict) and ev.get("session_id"):
            return ev["session_id"]
    return ""


def resume(run):
    """The command that picks a review's session back up, so you can ask it about its findings."""
    from . import sessions as SS
    return SS.resume_command({"cwd": run.get("cwd"), "id": run["session_id"]}) if run.get("session_id") else ""


def backfill(repo, number):
    """Reviews run before passes kept their session: the job log of the last run still has it, so give it to the
    latest pass if that pass came from that run."""
    import shutil
    rec, j = load(repo, number), job(repo, number) or {}
    p = ((rec or {}).get("passes") or [None])[-1]
    if not p or p.get("run") or j.get("status") != "done" or (p.get("ts") or "") < (j.get("started") or "~"):
        return rec
    sid = session_id(j.get("log") or "")
    if not sid:
        return rec
    kept = record_path(repo, number)[:-5] + ".pass%d.log" % p["n"]
    shutil.copyfile(j["log"], kept)
    p["run"] = {"session_id": sid, "cwd": j.get("cwd") or "", "log": kept, "with": list(j.get("with") or [])}
    store(rec)
    return rec


ASK = ("Lee is asking about the review you just did, from the LFG dashboard. Answer from what you found and what the "
       "code says; read more of it if you need to. Don't save, post or change anything, and don't rewrite the review "
       "unless asked: just answer, short and plain. If a finding was wrong, say so.\n\n%s")


def ask(repo, number, n, question):
    """Ask the very session that did a review about it (resumes it, read-only). The question and answer are kept on
    the pass, so the conversation shows on the review's page."""
    import subprocess
    if not str(question or "").strip():
        raise ReviewError("ask something, e.g. \"why is 1.2 a blocker?\"")
    rec = need(repo, number)
    p = next((x for x in rec["passes"] if x["n"] == int(n or 0)), None)
    run_ = (p or {}).get("run") or {}
    if not run_.get("session_id"):
        raise ReviewError("this review has no session to ask: it was imported, or run before LFG kept sessions")
    if not C.which("claude"):
        raise ReviewError("Claude Code (`claude`) is not on PATH")
    q = _text(question, "question", 4000)
    cp = subprocess.run(["claude", "-p", ASK % q, "--resume", run_["session_id"], "--output-format", "json",
                         "--permission-mode", "dontAsk", "--allowedTools",
                         ",".join(x for x in RUN_ALLOW if "review save" not in x),
                         "--disallowedTools", ",".join(RUN_DENY)],
                        cwd=run_.get("cwd") or None, capture_output=True, text=True, timeout=600,
                        stdin=subprocess.DEVNULL)
    try:
        text = (json.loads(cp.stdout).get("result") or "").strip()
    except ValueError:
        text = ""
    if not text:
        raise ReviewError("Claude didn't answer: %s" % (cp.stderr or cp.stdout or "")[-300:].strip())
    p.setdefault("chat", []).append({"q": q, "a": text, "at": C.now_iso()})
    store(rec)
    return {"q": q, "a": text}


def activity(path, limit=400):
    """What a review run did, in order, from its log: what it said and each tool it used."""
    out = []
    for ln in C.read_text(path).splitlines():
        try:
            ev = json.loads(ln)
        except ValueError:
            continue
        if not isinstance(ev, dict) or ev.get("type") != "assistant":
            continue
        for part in (ev.get("message") or {}).get("content") or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text" and (part.get("text") or "").strip():
                out.append({"kind": "said", "text": part["text"].strip()[:4000]})
            elif part.get("type") == "tool_use":
                inp = part.get("input") or {}
                what = inp.get("command") or inp.get("file_path") or inp.get("pattern") or inp.get("url") or ""
                out.append({"kind": "tool", "tool": part.get("name") or "", "text": str(what)[:400]})
    return out[-limit:]


# ---------------------------------------------------------------- links between reviews, and to sessions

def _links_path():
    return os.path.join(reviews_dir(), "links.json")


def _links():
    d = C.read_json(_links_path(), {}) or {}
    return {"prs": d.get("prs") or {}, "sessions": d.get("sessions") or {}}


def linked(pr):
    """PRs linked to this one: reviewed together, or linked by you. They can be in other repos."""
    return sorted(_links()["prs"].get(pr) or [])


def link(a, b, on=True):
    """Link two PRs' reviews (both ways), e.g. a backend and its frontend. Either can be in any repo."""
    a, b = ref(*parse_pr(a)), ref(*parse_pr(b))
    if a == b:
        raise ReviewError("a PR can't be linked to itself")
    d = _links()
    for x, y in ((a, b), (b, a)):
        cur = set(d["prs"].get(x) or [])
        cur = cur | {y} if on else cur - {y}
        if cur:
            d["prs"][x] = sorted(cur)
        else:
            d["prs"].pop(x, None)
    C.ensure_dir(reviews_dir())
    C.write_json(_links_path(), d)
    return {"pr": a, "linked": sorted(d["prs"].get(a) or [])}


def linked_sessions(pr):
    return list(_links()["sessions"].get(pr) or [])


def link_session(pr, sid, on=True):
    """Link a Claude Code session to a PR by hand, e.g. the session where you built it."""
    pr = ref(*parse_pr(pr))
    if not re.match(r"^[0-9a-f-]{36}$", str(sid or "")):
        raise ReviewError("not a session id: %r" % sid)
    d = _links()
    cur = [x for x in d["sessions"].get(pr) or [] if x != sid] + ([sid] if on else [])
    if cur:
        d["sessions"][pr] = cur
    else:
        d["sessions"].pop(pr, None)
    C.ensure_dir(reviews_dir())
    C.write_json(_links_path(), d)
    return {"pr": pr, "sessions": cur}


# ---------------------------------------------------------------- getting a review's JSON out of a session

def find_review_json(text, key="findings"):
    """The last review JSON ({..."findings": [...]}) in some text: a ```json block, a heredoc given to
    `lfg review save`, or a bare object. key="reviews" finds a review of several PRs instead. None if there is none."""
    dec, best = json.JSONDecoder(), None
    for m in re.finditer(r"\{", text or ""):
        try:
            obj, _ = dec.raw_decode(text, m.start())
        except ValueError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get(key), list):
            best = obj
    return best


def _session_texts(path):
    """What an agent said and the commands it ran, newest last, from a Claude Code transcript or a stream-json
    log (same event shapes)."""
    out = []
    for ln in C.read_text(path).splitlines():
        try:
            ev = json.loads(ln)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        if ev.get("type") == "result" and isinstance(ev.get("result"), str):
            out.append(ev["result"])
        if ev.get("type") != "assistant":
            continue
        for part in (ev.get("message") or {}).get("content") or []:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                out.append(part.get("text") or "")
            elif part.get("type") == "tool_use":
                inp = part.get("input") or {}
                out.append(str(inp.get("command") or inp.get("content") or ""))
    return out


def json_from_session(path, key="findings"):
    for t in reversed(_session_texts(path)):
        found = find_review_json(t, key)
        if found:
            return found
    return None


def _save_from_log(repo, number, log, ticket, many=False):
    """After an unattended run: save the JSON it ended with (or tried to save). many: a review of several PRs, where
    this PR's entry is picked out of {"reviews": [{"pr": ...}]}. Returns why not, or ""."""
    if many:
        want = ref(repo, number).lower()
        data = next((x for x in (json_from_session(log, "reviews") or {}).get("reviews") or []
                     if isinstance(x, dict) and str(x.get("pr") or "").lower().endswith(want)), None)
    else:
        data = json_from_session(log)
    if not data:
        return "Claude finished without a review of this PR to save; see the log"
    data.setdefault("reviewer", me())
    try:
        save(repo, number, data, ticket=ticket)
    except ReviewError as e:
        return "The review Claude wrote didn't fit the format (%s); see the log" % e
    return ""


SESSION_DIR = os.path.join(C.HOME, ".claude", "projects")


def _mentions(repo, number):
    name = repo.split("/")[-1]
    return [s.encode() for s in ("%s#%d" % (repo, number), "%s/pull/%d" % (repo, number), "%s#%d" % (name, number),
                                 "pr diff %d -R %s" % (number, repo), "pr view %d -R %s" % (number, repo),
                                 "review %d" % number)]


def mentions(raw, repo, number):
    """True if a transcript's bytes mention this PR. "review 12" alone is too loose: it also needs the repo's name."""
    keys = _mentions(repo, number)
    hits = [k for k in keys if k in raw]
    return bool(hits) and not (hits == [keys[-1]] and repo.split("/")[-1].encode() not in raw)


def sessions_for(repo, number, days=30):
    """Your Claude Code sessions from the last `days` that mention this PR, newest first."""
    cut, out = time.time() - days * 86400, []
    for p in glob.glob(os.path.join(SESSION_DIR, "*", "*.jsonl")):
        try:
            if os.path.getmtime(p) < cut:
                continue
            with open(p, "rb") as fh:
                raw = fh.read()
        except OSError:
            continue
        if not mentions(raw, repo, number):
            continue
        title, cwd, first = "", "", ""
        for ln in raw.splitlines():
            if b'"custom-title"' in ln or b'"cwd"' in ln or (not first and b'"type":"user"' in ln):
                try:
                    ev = json.loads(ln)
                except ValueError:
                    continue
                if ev.get("type") == "custom-title":
                    title = ev.get("customTitle") or title
                cwd = cwd or ev.get("cwd") or ""
                c = (ev.get("message") or {}).get("content") if ev.get("type") == "user" else None
                if not first and isinstance(c, str) and not c.startswith("<"):
                    first = c
        out.append({"path": p, "id": os.path.basename(p)[:-6], "title": title or first[:80] or "(untitled)",
                    "cwd": cwd, "modified": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(os.path.getmtime(p))),
                    "has_json": bool(json_from_session(p))})
    return sorted(out, key=lambda s: s["modified"], reverse=True)


CONVERT = ("Below is a code review someone did in a Claude Code session. Turn it into this JSON and reply with only "
           "the JSON in one ```json block. Keep every finding the review settled on, with its wording; leave out "
           "ones it dropped or withdrew. Use null where the review doesn't say.\n\n%s\n\nThe review:\n\n%s")
SHAPE = ('{"summary": "...", "score": 0-100 or null, "approach_notes": [], "findings": [{"title": "...", '
         '"severity": "blocker|major|minor|nitpick|note", "file": "path or null", "line": int or null, '
         '"issue": "one line", "fix": "one line", "detail": "evidence, not posted", "body": "the comment the author '
         'reads", "origin": "introduced|exposed|pre-existing", "since": "first"}]}')


def import_session(repo, number, path, ticket=None, convert=True):
    """Save a review you did in an ordinary Claude Code session. Uses the JSON if the session has one; otherwise
    asks Claude, with no tools, to turn the session's review into it (one short call on your login)."""
    import subprocess
    if not (os.path.isfile(path) and os.path.realpath(path).startswith(os.path.realpath(SESSION_DIR) + os.sep)
            or path.endswith(".log") and os.path.realpath(path).startswith(os.path.realpath(reviews_dir()))):
        raise ReviewError("not a Claude Code session or a review log: %s" % path)
    data = json_from_session(path)
    if not data:
        if not convert:
            raise ReviewError("that session has no review JSON")
        if not C.which("claude"):
            raise ReviewError("Claude Code (`claude`) is not on PATH")
        said = "\n\n".join(t for t in _session_texts(path) if t.strip())[-60000:]
        cp = subprocess.run(["claude", "-p", "--output-format", "json", "--permission-mode", "dontAsk", "--tools", ""],
                            input=CONVERT % (SHAPE, said), capture_output=True, text=True, timeout=600)
        try:
            data = find_review_json(json.loads(cp.stdout).get("result") or "")
        except ValueError:
            data = None
        if not data:
            raise ReviewError("couldn't find a review in that session")
    data.setdefault("reviewer", me())
    rec = save(repo, number, data, ticket=ticket)
    rec["passes"][-1]["imported_from"] = path
    store(rec)
    j = job(repo, number)
    if j and j.get("status") == "failed":  # the run's review is saved now, so stop showing it as failed
        j.update(status="done", why="")
        C.write_json(job_path(repo, number), j)
    return rec


def progress(repo, number, lines=8):
    """The last few things a running review did, in words, from its stream-json log."""
    j = job(repo, number)
    if not j:
        return None
    steps = []
    for ln in C.read_text(j.get("log") or "").splitlines()[-400:]:
        try:
            ev = json.loads(ln)
        except ValueError:
            continue
        for part in ((ev.get("message") or {}).get("content") or []) if ev.get("type") == "assistant" else []:
            if part.get("type") == "tool_use":
                inp = part.get("input") or {}
                what = inp.get("command") or inp.get("file_path") or inp.get("pattern") or ""
                steps.append("%s %s" % (part.get("name"), str(what)[:140]))
        if ev.get("type") == "result":
            steps.append("finished: %s" % str(ev.get("result") or ev.get("subtype") or "")[:300])
    return dict(j, steps=steps[-lines:])


def dashboard(fresh=False, only=None):
    """Everything the Reviews page shows: the request queue, your own open PRs, saved reviews, and running jobs.
    `only`: a main checkout; keeps the PRs in its GitHub repos (all of them when it has no GitHub remote, with
    `no_remote` set)."""
    import concurrent.futures
    lists = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        jobs = {w: pool.submit(queue, 0 if fresh else 120, w) for w in SEARCHES}
    for w, j in jobs.items():
        try:
            lists[w] = (j.result(), "")
        except ReviewError as e:
            lists[w] = ([], str(e))
    (q, qwhy), (mine, mwhy) = lists["requested"], lists["mine"]
    yours = {(x["repo"], x["number"]) for x in mine}
    q = [x for x in q if (x["repo"], x["number"]) not in yours]
    every = recs = all_records()
    names = github_names(only) if only else set()
    others = [dict(x) for x in q + mine if names and x["repo"].lower() not in names]
    if names:
        q = [x for x in q if x["repo"].lower() in names]
        mine = [x for x in mine if x["repo"].lower() in names]
        recs = [r for r in recs if r["repo"].lower() in names]
    q, mine = [dict(x) for x in q], [dict(x) for x in mine]  # the cached lists are shared by every filter
    have = {(r["repo"], r["number"]): r for r in recs}
    for x in q + mine:
        r = have.get((x["repo"], x["number"]))
        x["passes"] = len(r["passes"]) if r else 0
        x["job"] = job(x["repo"], x["number"])
    want = {(x["repo"], x["number"]) for x in q + mine + others}
    want |= {(r["repo"], r["number"]) for r in recs if r.get("state") == "OPEN"}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        st = dict(zip(want, pool.map(lambda k: gh_status(*k), want)))
    for x in q + mine:
        x["gh"] = st.get((x["repo"], x["number"]))
        x["ticket"] = ticket_of(x["title"], "", (x["gh"] or {}).get("branch")) or x.get("ticket") or ""
    for x in others:
        x["ticket"] = ticket_of(x["title"], "", (st.get((x["repo"], x["number"])) or {}).get("branch")) \
            or x.get("ticket") or ""
    out = []
    for r in recs:
        p = r["passes"][-1]
        tally = {}
        for f in p["findings"]:
            tally[f["status"]] = tally.get(f["status"], 0) + 1
        out.append({"repo": r["repo"], "number": r["number"], "title": r.get("title"), "author": r.get("author"),
                    "url": r.get("url"), "ticket": r.get("ticket") or ticket_of(r.get("title"), "", r.get("branch")),
                    "open": r.get("state") in (None, "OPEN"), "passes": len(r["passes"]),
                    "score": p.get("score"), "posted": p.get("posted"), "tally": tally, "updated": r.get("updated"),
                    "job": job(r["repo"], r["number"]), "gh": st.get((r["repo"], r["number"]))})
    links = _links()["prs"]  # linked PRs show on every row, whichever repo they are in
    for x in q + mine + out:
        x["linked"] = links.get(ref(x["repo"], x["number"])) or []
    if names:
        near = {y for x in out for y in x["linked"]}
        for r in every:
            if ref(r["repo"], r["number"]) in near and r["repo"].lower() not in names:
                p, n = r["passes"][-1], ref(r["repo"], r["number"])
                tally = {s: sum(f["status"] == s for f in p["findings"]) for s in ("pending", "keep", "drop")}
                out.append({"repo": r["repo"], "number": r["number"], "title": r.get("title"),
                            "author": r.get("author"), "url": r.get("url"), "ticket": r.get("ticket") or "",
                            "open": r.get("state") in (None, "OPEN"), "passes": len(r["passes"]),
                            "score": p.get("score"), "posted": p.get("posted"), "tally": tally,
                            "updated": r.get("updated"), "job": job(r["repo"], r["number"]), "gh": None,
                            "linked": links.get(n) or [], "other_repo": True})
    # a ticket's PRs in the repos not picked top left: its group shows all of them
    shown = {x.get("ticket") for x in q + mine + out} - {"", None}
    more = [dict(x, passes=0, job=job(x["repo"], x["number"])) for x in others if x["ticket"] in shown]
    return {"ticket_more": more, "queue": q, "queue_why": qwhy, "mine": mine, "mine_why": mwhy, "reviews": out,
            "no_remote": bool(only) and not names}
