"""The only place LFG changes anything outside ~/.lfg.

Every change is backed up, written with compare-and-swap (Claude Code rewrites its own settings files too, so a file
that changed while we were editing it is re-read and the edit redone), and recorded in the change ledger
(~/.lfg/state/ledger.json). `lfg uninstall` and the dashboard's Undo replay the ledger backwards and restore a value
only if it is still what LFG wrote: anything you changed since is left alone and reported.

Entry kinds:
  json   a key in a JSON file (settings.json, settings.local.json): before/after values
  list   items added to a JSON list (e.g. permissions.deny): only those items are removed again
  lines  lines appended to a text file (.git/info/exclude): only those lines are removed again
  link   a symlink LFG created (~/.local/bin/lfg)
  file   a file LFG created (a launchd plist): removed again, after its `undo` command runs
  cmd    a command with an undo command (claude plugin/mcp, launchctl)
"""
import hashlib
import json
import os
import shutil
import time

from . import common as C

MISSING = {"$lfg": "missing"}  # JSON-safe marker for "the key did not exist"


# ---------------------------------------------------------------- ledger

def ledger_path():
    return C.lfg_path("state", "ledger.json")


def _load():
    d = C.read_json(ledger_path(), {}) or {}
    return {"version": 1, "next": int(d.get("next") or 1), "entries": list(d.get("entries") or [])}


def _save(d):
    C.write_json(ledger_path(), d)


def entries(active_only=True):
    es = _load()["entries"]
    return [e for e in es if not (active_only and e.get("undone"))]


def _record(entry):
    d = _load()
    entry = dict(entry, id=d["next"], ts=C.now_iso())
    d["next"] += 1
    d["entries"].append(entry)
    _save(d)
    return entry


def _mark_undone(eid, note):
    d = _load()
    for e in d["entries"]:
        if e["id"] == eid:
            e["undone"], e["undo_note"] = C.now_iso(), note
    _save(d)


def find(**match):
    """Active entries whose fields equal all of `match` (e.g. kind="cmd", tag="plugin-local", target=root)."""
    return [e for e in entries() if all(e.get(k) == v for k, v in match.items())]


# ---------------------------------------------------------------- JSON files

