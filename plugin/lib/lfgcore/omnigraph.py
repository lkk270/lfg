"""Omnigraph dev-graph + second-brain: local-only setup, servers and MCP bridge.

Each graph is an Omnigraph cookbook cluster under ~/.lfg/omnigraph/<name>/ (filesystem storage), served on
127.0.0.1 only by a per-user launchd agent. Bearer tokens are random, generated here, kept in
~/.lfg/omnigraph/tokens.json (mode 600) and never printed: the server and the MCP bridge read them at start,
so Claude Code's config holds only `lfg omnigraph mcp <name>`."""
import json
import os
import re
import secrets
import shutil
import sys
import time
import urllib.parse
import urllib.request

from . import common as C

ROLES = ("act-admin", "act-writer", "act-reader")
EXTRA_PATH = ["/opt/homebrew/bin", "/usr/local/bin", os.path.join(C.HOME, ".local", "bin")]
LABEL = "dev.lfg.omnigraph.%s"
LOCK_RX = re.compile(r"^Admission lock: ([A-Z0-9]+);", re.M)


def cfg():
    return C.config()["omnigraph"]


def root(*parts):
    return C.lfg_path("omnigraph", *parts)


def _which(name):
    path = os.environ.get("PATH", "") + os.pathsep + os.pathsep.join(EXTRA_PATH)
    return shutil.which(name, path=path)


def tokens():
    """Read or create the per-machine tokens. Never print the result."""
    p = root("tokens.json")
    t = C.read_json(p, None)
    if not (isinstance(t, dict) and all(t.get(r) for r in ROLES)):
        C.ensure_dir(root())
        t = {r: secrets.token_urlsafe(32) for r in ROLES}
        C.write_json(p, t, mode=0o600)
    return t


def _graph(name):
    g = cfg()["graphs"].get(name)
    if not g:
        C.die("unknown graph %r (known: %s)" % (name, ", ".join(cfg()["graphs"])), 2)
    return g


def url(name):
    return "http://127.0.0.1:%d" % _graph(name)["port"]


def version_ok():
    exe = _which("omnigraph")
    if not exe:
        return False, "omnigraph not installed (brew install ModernRelay/tap/omnigraph)"
    out = C.run([exe, "version"]).stdout.strip().splitlines()
    v = out[0] if out else "unknown"
    want = cfg()["version"]
    return ("omnigraph " + want) in v, v if ("omnigraph " + want) in v else "%s; LFG needs %sx" % (v, want)


def ready(name, timeout=2):
    try:
        with urllib.request.urlopen(url(name) + "/readyz", timeout=timeout) as r:
            return r.status == 200 and bool(json.loads(r.read()).get("ready"))
    except Exception:
        return False


def _cookbooks():
    """Pinned clone of the cookbooks (schemas, policies, stored queries; seeds are never loaded)."""
    src = root("src")
    ref = cfg()["cookbooks_ref"]
    if not os.path.isdir(os.path.join(src, ".git")):
        C.ensure_dir(root())
        cp = C.run(["git", "clone", "-q", cfg()["cookbooks_repo"], src], timeout=300)
        if cp.returncode:
            C.die("could not clone the Omnigraph cookbooks: %s" % cp.stderr.strip()[-300:])
    if C.run(["git", "-C", src, "rev-parse", "HEAD"]).stdout.strip() != ref:
        C.run(["git", "-C", src, "fetch", "-q", "origin", ref], timeout=300)
        cp = C.run(["git", "-C", src, "checkout", "-q", ref])
        if cp.returncode:
            C.die("could not check out cookbooks %s: %s" % (ref[:12], cp.stderr.strip()[-300:]))
    return src


