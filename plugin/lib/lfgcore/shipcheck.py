"""`lfg shipcheck`: build → scan → run on an internal network → smoke test →
delete → verify cleanup, plus the 10-item shipping checklist. No deploy, no push, ever.

Every Docker resource gets the label lfg.shipcheck=<run-id>; cleanup only ever touches that label.
Author: Varun Singh.
"""
import json
import os
import re
import shutil
import signal
import time

from . import common as C
from . import gate as GT

LABEL = "lfg.shipcheck"


def _docker(*args, timeout=600):
    return C.run(["docker"] + list(args), timeout=timeout)


def docker_ok():
    if not C.which("docker"):
        return False, "Docker CLI not found. Install Docker Desktop (bootstrap does this)."
    cp = _docker("info", "--format", "{{.ServerVersion}}", timeout=20)
    if cp.returncode != 0:
        return False, "Docker is not running. Start Docker Desktop, then re-run `lfg shipcheck`."
    return True, cp.stdout.strip()


# ---------------------------------------------------------------- cleanup (label-scoped only)

def _ids(kind, label_value):
    flt = "label=%s=%s" % (LABEL, label_value) if label_value else "label=%s" % LABEL
    cmd = {"container": ["ps", "-aq", "--filter", flt], "image": ["images", "-q", "--filter", flt],
           "network": ["network", "ls", "-q", "--filter", flt], "volume": ["volume", "ls", "-q", "--filter", flt]}[kind]
    return sorted(set(_docker(*cmd, timeout=60).stdout.split()))


def leftovers(label_value=None):
    return {k: _ids(k, label_value) for k in ("container", "image", "network", "volume")}


def cleanup(label_value=None, project=None):
    """Remove only resources carrying our label (one run, or all LFG ship-check runs when label_value is None)."""
    log = []
    if project and project.startswith("lfg-shipcheck-"):
        cp = _docker("compose", "-p", project, "down", "-v", "--rmi", "local", "--remove-orphans", timeout=300)
        log.append("compose down %s -> %d" % (project, cp.returncode))
    for kind, rm in (("container", ["rm", "-f", "-v"]), ("network", ["network", "rm"]),
                     ("volume", ["volume", "rm", "-f"]), ("image", ["rmi", "-f"])):
        ids = _ids(kind, label_value)
        if ids:
            cp = _docker(*(rm + ids), timeout=300)
            log.append("%s rm %d -> %d" % (kind, len(ids), cp.returncode))
    if C.config()["shipcheck"].get("prune_build_cache"):
        flt = "label=%s=%s" % (LABEL, label_value) if label_value else "label=%s" % LABEL
        _docker("builder", "prune", "-f", "--filter", flt, timeout=300)
    left = leftovers(label_value)
    return {"log": log, "leftovers": left, "clean": not any(left.values())}


# ---------------------------------------------------------------- inputs

def find_dockerfiles(root):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules", ".venv", "venv", "vendor", "dist",
                                                         "build", "target", "__pycache__")]
        for fn in filenames:
            if fn == "Dockerfile" or fn.endswith(".Dockerfile") or fn.startswith("Dockerfile."):
                out.append(os.path.relpath(os.path.join(dirpath, fn), root))
        if dirpath.count(os.sep) - root.count(os.sep) >= 3:
            dirnames[:] = []
    return sorted(out, key=lambda p: (p.count("/"), p != "Dockerfile", p))


def ci_build_settings(root):
    """Dockerfile/target/platform the CI uses, read from .github/workflows (build args are never copied)."""
    res = {}
    wdir = os.path.join(root, ".github", "workflows")
    if not os.path.isdir(wdir):
        return res
    for fn in sorted(os.listdir(wdir)):
        txt = open(os.path.join(wdir, fn), errors="replace").read()
        if "docker" not in txt.lower():
            continue
        for key, rx in (("file", r"(?:^\s*file:\s*|\s-f\s+|--file[= ])([^\s'\"]+)"),
                        ("target", r"(?:^\s*target:\s*|--target[= ])([^\s'\"]+)"),
                        ("platform", r"(?:^\s*platforms?:\s*|--platform[= ])([^\s'\",]+)"),
                        ("context", r"^\s*context:\s*([^\s'\"]+)")):
            m = re.search(rx, txt, re.M)
            if m and key not in res and "${{" not in m.group(1):
                res[key] = m.group(1)
    return res