def _read(path):
    """(raw bytes or None, parsed dict). Refuses a file that isn't a JSON object rather than overwrite it."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except FileNotFoundError:
        return None, {}
    if not raw.strip():
        return raw, {}
    try:
        data = json.loads(raw)
    except ValueError:
        raise ValueError("%s is not valid JSON; fix it by hand first (LFG left it unchanged)" % path) from None
    if not isinstance(data, dict):
        raise ValueError("%s is not a JSON object; LFG left it unchanged" % path)
    return raw, data


def _get(d, keys):
    for k in keys:
        if not isinstance(d, dict) or k not in d:
            return MISSING
        d = d[k]
    return d


def _set(d, keys, value):
    for k in keys[:-1]:
        if not isinstance(d.get(k), dict):
            d[k] = {}
        d = d[k]
    if value == MISSING:
        d.pop(keys[-1], None)
    else:
        d[keys[-1]] = value


def _prune_empty(d, keys):
    """After removing keys[-1], drop parent objects that became empty (only along this path)."""
    for i in range(len(keys) - 1, 0, -1):
        obj = _get(d, keys[:i])
        if not (isinstance(obj, dict) and not obj):
            break
        parent = d if i == 1 else _get(d, keys[:i - 1])
        parent.pop(keys[i - 1])


def backup(path, kind="claude"):
    if not os.path.isfile(path):
        return None
    dst = C.lfg_path("backups", kind, "%s.%s" % (path.strip("/").replace("/", "__"),
                                                  time.strftime("%Y%m%d%H%M%S")))
    C.ensure_dir(os.path.dirname(dst))
    shutil.copy2(path, dst)
    os.chmod(dst, 0o600)
    return dst


def _write(path, data, expect_raw):
    """Atomic write, only if the file still holds expect_raw. Returns False when it changed under us."""
    try:
        with open(path, "rb") as f:
            now = f.read()
    except FileNotFoundError:
        now = None
    if now != expect_raw:
        return False
    mode = (os.stat(path).st_mode & 0o777) if os.path.exists(path) else 0o600
    C.ensure_dir(os.path.dirname(path), 0o755)
    tmp = "%s.lfg-%d.tmp" % (path, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    return True


def _edit(path, fn):
    """Read-modify-write with compare-and-swap; fn(data) mutates data and returns a result (None = no change)."""
    for _ in range(5):
        raw, data = _read(path)
        res = fn(data)
        if res is None:
            return None
        if raw is not None:
            backup(path)
        if _write(path, data, raw):
            return res
        time.sleep(0.05)
    raise RuntimeError("%s kept changing while LFG tried to edit it; try again" % path)


def json_set(path, keys, value, why, group, tag=None, **extra):
    """Set (or with value=MISSING remove) one key. Records before/after; no-op when already equal."""
    keys = list(keys)

    def fn(data):
        before = _get(data, keys)
        if before == value:
            return None
        _set(data, keys, value)
        if value == MISSING:
            _prune_empty(data, keys)
        return before
    existed = os.path.exists(path)
    before = _edit(path, fn)
    if before is None:
        return None
    return _record(dict(extra, kind="json", target=path, keys=keys, before=before, after=value, why=why,
                        group=group, tag=tag, created_file=not existed))


def json_list_add(path, keys, items, why, group, tag=None, **extra):
    keys, added = list(keys), []

    def fn(data):
        cur = _get(data, keys)
        cur = list(cur) if isinstance(cur, list) else []
        new = [i for i in items if i not in cur]
        if not new:
            return None
        added.extend(new)
        _set(data, keys, cur + new)
        return True
    existed = os.path.exists(path)
    if not _edit(path, fn):
        return None
    return _record(dict(extra, kind="list", target=path, keys=keys, added=added, why=why, group=group, tag=tag,
                        created_file=not existed))


def json_list_remove(path, keys, items):
    """Remove exactly these items (used when undoing and for legacy clean-up). Returns the ones removed."""
    keys, gone = list(keys), []

    def fn(data):
        cur = _get(data, keys)
        if not isinstance(cur, list):
            return None
        keep = [i for i in cur if i not in items]
        gone.extend(i for i in cur if i in items)
        if not gone:
            return None
        _set(data, keys, keep if keep else MISSING)
        if not keep:
            _prune_empty(data, keys)
        return True
    if not os.path.exists(path):
        return []
    _edit(path, fn)
    return gone


def read_key(path, keys):
    try:
        return _get(_read(path)[1], list(keys))
    except ValueError:
        return MISSING


# ---------------------------------------------------------------- text lines, links, files, commands

def lines_add(path, lines, why, group, tag=None, **extra):
    have = set(C.read_text(path).splitlines())
    new = [ln for ln in lines if ln not in have]
    if not new:
        return None
    existed = os.path.exists(path)
    backup(path)
    text = C.read_text(path)
    if text and not text.endswith("\n"):
        text += "\n"
    C.ensure_dir(os.path.dirname(path), 0o755)
    with open(path, "w") as f:
        f.write(text + "".join(ln + "\n" for ln in new))
    return _record(dict(extra, kind="lines", target=path, added=new, why=why, group=group, tag=tag,
                        created_file=not existed))


def lines_take_back(path, line, **match):
    """Remove one line an earlier lines_add recorded (and only if it did), and drop it from that entry, so undo
    stays exact. Returns True when the line was LFG's and is gone."""
    d = _load()
    hit = [e for e in d["entries"] if not e.get("undone") and e.get("kind") == "lines" and e.get("target") == path
           and line in (e.get("added") or []) and all(e.get(k) == v for k, v in match.items())]
    if not hit:
        return False
    for e in hit:
        e["added"] = [ln for ln in e["added"] if ln != line]
    _save(d)
    if os.path.exists(path):
        backup(path)
        kept = [ln for ln in C.read_text(path).splitlines() if ln != line]
        with open(path, "w") as f:
            f.write("".join(ln + "\n" for ln in kept))
    return True


def link(path, to, why, group, tag=None):
    if os.path.islink(path) and os.readlink(path) == to:
        return None
    if os.path.lexists(path) and not os.path.islink(path):
        raise ValueError("%s exists and isn't LFG's; left it alone" % path)
    before = os.readlink(path) if os.path.islink(path) else None
    C.ensure_dir(os.path.dirname(path), 0o755)
    if os.path.islink(path):
        os.remove(path)
    os.symlink(to, path)
    return _record({"kind": "link", "target": path, "to": to, "before": before, "why": why, "group": group,
                    "tag": tag})


def file_created(path, why, group, tag=None, undo=None, cwd=None):
    """Record a file LFG just created (and optionally the command that unloads it before it is removed)."""
    if find(kind="file", target=path):
        return None
    return _record({"kind": "file", "target": path, "why": why, "group": group, "tag": tag, "undo": undo,
                    "cwd": cwd, "sha256": hashlib.sha256(C.read_text(path).encode()).hexdigest()})


def cmd_done(argv, undo, why, group, tag=None, cwd=None, target=None, **extra):
    """Record a command LFG ran (argv) and the command that reverses it (undo)."""
    return _record(dict(extra, kind="cmd", argv=argv, undo=undo, cwd=cwd, target=target, why=why, group=group,
                        tag=tag))


# ---------------------------------------------------------------- undo

def _run_undo(argv, cwd):
    if not argv:
        return True, ""
    if cwd and not os.path.isdir(cwd):
        return True, "folder %s is gone" % cwd
    cp = C.run(argv, cwd=cwd, timeout=120)
    return cp.returncode == 0, (cp.stderr or cp.stdout or "").strip()[-300:]


