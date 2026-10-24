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
# Docker sets these itself (https://docs.docker.com/build/building/variables/#pre-defined-build-arguments)
BUILTIN_ARGS = {"TARGETPLATFORM", "TARGETOS", "TARGETARCH", "TARGETVARIANT", "BUILDPLATFORM", "BUILDOS", "BUILDARCH",
                "BUILDVARIANT", "HTTP_PROXY", "HTTPS_PROXY", "FTP_PROXY", "NO_PROXY", "ALL_PROXY", "http_proxy",
                "https_proxy", "ftp_proxy", "no_proxy", "all_proxy", "BUILDKIT_INLINE_CACHE"}
LOCKFILES = ("package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "uv.lock", "poetry.lock",
             "Pipfile.lock", "requirements.txt", "go.sum", "Cargo.lock", "Gemfile.lock", "composer.lock")
SKIPS = {"needs_credential", "optional", "on_main"}  # declared reasons a check didn't pass that aren't failures


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
        if "build_args_in" not in res and re.search(r"--build-arg\b|^\s*build-args:", txt, re.M):
            res["build_args_in"] = os.path.join(".github", "workflows", fn)
    return res


def dockerfile_info(path):
    txt = C.read_text(path)
    raw = re.sub(r"\\\n", " ", txt).splitlines()
    lines = [ln.strip() for ln in raw if ln.strip() and not ln.strip().startswith("#")]
    froms = [ln.split()[1] for ln in lines if ln.upper().startswith("FROM ") and len(ln.split()) > 1]
    expose = [p.split("/")[0] for ln in lines if ln.upper().startswith("EXPOSE ") for p in ln.split()[1:]]
    users = [ln.split()[1] for ln in lines if ln.upper().startswith("USER ") and len(ln.split()) > 1]
    args = []  # ARGs some stage declares with no default: the image needs them from --build-arg
    for ln in lines:
        if ln.upper().startswith("ARG "):
            for a in ln.split()[1:]:
                if "=" not in a and a not in BUILTIN_ARGS and a not in args:
                    args.append(a)
    return {"from": froms, "expose": expose, "user": users[-1] if users else None, "args": args,
            "healthcheck": any(ln.upper().startswith("HEALTHCHECK ") and "NONE" not in ln.upper() for ln in lines)}


def missing_args(info, build_args):
    return [a for a in info.get("args") or [] if a not in (build_args or {})]


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


def repo_spec(root):
    """<checkout>/.lfg/shipcheck.json: build_args, images (one per service), boot, port, health, routes,
    hadolint_threshold. Committed with the repo, so everyone's ship check builds the same images."""
    spec = C.read_json(C.repo_file(root, "shipcheck.json"), None)
    return spec if isinstance(spec, dict) else {}


def images(spec):
    """The images to check: each of `images` over the shared settings, else one unnamed image from the top level."""
    shared = {k: v for k, v in spec.items() if k != "images"}
    out = []
    for im in spec.get("images") or [{}]:
        if isinstance(im, dict):
            one = dict(shared, **im)
            one["build_args"] = dict(shared.get("build_args") or {}, **(im.get("build_args") or {}))
            one.setdefault("name", "")
            one.setdefault("boot", {})
            out.append(one)
    return out


def smoke_spec(root, rid, info, image=None):
    """Routes to smoke-test: run folder shipcheck-routes.json (written by /ship from acceptance criteria), else the
    image's own settings from <checkout>/.lfg/shipcheck.json; otherwise health + /."""
    run = C.current_run(root)
    spec = (C.read_json(os.path.join(run, "shipcheck-routes.json"), None) if run else None) or image or \
        repo_spec(root)
    port = str(spec.get("port") or (info["expose"][0] if info["expose"] else "8080"))
    routes = spec.get("routes") or [{"path": spec.get("health", "/health"), "status": [200, 204], "optional": True},
                                     {"path": "/", "status": [200, 204, 301, 302, 401, 403, 404]}]
    return port, spec.get("health"), routes


# ---------------------------------------------------------------- what the branch changed

