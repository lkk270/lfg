"""`lfg lane`, `lfg gate`, `lfg ci-local`: verdicts come from exit codes, never from claims.

Author: Varun Singh.
"""
import json
import os
import re
import shlex
import time

from . import common as C
from . import graphs as G
from . import guard
from .hooks import SECRET_OUTPUT_RX

# ---------------------------------------------------------------- diff helpers


def _git(root, *args):
    return C.run(["git"] + list(args), cwd=root)


def changed_files(root):
    """Uncommitted changes (staged, unstaged, untracked, not ignored), minus secret files."""
    out = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout
    files, entries, i = [], [e for e in out.split("\0") if e], 0
    while i < len(entries):
        code, path = entries[i][:2], entries[i][3:]
        if code[0] in "RC":
            i += 1
        if not guard.is_secret_path(path):
            files.append(path)
        i += 1
    return files


def diff_text(root, files=None):
    """Unified diff of the working tree vs HEAD, untracked files included, secret files excluded."""
    files = files if files is not None else changed_files(root)
    if not files:
        return ""
    has_head = _git(root, "rev-parse", "--verify", "-q", "HEAD").returncode == 0
    tracked = set(_git(root, "ls-files", "-z", "--", *files).stdout.split("\0")) - {""}
    parts = []
    if tracked:
        args = ["diff", "--no-color", "--no-ext-diff"] + (["HEAD"] if has_head else ["--cached"]) + ["--"]
        parts.append(_git(root, *(args + sorted(tracked))).stdout)
    for f in files:
        if f not in tracked and os.path.isfile(os.path.join(root, f)):
            parts.append(_git(root, "diff", "--no-color", "--no-index", "--", "/dev/null", f).stdout)
    return "".join(parts)


def added_lines(diff):
    cur, out = None, []
    for line in diff.splitlines():
        if line.startswith("+++ "):
            cur = line[6:] if line.startswith("+++ b/") else line[4:]
        elif line.startswith("+") and not line.startswith("+++"):
            out.append((cur, line[1:]))
    return out


# ---------------------------------------------------------------- lane

SENSITIVE = re.compile(r"(^|/)(auth|security|crypto|payment|billing|migrations?|infra|terraform|k8s|helm)(/|$)|"
                       r"(^|/)(Dockerfile|docker-compose[^/]*|\.github/workflows/[^/]+|package(-lock)?\.json|"
                       r"pnpm-lock\.yaml|yarn\.lock|requirements[^/]*\.txt|pyproject\.toml|poetry\.lock|uv\.lock|"
                       r"go\.(mod|sum)|Cargo\.(toml|lock)|Gemfile(\.lock)?)$", re.I)


def lane(root, rid):
    cfg = C.config()["lanes"]
    files = changed_files(root)
    lines = sum(1 for _ in added_lines(diff_text(root, files)))
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    sensitive = [f for f in files if SENSITIVE.search(f)]
    impact = None
    if C.which("code-review-graph") and files:
        cp = C.run(["code-review-graph", "impact", "--repo", C.main_root(root), "--max-results", "1", "--files"]
                   + files[:200],
                   cwd=root, timeout=120, env={"CRG_DATA_DIR": G.data_dir(rid, "crg", root) or ""})
        try:
            d = json.loads(cp.stdout or "{}")
            impact = None
            if d.get("status") == "ok":
                impact = (len(d.get("changed_nodes") or []) + (d.get("changed_nodes_omitted") or 0)
                          + (d.get("total_impacted") or 0))
        except ValueError:
            impact = None
    reasons = []
    if branch.startswith(("hotfix/", "hotfix-")):
        name = "hotfix"
        reasons.append("branch %s is a hotfix branch" % branch)
    elif sensitive or (impact is not None and impact > cfg["full_impact_nodes"]):
        name = "full"
        if sensitive:
            reasons.append("touches sensitive paths: %s" % ", ".join(sensitive[:8]))
        if impact is not None and impact > cfg["full_impact_nodes"]:
            reasons.append("impact radius %d nodes > %d" % (impact, cfg["full_impact_nodes"]))
    elif len(files) <= cfg["express_max_files"] and lines <= cfg["express_max_lines"]:
        name = "express"
        reasons.append("%d files, %d added lines (express limit %d/%d)" % (
            len(files), lines, cfg["express_max_files"], cfg["express_max_lines"]))
    else:
        name = "standard"
        reasons.append("%d files, %d added lines" % (len(files), lines))
    return {"lane": name, "reasons": reasons, "files": len(files), "added_lines": lines, "impact_nodes": impact,
            "note": "Lanes can only be raised by agents, never lowered. With no diff yet, plan from the brief."}


