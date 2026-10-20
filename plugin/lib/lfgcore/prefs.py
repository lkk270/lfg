"""Your rules for Claude: defaults for every session, changes for one session, and the hard ones enforced in code.

Each preference is a switch or a pick-one choice. Defaults go into ~/.claude/lfg-preferences.md, which your CLAUDE.md
imports (`@~/.claude/lfg-preferences.md`), so every session reads them the normal way. A session can differ from the
defaults: its changes are kept here and told to it by two hooks in ~/.claude/settings.json, on SessionStart and on each
message. Preferences marked `enforce` are also checked by a PreToolUse hook before every command, so a session can't
break them by mistake.

Only you can loosen a rule. `lfg prefs set` run by Claude may only make a session stricter; loosening is the
dashboard's (with its edit key) or yours in your own terminal (`! lfg prefs set …`, which runs without hooks).
Everything is in ~/.lfg/state/prefs.json.
"""
import hashlib
import json
import os
import re
import subprocess
import sys

from . import common as C

PREFS_MD = os.path.join(C.HOME, ".claude", "lfg-preferences.md")
IMPORT_LINE = "@~/.claude/lfg-preferences.md"
PROTECTED_BRANCHES = ("main", "master", "qa", "prod", "production")

# Built in. Options are listed strictest first: a change to a later option loosens the rule.
BUILTIN = [
    {"id": "commits", "group": "Git", "title": "Commits", "kind": "choice", "default": "ask", "enforce": True,
     "options": [
         {"value": "never", "label": "Never: I make every commit", "text": "Never run `git commit`. Leave changes "
          "uncommitted and give me the commit message to use."},
         {"value": "ask", "label": "When I say so", "text": "Commit only when I ask you to in this session."},
         {"value": "auto", "label": "On its own, once tests pass", "text": "Commit on your own when a change is "
          "complete and its tests and checks pass, one commit per logical change, without asking."}]},
    {"id": "amend", "group": "Git", "title": "Amend the last commit", "kind": "switch", "default": False,
     "enforce": True, "text": "You may amend the last commit (`git commit --amend`) when it is unpushed or on my own "
     "branch.", "off_text": "Never amend a commit; make a new one."},
    {"id": "push", "group": "Git", "title": "Push", "kind": "choice", "default": "ask", "enforce": True,
     "options": [
         {"value": "never", "label": "Never: I push", "text": "Never run `git push`."},
         {"value": "ask", "label": "When I say so", "text": "Push only when I ask you to in this session."},
         {"value": "auto", "label": "After every commit", "text": "Push right after each commit, to the branch "
          "you're on."}]},
    {"id": "force_push", "group": "Git", "title": "Force-push my own branch", "kind": "switch", "default": False,
     "enforce": True, "text": "You may force-push (prefer `--force-with-lease`) a branch that isn't main, master, "
     "qa or prod, e.g. after amending or rebasing my own work.", "off_text": "Never force-push."},
    {"id": "merge_pr", "group": "GitHub", "title": "Merging PRs", "kind": "choice", "default": "never",
     "enforce": True, "options": [
         {"value": "never", "label": "Never: I merge", "text": "Never merge a pull request."},
         {"value": "squash", "label": "When I say so, squashed",
          "text": "Merge a PR only when I ask, and always as one squashed commit (`gh pr merge --squash`)."}]},
    {"id": "coauthor", "group": "Git", "title": "Claude as co-author", "kind": "switch", "default": False,
     "text": "End commit messages with a Co-Authored-By line for Claude, and PR bodies with the Claude Code line.",
     "off_text": "I am the only author: no Co-Authored-By line for Claude in commits and no \"Generated with Claude "
     "Code\" line in PR bodies."},
]


def _state_path():
    return C.lfg_path("state", "prefs.json")


def _seen_path():
    return C.lfg_path("state", "prefs-seen.json")


def load():
    d = C.read_json(_state_path(), {}) or {}
    return {"catalog": list(d.get("catalog") or []), "defaults": dict(d.get("defaults") or {}),
            "sessions": dict(d.get("sessions") or {})}


def _save(d):
    C.ensure_dir(os.path.dirname(_state_path()))
    C.write_json(_state_path(), d)


def catalog(d=None):
    d = d or load()
    return BUILTIN + [p for p in d["catalog"] if p.get("id") not in {b["id"] for b in BUILTIN}]