def _pr_base(root):
    """The base branch of this branch's open PR (`gh pr view`), or "" with no PR or no gh."""
    if not C.which("gh"):
        return ""
    cp = C.run(["gh", "pr", "view", "--json", "baseRefName,state", "-q", "select(.state == \"OPEN\") | .baseRefName"],
               cwd=root, timeout=30)
    return cp.stdout.strip() if cp.returncode == 0 else ""


def branch_changes(root):
    """(base commit, what it is, files the branch changed since). A stacked PR is measured from its own base (the PR
    below it), not main: the PRs under it aren't this branch's work."""
    pr_base = _pr_base(root)
    if pr_base:
        for ref in ("origin/" + pr_base, pr_base):
            cp = C.run(["git", "merge-base", "HEAD", ref], cwd=root, timeout=15)
            if cp.returncode == 0 and cp.stdout.strip():
                base = cp.stdout.strip()
                got = C.run(["git", "diff", "--name-only", base, "HEAD"], cwd=root, timeout=30).stdout.split("\n")
                return base, "its PR's base %s" % pr_base, sorted({f for f in got if f} | set(GT.changed_files(root)))
    return GT.merge_base(root), "the default branch", GT.branch_files(root)


# ---------------------------------------------------------------- steps

def _old(check, touched):
    """A Dockerfile lint finding when the branch didn't change the Dockerfile: already on main, not a failure."""
    if check["ok"] is False and not touched:
        return dict(check, ok=None, skip="on_main",
                    detail="already on main: this branch didn't change the Dockerfile\n" + check["detail"])
    return check


def lint_dockerfile(root, dockerfile, info, threshold=None, changed=None):
    """hadolint fails at `threshold` (shipcheck.json hadolint_threshold, default warning) and above: its info and
    style notes are shown, never a failure. With `changed` (the branch's files), findings in a Dockerfile the branch
    didn't change are reported as already on main."""
    checks = []
    full = os.path.join(root, dockerfile)
    touched = changed is None or any(DOCKER_FILES.search(f) for f in changed)
    if C.which("hadolint"):
        level = threshold or C.config()["shipcheck"].get("hadolint_threshold") or "warning"
        cp = C.run(["hadolint", "--failure-threshold", level, "--no-color", full], timeout=120)
        out = (cp.stdout or cp.stderr).strip().splitlines()
        rank = {"error": 0, "warning": 1, "info": 2, "style": 3}
        out.sort(key=lambda ln: next((v for k, v in rank.items() if " %s:" % k in ln), 4))  # worst first
        checks.append(_old({"check": "hadolint (fails at %s or above)" % level if level != "warning" else "hadolint",
                            "ok": cp.returncode == 0, "detail": "\n".join(out)[:1500]}, touched))
    else:
        checks.append({"check": "hadolint", "ok": None, "detail": "hadolint not installed (bootstrap installs it)"})
    if C.which("trivy"):
        cp = C.run(["trivy", "config", "--quiet", "--exit-code", "1", "--severity", "HIGH,CRITICAL", full], timeout=300)
        checks.append(_old({"check": "trivy config", "ok": cp.returncode == 0,
                            "detail": (cp.stdout or cp.stderr).strip()[-1500:]}, touched))
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


DOCKER_FILES = re.compile(r"(^|/)(Dockerfile[^/]*|[^/]+\.Dockerfile|\.dockerignore)$")
MANIFESTS = ("package.json", "pyproject.toml", "setup.py", "go.mod", "Cargo.toml", "Gemfile", "composer.json")


def base_locks(root, base):
    """{path: text} of every lockfile at commit `base` (where the branch left main)."""
    if not base:
        return {}
    cp = C.run(["git", "ls-tree", "-r", "--name-only", base], cwd=root, timeout=30)
    out = {}
    for f in (cp.stdout.splitlines() if cp.returncode == 0 else []):
        if os.path.basename(f) in LOCKFILES and "node_modules/" not in f and len(out) < 40:
            got = C.run(["git", "show", "%s:%s" % (base, f)], cwd=root, timeout=30)
            if got.returncode == 0:
                out[f] = got.stdout
    return out


