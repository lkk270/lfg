"""One list request for Studio: the Sessions page's rows plus what only a running studio knows (live state, model,
kind). Opening a row costs nothing extra: the list is the Sessions listing joined with the live studios."""
import os

from . import claudesess as CS
from . import common as C
from . import models
from . import sessions as SS

SUMMARISED = 300  # rows (newest first) whose transcript summary is built or refreshed per request
BACKGROUND_ROWS = 200  # background runs (kind background) sent per request, newest first; every other row is kept
SCOPES = ("repo", "all", "loose")
STATE = {"starting": "working", "working": "working", "needs-you": "needs-you", "idle": "idle", "ended": "ended"}
ENTRY_KIND = {"cli": "terminal", "claude-desktop": "desktop"}
KIND_SOURCE = {"studio": "lfg", "terminal": "terminal", "desktop": "desktop", "background": "background"}


def _kind(row, mine):
    if mine.get("lfg"):
        return "studio"
    return ENTRY_KIND.get(row.get("entrypoint"), "background")


def _prs(rid):
    try:
        from . import dash
        return dash.pr_states(rid)[1]
    except Exception:
        return {}


def _pr_of(by_branch, branch):
    pr = by_branch.get(branch) if branch and branch not in ("HEAD", "main", "master") else None
    return {"number": pr["number"], "state": pr.get("state"), "url": pr.get("url")} if pr else None


def _row(row, idx, live, summary, prs, names):
    row = {k: v for k, v in row.items() if k not in ("path", "size", "mtime")}
    sid = row["id"]
    mine, lv = idx.get(sid) or {}, live.get(sid)
    kind = _kind(row, mine)
    model = CS.chosen_model(mine, lv.model if lv else None, summary.get("model"))
    return dict(row, kind=kind, source=KIND_SOURCE[kind], state=STATE.get(lv.state, "working") if lv else "saved",
                live=bool(lv), model=model, model_label=models.label(model),
                title=SS.display_title(sid, names, mine.get("title"), row.get("title"), row.get("name")),
                mode=lv.mode if lv else mine.get("mode"), pr=_pr_of(prs, row.get("branch")),
                files=summary.get("files") or 0, skills=summary.get("skills") or [], issues=summary.get("issues") or [],
                updated=row.get("modified"), via="pr" if row.get("via_pr") else "ticket" if row.get("via_ticket")
                else "", worktree_name=row.get("worktree") or None)


def _live_row(lv, placed, labels, names):
    where = placed.get(lv.sid) or {}
    title = SS.display_title(lv.sid, names, lv.title)
    return {"id": lv.sid, "name": title, "title": title, "repo": "", "cwd": lv.root, "resume": "",
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
    # scripted (`claude -p`) sessions too: LFG's own studios and its background runs
    only = root if scope == "repo" and root else None
    base = SS.listing(hidden=hidden, scripted=True, with_path=True, only=only, loose=scope == "loose")
    if scope == "repo" and not root:
        base = dict(base, sessions=[])
    live, prs, cache, fresh = dict(CS._LIVE), _prs(rid), CS._summary_cache(), False
    p = SS.prefs()
    rows = []
    background = 0
    for n, r in enumerate(base["sessions"]):
        if _kind(r, idx.get(r["id"]) or {}) == "background":
            background += 1
            if background > BACKGROUND_ROWS:
                continue
        if n >= SUMMARISED:  # older rows only use a summary that is already cached
            summary, built = cache.get(r["path"]) or {}, False
        else:
            summary, built = CS.summary_for(cache, r["path"], r.get("root") or "")
        fresh = fresh or built
        rows.append(_row(r, idx, live, summary, prs, p["names"]))
    if fresh:
        C.ensure_dir(C.lfg_path("sessions"))
        C.write_json(C.lfg_path("sessions", "list-cache.json"), {k: v for k, v in cache.items() if os.path.exists(k)})
    seen = {r["id"] for r in rows}
    labels = {sid: [{"name": n, "color": p["label_colors"].get(n.lower(), "gray")} for n in names]
              for sid, names in p["labels"].items()}
    placed = SS.placements()
    early = [_live_row(lv, placed, labels, p["names"]) for sid, lv in live.items()
             if sid not in seen and (lv.rid == rid if scope == "repo" else scope == "all")]
    return {"sessions": early + rows, "modes": CS.MODES, "models": models.choices(models.own_model()),
            "group_info": base["group_info"], "label_list": base["label_list"],
            "hidden_count": base["hidden_count"], "loose_count": base["loose_count"]}
