"""Every Claude Code session on this machine, whatever folder it was started in.

Claude Code keeps a session under the folder it started in, so `/resume` only lists that folder's sessions. This reads
all of them from ~/.claude/projects, works out each one's repo, worktree, branch, ticket and a name, and gives the
command that resumes it from the right folder. Names and folders you set are kept in ~/.lfg/state/sessions.json; the
transcripts themselves are only ever read.
"""
import glob
import json
import os
import re
import shlex
import time

from . import common as C

PROJECTS = os.path.join(C.HOME, ".claude", "projects")
TICKET = re.compile(r"\b([A-Z][A-Z0-9]{1,9}-\d{1,6})\b")
NOT_TICKETS = {"UTF-8", "SHA-1", "SHA-256", "ISO-8601", "HTTP-2"}
# Head and tail are enough for everything but the first prompt; big transcripts aren't read whole.
HEAD, TAIL = 256 * 1024, 512 * 1024


def _index_path():
    return C.lfg_path("state", "sessions-index.json")


def _prefs_path():
    return C.lfg_path("state", "sessions.json")


def prefs():
    p = C.read_json(_prefs_path(), {}) or {}
    return {"names": dict(p.get("names") or {}), "folders": dict(p.get("folders") or {})}


def _save_prefs(p):
    C.ensure_dir(os.path.dirname(_prefs_path()))
    C.write_json(_prefs_path(), p)


def _chunks(path, size):
    with open(path, "rb") as fh:
        if size <= HEAD + TAIL:
            return [fh.read()]
        head = fh.read(HEAD)
        fh.seek(size - TAIL)
        return [head, fh.read()]


def _prompt_text(content):
    if isinstance(content, str):
        return content
    for part in content or []:
        if isinstance(part, dict) and part.get("type") == "text":
            return part.get("text") or ""
    return ""


def _is_real_prompt(text):
    t = text.strip()
    return bool(t) and not t.startswith(("<", "[Request interrupted", "Caveat:"))


def parse(path):
    """One transcript's facts. Unreadable lines are skipped: transcripts are written while sessions run."""
    st = os.stat(path)
    out = {"id": os.path.basename(path)[:-6], "path": path, "size": st.st_size, "mtime": st.st_mtime,
           "cwd": "", "branch": "", "title": "", "ai_title": "", "first": "", "last": "", "started": "", "ended": "",
           "prompts": 0, "cost": None, "sidechain_only": True, "entrypoint": ""}
    for chunk in _chunks(path, st.st_size):
        for ln in chunk.splitlines():
            if not ln.startswith(b"{"):
                continue  # a line cut by the head/tail split
            try:
                ev = json.loads(ln)
            except ValueError:
                continue
            t = ev.get("type")
            if t == "custom-title":
                out["title"] = ev.get("customTitle") or out["title"]
            elif t == "ai-title":
                out["ai_title"] = ev.get("aiTitle") or out["ai_title"]
            elif t == "last-prompt":
                out["last"] = ev.get("lastPrompt") or out["last"]
            elif t == "cost-state":
                out["cost"] = ev.get("totalCostUSD", out["cost"])
            if t not in ("user", "assistant"):
                continue
            if not ev.get("isSidechain"):
                out["sidechain_only"] = False
            out["cwd"] = out["cwd"] or ev.get("cwd") or ""
            out["entrypoint"] = out["entrypoint"] or ev.get("entrypoint") or ""
            out["branch"] = ev.get("gitBranch") or out["branch"]
            ts = ev.get("timestamp") or ""
            out["started"] = out["started"] or ts
            out["ended"] = ts or out["ended"]
            if t == "user" and not ev.get("isMeta") and not ev.get("isSidechain"):
                text = _prompt_text((ev.get("message") or {}).get("content"))
                if _is_real_prompt(text):
                    out["prompts"] += 1
                    out["first"] = out["first"] or text.strip()[:300]
    return out


def _load_index():
    d = C.read_json(_index_path(), {}) or {}
    return d if d.get("v") == 2 else {"v": 2, "sessions": {}}


def scan():
    """Every session, parsing only transcripts that changed since last time."""
    idx = _load_index()
    old, new, changed = idx["sessions"], {}, False
    for p in glob.glob(os.path.join(PROJECTS, "*", "*.jsonl")):
        try:
            st = os.stat(p)
        except OSError:
            continue
        hit = old.get(p)
        if hit and hit["size"] == st.st_size and hit["mtime"] == st.st_mtime:
            new[p] = hit
            continue
        try:
            new[p] = parse(p)
            changed = True
        except OSError:
            continue
    if changed or len(new) != len(old):
        C.ensure_dir(os.path.dirname(_index_path()))
        C.write_json(_index_path(), {"v": 2, "sessions": new})
    return [s for s in new.values() if not s["sidechain_only"] and s["prompts"]]