def _in_base(name, version, locks):
    """Was package `name` at `version` already locked on main?"""
    for path, text in locks.items():
        if os.path.basename(path) in ("package-lock.json", "npm-shrinkwrap.json"):
            try:
                pk = (json.loads(text) or {}).get("packages") or {}
            except ValueError:
                pk = {}
            if any((k == "node_modules/" + name or k.endswith("/node_modules/" + name)) and
                   (v or {}).get("version") == version for k, v in pk.items()):
                return True
            if pk:
                continue
        lines = text.splitlines()
        for i, ln in enumerate(lines):  # yarn.lock, uv.lock, go.sum, Cargo.lock...: the name, then its version nearby
            if name in ln and version in " ".join(lines[i:i + 4]):
                return True
    return False


def split_image_findings(report, locks, changed):
    """trivy's JSON report split into (introduced by the branch, already on main). OS packages come from the
    Dockerfile; language packages from lockfiles: with neither changed, nothing in the image is new. A changed
    lockfile: a package at a version main already locked is old. Secrets and other findings: new when they sit in a
    file the branch changed."""
    changed = [f for f in changed or [] if f]
    dock = any(DOCKER_FILES.search(f) for f in changed)
    deps = any(os.path.basename(f) in LOCKFILES + MANIFESTS for f in changed)
    new, old = [], []
    for r in (report or {}).get("Results") or []:
        target, cls = r.get("Target") or "", r.get("Class") or ""
        mine = any(target.lstrip("/") == f or target.endswith("/" + f) for f in changed)
        for v in r.get("Vulnerabilities") or []:
            x = {"id": v.get("VulnerabilityID"), "pkg": v.get("PkgName"), "version": v.get("InstalledVersion"),
                 "severity": v.get("Severity"), "target": target, "fixed": v.get("FixedVersion") or ""}
            if cls == "os-pkgs":
                brought = dock
            elif cls == "lang-pkgs":
                brought = (deps or dock) and not _in_base(x["pkg"] or "", x["version"] or "", locks)
            else:
                brought = mine
            (new if brought else old).append(x)
        for sc in r.get("Secrets") or []:
            (new if mine else old).append({"id": sc.get("RuleID"), "pkg": "", "version": "",
                                           "severity": sc.get("Severity"), "target": target, "fixed": ""})
    return new, old


def _finding_line(x):
    return "%s %s %s%s (%s)" % (x["severity"], x["id"], x["pkg"] or "", "@" + x["version"] if x["version"] else "",
                                x["target"])


def scan_image(tag, rid, root=None, name="", changes=None):
    out = []
    if C.which("trivy"):
        cp = C.run(["trivy", "image", "--quiet", "--scanners", "vuln,secret", "--severity", "HIGH,CRITICAL",
                    "--exit-code", "0", "--ignore-unfixed", "--format", "json", tag], timeout=900)
        try:
            report = json.loads(cp.stdout or "")
        except ValueError:
            report = None
        if report is None:
            out.append({"check": "trivy image (vuln + secret)", "ok": False,
                        "detail": (cp.stderr or cp.stdout).strip()[-3000:] or "trivy gave no report"})
        else:
            base, what, files = changes or (branch_changes(root) if root else ("", "", []))
            new, old = split_image_findings(report, base_locks(root, base) if root else {}, files)
            note = "%d already there before this branch (on %s)" % (len(old), what or "main") if old else ""
            out.append({"check": "trivy image (vuln + secret), findings this branch brought", "ok": not new,
                        "on_main": len(old), "introduced": len(new),
                        "detail": "\n".join([_finding_line(x) for x in new[:40]] + ([note] if note else []))})
    else:
        out.append({"check": "trivy image", "ok": None, "detail": "trivy not installed"})
    hist = _docker("history", "--no-trunc", "--format", "{{.CreatedBy}}", tag).stdout
    secret_rx = r"(?:ENV|ARG)\s+[^\n]*?([A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PASSWD|API_KEY|PRIVATE)[A-Z0-9_]*)=(\S+)"
    bad = re.findall(secret_rx, hist, re.I)
    bad = [n for n, v in bad if v and not v.startswith("$")]
    out.append({"check": "no secrets in ENV/ARG layers", "ok": not bad, "detail": ", ".join(sorted(set(bad)))})
    size = int((_docker("image", "inspect", "--format", "{{.Size}}", tag).stdout.strip() or "0"))
    hist_path = C.lfg_path("repos", rid, "shipcheck-history.json")
    hist = C.read_json(hist_path, {}) or {}
    prev = (hist.get("images") or {}).get(name) if name else hist.get("size")
    growth = (size - prev) / float(prev) if prev else 0.0
    warn = C.config()["shipcheck"]["image_growth_warn"]
    out.append({"check": "image size", "ok": growth <= warn, "severity": "warn",
                "detail": "%.1f MB%s" % (size / 1e6, " (+%.0f%% vs last check)" % (growth * 100) if prev else "")})
    if name:  # one size per service image
        hist.setdefault("images", {})[name] = size
    else:
        hist["size"] = size
    hist["ts"] = C.now_iso()
    C.write_json(hist_path, hist)
    return out


