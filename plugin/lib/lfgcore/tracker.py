"""Run bookkeeping that must not depend on a model remembering it.

`lfg issue sync` mirrors the issue a run works on into dev-graph (what the dashboard's Issues page lists), and
`lfg run set` records lane, stage and issue in run.json, moving the linked Issue's status with the stage.
Skills call these at fixed points; the dashboard only reads."""
import datetime
import os
import re
import secrets

from . import common as C

GRAPH = "dev-graph"
ACTOR = "agent:lfg"
REF = re.compile(r"^[A-Z][A-Z0-9]*-\d+$", re.I)  # tracker id, e.g. ACME-4225 (or its slug, acme-4225)
TYPES = ("bug", "feature", "task", "chore", "question", "risk")
STATUSES = ("backlog", "todo", "in_progress", "needs_review", "hold", "done", "canceled", "duplicate")
LANES = ("express", "standard", "full", "hotfix")
# pipeline stage -> Issue status
STAGES = {"grill": "todo", "plan": "todo", "fix": "in_progress", "build": "in_progress", "check": "in_progress",
          "secure": "in_progress", "pentest": "in_progress", "expert": "needs_review", "ship": "needs_review",
          "blocked": "hold", "done": "done"}

LOOKUP = """query issue_lookup($slug: String) {
    match { $i: Issue { slug: $slug } }
    return { $i.slug, $i.title, $i.status, $i.legacyRef }
}"""

TITLE_LOOKUP = """query issue_by_title($title: String) {
    match { $i: Issue { title: $title } }
    return { $i.slug, $i.title, $i.status, $i.legacyRef }
}"""


def slug_for(key):
    """ACME-4225 -> acme-4225; free text -> iss-<kebab>."""
    key = (key or "").strip()
    if REF.match(key):
        return key.lower()
    s = re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")[:60]
    if not s:
        C.die("issue key is empty", 2)
    return s if s.startswith("iss-") else "iss-" + s


def _og():
    from . import omnigraph as OG
    if not OG.ready(GRAPH, timeout=2):
        raise RuntimeError("dev-graph is not running (lfg omnigraph status)")
    return OG


def _branch():
    from . import omnigraph as OG
    return OG.repo_branch(GRAPH)


def lookup(slug):
    rows = _og().read(GRAPH, LOOKUP, "issue_lookup", {"slug": slug}, branch=_branch())
    return rows[0] if rows else None


def resolve(key, new=True):
    """The Issue slug for a tracker id, a slug or a title. A title nobody used yet gets a short random suffix, so two
    people's "fix login" stay two issues once the repo's knowledge is shared; new=False returns None for it instead.
    With dev-graph down a title can't be matched, so it gets a fresh suffixed key."""
    slug = slug_for(key)
    if REF.match(key.strip()) or key.strip().startswith("iss-"):
        return slug
    try:
        rows = _og().read(GRAPH, TITLE_LOOKUP, "issue_by_title", {"title": key.strip()}, branch=_branch())
    except RuntimeError:
        rows = []
    for row in rows:
        if str(row.get("slug", "")).startswith("iss-"):
            return row["slug"]
    return "%s-%s" % (slug, secrets.token_hex(2)) if new else None


def _mutation(verb, fields, slug_param=True):
    """Build `query <name>(typed params) { insert|update Issue ... }` for just the fields given."""
    types = {"slug": "String", "title": "String", "description": "String", "status": "String",
             "issueType": "String", "legacyRef": "String", "priority": "I32", "acceptanceCriteria": "String",
             "actor": "String", "at": "Date"}
    names = list(fields) + ["actor", "at"]
    sig = ", ".join("$%s: %s" % (n, types[n]) for n in (["slug"] if slug_param else []) + names)
    stamp = "updatedAt: $at, updatedBy: $actor"
    body = ", ".join("%s: $%s" % (f, f) for f in fields)
    if verb == "insert":
        stmt = "insert Issue { slug: $slug, %s, createdAt: $at, createdBy: $actor, %s }" % (body, stamp)
    else:
        stmt = "update Issue set { %s%s } where slug = $slug" % (body + ", " if body else "", stamp)
    return "query lfg_%s_issue(%s) {\n    %s\n}" % (verb, sig, stmt), "lfg_%s_issue" % verb


