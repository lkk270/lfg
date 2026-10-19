"""Run bookkeeping that must not depend on a model remembering it.

`lfg issue sync` mirrors the issue a run works on into dev-graph (what the dashboard's Issues page lists), and
`lfg run set` records lane, stage and issue in run.json, moving the linked Issue's status with the stage.
Skills call these at fixed points; the dashboard only reads."""
import datetime
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
             "issueType": "String", "legacyRef": "String", "priority": "I32", "actor": "String", "at": "Date"}
    names = list(fields) + ["actor", "at"]
    sig = ", ".join("$%s: %s" % (n, types[n]) for n in (["slug"] if slug_param else []) + names)
    stamp = "updatedAt: $at, updatedBy: $actor"
    body = ", ".join("%s: $%s" % (f, f) for f in fields)
    if verb == "insert":
        stmt = "insert Issue { slug: $slug, %s, createdAt: $at, createdBy: $actor, %s }" % (body, stamp)
    else:
        stmt = "update Issue set { %s%s } where slug = $slug" % (body + ", " if body else "", stamp)
    return "query lfg_%s_issue(%s) {\n    %s\n}" % (verb, sig, stmt), "lfg_%s_issue" % verb


def sync(key, title=None, issue_type=None, status=None, priority=None, description=None):
    """Create the Issue if it's missing, else update the fields given. Returns {slug, action, status}."""
    slug = resolve(key)
    if status and status not in STATUSES:
        C.die("status must be one of %s" % ", ".join(STATUSES), 2)
    if issue_type and issue_type not in TYPES:
        C.die("type must be one of %s" % ", ".join(TYPES), 2)
    fields = {"title": title, "description": description, "status": status, "priority": priority}
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