def _runner(net, run_id, url, timeout=5):
    img = C.config()["shipcheck"]["runner_image"]
    cp = _docker("run", "--rm", "--network", net, "--label", "%s=%s" % (LABEL, run_id), "--memory", "128m",
                 img, "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", str(timeout), url, timeout=60)
    code = cp.stdout.strip()
    return int(code) if code.isdigit() else 0


LOG_ERR = re.compile(r"Traceback \(most recent|\bERROR\b|\bFATAL\b|panic:|Unhandled(Promise)?Rejection|"
                     r"Exception in thread")
BOOT_ERR = re.compile(LOG_ERR.pattern + r"|\b\w*Error\b|^\s+at ")


def boot_checks(logs, boot, routes, state=None):
    """A service that stops at startup without real credentials (shipcheck.json "boot": {"needs_credential": true,
    "expect_log": "<its start line>"}): it passes when that line shows in the log. Its routes, staying up and errors
    after that line are skipped as needing a credential; errors before it still fail. LFG never passes real
    credentials."""
    expect = boot.get("expect_log") or ""
    at = logs.find(expect) if expect else -1
    tail = "\n".join(logs.strip().splitlines()[-8:])
    checks = [{"check": "entry point started (%s)" % (expect or "set boot.expect_log"), "ok": at >= 0,
               "detail": "seen in the container log" if at >= 0 else
               ("not in the container log; it ended with:\n%s" % tail if expect else
                "add \"expect_log\": a line the service prints when it starts, to .lfg/shipcheck.json \"boot\"")}]
    why = "skipped: it stops at startup without real credentials (LFG never passes them)"
    checks.append({"check": "stays up and turns healthy", "ok": None, "skip": "needs_credential",
                   "detail": "%s; state: %s" % (why, {k: (state or {}).get(k) for k in ("Status", "ExitCode")})})
    for r in routes:
        checks.append({"check": "route %s" % r["path"], "ok": None, "skip": "needs_credential", "detail": why})
    before, after = (logs[:at], logs[at:]) if at >= 0 else (logs, "")
    early = [ln for ln in before.splitlines() if LOG_ERR.search(ln)]
    late = [ln for ln in after.splitlines() if BOOT_ERR.search(ln)]
    if early:
        checks.append({"check": "no errors or stack traces in logs", "ok": False,
                       "detail": "before the service started:\n" + "\n".join(ln[:200] for ln in early[:10])})
    elif late:
        checks.append({"check": "no errors or stack traces in logs", "ok": None, "skip": "needs_credential",
                       "detail": "after it started, expected without credentials:\n" +
                       "\n".join(ln[:200] for ln in late[:10])})
    else:
        checks.append({"check": "no errors or stack traces in logs", "ok": True, "detail": ""})
    return checks