def _ticket(branch, *texts):
    """A Linear-style id: from the branch first (any case, as in `lee/ato-3574-fix`), then from titles and the first
    prompt (upper case only, so prose like "gpt-4" doesn't count)."""
    for m in re.findall(r"(?:^|[/_-])([a-z][a-z0-9]{1,9}-\d{1,6})(?=$|[/_-])", branch or "", re.I):
        if m.upper() not in NOT_TICKETS:
            return m.upper()
    for t in texts:
        for m in TICKET.findall(t or ""):
            if m not in NOT_TICKETS:
                return m
    return ""


def _where(cwd):
    """(repo name, main checkout, worktree name or "") for a session's folder."""
    if not cwd:
        return "", "", ""
    root = C.git_main_root_fast(cwd) if os.path.isdir(cwd) else None
    if not root:  # folder gone (a removed worktree) or not a repo: guess from the path
        m = re.match(r"^(.*?)/([^/]+)\.worktrees/([^/]+)", cwd)
        if m:
            return m.group(2), os.path.join(m.group(1), m.group(2)), m.group(3)
        return os.path.basename(cwd.rstrip("/")) or cwd, "", ""
    wt = "" if os.path.realpath(cwd) == os.path.realpath(root) else os.path.basename(cwd.rstrip("/"))
    return os.path.basename(root), root, wt


def name_for(s, own=""):
    """Your name for it, else the /rename title, else the ticket and what the session was about, else the branch,
    else Claude Code's own title, else the first thing you asked."""
    about = s["ai_title"] or s["first"][:70]
    if own or s["title"]:
        return own or s["title"]
    if s["ticket"]:
        return "%s · %s" % (s["ticket"], about) if about else s["ticket"]
    if s["branch"] and s["branch"] not in ("main", "master", "HEAD", "qa", "prod", "dev"):
        return "%s · %s" % (s["branch"], about) if about else s["branch"]
    return about or "(untitled)"


def resume_command(s):
    return "cd %s && claude --resume %s" % (shlex.quote(s["cwd"] or C.HOME), s["id"])


def listing(days=None, scripted=False):
    """Sessions newest first, each with repo, ticket, group, name, folder and the resume command. Sessions started
    by a script (`claude -p`, e.g. the dashboard's review runs) are left out unless `scripted`."""
    p = prefs()
    folder_of = {sid: f for f, ids in p["folders"].items() for sid in ids}
    cut = time.time() - days * 86400 if days else 0
    rows = []
    for s in scan():
        if s["mtime"] < cut or (s["entrypoint"] == "sdk-cli" and not scripted):
            continue
        repo, root, wt = _where(s["cwd"])
        r = dict(s, repo=repo, root=root, worktree=wt,
                 ticket=_ticket(s["branch"], s["title"], s["ai_title"], s["first"]),
                 folder_exists=bool(s["cwd"]) and os.path.isdir(s["cwd"]),
                 app="desktop" if s["entrypoint"] == "claude-desktop" else "")
        r["name"] = name_for(r, p["names"].get(s["id"], ""))
        r["auto_name"] = name_for(r)
        r["folder"] = folder_of.get(s["id"], "")
        r["group"] = r["folder"] or r["ticket"] or (r["branch"] if r["branch"] not in ("", "HEAD") else "") \
            or ("(no branch)" if r["root"] else "Not in a repo")
        r["resume"] = resume_command(r)
        r["modified"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(s["mtime"]))
        for k in ("path", "size", "mtime", "sidechain_only"):
            r.pop(k, None)
        rows.append(r)
    rows.sort(key=lambda r: r["modified"], reverse=True)
    return {"sessions": rows, "folders": sorted(p["folders"]), "projects_dir": PROJECTS}


def _known(sid):
    if not re.match(r"^[0-9a-f-]{36}$", str(sid or "")):
        raise ValueError("not a session id: %r" % sid)
    if not glob.glob(os.path.join(PROJECTS, "*", sid + ".jsonl")):
        raise ValueError("no session %s on this machine" % sid)
    return sid


def rename(sid, name):
    """Your own name for a session, shown in LFG only (Claude Code's /rename title is left alone). Empty clears it."""
    sid, p = _known(sid), prefs()
    name = re.sub(r"\s+", " ", str(name or "")).strip()[:120]
    if name:
        p["names"][sid] = name
    else:
        p["names"].pop(sid, None)
    _save_prefs(p)
    return {"id": sid, "name": name}


def file_into(sid, folder):
    """Put a session in one of your folders (a session is in at most one). Empty folder takes it out."""
    sid, p = _known(sid), prefs()
    folder = re.sub(r"\s+", " ", str(folder or "")).strip()[:80]
    for f in list(p["folders"]):
        p["folders"][f] = [x for x in p["folders"][f] if x != sid]
        if not p["folders"][f]:
            del p["folders"][f]
    if folder:
        p["folders"].setdefault(folder, []).append(sid)
    _save_prefs(p)
    return {"id": sid, "folder": folder}