def dockerfile_info(path):
    txt = C.read_text(path)
    raw = re.sub(r"\\\n", " ", txt).splitlines()
    lines = [ln.strip() for ln in raw if ln.strip() and not ln.strip().startswith("#")]
    froms = [ln.split()[1] for ln in lines if ln.upper().startswith("FROM ") and len(ln.split()) > 1]
    expose = [p.split("/")[0] for ln in lines if ln.upper().startswith("EXPOSE ") for p in ln.split()[1:]]
    users = [ln.split()[1] for ln in lines if ln.upper().startswith("USER ") and len(ln.split()) > 1]
    return {"from": froms, "expose": expose, "user": users[-1] if users else None,
            "healthcheck": any(ln.upper().startswith("HEALTHCHECK ") and "NONE" not in ln.upper() for ln in lines)}


def env_example(root):
    """Names (and example values) from .env.example only; .env itself is never read."""
    for name in (".env.example", ".env.sample", ".env.template"):
        p = os.path.join(root, name)
        if os.path.exists(p):
            out = {}
            for line in C.read_text(p).splitlines():
                m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
                if m:
                    out[m.group(1)] = m.group(2).strip().strip("'\"")
            return out, name
    return {}, None


def smoke_spec(root, rid, info):
    """Routes to smoke-test: run folder shipcheck-routes.json (written by /ship from acceptance criteria) or
    <checkout>/.lfg/shipcheck.json; otherwise health + /."""
    run = C.current_run(root)
    spec = (C.read_json(os.path.join(run, "shipcheck-routes.json"), None) if run else None) or \
        C.read_json(C.repo_file(root, "shipcheck.json"), None) or {}
    port = str(spec.get("port") or (info["expose"][0] if info["expose"] else "8080"))
    routes = spec.get("routes") or [{"path": spec.get("health", "/health"), "status": [200, 204], "optional": True},
                                     {"path": "/", "status": [200, 204, 301, 302, 401, 403, 404]}]
    return port, spec.get("health"), routes


# ---------------------------------------------------------------- steps

def lint_dockerfile(root, dockerfile, info):
    checks = []
    full = os.path.join(root, dockerfile)
    if C.which("hadolint"):
        cp = C.run(["hadolint", "--no-color", full], timeout=120)
        checks.append({"check": "hadolint", "ok": cp.returncode == 0,
                       "detail": (cp.stdout or cp.stderr).strip()[-1500:]})
    else:
        checks.append({"check": "hadolint", "ok": None, "detail": "hadolint not installed (bootstrap installs it)"})
    if C.which("trivy"):
        cp = C.run(["trivy", "config", "--quiet", "--exit-code", "1", "--severity", "HIGH,CRITICAL", full], timeout=300)
        checks.append({"check": "trivy config", "ok": cp.returncode == 0,
                       "detail": (cp.stdout or cp.stderr).strip()[-1500:]})
    else:
        checks.append({"check": "trivy config", "ok": None, "detail": "trivy not installed"})
    unpinned = [f for f in info["from"]
                if "@sha256:" not in f and f.lower() != "scratch" and not re.match(r"^[a-z0-9_-]+$", f)]
    checks.append({"check": "base image pinned by digest", "ok": not unpinned, "detail": ", ".join(unpinned),
                   "severity": "warn"})
    checks.append({"check": "non-root USER", "ok": bool(info["user"]) and info["user"] not in ("root", "0", "0:0")})
    checks.append({"check": "HEALTHCHECK present", "ok": info["healthcheck"], "severity": "warn"})
    di = os.path.join(root, ".dockerignore")
    ign = C.read_text(di)
    missing = [p for p in (".env", ".git") if not re.search(r"(^|\n)\s*(\*\*/)?%s" % re.escape(p), ign)]
    checks.append({"check": ".dockerignore excludes .env* and .git", "ok": not missing,
                   "detail": "missing: %s" % ", ".join(missing) if missing else ""})
    graphs = [d for d in (".code-review-graph", "graphify-out") if os.path.isdir(os.path.join(root, d))]
    leak = [d for d in graphs if not re.search(r"(^|\n)\s*(\*\*/)?/?%s" % re.escape(d), ign)]
    checks.append({"check": ".dockerignore excludes LFG graph folders", "ok": not leak, "severity": "warn",
                   "detail": "add to .dockerignore: %s (git-ignored, but docker build still copies them)"
                   % ", ".join(leak) if leak else ""})
    return checks