def run_and_smoke(root, rid, run_id, tag, info, image=None, key=None):
    cfg = C.config()["shipcheck"]
    image = image or {}
    boot = image.get("boot") or {}
    key = key or run_id
    net = "lfg-shipcheck-%s" % key
    name = "lfg-shipcheck-%s-app" % key
    checks = []
    cp = _docker("network", "create", "--internal", "--label", "%s=%s" % (LABEL, run_id), net)
    if cp.returncode:
        return [{"check": "internal network", "ok": False, "detail": cp.stderr.strip()}]
    port, health_path, routes = smoke_spec(root, rid, info, image or None)
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
    if boot.get("needs_credential"):
        expect, deadline, state, logs = boot.get("expect_log") or "", time.time() + cfg["health_timeout_s"], {}, ""
        while time.time() < deadline:
            lg = _docker("logs", "--tail", "400", name)
            logs = (lg.stdout or "") + (lg.stderr or "")
            raw = _docker("inspect", "--format", "{{json .State}}", name).stdout.strip()
            state = json.loads(raw) if raw.startswith("{") else {}
            if not state.get("Running") or (expect and expect in logs):
                break
            time.sleep(2)
        time.sleep(3)  # what it says next, up to stopping for want of a credential
        lg = _docker("logs", "--tail", "400", name)
        logs = (lg.stdout or "") + (lg.stderr or "") or logs
        return checks + boot_checks(logs, boot, routes, state)
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
                checks.append({"check": "route %s" % r["path"], "ok": None, "skip": "needs_credential",
                               "detail": "skipped: needs a real credential"})
                continue
            got = _runner(net, run_id, "http://app:%s%s" % (port, r["path"]))
            want = r.get("status", [200])
            want = want if isinstance(want, list) else [want]
            ok = got in want
            if not ok and r.get("optional") and got == 404:
                checks.append({"check": "route %s" % r["path"], "ok": None, "skip": "optional",
                               "detail": "404 (optional route)"})
                continue
            checks.append({"check": "route %s -> %s" % (r["path"], "/".join(map(str, want))), "ok": ok,
                           "detail": "got %s" % got})
    lg = _docker("logs", "--tail", "400", name)
    logs = (lg.stdout or "") + (lg.stderr or "")
    errs = [ln for ln in logs.splitlines() if LOG_ERR.search(ln)]
    checks.append({"check": "no errors or stack traces in logs", "ok": not errs,
                   "detail": "\n".join(ln[:200] for ln in errs[:10])})
    return checks


# ---------------------------------------------------------------- checklist

def workflow_lint(root, changed):
    """actionlint and zizmor on the workflows the branch changed (`introduced`: these fail the check) and on the
    rest (`on_main`: reported, never a failure). Each list holds only the tools that found something."""
    wdir = os.path.join(root, ".github", "workflows")
    every = sorted(os.path.join(".github", "workflows", f) for f in (os.listdir(wdir) if os.path.isdir(wdir) else [])
                   if f.endswith((".yml", ".yaml")))
    mine = [f for f in every if f in set(changed or [])]
    rest = [f for f in every if f not in mine]
    out = {"introduced": [], "on_main": [], "missing": [], "changed": mine, "workflows": len(every)}
    for tool, argv in (("actionlint", ["actionlint"]), ("zizmor", ["zizmor", "--offline"])):
        if not C.which(tool):
            out["missing"].append(tool)
            continue
        for group, files in (("introduced", mine), ("on_main", rest)):
            if files:
                cp = C.run(argv + files, cwd=root, timeout=300)
                if cp.returncode:
                    out[group].append({"tool": tool, "exit": cp.returncode, "files": files,
                                       "tail": "\n".join(((cp.stdout or "") + (cp.stderr or "")).strip()
                                                         .splitlines()[-25:])})
    return out


def status_of(checks, items):
    """fail: a check failed (warnings aside) or a checklist item did. needs_config: the repo must say how to build or
    run its image. pass_with_skips: every check that didn't pass was skipped for a reason the repo declared (a route
    that needs a credential, an optional route) or because it was already on main. Else pass."""
    if any(c.get("ok") is False and c.get("severity") != "warn" for c in checks) or \
            any(i.get("status") == "fail" for i in items):
        return "fail"
    if any(c.get("needs") for c in checks) or any(i.get("status") == "needs_config" for i in items):
        return "needs_config"
    if any(c.get("ok") is None and c.get("skip") in SKIPS for c in checks) or any(i.get("skip") for i in items):
        return "pass_with_skips"
    return "pass"


