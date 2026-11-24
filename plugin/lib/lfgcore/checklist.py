"""Notes and a pinned checklist for a Studio session, kept in ~/.lfg/state/studio-notes.json by session id.

You edit them in the Studio sidebar; Claude edits the checklist with `lfg checklist`. Every call reads the file fresh
and changes one thing, so two writers in a row both keep their change. Writes only local state, never Linear or
GitHub."""
import os

from . import common as C

MAX_NOTES, MAX_ITEMS, MAX_TEXT = 100_000, 200, 500


def _path():
    return C.lfg_path("state", "studio-notes.json")


def _all():
    return C.read_json(_path(), {}) or {}


def _entry(data, sid):
    e = data.get(sid) or {}
    cl = e.get("checklist") or {}
    return {"notes": str(e.get("notes") or ""),
            "checklist": {"title": str(cl.get("title") or ""), "items": list(cl.get("items") or []),
                          "updated": str(cl.get("updated") or ""), "next": int(cl.get("next") or 0)}}


def _public(e):
    cl = dict(e["checklist"])
    cl.pop("next", None)
    return {"notes": e["notes"], "checklist": cl}


def _change(sid, fn):
    sid = str(sid or "").strip()
    if not sid:
        raise ValueError("No session given.")
    data = _all()
    e = _entry(data, sid)
    fn(e)
    e["checklist"]["updated"] = C.now_iso()
    data[sid] = e
    C.ensure_dir(os.path.dirname(_path()))
    C.write_json(_path(), data)
    return _public(e)


def get(sid):
    return _public(_entry(_all(), str(sid or "")))


def _text(text):
    text = str(text or "").strip()
    if not text:
        raise ValueError("An item needs some text.")
    if len(text) > MAX_TEXT:
        raise ValueError("An item can be at most %d characters." % MAX_TEXT)
    return text


def _new(cl, text, by):
    if len(cl["items"]) >= MAX_ITEMS:
        raise ValueError("A checklist can have at most %d items." % MAX_ITEMS)
    top = max([cl["next"]] + [int(str(i["id"])[1:] or 0) for i in cl["items"]])
    cl["next"] = top + 1  # ids only go up, so one that was removed is never given to another item
    return {"id": "c%d" % cl["next"], "text": _text(text), "done": False, "by": by, "at": C.now_iso()}


def _find(cl, ref):
    ref = str(ref).strip()
    for n, i in enumerate(cl["items"]):
        if i["id"] == ref or (ref.isdigit() and int(ref) == n + 1):
            return n
    raise ValueError("No item %s in this checklist." % ref)


def set_notes(sid, text):
    text = str(text or "")
    if len(text) > MAX_NOTES:
        raise ValueError("Notes can be at most %d characters." % MAX_NOTES)

    def fn(e):
        e["notes"] = text
    return _change(sid, fn)


def set_items(sid, texts, title="", by="you"):
    def fn(e):
        cl = e["checklist"]
        cl["items"], cl["next"], cl["title"] = [], 0, str(title or "")[:120]
        for t in texts:
            cl["items"].append(_new(cl, t, by))
    return _change(sid, fn)


def add(sid, text, by="you"):
    return _change(sid, lambda e: e["checklist"]["items"].append(_new(e["checklist"], text, by)))


def mark(sid, ref, done, by="you"):
    def fn(e):
        i = e["checklist"]["items"][_find(e["checklist"], ref)]
        i["done"], i["by"], i["at"] = bool(done), by, C.now_iso()
    return _change(sid, fn)


def edit(sid, ref, text, by="you"):
    def fn(e):
        i = e["checklist"]["items"][_find(e["checklist"], ref)]
        i["text"], i["by"], i["at"] = _text(text), by, C.now_iso()
    return _change(sid, fn)


def remove(sid, ref):
    return _change(sid, lambda e: e["checklist"]["items"].pop(_find(e["checklist"], ref)))


def move(sid, ref, to):
    def fn(e):
        items = e["checklist"]["items"]
        items.insert(max(0, min(int(to), len(items) - 1)), items.pop(_find(e["checklist"], ref)))
    return _change(sid, fn)


def clear_done(sid):
    def fn(e):
        e["checklist"]["items"] = [i for i in e["checklist"]["items"] if not i["done"]]
    return _change(sid, fn)


def lines(d):
    """The checklist as plain lines, `[x] 3. text`, for the command's output."""
    items = d["checklist"]["items"]
    return "\n".join("[%s] %d. %s" % ("x" if i["done"] else " ", n + 1, i["text"]) for n, i in enumerate(items)) \
        or "Checklist is empty."


def setup(env, sid):
    """Tell a Studio session's Claude about its checklist: its id in the environment (so `lfg checklist` knows whose
    list it is) and a line in the system prompt. Returns the extra claude arguments."""
    env["LFG_SESSION_ID"] = sid
    lfg = C.lfg_bin()
    return ["--append-system-prompt",
            "This is an LFG Studio session with a notes sidebar and a pinned checklist that the user can see. When the "
            "user gives you a list of things to do or track, pin it with `%s checklist set \"item\" \"item\"`, and "
            "tick items off with `%s checklist done <number>` as you finish them (also add, undo, edit, rm, show). "
            "Do not re-print the list as a table each time: the user sees it on the page." % (lfg, lfg)]