def scan_image(tag, rid):
    out = []
    if C.which("trivy"):
        cp = C.run(["trivy", "image", "--quiet", "--scanners", "vuln,secret", "--severity", "HIGH,CRITICAL",
                    "--exit-code", "1", "--ignore-unfixed", tag], timeout=900)
        out.append({"check": "trivy image (vuln + secret)", "ok": cp.returncode == 0,
                    "detail": (cp.stdout or cp.stderr).strip()[-3000:]})
    else:
        out.append({"check": "trivy image", "ok": None, "detail": "trivy not installed"})
    hist = _docker("history", "--no-trunc", "--format", "{{.CreatedBy}}", tag).stdout
    secret_rx = r"(?:ENV|ARG)\s+[^\n]*?([A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PASSWD|API_KEY|PRIVATE)[A-Z0-9_]*)=(\S+)"
    bad = re.findall(secret_rx, hist, re.I)
    bad = [n for n, v in bad if v and not v.startswith("$")]
    out.append({"check": "no secrets in ENV/ARG layers", "ok": not bad, "detail": ", ".join(sorted(set(bad)))})
    size = int((_docker("image", "inspect", "--format", "{{.Size}}", tag).stdout.strip() or "0"))
    hist_path = C.lfg_path("repos", rid, "shipcheck-history.json")
    prev = (C.read_json(hist_path, {}) or {}).get("size")
    growth = (size - prev) / float(prev) if prev else 0.0
    warn = C.config()["shipcheck"]["image_growth_warn"]
    out.append({"check": "image size", "ok": growth <= warn, "severity": "warn",
                "detail": "%.1f MB%s" % (size / 1e6, " (+%.0f%% vs last check)" % (growth * 100) if prev else "")})
    C.write_json(hist_path, {"size": size, "ts": C.now_iso()})
    return out


def _runner(net, run_id, url, timeout=5):
    img = C.config()["shipcheck"]["runner_image"]
    cp = _docker("run", "--rm", "--network", net, "--label", "%s=%s" % (LABEL, run_id), "--memory", "128m",
                 img, "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", str(timeout), url, timeout=60)
    code = cp.stdout.strip()
    return int(code) if code.isdigit() else 0