def checklist(root, rid, part_a_ok, part_a_na, part_a_status=None, changes=None):
    run = C.current_run(root)
    rd = C.read_json(os.path.join(run, "ready.json"), {}) if run else {}
    items = []

    def add(n, title, status, why=""):
        items.append({"n": n, "requirement": title, "status": status, "detail": why})

    add(1, "Gates 1-7 green (ready.json)", "pass" if rd.get("green") else "fail",
        "" if rd else "no ready.json - run `lfg gate`")
    ci = GT.ci_local(root, list_only=True, lint=False)
    wl = workflow_lint(root, (changes or branch_changes(root))[2])
    replay = "run `lfg ci-local` to replay %d step(s)" % len([s for s in ci["steps"] if not s["skipped"]])
    old = "; already there, in workflows this branch didn't change: %s" % ", ".join(
        "%s exit %s" % (w["tool"], w["exit"]) for w in wl["on_main"]) if wl["on_main"] else ""
    add(2, "Local CI replay green, workflows valid", "fail" if wl["introduced"] else
        ("n/a" if not ci["steps"] and not wl["workflows"] else "pass"),
        ("in workflows this branch changed: %s" % "; ".join("%s exit %s" % (w["tool"], w["exit"])
                                                           for w in wl["introduced"]) if wl["introduced"] else
         replay) + old)
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
    if part_a_na:
        add(9, "Docker part A passed and cleaned up", "n/a", "no Dockerfile in the repo")
    elif part_a_status == "needs_config":
        add(9, "Docker part A passed and cleaned up", "needs_config",
            "the image needs build args: add them to .lfg/shipcheck.json")
    else:
        add(9, "Docker part A passed and cleaned up", "pass" if part_a_ok else "fail",
            "passed with declared skips" if part_a_status == "pass_with_skips" else "")
    have = [n for n in ("COMMIT_MSG.md", "PR_BODY.md", "ready.json") if run and os.path.exists(os.path.join(run, n))]
    add(10, "Ship packet written", "pass" if len(have) == 3 else "pending",
        "present: %s (/ship writes COMMIT_MSG.md and PR_BODY.md after this check)" % (", ".join(have) or "none"))
    return items


# ---------------------------------------------------------------- main

def build_argv(root, dockerfile, tag, run_id, ci, build_args):
    argv = ["build", "-f", os.path.join(root, dockerfile), "-t", tag, "--label", "%s=%s" % (LABEL, run_id),
            "--pull=false"]
    for k, v in sorted((build_args or {}).items()):
        argv += ["--build-arg", "%s=%s" % (k, v)]
    if ci.get("target"):
        argv += ["--target", ci["target"]]
    if ci.get("platform"):
        argv += ["--platform", ci["platform"]]
    return argv