def apply(name):
    """Create the graph once from the cookbook (no seed data). Returns a status string."""
    d = root(name)
    if os.path.isdir(os.path.join(d, "__cluster")):
        return "exists"
    if ready(name):
        return "exists"
    src = os.path.join(_cookbooks(), name)
    if not os.path.isdir(src):
        C.die("cookbook %s not found in %s" % (name, root("src")))
    if os.path.isdir(d):
        shutil.rmtree(d)
    shutil.copytree(src, d, ignore=shutil.ignore_patterns("seed.jsonl", "seed.md"))
    os.chmod(d, 0o700)
    exe = _which("omnigraph")
    cp = C.run([exe, "cluster", "apply", "--config", ".", "--as", "act-admin", "--json"], cwd=d, timeout=600)
    if cp.returncode:
        C.die("omnigraph cluster apply failed for %s:\n%s" % (name, (cp.stderr or cp.stdout).strip()[-800:]))
    m = LOCK_RX.search(cp.stderr or "")
    if m:  # the apply process has exited, so the lock it left is safe to clear (cookbook README procedure)
        un = C.run([exe, "cluster", "force-unlock", m.group(1), "--config", "."], cwd=d, timeout=120)
        if un.returncode:
            C.die("force-unlock failed for %s: %s" % (name, un.stderr.strip()[-300:]))
    return "created"


def _plist_path(name):
    return os.path.join(C.HOME, "Library", "LaunchAgents", (LABEL % name) + ".plist")


def _plist(name):
    lfg = C.lfg_bin()
    log = root(name, "server.log")
    args = "".join("<string>%s</string>" % x for x in (sys.executable, lfg, "omnigraph", "serve", name))
    return """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>%s</string>
  <key>ProgramArguments</key><array>%s</array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>%s</string>
  <key>StandardErrorPath</key><string>%s</string>
</dict></plist>
""" % (LABEL % name, args, log, log)


def install_agent(name):
    """Write and (re)load the launchd agent that keeps this graph's server running."""
    p = _plist_path(name)
    C.ensure_dir(os.path.dirname(p), 0o755)
    want = _plist(name)
    uid = str(os.getuid())
    if C.read_text(p) != want:
        C.run(["launchctl", "bootout", "gui/%s/%s" % (uid, LABEL % name)])
        C.write_text(p, want, mode=0o644)
        from . import claudecfg as CC
        CC.file_created(p, "%s graph server login agent" % name, "knowledge", tag="omnigraph-agent",
                        undo=["launchctl", "bootout", "gui/%s/%s" % (uid, LABEL % name)])
    if C.run(["launchctl", "print", "gui/%s/%s" % (uid, LABEL % name)]).returncode:
        cp = C.run(["launchctl", "bootstrap", "gui/" + uid, p])
        if cp.returncode:
            C.die("launchctl bootstrap failed for %s: %s" % (name, cp.stderr.strip()))