def run_and_smoke(root, rid, run_id, tag, info):
    cfg = C.config()["shipcheck"]
    net = "lfg-shipcheck-%s" % run_id
    name = "lfg-shipcheck-%s-app" % run_id
    checks = []
    cp = _docker("network", "create", "--internal", "--label", "%s=%s" % (LABEL, run_id), net)
    if cp.returncode:
        return [{"check": "internal network", "ok": False, "detail": cp.stderr.strip()}]
    port, health_path, routes = smoke_spec(root, rid, info)
    envs, src = env_example(root)
    args = ["run", "-d", "--name", name, "--network", net, "--network-alias", "app",
            "--label", "%s=%s" % (LABEL, run_id), "--memory", cfg["memory"], "--cpus", str(cfg["cpus"]),
            "--security-opt", "no-new-privileges"]
    for k, v in envs.items():
        args += ["-e", "%s=%s" % (k, port if k == "PORT" else (v or "lfg-test-placeholder"))]
    if "PORT" not in envs:
        args += ["-e", "PORT=%s" % port]
    cp = _docker(*(args + [tag]), timeout=120)
    checks.append({"check": "container started (internal network, no published ports, env from %s)" % (src or "none"),
                   "ok": cp.returncode == 0, "detail": cp.stderr.strip()[-500:]})
    if cp.returncode:
        return checks
    deadline, healthy, state = time.time() + cfg["health_timeout_s"], False, {}
    while time.time() < deadline:
        raw = _docker("inspect", "--format", "{{json .State}}", name).stdout.strip()
        state = json.loads(raw) if raw.startswith("{") else {}
        if not state.get("Running"):
            break
        hs = (state.get("Health") or {}).get("Status")
        if hs == "healthy":
            healthy = True
            break
        if hs is None and _runner(net, run_id, "http://app:%s%s" % (port, health_path or "/"), 3):
            healthy = True
            break
        time.sleep(2)
    checks.append({"check": "stays up and turns healthy within %ss" % cfg["health_timeout_s"], "ok": healthy,
                   "detail": "" if healthy else
                   "state: %s" % {k: state.get(k) for k in ("Status", "ExitCode", "Error")}})
    if healthy:
        for r in routes:
            if r.get("needs_credential"):
                checks.append({"check": "route %s" % r["path"], "ok": None,
                               "detail": "skipped: needs a real credential"})
                continue
            got = _runner(net, run_id, "http://app:%s%s" % (port, r["path"]))
            want = r.get("status", [200])
            want = want if isinstance(want, list) else [want]
            ok = got in want
            if not ok and r.get("optional") and got == 404:
                checks.append({"check": "route %s" % r["path"], "ok": None, "detail": "404 (optional route)"})
                continue
            checks.append({"check": "route %s -> %s" % (r["path"], "/".join(map(str, want))), "ok": ok,
                           "detail": "got %s" % got})
    lg = _docker("logs", "--tail", "400", name)
    logs = (lg.stdout or "") + (lg.stderr or "")
    errs = [ln for ln in logs.splitlines() if re.search(r"Traceback \(most recent|\bERROR\b|\bFATAL\b|panic:|"
                                                     r"Unhandled(Promise)?Rejection|Exception in thread", ln)]
    checks.append({"check": "no errors or stack traces in logs", "ok": not errs,
                   "detail": "\n".join(ln[:200] for ln in errs[:10])})
    return checks


# ---------------------------------------------------------------- checklist

