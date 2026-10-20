"""Graph preflight: build graphify + code-review-graph on first use in a repo and
keep them in sync with the *working tree* (committed or not) before every skill.

Graph data lives in the repo's main checkout, in `.code-review-graph/` and `graphify-out/`: git-ignored (global
gitignore plus a `*` .gitignore inside each), shared by every branch and by linked worktrees, and found by the
tools' own defaults. Only bookkeeping (state.json, the lock, sync.log, docs.json) stays in ~/.lfg/graphs/<repo-id>/.
No git hooks are installed. Author: Varun Singh.
"""
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

from . import common as C

TOOL_ENV = {"GRAPHIFY_NO_AUTO_REFRESH": "1", "GRAPHIFY_NO_TIPS": "1"}
DATA = {"crg": ".code-review-graph", "graphify": "graphify-out"}  # tool defaults, in the global gitignore


def gdir(rid):
    """Bookkeeping only (state, lock, log); the graphs themselves are in the repo (see data_dir)."""
    return C.ensure_dir(C.lfg_path("graphs", rid))


def data_dir(rid, kind, root=None):
    """`<main checkout>/.code-review-graph` or `/graphify-out`; None before the repo's first sync."""
    base = C.main_root(root) if root else (C.read_json(C.lfg_path("graphs", rid, "state.json"), {}) or {}).get(
        "repo_root")
    return os.path.join(base, DATA[kind]) if base else None


def _prepare(root, rid):
    """Create the in-repo data dirs with a `*` .gitignore (so they never show in git status, even without the
    global gitignore) and move graphs from the old ~/.lfg/graphs/<rid>/{crg,graphify} layout once. The old paths
    stay as symlinks to the new dirs, so instructions that still name them keep working."""
    for kind, old in (("crg", "crg"), ("graphify", "graphify")):
        d = data_dir(rid, kind, root)
        legacy = C.lfg_path("graphs", rid, old)
        if os.path.isdir(legacy) and not os.path.islink(legacy) and not os.path.exists(d):
            shutil.move(legacy, d)
        C.ensure_dir(d, 0o755)
        gi = os.path.join(d, ".gitignore")
        if not os.path.exists(gi):
            with open(gi, "w") as f:
                f.write("*\n")
        if os.path.islink(legacy) and os.readlink(legacy) != d:
            os.remove(legacy)
        if not os.path.lexists(legacy):
            gdir(rid)
            os.symlink(d, legacy)


def state_path(rid):
    return os.path.join(gdir(rid), "state.json")


def load_state(rid):
    return C.read_json(state_path(rid), {}) or {}


def save_state(rid, st):
    C.write_json(state_path(rid), st)


# ---------------------------------------------------------------- fingerprint

def _git(root, *args):
    return C.run(["git"] + list(args), cwd=root)


def snapshot(root):
    """Fingerprint of the code as it is right now: HEAD + every dirty/untracked (non-ignored) file's stat."""
    head = _git(root, "rev-parse", "HEAD").stdout.strip() or "none"
    st = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    entries = [e for e in st.stdout.split("\0") if e]
    files, i = {}, 0
    while i < len(entries):
        e = entries[i]
        code, path = e[:2], e[3:]
        if code[0] in "RC":  # rename/copy: next entry is the source path
            i += 1
            if i < len(entries):
                files[entries[i]] = None
        if path == ".lfg/" or path.startswith(".lfg/"):  # LFG's own knowledge files, not code: never a reason to sync
            i += 1
            continue
        try:
            s = os.stat(os.path.join(root, path))
            files[path] = [s.st_mtime_ns, s.st_size]
        except OSError:
            files[path] = None  # deleted
        i += 1
    h = hashlib.sha1()
    h.update(head.encode())
    h.update(json.dumps(files, sort_keys=True).encode())
    return {"head": head, "files": files, "fingerprint": h.hexdigest()}


def changed_files(root, old, new):
    changed = set(new["files"]) | set(old.get("files") or {})
    changed = {p for p in changed if (old.get("files") or {}).get(p) != new["files"].get(p)}
    if old.get("head") and old.get("head") != new["head"] and new["head"] != "none":
        if _git(root, "cat-file", "-e", old["head"] + "^{commit}").returncode != 0:
            return None  # history rewritten / unknown base: full rebuild
        diff = _git(root, "diff", "--name-only", old["head"], new["head"])
        if diff.returncode != 0:
            return None
        changed |= {p for p in diff.stdout.splitlines() if p}
    return sorted(changed)