def _pref(pid, d=None):
    p = next((x for x in catalog(d) if x["id"] == pid), None)
    if not p:
        raise ValueError("no preference %r (see `lfg prefs`)" % pid)
    return p


def _coerce(p, value):
    if p["kind"] == "switch":
        if isinstance(value, bool):
            return value
        v = str(value).lower()
        if v in ("on", "true", "yes", "1"):
            return True
        if v in ("off", "false", "no", "0"):
            return False
        raise ValueError("%s is on or off" % p["id"])
    vals = [o["value"] for o in p["options"]]
    if value not in vals:
        raise ValueError("%s is one of %s" % (p["id"], ", ".join(vals)))
    return value


def _rank(p, value):
    """Higher is looser. Switches: on is looser for enforced rules (they allow something)."""
    if p["kind"] == "switch":
        return 1 if value else 0
    return [o["value"] for o in p["options"]].index(value)


def effective(session_id=None, d=None):
    d = d or load()
    out = {}
    over = d["sessions"].get(session_id or "", {})
    for p in catalog(d):
        out[p["id"]] = over.get(p["id"], d["defaults"].get(p["id"], p["default"]))
    return out


def _text(p, value):
    if p["kind"] == "switch":
        return p.get("text") if value else p.get("off_text")
    o = next((o for o in p["options"] if o["value"] == value), None)
    return o and o["text"]


def set_pref(pid, value, session=None, by_agent=False):
    """Set a default (session=None) or one session's value. by_agent: refuse anything that loosens a rule."""
    d = load()
    p = _pref(pid, d)
    value = _coerce(p, value)
    if session is not None and not re.match(r"^[0-9a-f-]{36}$", session):
        raise ValueError("not a session id: %r" % session)
    cur = effective(session, d)[pid]
    if by_agent and _rank(p, value) > _rank(p, cur):
        raise PermissionError("loosening %s is yours to do: lfg ui → Sessions → Rules, or `! lfg prefs set` in your "
                              "own terminal" % pid)
    if session is None:
        if value == p["default"]:
            d["defaults"].pop(pid, None)
        else:
            d["defaults"][pid] = value
    else:
        s = d["sessions"].setdefault(session, {})
        if value == d["defaults"].get(pid, p["default"]):
            s.pop(pid, None)
        else:
            s[pid] = value
        if not s:
            d["sessions"].pop(session, None)
    _save(d)
    if session is None:
        write_defaults_file(d)
    return {"id": pid, "value": value, "session": session}


def clear_session(session):
    d = load()
    d["sessions"].pop(session, None)
    _save(d)
    return {"session": session, "cleared": True}


def add_custom(pid, group, title, text, off_text="", default=True):
    """One of your own rules as a switch (e.g. split out of CLAUDE.md). Instruction only, never enforced."""
    if not re.match(r"^[a-z0-9][a-z0-9_-]{1,60}$", pid or ""):
        raise ValueError("id is lowercase letters, digits, - and _")
    if pid in {b["id"] for b in BUILTIN}:
        raise ValueError("%s is a built-in preference" % pid)
    d = load()
    d["catalog"] = [x for x in d["catalog"] if x.get("id") != pid] + [
        {"id": pid, "group": group or "Yours", "title": title, "kind": "switch", "default": bool(default),
         "text": text.strip(), "off_text": (off_text or "").strip(), "custom": True}]
    _save(d)
    write_defaults_file(d)
    return {"id": pid}


def remove_custom(pid):
    d = load()
    d["catalog"] = [x for x in d["catalog"] if x.get("id") != pid]
    d["defaults"].pop(pid, None)
    for s in d["sessions"].values():
        s.pop(pid, None)
    _save(d)
    write_defaults_file(d)
    return {"removed": pid}


# ---------------------------------------------------------------- what Claude reads

def render(values, d, only=None, header="Your rules"):
    groups = {}
    for p in catalog(d):
        if only is not None and p["id"] not in only:
            continue
        t = _text(p, values[p["id"]])
        if t:
            groups.setdefault(p["group"], []).append("- %s" % t)
    if not groups:
        return ""
    body = "\n\n".join("## %s\n%s" % (g, "\n".join(ls)) for g, ls in groups.items())
    return "# %s\n\n%s\n" % (header, body)