def checklist(root, rid, part_a_ok, part_a_na):
    run = C.current_run(root)
    rd = C.read_json(os.path.join(run, "ready.json"), {}) if run else {}
    items = []

    def add(n, title, status, why=""):
        items.append({"n": n, "requirement": title, "status": status, "detail": why})

    add(1, "Gates 1-7 green (ready.json)", "pass" if rd.get("green") else "fail",
        "" if rd else "no ready.json - run `lfg gate`")
    ci = GT.ci_local(root, list_only=True)
    wl = [w for w in ci["workflows_lint"] if w["exit"] not in (None, 0)]
    add(2, "Local CI replay green, workflows valid", "fail" if wl else ("n/a" if not ci["steps"] and not
                                                                          ci["workflows_lint"] else "pass"),
        "; ".join("%s exit %s" % (w["tool"], w["exit"]) for w in wl) or
        "run `lfg ci-local` to replay %d step(s)" % len([s for s in ci["steps"] if not s["skipped"]]))
    lock = None
    if os.path.exists(os.path.join(root, "package-lock.json")):
        lock = ["npm", "ci", "--dry-run", "--ignore-scripts"]
    elif os.path.exists(os.path.join(root, "uv.lock")):
        lock = ["uv", "lock", "--check"]
    elif os.path.exists(os.path.join(root, "go.sum")):
        lock = ["go", "mod", "verify"]
    elif os.path.exists(os.path.join(root, "Cargo.lock")):
        lock = ["cargo", "metadata", "--locked", "--format-version", "1", "--no-deps"]
    if lock:
        cp = C.run(lock, cwd=root, timeout=600)
        add(3, "Lockfile in sync with manifest", "pass" if cp.returncode == 0 else "fail",
            " ".join(lock) + ("" if cp.returncode == 0 else ": " + (cp.stderr or cp.stdout).strip()[-300:]))
    else:
        add(3, "Lockfile in sync with manifest", "n/a", "no supported lockfile found")
    envs, _src = env_example(root)
    diff = GT.diff_text(root)
    used = set()
    for _f, line in GT.added_lines(diff):
        used |= set(re.findall(r"(?:process\.env\.|os\.environ(?:\.get)?\(?\[?['\"]|os\.getenv\(['\"]|"
                               r"Getenv\(\"|env::var\(\")([A-Z][A-Z0-9_]+)", line))
    missing = sorted(used - set(envs))
    add(4, "New env vars listed by name in .env.example", "fail" if missing else ("pass" if used else "n/a"),
        ("missing: " + ", ".join(missing)) if missing else
        ("names checked: %s (deploy secrets: check `gh secret list` names)" % ", ".join(sorted(used)) if used
         else "no new env vars in the diff"))
    add(5, "Migrations apply to a throwaway DB", "n/a" if not any(re.search(r"migrat", f, re.I)
                                                                  for f in GT.changed_files(root)) else "manual",
        "no migration files changed" if not any(re.search(r"migrat", f, re.I) for f in GT.changed_files(root))
        else "migration files changed: /ship verifies them against the throwaway DB")
    left = [("%s: %s" % (f, ln.strip()[:120])) for f, ln in GT.added_lines(diff)
            if re.search(r"\b(console\.log|debugger;|print\(|pdb\.set_trace|breakpoint\(\)|fmt\.Println|dbg!)|"
                         r"\b(it|test|describe)\.only\(|\bfit\(|\bfdescribe\(|\bTODO\b|\bFIXME\b", ln)]
    add(6, "No leftovers (debug prints, .only, TODOs)", "fail" if left else "pass", "\n".join(left[:15]))
    has_changelog = any(os.path.exists(os.path.join(root, n)) for n in ("CHANGELOG.md", "CHANGES.md", "HISTORY.md"))
    touched = any(os.path.basename(f) in ("CHANGELOG.md", "CHANGES.md", "HISTORY.md") for f in GT.changed_files(root))
    add(7, "Changelog / version bump", "n/a" if not has_changelog else ("pass" if touched else "fail"),
        "" if has_changelog else "repo has no changelog")
    sec = C.read_json(os.path.join(run, "05-secure.json"), None) if run else None
    lic = [f for f in (sec or {}).get("findings", []) if f.get("type") == "license" and f.get("blocking")]
    if sec is None:
        add(8, "New dependency licences compatible", "fail", "no 05-secure.json in this run - run /secure first")
    elif not sec.get("inventory", {}).get("packages"):
        add(8, "New dependency licences compatible", "n/a", "no new dependencies")
    else:
        add(8, "New dependency licences compatible", "fail" if lic else "pass",
            "checked via deps.dev: %s" % ", ".join(sec.get("licences_checked") or []))
    add(9, "Docker part A passed and cleaned up", "n/a" if part_a_na else ("pass" if part_a_ok else "fail"),
        "no Dockerfile in the repo" if part_a_na else "")
    have = [n for n in ("COMMIT_MSG.md", "PR_BODY.md", "ready.json") if run and os.path.exists(os.path.join(run, n))]
    add(10, "Ship packet written", "pass" if len(have) == 3 else "pending",
        "present: %s (/ship writes COMMIT_MSG.md and PR_BODY.md after this check)" % (", ".join(have) or "none"))
    return items


# ---------------------------------------------------------------- main

