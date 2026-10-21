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
    return {"names": dict(p.get("names") or {}), "folders": dict(p.get("folders") or {}),
            "hidden": list(p.get("hidden") or [])}


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


CMD = re.compile(r"<command-name>\s*(/?[^<]+?)\s*</command-name>")
CMD_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.S)
BASH_IN = re.compile(r"<bash-input>(.*?)</bash-input>", re.S)
QUIET_CMDS = ("/rename", "/color", "/clear", "/compact", "/model", "/config", "/status", "/cost", "/help", "/exit")


def _prompt_of(text):
    """What you typed, as you'd recognize it: a message, a slash command with its arguments ("/review-pr 1759"), or a
    `!` shell command. None for what Claude Code adds itself (command output, caveats, interrupts)."""
    t = (text or "").strip()
    if not t or t.startswith(("[Request interrupted", "Caveat:", "<local-command", "<bash-stdout", "<bash-stderr",
                              "<task-notification", "<system-reminder")):
        return None
    m = CMD.search(t)
    if m:
        name = m.group(1) if m.group(1).startswith("/") else "/" + m.group(1)
        if name in QUIET_CMDS:
            return None
        a = CMD_ARGS.search(t)
        return (name + " " + (a.group(1).strip() if a else "")).strip()
    m = BASH_IN.search(t)
    if m:
        return "! " + m.group(1).strip()
    return None if t.startswith("<") else t


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
                text = _prompt_of(_prompt_text((ev.get("message") or {}).get("content")))
                if text:
                    out["prompts"] += 1
                    out["first"] = out["first"] or text[:300]
    return out


def _load_index():
    d = C.read_json(_index_path(), {}) or {}
    return d if d.get("v") == 3 else {"v": 3, "sessions": {}}


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
        C.write_json(_index_path(), {"v": 3, "sessions": new})
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


def listing(days=None, scripted=False, hidden=False, only=None):
    """Sessions newest first, each with repo, ticket, group, name, folder and the resume command. Sessions started
    by a script (`claude -p`, e.g. the dashboard's review runs) are left out unless `scripted`. `only`: a main
    checkout; keeps the sessions that ran in it or one of its worktrees."""
    p = prefs()
    want = os.path.realpath(only) if only else ""
    folder_of = {sid: f for f, ids in p["folders"].items() for sid in ids}
    hid = set(p["hidden"])
    cut = time.time() - days * 86400 if days else 0
    rows = []
    for s in scan():
        if s["mtime"] < cut or (s["entrypoint"] == "sdk-cli" and not scripted) or (s["id"] in hid and not hidden):
            continue
        repo, root, wt = _where(s["cwd"])
        if want and (not root or os.path.realpath(root) != want):
            continue
        r = dict(s, repo=repo, root=root, worktree=wt,
                 ticket=_ticket(s["branch"], s["title"], s["ai_title"], s["first"]),
                 folder_exists=bool(s["cwd"]) and os.path.isdir(s["cwd"]),
                 app="desktop" if s["entrypoint"] == "claude-desktop" else "")
        r["name"] = name_for(r, p["names"].get(s["id"], ""))
        r["auto_name"] = name_for(r)
        r["named"] = bool(p["names"].get(s["id"]) or s["title"])
        r["folder"] = folder_of.get(s["id"], "")
        r["hidden"] = s["id"] in hid
        r["group"] = r["folder"] or r["ticket"] or (r["branch"] if r["branch"] not in ("", "HEAD") else "") \
            or ("(no branch)" if r["root"] else "Not in a repo")
        r["resume"] = resume_command(r)
        r["modified"] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(s["mtime"]))
        for k in ("path", "size", "mtime", "sidechain_only"):
            r.pop(k, None)
        rows.append(r)
    rows.sort(key=lambda r: r["modified"], reverse=True)
    return {"sessions": rows, "folders": sorted(p["folders"]), "projects_dir": PROJECTS, "hidden_count": len(hid)}


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
    """Put a session in one of your groups (stored as "folders"; a label in LFG only, nothing on disk moves). A
    session is in at most one. Empty takes it out."""
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


# ---------------------------------------------------------------- usage, from the transcripts themselves

