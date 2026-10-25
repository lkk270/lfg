"""What a Claude Code session changed and what it has running, read from its own transcript. Read only.

Changes: Claude Code keeps the exact patch of each Edit and the content of each new file in the transcript, so this is
what the session itself did, not what git shows now (which mixes in other sessions and your own edits). Edits that
were denied, failed or rewound are left out. Shell commands that may write files (sed -i, a script, a formatter) aren't
recorded as edits, so they're listed for you to look at.

Background work: subagents (the Agent tool) and background commands, with what each subagent is doing now from its
own transcript in <session>/subagents/. Ideas from upstream LFG's Studio (claudesess.py), reworked for this fork."""
import glob
import json
import os
import re
import time

from . import sessions as SS

EDIT_TOOLS = ("Edit", "MultiEdit", "Write", "NotebookEdit")
AGENT_TOOLS = ("Agent", "Task")
STOP_TOOLS = ("TaskStop", "KillShell", "KillBash")
NOTE = re.compile(r"<task-notification>(.*?)</task-notification>", re.S)
TASK_ID = re.compile(r"\b(?:ID|id|agentId|task_id)[:=]\s*`?([A-Za-z0-9_-]{5,})")
DONE = {"completed": "done", "success": "done", "failed": "failed", "error": "failed", "killed": "stopped",
        "stopped": "stopped", "cancelled": "stopped"}
NOISE = re.compile(r"^\s*<(local-command-stdout|local-command-caveat|system-reminder|bash-input|bash-stdout|"
                   r"bash-stderr|user-prompt-submit-hook|task-notification|command-name)", re.S)
QUIET = re.compile(r"\d?>>?\s*/dev/null|\d?>&\d")  # output thrown away, not a file written
SHELL_WRITES = re.compile(r"(\bsed\s+-i|>\s*[^&|\s]|\btee\b|\bmv\b|\bcp\b|\brm\b|\bpatch\b|\bgit\s+(apply|checkout|"
                          r"restore|stash|reset|mv|rm)\b|python3?\s+-\s*<<|\bprettier\b.*--write|\bruff\b.*(format|"
                          r"--fix)|\bblack\b|\bgofmt\b.*-w|\bnpm\s+(install|i)\b|\bpip\s+install\b)")
TOO_BIG = 6000  # lines in one file's hunks before it's summarized instead of drawn
QUIET_AFTER, KEEP_DONE = 900, 1200  # seconds: no news for 15 minutes; finished work stays 20 minutes


def _path(sid):
    sid = SS._known(sid)
    return glob.glob(os.path.join(SS.PROJECTS, "*", sid + ".jsonl"))[0]


def _text(content):
    if isinstance(content, str):
        return content
    return "\n".join(c.get("text", "") for c in content or [] if isinstance(c, dict) and c.get("type") == "text")


def _human(ev):
    """A prompt somebody typed (text or an image), not a tool result, a notification or Claude Code's own."""
    c = (ev.get("message") or {}).get("content")
    if ev.get("isMeta") or ev.get("isCompactSummary"):
        return False
    typed = isinstance(c, str) or any(isinstance(x, dict) and x.get("type") in ("text", "image") for x in c or [])
    return typed and not NOISE.match(_text(c))