def tracked_count(root):
    out = _git(root, "ls-files", "-z").stdout
    return max(1, out.count("\0"))


# ---------------------------------------------------------------- tool runners

def present(rid, root=None):
    """False when a graph LFG should have built is gone (e.g. someone deleted graphify-out/)."""
    need = [("crg", "graph.db", "code-review-graph"), ("graphify", "graph.json", "graphify")]
    for kind, f, tool in need:
        d = data_dir(rid, kind, root)
        if C.which(tool) and not (d and os.path.isfile(os.path.join(d, f))):
            return False
    return True


def _tool_env(rid, root):
    env = dict(TOOL_ENV)
    env["GRAPHIFY_OUT"] = data_dir(rid, "graphify", root)
    env["CRG_DATA_DIR"] = data_dir(rid, "crg", root)
    return env


def _log(rid, text):
    path = os.path.join(gdir(rid), "sync.log")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a") as f:
        f.write("[%s] %s\n" % (C.now_iso(), text))


def _run_tool(rid, cmd, root, timeout, cwd=None):
    t0 = time.time()
    cp = C.run(cmd, cwd=cwd or root, timeout=timeout, env=_tool_env(rid, root))
    _log(rid, "%s -> %d in %.1fs %s" % (" ".join(cmd), cp.returncode, time.time() - t0,
                                       (cp.stderr or "").strip().splitlines()[-1:] if cp.returncode else ""))
    return cp


def build_full(root, rid, timeout):
    errors = []
    crg = C.which("code-review-graph")
    if crg:
        cp = _run_tool(rid, [crg, "build", "--repo", root, "--data-dir", data_dir(rid, "crg", root), "-q"],
                       root, timeout)
        if cp.returncode:
            errors.append("code-review-graph build failed: %s" % (cp.stderr or cp.stdout)[-400:].strip())
    else:
        errors.append("code-review-graph is not installed")
    gfy = C.which("graphify")
    if gfy:
        cp = _run_tool(rid, [gfy, "update", root, "--force"], root, timeout)
        if cp.returncode:
            errors.append("graphify update failed: %s" % (cp.stderr or cp.stdout)[-400:].strip())
    else:
        errors.append("graphify is not installed")
    return errors


def build_incremental(root, rid, files, timeout):
    errors = []
    crg = C.which("code-review-graph")
    if crg:
        cp = _run_tool(rid, [crg, "update", "--repo", root, "--data-dir", data_dir(rid, "crg", root), "-q"],
                       root, timeout)
        if cp.returncode:
            errors.append("code-review-graph update failed: %s" % (cp.stderr or cp.stdout)[-400:].strip())
    else:
        errors.append("code-review-graph is not installed")
    gfy = C.which("graphify")
    code_ext = (".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt", ".rb", ".php", ".cs", ".c",
                ".h", ".cpp", ".hpp", ".swift", ".scala", ".lua", ".sh", ".mjs", ".cjs", ".vue", ".svelte", ".zig",
                ".ex", ".exs", ".dart", ".m", ".sql")
    if gfy and any(f.endswith(code_ext) for f in files):
        cp = _run_tool(rid, [gfy, "update", root, "--force"], root, timeout)
        if cp.returncode:
            errors.append("graphify update failed: %s" % (cp.stderr or cp.stdout)[-400:].strip())
    elif not gfy:
        errors.append("graphify is not installed")
    return errors


# ---------------------------------------------------------------- lock

class Lock(object):
    def __init__(self, rid, name=".lock"):
        self.path = os.path.join(gdir(rid), name)
        self.fd = None

    def acquire(self, blocking=True, timeout=None):
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        deadline = None if timeout is None else time.time() + timeout
        while True:
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except OSError:
                if not blocking or (deadline and time.time() > deadline):
                    os.close(self.fd)
                    self.fd = None
                    return False
                time.sleep(0.25)

    def release(self):
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None