def write_defaults_file(d=None):
    d = d or load()
    text = ("<!-- Written by LFG from your preferences (lfg ui → Preferences). Edit them there, not here. -->\n"
            + render(effective(None, d), d, header="Your rules (defaults for every session)"))
    if C.read_text(PREFS_MD) != text:
        C.ensure_dir(os.path.dirname(PREFS_MD))
        C.write_text(PREFS_MD, text, mode=0o644)
    return PREFS_MD


def session_note(session_id, d=None):
    """What's different for this session, for the hooks to tell it. Empty if nothing is."""
    d = d or load()
    over = d["sessions"].get(session_id or "", {})
    if not over:
        return ""
    values = effective(session_id, d)
    text = render(values, d, only=set(over), header="Rules changed for this session only")
    return (text + "\nThese replace the matching defaults from lfg-preferences.md for the rest of this session. "
            "Changing them back is the user's, in lfg ui → Sessions → Rules.")


# ---------------------------------------------------------------- hooks

def _commands(cmd, depth=0):
    """(argv) for every simple command in a shell string, including `sh -c "…"` and $(…)."""
    from . import guard as G
    if depth > 6 or not cmd or not cmd.strip():
        return
    for inner in G._substitutions(cmd):
        yield from _commands(inner, depth + 1)
    segs, _ = G._segments(G._tokens(cmd))
    for seg in segs:
        try:
            _, argv = G._strip_wrappers(seg)
        except Exception:  # noqa: BLE001 - a wrapper the guard refuses: nothing for us to check
            continue
        if not argv:
            continue
        base = os.path.basename(argv[0])
        if base in ("sh", "bash", "zsh", "dash") and len(argv) >= 3 and argv[1] in ("-c", "-lc", "-ic", "-ec"):
            yield from _commands(argv[2], depth + 1)
            continue
        yield argv


def _git_sub(argv):
    i, args = 1, argv
    while i < len(args):
        a = args[i]
        if a in ("-C", "-c", "--git-dir", "--work-tree") and i + 1 < len(args):
            i += 2
            continue
        if a.startswith("-"):
            i += 1
            continue
        return a, args[i + 1:]
    return None, []


def _branch(cwd):
    try:
        cp = subprocess.run(["git", "branch", "--show-current"], cwd=cwd or None, capture_output=True, text=True,
                            timeout=5)
        return cp.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def check_command(cmd, values, cwd=None):
    """Why this shell command breaks a rule, or None."""
    for argv in _commands(cmd):
        base = os.path.basename(argv[0])
        if base == "git":
            sub, rest = _git_sub(argv)
            if sub == "commit":
                if values["commits"] == "never":
                    return "your rule for this session is that you commit, not Claude"
                if "--amend" in rest and not values["amend"]:
                    return "amending commits is off for this session"
            if sub == "push":
                if values["push"] == "never":
                    return "your rule for this session is that you push, not Claude"
                force = any(a in ("-f", "--force", "--force-with-lease", "--force-if-includes") or
                            a.startswith("--force-with-lease=") for a in rest) or \
                    any(a.startswith("+") for a in rest if not a.startswith("-"))
                if force:
                    if not values["force_push"]:
                        return "force-pushing is off for this session"
                    refs = [a.lstrip("+").split(":")[-1] for a in rest if not a.startswith("-")][1:]
                    target = refs or [_branch(cwd)]
                    if any(t.replace("refs/heads/", "") in PROTECTED_BRANCHES for t in target if t):
                        return "force-pushing main, master, qa or prod is never allowed"
        if base == "gh" and argv[1:3] == ["pr", "merge"]:
            if values["merge_pr"] == "never":
                return "your rule for this session is that you merge PRs, not Claude"
            if "--squash" not in argv and "-s" not in argv:
                return "PRs are merged as one squashed commit: add --squash"
        if base == "lfg" and argv[1:3] == ["prefs", "set"] and "--by-user" in argv:
            return "--by-user is only for your own terminal"
    return None


def _hook_input():
    try:
        return json.load(sys.stdin)
    except ValueError:
        return {}


def _seen():
    return C.read_json(_seen_path(), {}) or {}


