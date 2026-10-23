"""Run a skill (or any instruction) on one of your Claude Code sessions from the dashboard, once or in a loop.

The run resumes the session, so Claude knows everything said in it. By default it works in a copy of the session
(`--fork-session`): the session you have open stays as it was, and the copy is yours to resume afterwards. Each run is
a job file under ~/.lfg/skillruns with its log, so the Sessions page can show progress, Claude's last reply and what
the run used."""
import glob
import json
import os
import re
import subprocess
import sys

from . import common as C
from . import sessions as SS


class RunError(Exception):
    pass


# Claude Code's own review commands, which aren't skill files anyone can list
BUILTIN = [("/security-review", "Security review of the pending changes on the current branch"),
           ("/code-review", "Review the current diff for correctness bugs"),
           ("/simplify", "Review the changed code for reuse, simplification and efficiency, then fix it")]
MODES = {"auto": "Claude decides; risky actions are blocked",
         "acceptEdits": "Edit files; other actions only if you've allowed them",
         "dontAsk": "Only what you've already allowed in Claude Code"}
MAX_TIMES = 10
DONE_MARK = "LFG: nothing left"
LOOP = ("This is pass %d of up to %d. If this pass found nothing new to change and changed nothing, end your reply "
        "with the line `%s`.")


def runs_dir():
    return C.ensure_dir(C.lfg_path("skillruns"))


def skills(rid=None):
    """What can run on a session: your skills, plugin and project skills, and Claude Code's own review commands."""
    from . import control as K
    out = [{"invoke": i["invoke"], "about": i.get("description") or "", "source": i["source"]}
           for i in K.skills_inventory(rid)["skills"] if i.get("user_invocable", True)]  # plugins on per repo count
    return out + [{"invoke": k, "about": v, "source": "Claude Code"} for k, v in BUILTIN]


def _transcript(sid):
    sid = SS._known(sid)
    return glob.glob(os.path.join(SS.PROJECTS, "*", sid + ".jsonl"))[0]


def _cwd(path):
    with open(path, "rb") as fh:
        for ln in fh:
            if b'"cwd"' not in ln:
                continue
            try:
                cwd = json.loads(ln).get("cwd")
            except ValueError:
                continue
            if cwd:
                return cwd
    return ""