# ---------------------------------------------------------------- public API

def status(root, rid):
    root = C.main_root(root)
    st = load_state(rid)
    if not st.get("fingerprint") or not present(rid, root):
        lock = Lock(rid)
        busy = not lock.acquire(blocking=False)
        lock.release()
        return {"status": "syncing" if busy else "missing", "repo_id": rid, "graphs_dir": root}
    now = snapshot(root)
    lock = Lock(rid)
    busy = not lock.acquire(blocking=False)
    lock.release()
    s = "fresh" if now["fingerprint"] == st["fingerprint"] else ("syncing" if busy else "stale")
    if st.get("last_error") and s != "fresh":
        s = "stale"
    return {"status": s, "repo_id": rid, "graphs_dir": root, "synced_at": st.get("synced_at"),
            "last_sync_s": st.get("last_sync_s"), "mode": st.get("mode"), "last_error": st.get("last_error")}


def ensure(root, rid, allow_stale=False, wait_timeout=None, force_full=False):
    """Make the graphs fresh. Returns dict(status, ...). status ∈ fresh | stale | error."""
    cfg = C.config()["graphs"]
    timeout = cfg.get("sync_timeout_s", 900)
    root = C.main_root(root)  # one graph per repo, built from the main checkout, used from every worktree
    lock = Lock(rid)
    if not lock.acquire(blocking=True, timeout=wait_timeout):
        return {"status": "syncing", "message": "another sync is running; try again shortly", "repo_id": rid}
    try:
        _prepare(root, rid)
        for _attempt in range(3):  # re-check: files may change while we sync
            old = load_state(rid)
            now = snapshot(root)
            rebuild = force_full or not present(rid, root)
            if old.get("fingerprint") == now["fingerprint"] and not rebuild and not old.get("last_error"):
                return {"status": "fresh", "repo_id": rid, "mode": "unchanged", "graphs_dir": root}
            t0 = time.time()
            files = None if (rebuild or not old.get("fingerprint")) else changed_files(root, old, now)
            full = files is None or len(files) > cfg.get("full_rebuild_ratio", 0.3) * tracked_count(root)
            if full:
                errors = build_full(root, rid, timeout)
                mode = "full"
            else:
                errors = build_incremental(root, rid, files, timeout) if files else []
                mode = "incremental"
                if errors:  # retry once as a full rebuild
                    _log(rid, "incremental failed, retrying full rebuild")
                    errors = build_full(root, rid, timeout)
                    mode = "full-retry"
            st = {"fingerprint": now["fingerprint"], "head": now["head"], "files": now["files"],
                  "synced_at": C.now_iso(), "last_sync_s": round(time.time() - t0, 2), "mode": mode,
                  "changed": (files or [])[:200] if not full else "all", "repo_root": root,
                  "last_error": "; ".join(errors) if errors else None}
            if errors:
                st["fingerprint"] = old.get("fingerprint")  # stay stale so the next skill retries
                save_state(rid, st)
                C.audit("graphs.error", {"repo_id": rid, "errors": errors})
                return {"status": "stale" if allow_stale else "error", "repo_id": rid, "errors": errors,
                        "log": os.path.join(gdir(rid), "sync.log"), "allow_stale": allow_stale}
            save_state(rid, st)
            if snapshot(root)["fingerprint"] == now["fingerprint"]:
                return {"status": "fresh", "repo_id": rid, "mode": mode, "seconds": st["last_sync_s"],
                        "changed": len(files) if files is not None else "all", "graphs_dir": root}
        return {"status": "fresh", "repo_id": rid, "mode": "settled", "graphs_dir": root}
    finally:
        lock.release()


def spawn_background(root, rebuild=False):
    """Start `lfg graphs ensure` detached (used by SessionStart and PostToolUse hooks, and the dashboard)."""
    lfg = C.lfg_bin()
    if not os.path.exists(lfg):
        lfg = os.path.abspath(sys.argv[0])
    with open(os.devnull, "wb") as dn:
        subprocess.Popen([sys.executable, lfg, "graphs", "ensure", "--quiet"] + (["--rebuild"] if rebuild else []),
                         cwd=root, stdout=dn, stderr=dn,
                         stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True)