def _one_line(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _scan(path):
    """One pass over a transcript: the tool calls still in the conversation, in order (a rewind drops the turns it
    undid, as Claude Code does), each tool call's result, and the cwd. Subagent (sidechain) lines are left out.
    A rewind shows as a typed prompt that continues from an earlier line, or a `rewound` marker. Following
    parentUuid through the whole file isn't safe: parallel tool calls branch it too."""
    seq, results, pos, notes, cwd = [], {}, {}, [], ""
    with open(path, "rb") as fh:
        for raw in fh:
            try:
                ev = json.loads(raw)
            except ValueError:
                continue
            t = ev.get("type")
            # Claude Code queues a finished background task's notice (queue-operation, then an attachment) before it
            # reaches the conversation, if it ever does
            for body in (ev.get("content") if t == "queue-operation" else None,
                         (ev.get("attachment") or {}).get("prompt") if t == "attachment" else None):
                for m in NOTE.finditer(body if isinstance(body, str) else ""):
                    notes.append((m.group(1), ev.get("timestamp")))
            if t == "last-prompt" and ev.get("rewound") and ev.get("leafUuid") in pos:
                del seq[pos[ev["leafUuid"]]:]
                continue
            if ev.get("isSidechain") or t not in ("user", "assistant"):
                if ev.get("uuid"):
                    pos[ev["uuid"]] = len(seq)
                continue
            cwd = cwd or ev.get("cwd") or ""
            if t == "user" and _human(ev) and pos.get(ev.get("parentUuid"), len(seq)) < len(seq):
                del seq[pos[ev["parentUuid"]]:]  # rewound: this prompt continues from before those turns
            content = (ev.get("message") or {}).get("content")
            if t == "user":
                for c in content if isinstance(content, list) else []:
                    if isinstance(c, dict) and c.get("type") == "tool_result":
                        body = c.get("content")
                        if isinstance(body, list):
                            body = "\n".join(x.get("text", "") if isinstance(x, dict) else str(x) for x in body)
                        results[c.get("tool_use_id")] = {"error": bool(c.get("is_error")), "text": str(body or ""),
                                                         "file": ev.get("toolUseResult"), "ts": ev.get("timestamp")}
                for m in NOTE.finditer(_text(content)):
                    notes.append((m.group(1), ev.get("timestamp")))
            else:
                for c in content if isinstance(content, list) else []:
                    if isinstance(c, dict) and c.get("type") == "tool_use":
                        seq.append({"id": c.get("id"), "name": c.get("name"), "input": c.get("input") or {},
                                    "ts": ev.get("timestamp")})
            if ev.get("uuid"):
                pos[ev["uuid"]] = len(seq)
    return seq, results, notes, cwd


# ---------------------------------------------------------------- what it changed

def _hunks(r):
    """Claude Code's record of one edit as display hunks: [{header, lines: [{t, old, new, text}]}]."""
    patch = r.get("structuredPatch") or []
    if not patch and r.get("type") == "create":
        body = str(r.get("content") or "").split("\n")
        patch = [{"oldStart": 0, "oldLines": 0, "newStart": 1, "newLines": len(body), "lines": ["+" + x for x in body]}]
    out = []
    for h in patch:
        old, new, lines = int(h.get("oldStart") or 0), int(h.get("newStart") or 0), []
        for ln in h.get("lines") or []:
            t = ln[:1] if ln[:1] in ("+", "-", " ") else " "
            lines.append({"t": t, "old": old if t != "+" else None, "new": new if t != "-" else None,
                          "text": ln[1:] if ln[:1] in ("+", "-", " ") else ln})
            old += t != "+"
            new += t != "-"
        out.append({"header": "@@ -%s,%s +%s,%s @@" % (h.get("oldStart"), h.get("oldLines"), h.get("newStart"),
                                                     h.get("newLines")), "lines": lines})
    return out


def changes(sid):
    """Every file this session changed, as diffs: one hunk per edit, in order, each with when it was made. The
    project's own files first; a file outside the session's folder (a scratch file, another repo) is marked."""
    seq, results, _notes, cwd = _scan(_path(sid))
    files, shell = {}, []
    for call in seq:
        res = results.get(call["id"])
        if not res or res["error"]:
            continue
        if call["name"] == "Bash":
            cmd = str(call["input"].get("command") or "")
            if SHELL_WRITES.search(QUIET.sub(" ", cmd)):
                shell.append({"command": _one_line(cmd)[:240], "ts": call["ts"]})
            continue
        r = res["file"]
        if call["name"] not in EDIT_TOOLS or not isinstance(r, dict) or not r.get("filePath"):
            continue
        fp = r["filePath"]
        rel, wt = _where(fp, cwd)
        key = (wt, rel)
        f = files.get(key)
        if f is None:
            f = files[key] = {"path": rel, "worktree": wt, "status": "added" if r.get("type") == "create" else
                              "modified", "additions": 0, "deletions": 0, "edits": 0, "hunks": [],
                              "too_big": False, "outside": rel == fp, "first": call["ts"]}
        f["edits"] += 1
        f["last"] = res["ts"] or call["ts"]
        for h in _hunks(r):
            h["at"] = res["ts"] or call["ts"]
            f["hunks"].append(h)
            f["additions"] += sum(x["t"] == "+" for x in h["lines"])
            f["deletions"] += sum(x["t"] == "-" for x in h["lines"])
    out = sorted(files.values(), key=lambda f: (f["outside"], f["worktree"]))
    for f in out:
        if sum(len(h["lines"]) for h in f["hunks"]) > TOO_BIG:
            f["too_big"], f["hunks"] = True, []
    return {"available": True, "id": sid, "cwd": cwd, "files": out, "shell": shell[-30:],
            "additions": sum(f["additions"] for f in out), "deletions": sum(f["deletions"] for f in out)}


def _where(fp, cwd):
    """(path to show, worktree name) for a file an edit wrote: relative to the session's folder, or to one of that
    repo's worktrees (<repo>.worktrees/<name>/, where LFG puts them), else the full path."""
    base = (cwd or "").rstrip("/")
    if base and fp.startswith(base + "/"):
        return fp[len(base) + 1:], ""
    m = re.match(r"^(.*?)\.worktrees/([^/]+)/(.+)$", fp)
    if base and m and (m.group(1) == base or base.startswith(m.group(1) + ".worktrees/")):
        return m.group(3), m.group(2)
    return fp, ""


def about_lines(path, lines, said, kind):
    """The message that goes to the session when you pick lines in its changes: the file, the line range and the
    lines themselves, so Claude knows exactly what you mean. `kind` "ask" answers without changing files; "change"
    makes the change."""
    nums = [x.get("new") or x.get("old") for x in lines or [] if isinstance(x, dict)]
    nums = [n for n in nums if isinstance(n, int)]
    if not nums or not str(said or "").strip():
        raise ValueError("pick some lines and say what you want")
    span = "line %d" % nums[0] if min(nums) == max(nums) else "lines %d-%d" % (min(nums), max(nums))
    body = "\n".join("%s %s" % (x.get("t") or " ", x.get("text") or "") for x in lines[:200])
    head = "About %s %s, which you changed in this session:\n```\n%s\n```\n\n" % (path, span, body)
    if kind == "change":
        return head + "Make this change there: %s" % said.strip()
    return head + "%s\n\nDon't change any files; just answer." % said.strip()


# ---------------------------------------------------------------- what it has running

def _short(name, inp):
    """What a tool call was about, in a few words: the file, the command, the search."""
    inp = inp or {}
    for k in ("file_path", "notebook_path", "path"):
        if inp.get(k):
            return "%s %s" % (name, os.path.basename(str(inp[k]).rstrip("/")))
    for k in ("description", "command", "pattern", "query", "url", "skill", "prompt"):
        if inp.get(k):
            return "%s: %s" % (name, _one_line(inp[k])[:70])
    return name


def _epoch(ts):
    try:
        import datetime
        return datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def work(sid):
    """Subagents and background commands the session started: running ones, plus what finished in the last 20
    minutes. A running subagent shows its steps so far and what it's doing now. When nothing about the session has
    been written for 15 minutes, "running" is only what the transcript last said, so it shows as "quiet"."""
    path = _path(sid)
    seq, results, notes, _cwd = _scan(path)
    acts, stopped = {}, set()
    for call in seq:
        inp = call["input"]
        if call["name"] in STOP_TOOLS:
            stopped.add(str(inp.get("task_id") or inp.get("shell_id") or inp.get("id") or ""))
        if call["name"] not in AGENT_TOOLS and not inp.get("run_in_background"):
            continue
        a = {"id": call["id"], "kind": "agent" if call["name"] in AGENT_TOOLS else "command",
             "label": _one_line(inp.get("description") or inp.get("command") or call["name"])[:120],
             "type": inp.get("subagent_type") or "", "background": bool(inp.get("run_in_background")),
             "status": "running", "started": call["ts"], "ended": None, "summary": "", "task": ""}
        res = results.get(call["id"])
        if res and a["background"]:  # its result only says it started, with the id later notices use
            m = TASK_ID.search(res["text"])
            a["task"] = m.group(1) if m else ""
            if res["error"]:
                a.update(status="failed", ended=res["ts"])
        elif res:
            a.update(status="failed" if res["error"] else "done", ended=res["ts"])
        acts[call["id"]] = a
    for body, ts in notes:  # Claude Code's word that background work finished, failed or was stopped

        def tag(t, body=body):
            m = re.search(r"<%s>(.*?)</%s>" % (t, t), body, re.S)
            return m.group(1).strip() if m else ""
        tid, task, st = tag("tool-use-id"), tag("task-id"), DONE.get(tag("status").lower())
        a = acts.get(tid) or next((x for x in acts.values() if task and x["task"] == task), None)
        if a and st:
            a.update(status=st, ended=ts, summary=_one_line(tag("summary"))[:200])
    for a in acts.values():
        if a["status"] == "running" and a["task"] and a["task"] in stopped:
            a["status"] = "stopped"
    subs = {}
    for mp in glob.glob(os.path.join(path[:-len(".jsonl")], "subagents", "*.meta.json")):
        try:
            meta = json.load(open(mp))
        except (OSError, ValueError):
            continue
        if isinstance(meta, dict) and meta.get("toolUseId"):
            subs[meta["toolUseId"]] = mp[:-len(".meta.json")] + ".jsonl"
    newest = os.path.getmtime(path)
    for a in acts.values():
        jp = subs.get(a["id"])
        if not jp or not os.path.exists(jp):
            continue
        steps, last = 0, None
        with open(jp, "rb") as fh:
            for raw in fh:
                try:
                    ev = json.loads(raw)
                except ValueError:
                    continue
                for c in ((ev.get("message") or {}).get("content") or []) if ev.get("type") == "assistant" else []:
                    if isinstance(c, dict) and c.get("type") == "tool_use":
                        steps, last = steps + 1, _short(c.get("name"), c.get("input"))
        a.update(steps=steps, now=last)
        newest = max(newest, os.path.getmtime(jp))
    quiet = time.time() - newest > QUIET_AFTER
    keep = []
    for a in acts.values():
        if a["status"] == "running":
            keep.append(dict(a, status="quiet") if quiet else a)
        elif (_epoch(a["ended"]) or 0) > time.time() - KEEP_DONE:
            keep.append(a)
    return {"available": True, "id": sid, "items": keep[-12:], "quiet": quiet}