# ---------------------------------------------------------------- commands.json

def _pm(root):
    for lock, pm in (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"), ("bun.lockb", "bun"), ("bun.lock", "bun")):
        if os.path.exists(os.path.join(root, lock)):
            return pm
    return "npm"


def detect_commands(root):
    cmds = {}
    pj = C.read_json(os.path.join(root, "package.json"), None)
    if isinstance(pj, dict):
        scripts, pm = pj.get("scripts") or {}, _pm(root)
        for key, names in (("lint", ["lint"]), ("lint_fix", ["lint:fix", "lint-fix", "fix"]),
                           ("types", ["typecheck", "type-check", "types", "tsc"]), ("test", ["test"]),
                           ("build", ["build"]), ("start", ["start"])):
            for n in names:
                if n in scripts:
                    cmds[key] = "%s run %s" % (pm, n)
                    break
        if "types" not in cmds and os.path.exists(os.path.join(root, "tsconfig.json")):
            cmds["types"] = "npx --no-install tsc --noEmit"
    elif os.path.exists(os.path.join(root, "pyproject.toml")) or os.path.exists(os.path.join(root, "setup.py")):
        py = C.read_text(os.path.join(root, "pyproject.toml"))
        if "ruff" in py or C.which("ruff"):
            cmds["lint"], cmds["lint_fix"] = "ruff check .", "ruff check --fix ."
        if "mypy" in py:
            cmds["types"] = "mypy ."
        if "pytest" in py or os.path.isdir(os.path.join(root, "tests")):
            cmds["test"], cmds["test_affected"] = "python3 -m pytest -q", "python3 -m pytest -q {files}"
    elif os.path.exists(os.path.join(root, "go.mod")):
        cmds.update(lint="go vet ./...", test="go test ./...", build="go build ./...")
    elif os.path.exists(os.path.join(root, "Cargo.toml")):
        cmds.update(lint="cargo clippy -- -D warnings", lint_fix="cargo clippy --fix --allow-dirty",
                    test="cargo test", build="cargo build")
    mk = os.path.join(root, "Makefile")
    if os.path.exists(mk):
        targets = set(re.findall(r"^([A-Za-z0-9_-]+):", C.read_text(mk), re.M))
        for key in ("lint", "test", "build"):
            if key not in cmds and key in targets:
                cmds[key] = "make %s" % key
    return cmds


def commands(root, rid):
    path = C.repo_file(root, "commands.json")
    saved = C.read_json(path, None)
    if isinstance(saved, dict) and saved:
        return saved, path, False
    cmds = detect_commands(root)
    if cmds:
        C.write_json(C.repo_file(root, "commands.json", create=True), cmds)
    return cmds, path, True


# ---------------------------------------------------------------- gate

SUPPRESSION = re.compile(
    r"eslint-disable|@ts-ignore|@ts-expect-error|@ts-nocheck|#\s*noqa|#\s*type:\s*ignore|pylint:\s*disable|"
    r"#\s*nosec|//\s*nolint|#\[allow\(|@SuppressWarnings|istanbul ignore|c8 ignore|"
    r"\b(it|test|describe)\.skip\(|\bxit\(|\bxdescribe\(|@pytest\.mark\.skip|@unittest\.skip|t\.Skip\(")


def _run_check(root, name, cmd, logdir, timeout=1800):
    argv = cmd if isinstance(cmd, list) else shlex.split(cmd)
    blocked = guard.check("Bash", {"command": " ".join(shlex.quote(a) for a in argv)})
    if blocked:
        return {"name": name, "cmd": cmd, "exit": 2, "seconds": 0, "tail": "blocked by LFG rule %s" % blocked[0]}
    t0 = time.time()
    cp = C.run(argv, cwd=root, timeout=timeout, env={"CI": "1", "FORCE_COLOR": "0"})
    out = (cp.stdout or "") + (cp.stderr or "")
    if logdir:
        C.write_text(os.path.join(logdir, "%s.log" % name), out)
    tail = "\n".join(out.strip().splitlines()[-25:])
    for _k, rx in SECRET_OUTPUT_RX:
        tail = rx.sub("[REDACTED]", tail)
    res = {"name": name, "cmd": cmd, "exit": cp.returncode, "seconds": round(time.time() - t0, 1), "tail": tail}
    missing = missing_tools(out) if cp.returncode else []
    if missing:
        res.update(cant_run=missing, hint="%s isn't installed on this machine, so this check can't run here (CI "
                   "has it): install it (%s) and run the checks again" % (
                       ", ".join(missing), "; ".join(install_hint(t) for t in missing)))
    return res


MISSING_TOOL = [re.compile(p, re.M) for p in (
    r"spawn ([\w.+-]+) ENOENT", r'"code":"ENOENT","syscall":"spawn ([\w.+-]+)"',
    r"^(?:\S+: )?([\w.+-]+): command not found", r"command not found: ([\w.+-]+)",
    r"No such file or directory: '([\w.+-]+)'")]


def missing_tools(out):
    """Programs a failed check's output says it couldn't start, that really aren't installed here."""
    found = []
    for rx in MISSING_TOOL:
        for m in rx.finditer(out):
            t = m.group(1)
            if t not in found and "/" not in t and not C.which(t):
                found.append(t)
    return found


def install_hint(tool):
    return ("brew install %s" % tool) if C.which("brew") or os.uname().sysname == "Darwin" else \
        ("your package manager, e.g. apt-get install %s" % tool)


def gate_state(checks):
    """green (everything that ran passed), red (a check failed), cant_run (the only failures are tools missing on
    this machine: not proven here, not failing either) or none (nothing ran)."""
    ran = [c for c in checks if c.get("exit") is not None and c.get("name") != "lint_fix"]
    if not ran:
        return "none"
    bad = [c for c in ran if c["exit"] != 0]
    if not bad:
        return "green"
    return "cant_run" if all(c.get("cant_run") for c in bad) else "red"


def secret_scan(root, diff):
    res = {"name": "secrets", "cmd": "gitleaks stdin (diff only) + LFG patterns", "seconds": 0}
    t0 = time.time()
    hits = sorted({"%s: %s" % (f, k) for f, line in added_lines(diff) for k, rx in SECRET_OUTPUT_RX
                   if rx.search(line)})
    gl = C.which("gitleaks")
    if gl and diff:
        import subprocess
        p = subprocess.run([gl, "stdin", "--no-banner", "--redact", "--exit-code", "3", "--report-format", "json",
                            "--report-path", "-"], input=diff, text=True, cwd=root,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode == 3:
            try:
                for f in json.loads(p.stdout or "[]"):
                    hits.append("gitleaks: %s" % f.get("RuleID", "secret"))
            except ValueError:
                hits.append("gitleaks: finding (unparsed report)")
        elif p.returncode not in (0,):
            hits.append("gitleaks failed to run (exit %d)" % p.returncode)
    elif not gl:
        res["note"] = "gitleaks not installed; LFG patterns only (run bootstrap)"
    res.update(exit=1 if hits else 0, seconds=round(time.time() - t0, 1), tail="\n".join(hits[:30]))
    return res


def suppression_scan(diff):
    hits = ["%s: %s" % (f, line.strip()[:160]) for f, line in added_lines(diff) if SUPPRESSION.search(line)]
    return {"name": "suppressions", "cmd": "new lint/type/test suppressions in the diff", "seconds": 0,
            "exit": 1 if hits else 0, "tail": "\n".join(hits[:30])}


def gate(root, rid, fix=False, affected=False, only=None):
    cmds, path, detected = commands(root, rid)
    run = C.current_run(root)
    logdir = os.path.join(run, "gate-logs") if run else None
    checks = []
    if fix and cmds.get("lint_fix"):
        checks.append(_run_check(root, "lint_fix", cmds["lint_fix"], logdir))
    files = changed_files(root)
    for key in ("lint", "types", "test", "build"):
        if only and key not in only:
            continue
        cmd = cmds.get(key)
        if key == "test" and affected and cmds.get("test_affected") and files:
            cmd = cmds["test_affected"].replace("{files}", " ".join(shlex.quote(f) for f in files))
        if cmd:
            checks.append(_run_check(root, key, cmd, logdir))
        else:
            checks.append({"name": key, "cmd": None, "exit": None, "seconds": 0,
                           "tail": "no command configured (edit %s)" % path})
    diff = diff_text(root, files)
    if not only:
        checks.append(secret_scan(root, diff))
        checks.append(suppression_scan(diff))
    ran = [c for c in checks if c["exit"] is not None and c["name"] != "lint_fix"]
    green = bool(ran) and all(c["exit"] == 0 for c in ran)
    result = {"ts": C.now_iso(), "green": green, "state": gate_state(checks), "head": C.git_head(root),
              "commands_file": path, "commands_detected": detected,
              "checks": checks, "logs": logdir, "missing": [c["name"] for c in checks if c["exit"] is None]}
    if run and not only:
        C.write_json(os.path.join(run, "ready.json"), result)
    return result


# ---------------------------------------------------------------- ci-local

CI_KEYWORDS = re.compile(r"\b(lint|eslint|ruff|flake8|pylint|clippy|vet|fmt|format|prettier|black|"
                         r"mypy|tsc|typecheck|type-check|pyright|test|pytest|jest|vitest|mocha|go test|"
                         r"cargo test|build|compile)\b", re.I)


def workflow_steps(root):
    wdir = os.path.join(root, ".github", "workflows")
    steps = []
    if not os.path.isdir(wdir):
        return steps
    for fn in sorted(os.listdir(wdir)):
        if not fn.endswith((".yml", ".yaml")):
            continue
        lines = C.read_text(os.path.join(wdir, fn)).splitlines()
        name, i = None, 0
        while i < len(lines):
            line = lines[i]
            m_name = re.match(r"^\s*-?\s*name:\s*(.+)$", line)
            if m_name:
                name = m_name.group(1).strip().strip("'\"")
            m = re.match(r"^(\s*)-?\s*run:\s*(.*)$", line)
            if m:
                indent, val = len(m.group(1)), m.group(2).strip()
                if val in ("|", "|-", ">", ">-", "|+"):
                    body, i = [], i + 1
                    while i < len(lines) and (not lines[i].strip() or len(lines[i]) - len(lines[i].lstrip()) > indent):
                        body.append(lines[i].strip())
                        i += 1
                    val = "\n".join(b for b in body if b)
                    i -= 1
                steps.append({"workflow": fn, "name": name or val.splitlines()[0][:60] if val else name,
                              "run": val.strip("'\"")})
                name = None
            i += 1
    return steps


PR_TRIGGERS = ("push", "pull_request", "pull_request_target")


def workflow_filters(text):
    """What a workflow's `on:` says about changed files: None when a push or pull request runs it whatever changed,
    [] when neither does (manual or scheduled only), else [(paths, paths_ignore)] for each trigger that filters."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if re.match(r"^['\"]?on['\"]?\s*:", ln)), None)
    if start is None:
        return []
    inline = lines[start].split(":", 1)[1].split("#")[0].strip()
    if inline:  # `on: push` or `on: [push, pull_request]`
        return None if any(t in re.findall(r"[\w-]+", inline) for t in PR_TRIGGERS) else []
    triggers, cur, key, ind = {}, None, None, None
    for ln in lines[start + 1:]:
        if ln.strip() and not ln.startswith((" ", "\t", "#")):
            break  # the next top-level key
        body = ln.split(" #")[0].rstrip()
        if not body.strip() or body.strip().startswith("#"):
            continue
        depth = len(body) - len(body.lstrip())
        ind = depth if ind is None else ind
        if depth == ind:
            cur, key = body.strip().rstrip(":").strip(), None
            triggers[cur] = {"paths": [], "paths-ignore": []}
            continue
        m = re.match(r"^\s*(paths|paths-ignore)\s*:\s*(.*)$", body)
        if m and cur:
            key = m.group(1)
            if m.group(2).startswith("["):
                triggers[cur][key] += [x.strip().strip("'\"") for x in m.group(2).strip("[]").split(",") if x.strip()]
            continue
        item = re.match(r"^\s*-\s*(.+)$", body)
        if item and cur and key:
            triggers[cur][key].append(item.group(1).strip().strip("'\""))
        elif re.match(r"^\s*[\w-]+\s*:", body):
            key = None
    filters = []
    for t in PR_TRIGGERS:
        if t in triggers:
            f = triggers[t]
            if not f["paths"] and not f["paths-ignore"]:
                return None
            filters.append((f["paths"], f["paths-ignore"]))
    return filters


def _glob_rx(pattern):
    """A GitHub Actions path filter as a regex: `**` any depth, `*` and `?` within one folder."""
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pattern[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile("^" + out + "$")


def workflow_touched(filters, files):
    """Would a change to `files` start a workflow with these filters (see workflow_filters)?"""
    if filters is None:
        return True
    for paths, ignore in filters:
        for f in files:
            neg = [p[1:] for p in paths if p.startswith("!")]
            pos = [p for p in paths if not p.startswith("!")]
            if pos and not any(_glob_rx(p).match(f) for p in pos) or any(_glob_rx(p).match(f) for p in neg):
                continue
            if not any(_glob_rx(p).match(f) for p in ignore):
                return True
    return False


def branch_files(root):
    """Files this branch changes: committed since it left the default branch, plus uncommitted ones."""
    base = ""
    for ref in ("origin/HEAD", "origin/main", "origin/master", "main", "master"):
        cp = _git(root, "merge-base", "HEAD", ref)
        if cp.returncode == 0 and cp.stdout.strip():
            base = cp.stdout.strip()
            break
    committed = _git(root, "diff", "--name-only", base, "HEAD").stdout.split("\n") if base else []
    return sorted({f for f in committed if f} | set(changed_files(root)))


def _timed(cmd, root, on_tick, every=60):
    """C.run, calling on_tick(seconds so far) every `every` seconds while it runs."""
    import threading
    done = threading.Event()
    t0 = time.time()

    def tick():
        while not done.wait(every):
            on_tick(round(time.time() - t0))
    if on_tick:
        threading.Thread(target=tick, daemon=True).start()
    try:
        return C.run(cmd, cwd=root, timeout=1800, env={"CI": "1"})
    finally:
        done.set()


def ci_local(root, list_only=False, affected=False, files=None, progress=None):
    """Replay the workflows' lint/type/test/build steps. affected: only workflows whose path filters match the
    branch's changed files (`files`, default branch_files). progress(event, n, total, step, extra): "start" and "done"
    for each step that runs (extra: its result), "tick" each minute it is still running (extra: seconds so far)."""
    out = {"workflows_lint": [], "steps": []}
    if affected:
        files = branch_files(root) if files is None else files
        out["changed_files"] = len(files)
    wdir = os.path.join(root, ".github", "workflows")
    if os.path.isdir(wdir):
        for tool, argv in (("actionlint", ["actionlint"]), ("zizmor", ["zizmor", "--offline", wdir])):
            if C.which(tool):
                cp = C.run(argv, cwd=root, timeout=300)
                out["workflows_lint"].append({"tool": tool, "exit": cp.returncode,
                                              "tail": "\n".join(((cp.stdout or "") + (cp.stderr or "")).strip()
                                                                .splitlines()[-25:])})
            else:
                out["workflows_lint"].append({"tool": tool, "exit": None, "tail": "not installed"})
    touched = {}
    todo = []
    for st in workflow_steps(root):
        run = st["run"]
        why = None
        if affected and st["workflow"] not in touched:
            touched[st["workflow"]] = workflow_touched(
                workflow_filters(C.read_text(os.path.join(wdir, st["workflow"]))), files)
        if affected and not touched[st["workflow"]]:
            why = "no changed file matches its paths (--affected)"
        elif "${{" in run:
            why = "uses GitHub expressions/secrets"
        elif not CI_KEYWORDS.search((st["name"] or "") + " " + run):
            why = "not a lint/type/test/build step"
        else:
            blocked = guard.check("Bash", {"command": run})
            if blocked:
                why = "blocked by LFG rule %s" % blocked[0]
        entry = dict(st, skipped=why)
        if not why and not list_only:
            todo.append(entry)
        out["steps"].append(entry)
    for n, entry in enumerate(todo, 1):
        if progress:
            progress("start", n, len(todo), entry)
        t0 = time.time()
        cp = _timed(["bash", "-eo", "pipefail", "-c", entry["run"]], root,
                    progress and (lambda s, n=n, e=entry: progress("tick", n, len(todo), e, s)))
        entry.update(exit=cp.returncode, seconds=round(time.time() - t0, 1),
                     tail="\n".join(((cp.stdout or "") + (cp.stderr or "")).strip().splitlines()[-20:]))
        if progress:
            progress("done", n, len(todo), entry, entry)
    ran = [s for s in out["steps"] if "exit" in s] + [w for w in out["workflows_lint"] if w["exit"] is not None]
    out["green"] = all(x["exit"] == 0 for x in ran)
    return out
