"""When and where Headroom compressed what Claude Code sent.

"When" is exact: Headroom writes one line per request to ~/.headroom/savings_events.jsonl (time, model, tokens
before and after, dollars saved). "Where" is matched: its request log (~/.headroom/logs/proxy.log*, the last few
hours only, it rotates) records each request's cache-read, cache-write and output token counts, which are the same
numbers Claude Code writes into the session's transcript. A request whose three numbers belong to exactly one
session is counted for that session; the rest are shown as not matched. Nothing here changes Headroom.
"""
import calendar
import glob
import json
import os
import re
import time

from . import common as C
from . import sessions as SS

HR_HOME = os.path.join(C.HOME, ".headroom")
PERF = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d).* PERF (.*)$")
KV = re.compile(r"(\w+)=(\S+)")


def _local_day_hour(ts):
    """ISO UTC timestamp -> local (day, hour)."""
    try:
        t = calendar.timegm(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))  # UTC; localtime() handles daylight saving
    except ValueError:
        return None, None
    lt = time.localtime(t)
    return time.strftime("%Y-%m-%d", lt), lt.tm_hour


def when(days=30):
    """Saved tokens and dollars per day, and per hour for today, from Headroom's own event log."""
    path = os.path.join(HR_HOME, "savings_events.jsonl")
    since = time.strftime("%Y-%m-%d", time.localtime(time.time() - (days - 1) * 86400))
    today = time.strftime("%Y-%m-%d")
    per_day, per_hour, models = {}, {h: {"calls": 0, "saved": 0} for h in range(24)}, {}
    try:
        fh = open(path, "rb")
    except OSError:
        return {"available": False, "why": "Headroom has no savings log yet (%s)" % path}
    with fh:
        for ln in fh:
            try:
                e = json.loads(ln)
            except ValueError:
                continue
            day, hour = _local_day_hour(e.get("ts") or "")
            if not day or day < since:
                continue
            d = per_day.setdefault(day, {"day": day, "calls": 0, "before": 0, "saved": 0, "usd": 0.0})
            d["calls"] += 1
            d["before"] += e.get("before") or 0
            d["saved"] += e.get("saved") or 0
            d["usd"] += e.get("cost_usd") or 0
            m = models.setdefault(e.get("model") or "?", {"model": e.get("model") or "?", "calls": 0, "saved": 0,
                                                          "usd": 0.0})
            m["calls"] += 1
            m["saved"] += e.get("saved") or 0
            m["usd"] += e.get("cost_usd") or 0
            if day == today:
                per_hour[hour]["calls"] += 1
                per_hour[hour]["saved"] += e.get("saved") or 0
    rows = [per_day[k] for k in sorted(per_day)]
    for r in rows:
        r["usd"] = round(r["usd"], 2)
        r["percent"] = round(100.0 * r["saved"] / r["before"], 1) if r["before"] else 0
    return {"available": True, "days": rows, "today_by_hour": [dict(v, hour=h) for h, v in per_hour.items()],
            "models": sorted(({**m, "usd": round(m["usd"], 2)} for m in models.values()), key=lambda m: -m["saved"])}


def _requests():
    """Every request in Headroom's (rotating) request log: when, model, the three matching numbers, tokens saved."""
    out = []
    for f in sorted(glob.glob(os.path.join(HR_HOME, "logs", "proxy.log*"))):
        try:
            fh = open(f, errors="replace")
        except OSError:
            continue
        with fh:
            for ln in fh:
                if " PERF model=" not in ln:
                    continue
                m = PERF.match(ln.rstrip())
                if not m:
                    continue
                kv = dict(KV.findall(m.group(2)))
                try:
                    key = (int(kv["cache_read"]), int(kv["cache_write"]), int(kv["tok_out"]))
                    saved = int(kv.get("total_saved") or kv.get("tok_saved") or 0)
                    before = int(kv.get("tok_before") or 0)
                except (KeyError, ValueError):
                    continue
                out.append({"at": m.group(1).replace(" ", "T"), "model": kv.get("model"), "key": key,
                            "saved": saved, "before": before})
    return out


def _reply_index(paths):
    """(cache_read, cache_write, output) -> set of session ids, for the given transcripts."""
    idx = {}
    for p in paths:
        sid = os.path.basename(os.path.dirname(os.path.dirname(p))) if "/subagents/" in p else os.path.basename(p)[:-6]
        try:
            fh = open(p, "rb")
        except OSError:
            continue
        with fh:
            for ln in fh:
                if b'"usage"' not in ln or b'"assistant"' not in ln:
                    continue
                try:
                    e = json.loads(ln)
                except ValueError:
                    continue
                u = (e.get("message") or {}).get("usage") if e.get("type") == "assistant" else None
                if not isinstance(u, dict):
                    continue
                k = (u.get("cache_read_input_tokens") or 0, u.get("cache_creation_input_tokens") or 0,
                     u.get("output_tokens") or 0)
                idx.setdefault(k, set()).add(sid)
    return idx


def where():
    """Tokens Headroom saved per session and per repo, for the requests still in its request log."""
    reqs = _requests()
    if not reqs:
        return {"available": False, "why": "Headroom's request log is empty or missing"}
    start = min(r["at"] for r in reqs)
    cut = time.mktime(time.strptime(start[:19], "%Y-%m-%dT%H:%M:%S")) - 3600
    paths = [p for p in glob.glob(os.path.join(SS.PROJECTS, "*", "*.jsonl")) +
             glob.glob(os.path.join(SS.PROJECTS, "*", "*", "subagents", "*.jsonl"))
             if os.path.getmtime(p) >= cut]
    idx = _reply_index(paths)
    by_session, unmatched = {}, {"calls": 0, "saved": 0}
    for r in reqs:
        ids = idx.get(r["key"]) or set()
        if len(ids) != 1:
            unmatched["calls"] += 1
            unmatched["saved"] += r["saved"]
            continue
        sid = next(iter(ids))
        s = by_session.setdefault(sid, {"id": sid, "calls": 0, "saved": 0, "before": 0, "last": ""})
        s["calls"] += 1
        s["saved"] += r["saved"]
        s["before"] += r["before"]
        s["last"] = max(s["last"], r["at"])
    names = {s["id"]: s for s in SS.listing(hidden=True, scripted=True)["sessions"]}
    rows, repos = [], {}
    for s in by_session.values():
        info = names.get(s["id"], {})
        s.update(name=info.get("name") or s["id"][:8], repo=info.get("repo") or "(unknown)",
                 group=info.get("group") or "", resume=info.get("resume") or "",
                 percent=round(100.0 * s["saved"] / s["before"], 1) if s["before"] else 0)
        rows.append(s)
        g = repos.setdefault(s["repo"], {"repo": s["repo"], "calls": 0, "saved": 0, "sessions": 0})
        g["calls"] += s["calls"]
        g["saved"] += s["saved"]
        g["sessions"] += 1
    return {"available": True, "since": start, "requests": len(reqs), "matched": len(reqs) - unmatched["calls"],
            "unmatched": unmatched, "sessions": sorted(rows, key=lambda s: -s["saved"]),
            "repos": sorted(repos.values(), key=lambda g: -g["saved"])}


def summary(days=30):
    from . import headroom as HR
    return {"live": HR.live(timeout=1), "routed": HR.routed(), "scope": HR.scope(), "port": HR.port(),
            "when": when(days), "where": where()}