# Dollars per million tokens: (input, output, cache read). Cache writes cost 1.25x input (5 minutes) or 2x (1 hour).
# Anthropic's first-party API list prices; on a Max or Team plan this is what the same work would cost at API rates.
# Requests are priced as transcripts are read and the dollars kept in the usage index: after changing a price, bump
# USAGE_V so every transcript is priced again.
PRICES = {
    "claude-fable-5-1": (10.0, 50.0, 0.25), "claude-mythos-5-1": (10.0, 50.0, 0.25),
    "claude-fable-5": (10.0, 50.0, 1.00), "claude-opus-5-5": (4.0, 20.0, 0.20), "claude-opus-5": (5.0, 25.0, 0.50),
    "claude-opus-4-8": (5.0, 25.0, 0.50), "claude-opus-4-7": (5.0, 25.0, 0.50), "claude-opus-4-6": (5.0, 25.0, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20), "claude-sonnet-5": (2.0, 10.0, 0.20),
    "claude-sonnet-4-6": (3.0, 15.0, 0.30),
    "claude-haiku-5-5": (0.10, 0.50, 0.01), "claude-haiku-4-5": (1.0, 5.0, 0.10),
}
# Models whose price goes up when one request's prompt (input + cache read + cache write) is over a size.
LONG_PROMPT = {"claude-haiku-5-5": (100_000, (0.50, 2.50, 0.05))}
FIELDS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")
USAGE_V = 3


def cost(model, t):
    """Dollars for one request's token counts, or None for a model LFG has no price for. Per request, because a
    model in LONG_PROMPT is priced by the size of each prompt, not of a day's total."""
    name = re.sub(r"-\d{8}$", "", model or "")
    p = PRICES.get(name)
    if not p:
        return None
    if name in LONG_PROMPT and t["input"] + t["cache_read"] + t["cache_write_5m"] + t["cache_write_1h"] > \
            LONG_PROMPT[name][0]:
        p = LONG_PROMPT[name][1]
    inp, out, read = p
    return (t["input"] * inp + t["output"] * out + t["cache_read"] * read + t["cache_write_5m"] * inp * 1.25
            + t["cache_write_1h"] * inp * 2) / 1e6