def revert(e, dry_run=False):
    """Undo one entry. Returns (status, note): status is undone | kept | failed | would-undo."""
    k, path = e["kind"], e.get("target")
    if k == "json":
        cur = read_key(path, e["keys"])
        if cur != e["after"]:
            return "kept", "%s %s was changed after LFG set it; left as is" % (path, ".".join(e["keys"]))
        if dry_run:
            return "would-undo", "restore %s in %s" % (".".join(e["keys"]), path)
        json_set_raw(path, e["keys"], e["before"])
        _cleanup_created(e)
        return "undone", "restored %s in %s" % (".".join(e["keys"]), path)
    if k == "list":
        if dry_run:
            return "would-undo", "remove %d item(s) LFG added to %s in %s" % (len(e["added"]), ".".join(e["keys"]),
                                                                            path)
        gone = json_list_remove(path, e["keys"], e["added"])
        _cleanup_created(e)
        return "undone", "removed %d item(s) from %s in %s" % (len(gone), ".".join(e["keys"]), path)
    if k == "lines":
        if dry_run:
            return "would-undo", "remove %d line(s) LFG added to %s" % (len(e["added"]), path)
        if os.path.exists(path):
            backup(path)
            kept = [ln for ln in C.read_text(path).splitlines() if ln not in set(e["added"])]
            if not kept and e.get("created_file"):
                os.remove(path)
            else:
                with open(path, "w") as f:
                    f.write("".join(ln + "\n" for ln in kept))
        return "undone", "removed LFG's lines from %s" % path
    if k == "link":
        if not os.path.islink(path) or os.readlink(path) != e["to"]:
            return "kept", "%s no longer points at LFG; left as is" % path
        if dry_run:
            return "would-undo", "remove %s" % path
        os.remove(path)
        if e.get("before"):
            os.symlink(e["before"], path)
        return "undone", "removed %s" % path
    if k == "file":
        if dry_run:
            return "would-undo", "unload and remove %s" % path
        ok, out = _run_undo(e.get("undo"), e.get("cwd"))
        if os.path.exists(path):
            os.remove(path)
        return "undone", "removed %s%s" % (path, "" if ok else " (unload: %s)" % out)
    if k == "cmd":
        if dry_run:
            return "would-undo", " ".join(e.get("undo") or []) or "nothing to run"
        ok, out = _run_undo(e.get("undo"), e.get("cwd"))
        if e.get("cleanup_json"):  # e.g. drop the empty enabledPlugins left in settings.local.json
            for p, keys in e["cleanup_json"]:
                _drop_if_empty(p, keys)
        if e.get("remove_dir_if_empty") and os.path.isdir(e["remove_dir_if_empty"]):
            try:
                os.rmdir(e["remove_dir_if_empty"])
            except OSError:
                pass
        return ("undone" if ok else "failed"), out or " ".join(e.get("undo") or [])
    return "failed", "unknown entry kind %s" % k


def json_set_raw(path, keys, value):
    """Set without recording (used by revert)."""
    def fn(data):
        if _get(data, keys) == value:
            return None
        _set(data, keys, value)
        if value == MISSING:
            _prune_empty(data, keys)
        return True
    if os.path.exists(path):
        _edit(path, fn)


def _drop_if_empty(path, keys):
    v = read_key(path, keys)
    if isinstance(v, (dict, list)) and not v:
        json_set_raw(path, keys, MISSING)
    raw, data = _read(path) if os.path.exists(path) else (None, None)
    if raw is not None and data == {}:
        os.remove(path)


def _cleanup_created(e):
    """Remove a file LFG created that is now empty ({} or no lines)."""
    path = e.get("target")
    if e.get("created_file") and path and os.path.exists(path):
        try:
            if _read(path)[1] == {}:
                os.remove(path)
        except ValueError:
            pass


def undo(eid, dry_run=False):
    e = next((x for x in entries() if x["id"] == eid), None)
    if not e:
        raise ValueError("no active change #%s" % eid)
    status, note = revert(e, dry_run)
    if status in ("undone", "kept") and not dry_run:
        _mark_undone(eid, note)
    return {"id": eid, "status": status, "note": note}


def undo_where(dry_run=False, **match):
    """Undo matching entries, newest first."""
    out = []
    for e in sorted(find(**match), key=lambda x: -x["id"]):
        out.append(undo(e["id"], dry_run))
    return out


def undo_all(dry_run=False, groups=None):
    out = []
    for e in sorted(entries(), key=lambda x: -x["id"]):
        if groups and e.get("group") not in groups:
            continue
        out.append(dict(undo(e["id"], dry_run), why=e.get("why"), group=e.get("group")))
    return out


def describe(e):
    """One plain-language line for the dashboard and `lfg changes`."""
    k, t = e["kind"], e.get("target") or ""
    if k == "json":
        return "Set %s in %s" % (".".join(e["keys"]), t) if e["after"] != MISSING else \
            "Removed %s from %s" % (".".join(e["keys"]), t)
    if k == "list":
        return "Added %d entr%s to %s in %s" % (len(e["added"]), "y" if len(e["added"]) == 1 else "ies",
                                               ".".join(e["keys"]), t)
    if k == "lines":
        return "Added %d line(s) to %s" % (len(e["added"]), t)
    if k == "link":
        return "Created %s -> %s" % (t, e.get("to"))
    if k == "file":
        return "Created %s" % t
    return "Ran `%s`" % " ".join(os.path.basename(a) if i == 0 else a for i, a in enumerate(e.get("argv") or []))