def shipcheck(root, rid):
    run = C.current_run(root)
    run_id = os.path.basename(run) if run else "adhoc-%s" % time.strftime("%Y%m%d-%H%M%S")
    run_id = re.sub(r"[^a-z0-9_.-]", "-", run_id.lower())
    result = {"ts": C.now_iso(), "run_id": run_id, "part_a": {"applicable": False, "checks": []}}
    dockerfiles = find_dockerfiles(root)
    ci = ci_build_settings(root)
    dockerfile = ci.get("file") if ci.get("file") and os.path.exists(os.path.join(root, ci["file"])) else \
        (dockerfiles[0] if dockerfiles else None)
    part_a_ok, interrupted = False, []
    if dockerfile:
        result["part_a"]["applicable"] = True
        ok, why = docker_ok()
        if not ok:
            result["part_a"]["error"] = why
            result["checklist"] = checklist(root, rid, False, False)
            result["pass"] = False
            return result
        info = dockerfile_info(os.path.join(root, dockerfile))
        free = shutil.disk_usage(root).free
        checks = [{"check": "docker daemon", "ok": True, "detail": "server %s" % why},
                  {"check": "free disk >= 5 GB", "ok": free >= 5e9, "detail": "%.1f GB free" % (free / 1e9)}]
        checks += lint_dockerfile(root, dockerfile, info)
        tag = "lfg-shipcheck/%s:%s" % (rid.lower(), run_id)
        project = "lfg-shipcheck-%s" % run_id
        old = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, lambda *_: interrupted.append(1) or (_ for _ in ()).throw(KeyboardInterrupt()))
        try:
            ctx = os.path.join(root, ci.get("context", ".")) if ci.get("context") else root
            bargs = ["build", "-f", os.path.join(root, dockerfile), "-t", tag, "--label", "%s=%s" % (LABEL, run_id),
                     "--pull=false"]
            if ci.get("target"):
                bargs += ["--target", ci["target"]]
            if ci.get("platform"):
                bargs += ["--platform", ci["platform"]]
            t0 = time.time()
            cp = _docker(*(bargs + [ctx]), timeout=3600)
            tgt = ", target " + ci["target"] if ci.get("target") else ""
            plat = ", " + ci["platform"] if ci.get("platform") else ""
            checks.append({"check": "build (%s%s%s)" % (dockerfile, tgt, plat),
                           "ok": cp.returncode == 0, "detail": ("%.0fs" % (time.time() - t0)) if cp.returncode == 0
                           else (cp.stderr or cp.stdout).strip()[-2000:]})
            if cp.returncode == 0:
                checks += scan_image(tag, rid)
                checks += run_and_smoke(root, rid, run_id, tag, info)
        except KeyboardInterrupt:
            checks.append({"check": "interrupted", "ok": False, "detail": "Ctrl-C; cleaned up"})
        finally:
            cl = cleanup(run_id, project)
            signal.signal(signal.SIGINT, old)
        checks.append({"check": "cleanup verified (label %s=%s)" % (LABEL, run_id), "ok": cl["clean"],
                       "detail": "" if cl["clean"] else
                       "leftovers: %s - run `lfg shipcheck --cleanup`" % cl["leftovers"]})
        result["part_a"]["checks"] = checks
        part_a_ok = all(c["ok"] is not False for c in checks if c.get("severity") != "warn")
        result["part_a"]["pass"] = part_a_ok
        result["part_a"]["warnings"] = [c["check"] for c in checks if c.get("severity") == "warn" and c["ok"] is False]
    else:
        result["part_a"]["note"] = ("No Dockerfile: part A is not applicable. /ship smoke-tests the CI start "
                                    "command locally instead (commands.json `start`).")
    result["checklist"] = checklist(root, rid, part_a_ok, not dockerfile)
    result["pass"] = (part_a_ok or not dockerfile) and all(i["status"] in ("pass", "n/a", "pending", "manual")
                                                           for i in result["checklist"])
    if run:
        C.write_json(os.path.join(run, "07-shipcheck.json"), result)
    if interrupted:
        raise KeyboardInterrupt()
    return result
