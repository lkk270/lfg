"""One list request for Studio: the Sessions page's rows plus what only a running studio knows (live state, model,
kind). Opening a row costs nothing extra: the list is the Sessions listing joined with the live studios."""
from . import claudesess as CS
from . import models
from . import sessions as SS

SCOPES = ("repo", "all", "loose")
STATE = {"starting": "working", "working": "working", "needs-you": "needs-you", "idle": "idle", "ended": "ended"}
ENTRY_KIND = {"cli": "terminal", "claude-desktop": "desktop"}
KIND_SOURCE = {"studio": "lfg", "terminal": "terminal", "desktop": "desktop", "background": "background"}


def _kind(row, mine):
    if mine.get("lfg"):
        return "studio"
    return ENTRY_KIND.get(row.get("entrypoint"), "background")


def _summaries():
    """What the old Studio list kept per transcript (model, skills, issues), read from its cache, never re-parsed."""
    cache = CS._summary_cache()
    return {k.rsplit("/", 1)[-1][:-6]: v for k, v in cache.items() if k.endswith(".jsonl")}


def _prs(rid):
    try:
        from . import dash
        return dash.pr_states(rid)[1]
    except Exception:
        return {}


def _pr_of(by_branch, branch):
    pr = by_branch.get(branch) if branch and branch not in ("HEAD", "main", "master") else None
    return {"number": pr["number"], "state": pr.get("state"), "url": pr.get("url")} if pr else None


def _row(row, idx, live, summary, prs):
    sid = row["id"]
    mine, lv = idx.get(sid) or {}, live.get(sid)
    kind = _kind(row, mine)
    model = mine.get("model") or (lv.model if lv else "") or summary.get("model") or ""
    return dict(row, kind=kind, source=KIND_SOURCE[kind], state=STATE.get(lv.state, "working") if lv else "saved",
                live=bool(lv), model=model, model_label=models.label(model),
                title=mine.get("title") or row.get("title") or row.get("name") or "Untitled session",
                mode=lv.mode if lv else mine.get("mode"), pr=_pr_of(prs, row.get("branch")),
                skills=summary.get("skills") or [], issues=summary.get("issues") or [],
                updated=row.get("modified"), via="pr" if row.get("via_pr") else "ticket" if row.get("via_ticket")
                else "", worktree_name=row.get("worktree") or None)


def _live_row(lv, placed, labels):
    where = placed.get(lv.sid) or {}
    return {"id": lv.sid, "name": lv.title, "title": lv.title, "repo": "", "cwd": lv.root, "resume": "",
            "starred": False, "hidden": False, "folder": where.get("folder", ""), "via_pr": False,
            "via_ticket": False, "via": where.get("via", ""), "labels": labels.get(lv.sid, []),
            "branch": lv.branch, "worktree": "", "worktree_name": None, "cost": None, "modified": lv.started,
            "updated": lv.started, "prompts": 0, "loose": False, "kind": "studio", "source": "lfg",
            "state": STATE.get(lv.state, "working"), "live": True, "model": lv.model or "",
            "model_label": models.label(lv.model or ""), "mode": lv.mode, "pr": None, "skills": [], "issues": []}


def listing(rid, root, hidden=False, scope="repo"):
    """Every session in `scope` (`repo`: this repo and its worktrees, `all`, or `loose`: outside any repo), newest
    first, a live studio with no transcript yet first. Keeps the keys the Studio page reads."""
    if scope not in SCOPES:
        scope = "repo"
    idx = CS._index()
    # LFG's own studios run as `claude -p` (sdk-cli), which the Sessions page hides as scripted: ask for them by id
    studios = {sid for sid, e in idx.items() if isinstance(e, dict) and e.get("lfg")}
    only = root if scope == "repo" and root else None
    base = SS.listing(hidden=hidden, also=studios, only=only, loose=scope == "loose")
    if scope == "repo" and not root:
        base = dict(base, sessions=[])
    live, summaries, prs = dict(CS._LIVE), _summaries(), _prs(rid)
    rows = [_row(r, idx, live, summaries.get(r["id"], {}), prs) for r in base["sessions"]]
    seen = {r["id"] for r in rows}
    p = SS.prefs()
    labels = {sid: [{"name": n, "color": p["label_colors"].get(n.lower(), "gray")} for n in names]
              for sid, names in p["labels"].items()}
    placed = SS.placements()
    early = [_live_row(lv, placed, labels) for sid, lv in live.items()
             if sid not in seen and (lv.rid == rid if scope == "repo" else scope == "all")]
    return {"sessions": early + rows, "modes": CS.MODES, "models": models.choices(models.own_model()),
            "group_info": base["group_info"], "label_list": base["label_list"],
            "hidden_count": base["hidden_count"], "loose_count": base["loose_count"]}