def hook(event):
    """Entry for the three hooks. Never breaks a session: on an internal error it lets the tool run."""
    data = _hook_input()
    sid = data.get("session_id") or ""
    try:
        d = load()
        if event in ("session-start", "prompt"):
            # A session read the defaults file when it started. Tell it again only when something changed since:
            # its own rules (from Sessions → Rules) or the defaults (from Preferences).
            note = session_note(sid, d)
            dflt = render(effective(None, d), d, header="Your rules (defaults)")
            digest = hashlib.sha1((note + "\0" + dflt).encode()).hexdigest()[:12]
            seen = _seen()
            prev = seen.get(sid)
            seen[sid] = {"digest": digest, "defaults": hashlib.sha1(dflt.encode()).hexdigest()[:12]}
            C.write_json(_seen_path(), dict(list(seen.items())[-500:]))
            if event == "session-start":
                out = note
            else:
                if not isinstance(prev, dict) or prev.get("digest") == digest:
                    return 0
                parts = []
                if prev.get("defaults") != seen[sid]["defaults"]:
                    parts.append(dflt + "\nThe user changed their default rules while this session was open; these "
                                 "replace lfg-preferences.md as you read it at the start.")
                parts.append(note or "This session now follows the user's default rules, with no session changes.")
                out = "\n\n".join(parts)
            if out:
                print(json.dumps({"hookSpecificOutput": {
                    "hookEventName": "SessionStart" if event == "session-start" else "UserPromptSubmit",
                    "additionalContext": out}}))
            return 0
        if event == "pre-tool":
            tool, ti = data.get("tool_name"), data.get("tool_input") or {}
            if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
                p = os.path.realpath(os.path.expanduser(str(ti.get("file_path") or "")))
                if p in (os.path.realpath(_state_path()), os.path.realpath(PREFS_MD)):
                    sys.stderr.write("Blocked by your rules: %s holds your rules; change them in lfg ui → "
                                     "Preferences.\n" % p)
                    return 2
            if tool == "Bash":
                why = check_command(str(ti.get("command") or ""), effective(sid, d), cwd=data.get("cwd"))
                if why:
                    sys.stderr.write("Blocked by your rules: %s. Change it in lfg ui → Sessions → Rules if you "
                                     "meant to.\n" % why)
                    return 2
    except Exception as e:  # noqa: BLE001
        sys.stderr.write("lfg prefs hook error: %s\n" % type(e).__name__)
    return 0


# ---------------------------------------------------------------- installing into Claude Code

HOOKS = (("SessionStart", "startup|resume|clear|compact", "session-start"), ("UserPromptSubmit", None, "prompt"),
         ("PreToolUse", "Bash|Edit|Write|MultiEdit|NotebookEdit", "pre-tool"))


def _hook_cmd(event):
    return "%s prefs hook %s" % (C.lfg_bin(), event)


def installed():
    from . import claudecfg as CC
    s = C.read_json(os.path.join(C.HOME, ".claude", "settings.json"), {}) or {}
    have = json.dumps(s.get("hooks") or {})
    md = C.read_text(os.path.join(C.HOME, ".claude", "CLAUDE.md"))
    return {"hooks": all(_hook_cmd(e) in have for _, _, e in HOOKS), "import": IMPORT_LINE in md,
            "file": os.path.isfile(PREFS_MD), "ledger": len(CC.find(tag="prefs-hook"))}


def install():
    """Add the three hooks to ~/.claude/settings.json and the import line to ~/.claude/CLAUDE.md, through the change
    ledger (backed up, undone by `lfg changes undo` / `lfg uninstall`)."""
    from . import claudecfg as CC
    write_defaults_file()
    settings = os.path.join(C.HOME, ".claude", "settings.json")
    done = []
    for ev, matcher, name in HOOKS:
        entry = {"hooks": [{"type": "command", "command": _hook_cmd(name), "timeout": 10}]}
        if matcher:
            entry = {"matcher": matcher, **entry}
        if CC.json_list_add(settings, ["hooks", ev], [entry], "your rules: %s hook" % ev, "prefs", tag="prefs-hook"):
            done.append(ev)
    md = os.path.join(C.HOME, ".claude", "CLAUDE.md")
    if IMPORT_LINE not in C.read_text(md):
        CC.lines_add(md, ["", "# Your rules", IMPORT_LINE], "your rules: CLAUDE.md imports lfg-preferences.md",
                     "prefs", tag="prefs-import")
        done.append("CLAUDE.md import")
    return {"added": done, **installed()}