def wait_ready(name, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        if ready(name):
            return True
        time.sleep(1)
    return False


def mcp_registered(name):
    """The plugin declares the dev-graph and second-brain MCP servers itself (plugin/.mcp.json), so they exist only
    in repos where LFG is on. Nothing is registered machine-wide any more."""
    return os.path.isfile(os.path.join(C.PLUGIN_ROOT, ".mcp.json"))


def setup(launchd=True, mcp=False):
    ok, why = version_ok()
    if not ok:
        C.die(why, 2)
    tokens()
    out = {}
    for name in cfg()["graphs"]:
        r = {"graph": _graph(name)["graph"], "url": url(name), "dir": root(name), "apply": apply(name)}
        if launchd:
            install_agent(name)
            r["ready"] = wait_ready(name)
            if not r["ready"]:
                r["hint"] = "see %s" % root(name, "server.log")
        r["mcp"] = "provided by the LFG plugin"
        out[name] = r
    return out


def status():
    out = {"installed": version_ok()[1], "graphs": {}}
    uid = str(os.getuid())
    for name, g in cfg()["graphs"].items():
        out["graphs"][name] = {
            "graph": g["graph"], "url": url(name),
            "created": os.path.isdir(root(name, "__cluster")),
            "launchd": C.run(["launchctl", "print", "gui/%s/%s" % (uid, LABEL % name)]).returncode == 0,
            "ready": ready(name),
            "mcp": mcp_registered(name),
        }
    return out


def _exec(argv, env):
    os.execvpe(argv[0], argv, env)


def _alive(pid):
    try:
        os.kill(int(pid), 0)
    except (OSError, TypeError, ValueError):
        return False
    return True


def clear_stale_lock(name):
    """A server killed without a clean shutdown (crash, kill -9, power loss) leaves __cluster/lock.json behind, and
    omnigraph-server then refuses to start, so launchd retries until it gives up. The lock names the pid that took
    it: clear it (the documented force-unlock) only when that process is gone. Returns the cleared lock id or None."""
    try:
        lock = json.loads(C.read_text(root(name, "__cluster", "lock.json")) or "null")
    except ValueError:
        return None
    if not isinstance(lock, dict) or not lock.get("lock_id") or _alive(lock.get("pid")):
        return None
    exe = _which("omnigraph")
    if not exe:
        return None
    cp = C.run([exe, "cluster", "force-unlock", lock["lock_id"], "--config", "."], cwd=root(name), timeout=120)
    if cp.returncode:
        C.die("force-unlock failed for %s: %s" % (name, (cp.stderr or "").strip()[-300:]))
    sys.stderr.write("lfg: cleared stale lock %s left by pid %s\n" % (lock["lock_id"], lock.get("pid")))
    return lock["lock_id"]


def serve(name):
    """launchd entry point: run this graph's server on loopback with the per-machine tokens."""
    g = _graph(name)
    exe = _which("omnigraph-server")
    if not exe:
        C.die("omnigraph-server not found", 2)
    while ready(name):  # a server started some other way already answers: take over when it stops, don't crash-loop
        time.sleep(30)
    clear_stale_lock(name)
    env = dict(os.environ, OMNIGRAPH_SERVER_BEARER_TOKENS_JSON=json.dumps(tokens()))
    os.chdir(root(name))
    _exec([exe, "--cluster", ".", "--bind", "127.0.0.1:%d" % g["port"]], env)


def mcp(name):
    """Claude Code MCP entry point: the official stdio bridge, as the writer role, for this one graph."""
    g = _graph(name)
    npx = _which("npx")
    if not npx:
        C.die("npx not found (install node)", 2)
    env = dict(os.environ, OMNIGRAPH_BASE_URL=url(name), OMNIGRAPH_GRAPH_ID=g["graph"],
               OMNIGRAPH_TOKEN=tokens()["act-writer"])
    env["PATH"] = env.get("PATH", "") + os.pathsep + os.pathsep.join(EXTRA_PATH)
    _exec([npx, "-y", cfg()["mcp_package"]], env)


def _post(name, path, body, timeout=8, role="act-reader"):
    """POST to this graph's server, as the *reader* role unless told otherwise (the dashboard never writes)."""
    g = _graph(name)
    req = urllib.request.Request(
        "%s/graphs/%s%s" % (url(name), g["graph"], path), data=json.dumps(body).encode(), method="POST",
        headers={"Authorization": "Bearer " + tokens()[role], "Content-Type": "application/json",
                 "Accept": "application/json",
                 # the server rejects requests without its API contract version (major.minor of the pin)
                 "omnigraph-http-api": cfg()["version"].rstrip(".")})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def _rows(res):
    """Normalise a read result to a list of dicts keyed by bare field name (`$i.slug` → `slug`)."""
    rows, cols = res.get("rows") or [], res.get("columns") or []
    names = [(c.get("name") if isinstance(c, dict) else str(c)) for c in cols]
    out = []
    for r in rows:
        d = r if isinstance(r, dict) else dict(zip(names, r))
        row = {}
        for k, v in d.items():  # the first variable is the subject (`i.slug` before a blocker's `b.slug`): keep it
            row.setdefault(k.rsplit(".", 1)[-1].lstrip("$"), v)
        out.append(row)
    return out


def read(name, query, qname, params=None):
    """Ad-hoc read query (GQ text) on graph `name` (read-only route)."""
    return _rows(_post(name, "/query", {"query": query, "name": qname, "params": params or {}}))


def invoke(name, stored, params=None):
    """Invoke a stored (read) query registered from the cookbook's queries/*.gq."""
    return _rows(_post(name, "/queries/%s" % urllib.parse.quote(stored), {"params": params or {}}))


def mutate(name, query, qname, params=None):
    """GQ mutation on `main` as the writer role. Only the lfg CLI calls this (run bookkeeping), never the UI."""
    return _post(name, "/mutate", {"query": query, "name": qname, "params": params or {}}, role="act-writer")


def restart(name):
    uid = str(os.getuid())
    install_agent(name)  # reloads an agent launchd gave up on, so restart works after a crash loop
    return C.run(["launchctl", "kickstart", "-k", "gui/%s/%s" % (uid, LABEL % name)]).returncode == 0