def shipcheck(root, rid):
    run = C.current_run(root)
    run_id = os.path.basename(run) if run else "adhoc-%s" % time.strftime("%Y%m%d-%H%M%S")
    run_id = re.sub(r"[^a-z0-9_.-]", "-", run_id.lower())
    result = {"ts": C.now_iso(), "run_id": run_id, "part_a": {"applicable": False, "checks": []}}
    dockerfiles = find_dockerfiles(root)
    ci = ci_build_settings(root)
    dockerfile = ci.get("file") if ci.get("file") and os.path.exists(os.path.join(root, ci["file"])) else \
        (dockerfiles[0] if dockerfiles else None)
    part_a_ok, interrupted, changes = False, [], None
    if dockerfile:
        result["part_a"]["applicable"] = True
        ok, why = docker_ok()
        if not ok:
            result["part_a"]["error"] = why
            result["checklist"] = checklist(root, rid, False, False)
            result["pass"], result["status"] = False, "fail"
            return result
        info = dockerfile_info(os.path.join(root, dockerfile))
        free = shutil.disk_usage(root).free
        checks = [{"check": "docker daemon", "ok": True, "detail": "server %s" % why},
                  {"check": "free disk >= 5 GB", "ok": free >= 5e9, "detail": "%.1f GB free" % (free / 1e9)}]
        spec = repo_spec(root)
        changes = branch_changes(root)
        result["base"] = changes[1]
        checks += lint_dockerfile(root, dockerfile, info, spec.get("hadolint_threshold"), changes[2])
        project = "lfg-shipcheck-%s" % run_id
        old = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, lambda *_: interrupted.append(1) or (_ for _ in ()).throw(KeyboardInterrupt()))
        try:
            ctx = os.path.join(root, ci.get("context", ".")) if ci.get("context") else root
            for im in images(spec):
                slug = re.sub(r"[^a-z0-9_.-]", "-", im["name"].lower())
                pre = "[%s] " % im["name"] if im["name"] else ""
                miss = missing_args(info, im["build_args"])
                if miss:  # the image would build but start nothing: say how to fix it, not a failure
                    checks.append({"check": pre + "needs build args", "ok": None, "needs": "build_args",
                                   "detail": "%s has ARG %s with no default and .lfg/shipcheck.json gives no value%s. "
                                   "Add \"build_args\" there (or \"images\", one per service) with the values CI "
                                   "uses." % (dockerfile, ", ".join(miss), " (CI passes them in %s)"
                                              % ci["build_args_in"] if ci.get("build_args_in") else "")})
                    continue
                key = run_id + ("-" + slug if slug else "")
                tag = "lfg-shipcheck/%s:%s" % (rid.lower(), key)
                t0 = time.time()
                cp = _docker(*(build_argv(root, dockerfile, tag, run_id, ci, im["build_args"]) + [ctx]), timeout=3600)
                tgt = ", target " + ci["target"] if ci.get("target") else ""
                plat = ", " + ci["platform"] if ci.get("platform") else ""
                args = ", %s" % " ".join("%s=%s" % kv for kv in sorted(im["build_args"].items())) \
                    if im["build_args"] else ""
                checks.append({"check": "%sbuild (%s%s%s%s)" % (pre, dockerfile, tgt, plat, args),
                               "ok": cp.returncode == 0, "detail": ("%.0fs" % (time.time() - t0))
                               if cp.returncode == 0 else (cp.stderr or cp.stdout).strip()[-2000:]})
                if cp.returncode == 0:
                    found = scan_image(tag, rid, root, im["name"], changes)
                    found += run_and_smoke(root, rid, run_id, tag, info, im, key)
                    for c in found:
                        checks.append(dict(c, check=pre + c["check"]))
        except KeyboardInterrupt:
            checks.append({"check": "interrupted", "ok": False, "detail": "Ctrl-C; cleaned up"})
        finally:
            cl = cleanup(run_id, project)
            signal.signal(signal.SIGINT, old)
        checks.append({"check": "cleanup verified (label %s=%s)" % (LABEL, run_id), "ok": cl["clean"],
                       "detail": "" if cl["clean"] else
                       "leftovers: %s - run `lfg shipcheck --cleanup`" % cl["leftovers"]})
        result["part_a"]["checks"] = checks
        result["part_a"]["status"] = status_of(checks, [])
        part_a_ok = result["part_a"]["status"] in ("pass", "pass_with_skips")
        result["part_a"]["pass"] = part_a_ok
        result["part_a"]["warnings"] = [c["check"] for c in checks if c.get("severity") == "warn" and c["ok"] is False]
    else:
        result["part_a"]["note"] = ("No Dockerfile: part A is not applicable. /ship smoke-tests the CI start "
                                    "command locally instead (commands.json `start`).")
    result["checklist"] = checklist(root, rid, part_a_ok, not dockerfile, result["part_a"].get("status"),
                                    changes)
    result["status"] = status_of(result["part_a"]["checks"], result["checklist"])
    result["pass"] = result["status"] in ("pass", "pass_with_skips")
    if run:
        C.write_json(os.path.join(run, "07-shipcheck.json"), result)
    if interrupted:
        raise KeyboardInterrupt()
    return result