def _file_usage(path):
    """{day: {model: {field: tokens, "usd": dollars or None if unpriced}}} for one transcript. A reply is logged once
    per content block with the same usage, so each message id counts once."""
    out, seen = {}, set()
    with open(path, "rb") as fh:
        for ln in fh:
            if b'"usage"' not in ln:
                continue
            try:
                ev = json.loads(ln)
            except ValueError:
                continue
            m = ev.get("message") if ev.get("type") == "assistant" else None
            u = (m or {}).get("usage")
            if not isinstance(u, dict) or m.get("model") in (None, "<synthetic>"):
                continue
            key = m.get("id") or ev.get("requestId") or ev.get("uuid")
            if key in seen:
                continue
            seen.add(key)
            cc = u.get("cache_creation") or {}
            w1h = cc.get("ephemeral_1h_input_tokens") or 0
            row = {"input": u.get("input_tokens") or 0, "output": u.get("output_tokens") or 0,
                   "cache_read": u.get("cache_read_input_tokens") or 0, "cache_write_1h": w1h,
                   "cache_write_5m": max((u.get("cache_creation_input_tokens") or 0) - w1h, 0)}
            ts = ev.get("timestamp") or ""
            try:
                day = time.strftime("%Y-%m-%d", time.localtime(
                    time.mktime(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")) - time.timezone))
            except ValueError:
                continue
            d = out.setdefault(day, {}).setdefault(m["model"], dict(dict.fromkeys(FIELDS, 0), usd=0.0))
            for k in FIELDS:
                d[k] += row[k]
            usd = cost(m["model"], row)
            d["usd"] = None if usd is None or d["usd"] is None else d["usd"] + usd
    return out


REVIEW_CMD = re.compile(r"^/(?:lfg:)?review(?:-pr)?(?:\s+(.*))?$")
REVIEW_RUN = re.compile(r"follow it to review (\S+#\d+)")  # the dashboard's unattended review (review.run)


def review_of(path):
    """What PR a session reviews, from its first prompt: "/review-pr 1759", "/lfg:review 12", or the dashboard's
    Review button ("owner/repo#12"). "PR review" when it names none; "" for any other session."""
    with open(path, "rb") as fh:
        for i, ln in enumerate(fh):
            if i > 200:
                return ""
            try:
                ev = json.loads(ln)
            except ValueError:
                continue
            if ev.get("type") != "user" or ev.get("isMeta") or ev.get("isSidechain"):
                continue
            text = _prompt_text((ev.get("message") or {}).get("content"))
            m = REVIEW_RUN.search(text or "")
            if m:
                return m.group(1)
            first = _prompt_of(text)
            if first is None:
                continue
            m = REVIEW_CMD.match(first)
            return ((m.group(1) or "").strip()[:60] or "PR review") if m else ""
    return ""


def _usage_index_path():
    return C.lfg_path("state", "usage-index.json")


def usage(days=30):
    """Tokens and dollars per day and per model for every Claude Code session (and its subagents), whether or not
    LFG is on there. Only transcripts that changed since last time are read again."""
    idx = C.read_json(_usage_index_path(), {}) or {}
    idx = idx if idx.get("v") == USAGE_V else {"v": USAGE_V, "files": {}}
    old, new, changed = idx["files"], {}, False
    files = glob.glob(os.path.join(PROJECTS, "*", "*.jsonl")) + \
        glob.glob(os.path.join(PROJECTS, "*", "*", "subagents", "*.jsonl"))
    for p in files:
        try:
            st = os.stat(p)
        except OSError:
            continue
        hit = old.get(p)
        if hit and hit["size"] == st.st_size and hit["mtime"] == st.st_mtime:
            new[p] = hit
            continue
        try:
            # a subagent's file sits under its session's folder: it counts as that session's work
            main = p if os.path.basename(os.path.dirname(p)) != "subagents" else \
                os.path.dirname(os.path.dirname(p)) + ".jsonl"
            try:
                rv = review_of(main)
            except OSError:
                rv = ""
            new[p] = {"size": st.st_size, "mtime": st.st_mtime, "days": _file_usage(p), "review": rv,
                      "session": os.path.basename(main)[:-6]}
            changed = True
        except OSError:
            continue
    if changed or len(new) != len(old):
        C.ensure_dir(os.path.dirname(_usage_index_path()))
        C.write_json(_usage_index_path(), {"v": USAGE_V, "files": new})
    since = time.strftime("%Y-%m-%d", time.localtime(time.time() - (days - 1) * 86400))
    today = time.strftime("%Y-%m-%d")
    week = time.strftime("%Y-%m-%d", time.localtime(time.time() - 6 * 86400))
    month = time.strftime("%Y-%m-%d", time.localtime(time.time() - 29 * 86400))
    per_day, per_model, unpriced, reviews = {}, {}, set(), {}
    spend = {"today": 0.0, "7d": 0.0, "30d": 0.0, "range": 0.0}  # range: all `days` asked for
    for f in new.values():
        rv = f.get("review") or ""
        for day, models in f["days"].items():
            if day < since:
                continue
            for model, t in models.items():
                dd = per_day.setdefault(day, dict(dict.fromkeys(FIELDS + ("usd", "review_usd", "review_tokens"), 0),
                                                  models={}))
                dm = dd["models"].setdefault(model, dict.fromkeys(FIELDS + ("usd",), 0))
                mm = per_model.setdefault(model, dict.fromkeys(FIELDS + ("usd",), 0))
                usd = t["usd"]
                if usd is None:
                    unpriced.add(model)
                    usd = 0.0
                for k in FIELDS:
                    dd[k] += t[k]
                    mm[k] += t[k]
                    dm[k] += t[k]
                dm["usd"] += usd
                dd["usd"] += usd
                if rv:
                    dd["review_usd"] += usd
                    dd["review_tokens"] += sum(t[k] for k in FIELDS)
                    r = reviews.setdefault(f.get("session") or "", {"session": f.get("session") or "", "pr": rv,
                                                                    "usd": 0.0, "tokens": 0, "last": day})
                    r["usd"] += usd
                    r["tokens"] += sum(t[k] for k in FIELDS)
                    r["last"] = max(r["last"], day)
                mm["usd"] += usd
                spend["range"] += usd
                spend["30d"] += usd if day >= month else 0
                spend["7d"] += usd if day >= week else 0
                spend["today"] += usd if day == today else 0
    for dd in per_day.values():
        dd["models"] = {m: dict(v, usd=round(v["usd"], 4)) for m, v in dd["models"].items()}
        dd["review_usd"] = round(dd["review_usd"], 4)
    as_rows = lambda d, k: [dict(v, **{k: n}) for n, v in sorted(d.items())]  # noqa: E731
    return {"days": [dict(r, cache_write=r["cache_write_5m"] + r["cache_write_1h"]) for r in as_rows(per_day, "day")],
            "models": sorted([dict(r, cache_write=r["cache_write_5m"] + r["cache_write_1h"])
                              for r in as_rows(per_model, "model")], key=lambda r: -r["usd"]),
            "spend": {k: round(v, 2) for k, v in spend.items()}, "unpriced": sorted(unpriced),
            "reviews": sorted([dict(r, usd=round(r["usd"], 2)) for r in reviews.values()], key=lambda r: r["last"],
                              reverse=True)}


# ---------------------------------------------------------------- done with a ticket: hide, trash, worktrees

def hide(ids, on=True):
    """Hide sessions from the Sessions page (or show them again). Their files are untouched, so /resume still works."""
    ids = [_known(i) for i in ids]
    p = prefs()
    hidden = set(p.get("hidden") or [])
    hidden = hidden | set(ids) if on else hidden - set(ids)
    p["hidden"] = sorted(hidden)
    _save_prefs(p)
    return {"hidden": len(ids) if on else 0, "shown": 0 if on else len(ids)}


def trash(sid):
    """Move a session's transcript (and its subagents' folder) to the macOS Trash. Refused while it looks in use."""
    sid = _known(sid)
    paths = glob.glob(os.path.join(PROJECTS, "*", sid + ".jsonl"))
    if any(time.time() - os.path.getmtime(p) < 300 for p in paths):
        raise ValueError("that session was used in the last 5 minutes; close it in Claude Code first")
    bin_ = os.path.join(C.HOME, ".Trash")
    moved = []
    for p in paths + [d for d in glob.glob(os.path.join(PROJECTS, "*", sid)) if os.path.isdir(d)]:
        dest = os.path.join(bin_, "%s %s" % (os.path.basename(os.path.dirname(p)), os.path.basename(p)))
        if os.path.exists(dest):
            dest += " %d" % int(time.time())
        os.rename(p, dest)
        moved.append(dest)
    p = prefs()
    p["hidden"] = [x for x in p.get("hidden") or [] if x != sid]
    p["names"].pop(sid, None)
    for f in list(p["folders"]):
        p["folders"][f] = [x for x in p["folders"][f] if x != sid]
        if not p["folders"][f]:
            del p["folders"][f]
    _save_prefs(p)
    return {"id": sid, "moved_to_trash": moved}


def _git(cwd, *args):
    return C.run(["git", *args], cwd=cwd, timeout=30)


def worktree_state(path):
    """What would be lost by removing this worktree: uncommitted files and commits no remote has."""
    if not os.path.isdir(path):
        return {"path": path, "exists": False, "safe": False, "why": "already gone"}
    top = _git(path, "rev-parse", "--show-toplevel").stdout.strip()
    common = _git(path, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    if not top or os.path.realpath(top) != os.path.realpath(path):
        return {"path": path, "exists": True, "safe": False, "why": "not the top of a git worktree"}
    if os.path.realpath(os.path.join(path, ".git")) == os.path.realpath(common):
        return {"path": path, "exists": True, "safe": False, "why": "this is the main checkout, not a worktree"}
    branch = _git(path, "branch", "--show-current").stdout.strip()
    dirty = [ln for ln in _git(path, "status", "--porcelain").stdout.splitlines() if ln.strip()]
    unpushed = [ln for ln in _git(path, "log", "--oneline", "HEAD", "--not", "--remotes").stdout.splitlines() if ln]
    why = "; ".join(x for x in (
        "%d uncommitted file(s)" % len(dirty) if dirty else "",
        "%d commit(s) not pushed anywhere" % len(unpushed) if unpushed else "") if x)
    return {"path": path, "exists": True, "branch": branch, "dirty": dirty[:20], "unpushed": unpushed[:20],
            "safe": not why, "why": why}


def remove_worktree(path):
    """Remove a worktree only if nothing would be lost. Never forces; the branch is kept."""
    st = worktree_state(path)
    if not st["safe"]:
        raise ValueError("kept %s: %s" % (path, st["why"]))
    main = os.path.dirname(_git(path, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip())
    cp = _git(main, "worktree", "remove", path)
    if cp.returncode:
        raise ValueError((cp.stderr or cp.stdout).strip())
    return {"path": path, "branch": st["branch"]}


def group_cleanup(repo, group):
    """For "Done with this": the group's sessions and the worktrees they ran in, each with what removing it loses."""
    rows = [r for r in listing(hidden=True)["sessions"] if r["repo"] == repo and r["group"] == group]
    paths = sorted({r["cwd"] for r in rows if r["worktree"] and r["cwd"]})
    return {"sessions": [r["id"] for r in rows if not r["hidden"]], "worktrees": [worktree_state(p) for p in paths]}