def _job_path(jid):
    if not re.match(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$", str(jid or "")):
        raise RunError("not a run: %r" % jid)
    return os.path.join(runs_dir(), jid + ".json")


def job(jid):
    return C.read_json(_job_path(jid), None)


def start(sid, skill="", say="", times=1, until_clean=False, mode="auto", model="", fork=True):
    """Start a run detached (the Sessions page's Run button). skill: "/name" from skills(), or "" to send only `say`."""
    sid, path = SS._known(sid), _transcript(sid)
    skill, say = str(skill or "").strip(), str(say or "").strip()
    if skill and not re.match(r"^/[\w:.-]+$", skill):
        raise RunError("not a skill: %r" % skill)
    if not skill and not say:
        raise RunError("pick a skill or say what to do")
    if mode not in MODES:
        raise RunError("mode must be one of %s" % ", ".join(MODES))
    from . import review as R
    if model and model not in [m["id"] for m in R.models()]:
        raise RunError("unknown model %r" % model)
    times = max(1, min(MAX_TIMES, int(times or 1)))
    busy = [j for j in listing(sid) if j["status"] == "running" and _alive(j.get("pid"))]
    if busy:
        raise RunError("a run on this session is still going")
    jid = "%s-%s" % (C.now_iso()[:19].replace("-", "").replace(":", "").replace("T", "-"), os.urandom(3).hex())
    j = {"id": jid, "session": sid, "cwd": _cwd(path) or C.HOME, "skill": skill, "say": say[:4000], "times": times,
         "until_clean": bool(until_clean), "mode": mode, "model": model, "fork": bool(fork), "status": "starting",
         "started": C.now_iso(), "passes": [], "log": os.path.join(runs_dir(), jid + ".log")}
    C.write_json(_job_path(jid), j)
    args = [sys.executable, os.path.join(C.PLUGIN_ROOT, "bin", "lfg"), "sessions", "run", jid]
    with open(os.devnull, "wb") as dn:
        subprocess.Popen(args, stdout=dn, stderr=dn, stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    C.audit("skill_run", {"session": sid, "skill": skill or "(instruction)", "times": times, "mode": mode})
    return {"started": True, "id": jid}


def prompt(j, n):
    """What Claude is told on pass n (1-based)."""
    first = " ".join(x for x in (j["skill"], j["say"]) if x)
    text = first if n == 1 else "Run %s again on the same work, picking up where the last pass left off.%s" % (
        j["skill"] or "that", " " + j["say"] if j["say"] else "")
    if j["times"] > 1:
        more = LOOP % (n, j["times"], DONE_MARK) if j["until_clean"] else "(Pass %d of %d.)" % (n, j["times"])
        text += "\n\n" + more
    return text


def run(jid):
    """Do the run in this process (`lfg session run <id>`): one `claude -p` per pass, each resuming the last."""
    j = job(jid)
    if not j:
        raise RunError("no run %s" % jid)
    if not C.which("claude"):
        j.update(status="failed", why="Claude Code (`claude`) is not on PATH", ended=C.now_iso())
        C.write_json(_job_path(jid), j)
        return j
    j.update(status="running", pid=os.getpid())
    C.write_json(_job_path(jid), j)
    resume, fork = j["session"], j["fork"]
    env = dict(os.environ, PATH=os.path.join(C.PLUGIN_ROOT, "bin") + os.pathsep + os.environ.get("PATH", ""))
    for n in range(1, j["times"] + 1):
        log = j["log"][:-4] + ".pass%d.log" % n
        cmd = ["claude", "-p", prompt(j, n), "--resume", resume, "--permission-mode", j["mode"], "--output-format",
               "stream-json", "--verbose"] + (["--fork-session"] if fork else []) + (
            ["--model", j["model"]] if j["model"] else [])
        fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            cp = subprocess.run(cmd, cwd=j["cwd"] if os.path.isdir(j["cwd"]) else None, stdout=fh,
                                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env)
        from . import review as R
        sid, said = R.session_id(log) or resume, _result(log)
        clean = DONE_MARK.lower() in said.lower()
        j = job(jid)
        j["passes"].append({"n": n, "session": sid, "exit": cp.returncode, "said": said.replace(DONE_MARK, "").strip()
                            [-6000:], "log": log, "ended": C.now_iso(), "clean": clean})
        j["session_now"] = sid
        C.write_json(_job_path(jid), j)
        resume, fork = sid, False  # later passes continue the copy the first one made
        if cp.returncode != 0 or (j["until_clean"] and clean) or j.get("stop"):
            break
    last = j["passes"][-1] if j["passes"] else {}
    ok = last.get("exit") == 0
    j.update(status="done" if ok else "failed", ended=C.now_iso(),
             why="" if ok else (last.get("said") or "Claude stopped with an error; see the log")[-400:])
    C.write_json(_job_path(jid), j)
    from . import review as R
    R.notify("", "%s %s" % (j["skill"] or "Instruction", "done" if ok else "failed"),
             "%s on a session · %s" % (j["skill"] or "Instruction", "passes: %d" % len(j["passes"])), ok=ok,
             place="session:" + j["session"])
    return j


def _result(log):
    """Claude's final reply in a stream-json log."""
    text = ""
    for ln in C.read_text(log).splitlines():
        try:
            ev = json.loads(ln)
        except ValueError:
            continue
        if isinstance(ev, dict) and ev.get("type") == "result":
            text = str(ev.get("result") or ev.get("error") or "")
    return text


def _alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def stop(jid):
    """Stop after the pass that's running now."""
    j = job(jid)
    if not j:
        raise RunError("no run %s" % jid)
    j["stop"] = True
    C.write_json(_job_path(jid), j)
    return {"stopping": True}


def view(j):
    """A run as the page shows it: what it used, the command to resume the session it worked in."""
    if j["status"] in ("running", "starting") and j.get("pid") and not _alive(j["pid"]):
        j = dict(j, status="failed", why="the run stopped unexpectedly")
    last = j["passes"][-1] if j["passes"] else {}
    used = SS.used(last["log"]) if last.get("log") else None
    if used is not None and j["skill"] and not any("/" + x["name"] == j["skill"] for x in used["skills"]):
        used["skills"].insert(0, {"name": j["skill"].lstrip("/"), "count": 1, "plugin": ""})
    from . import review as R
    now = j["log"][:-4] + ".pass%d.log" % (len(j["passes"]) + 1)
    return dict(j, used=used, resume=SS.resume_command({"cwd": j["cwd"], "id": j.get("session_now") or j["session"]}),
                steps=R.activity(now) if j["status"] == "running" else [])


def listing(sid=None, limit=30):
    """Runs, newest first; only one session's when sid is given."""
    out = []
    for f in sorted(glob.glob(os.path.join(runs_dir(), "*.json")), reverse=True):
        j = C.read_json(f, None)
        if isinstance(j, dict) and (not sid or j.get("session") == sid):
            out.append(j)
        if len(out) >= limit:
            break
    return out