def sync(key, title=None, issue_type=None, status=None, priority=None, description=None, criteria=None):
    """Create the Issue if it's missing, else update the fields given. Returns {slug, action, status}."""
    slug = resolve(key)
    if status and status not in STATUSES:
        C.die("status must be one of %s" % ", ".join(STATUSES), 2)
    if issue_type and issue_type not in TYPES:
        C.die("type must be one of %s" % ", ".join(TYPES), 2)
    fields = {"title": title, "description": description, "status": status, "priority": priority,
              "acceptanceCriteria": criteria}
    found = lookup(slug)
    if found:
        fields = {k: v for k, v in fields.items() if v is not None}
        if issue_type:
            fields["issueType"] = issue_type
        verb = "update"
    else:
        fields = {k: v for k, v in fields.items() if v is not None}
        fields.setdefault("title", key)
        fields.setdefault("status", "todo")
        fields["issueType"] = issue_type or "task"
        if REF.match(key.strip()):
            fields["legacyRef"] = key.strip().upper()
        verb = "insert"
    query, name = _mutation(verb, list(fields))
    params = dict(fields, slug=slug, actor=ACTOR, at=datetime.date.today().isoformat())
    _og().mutate(GRAPH, query, name, params, branch=_branch())
    return {"slug": slug, "action": "created" if verb == "insert" else "updated",
            "status": fields.get("status") or (found or {}).get("status")}


def set_status(key, status):
    return sync(key, status=status)


def task_text(task):
    """(description, done-when) for a tasks.json entry, as the Issues page shows them."""
    desc = str(task.get("description") or "").strip()
    steps = [str(x).strip() for x in task.get("steps") or [] if str(x).strip()]
    if steps:
        desc += ("\n\n" if desc else "") + "Steps:\n" + "\n".join("- " + x for x in steps)
    return desc, str(task.get("verification") or "").strip()


def task_key(task):
    """The Issue key for a task: its tracker id when it has one, else iss-<task id>."""
    ref = str(task.get("linear_id") or "").strip()
    return ref if REF.match(ref) else "iss-" + str(task.get("id"))


def sync_tasks(run_dir):
    """Mirror RUN/tasks.json into dev-graph: one Issue per task with its description, steps and verification, and
    status done once the task passes (an open task keeps whatever status it has). Returns one result per task."""
    tasks = C.read_json(os.path.join(run_dir, "tasks.json"), []) or []
    tasks = tasks.get("tasks", []) if isinstance(tasks, dict) else tasks
    out = []
    for t in tasks:
        if not isinstance(t, dict) or not t.get("id"):
            continue
        desc, done_when = task_text(t)
        title = desc.split("\n", 1)[0][:200] or str(t["id"])
        key = task_key(t)
        found = lookup(slug_for(key))
        out.append(sync(key, title=None if found else title, description=desc or None, criteria=done_when or None,
                        status="done" if t.get("passes") else (None if found else "todo"),
                        priority=t.get("priority") if isinstance(t.get("priority"), int) and
                        0 <= t["priority"] <= 4 else None))
    return out


def brief_section(run_dir, name):
    """The body of the brief's section whose heading starts with `name` (e.g. "Problem"), as written."""
    text = C.read_text(os.path.join(run_dir, "01-brief.md"))
    m = re.search(r"^(#+)\s*%s[^\n]*\n" % re.escape(name), text, re.M | re.I)
    if not m:
        return ""
    rest = text[m.end():]
    end = re.search(r"^#{1,%d}\s" % len(m.group(1)), rest, re.M)
    return (rest[:end.start()] if end else rest).strip()[:6000]


def sync_brief(run_dir):
    """Copy the brief's Problem and Acceptance criteria onto the run's Issue (run.json `issue`)."""
    meta = C.read_json(os.path.join(run_dir, "run.json"), {}) or {}
    if not meta.get("issue"):
        raise RuntimeError("this run has no issue yet: `lfg run set issue=<ID or title>` first")
    desc, crit = brief_section(run_dir, "Problem"), brief_section(run_dir, "Acceptance criteria")
    if not desc and not crit:
        raise RuntimeError("01-brief.md has no Problem or Acceptance criteria section")
    return sync(meta["issue"], description=desc or None, criteria=crit or None)

