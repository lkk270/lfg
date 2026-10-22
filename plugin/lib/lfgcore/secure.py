"""`lfg secure`: local scanners + metadata-only online intelligence.

Only public metadata leaves the machine (ecosystem/name/version, public URL/domain, image tag, action ref),
only to the allowlisted hosts below, and only after the sanitizer approves it. Never code, paths or secrets.
Author: Varun Singh.
"""
import datetime
import hashlib
import ipaddress
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import common as C
from . import gate as GT
from . import guard
from .hooks import SECRET_OUTPUT_RX

INTEL_HOSTS = {"api.osv.dev", "registry.npmjs.org", "pypi.org", "proxy.golang.org", "crates.io", "rubygems.org",
               "api.deps.dev", "www.cisa.gov", "api.first.org", "endoflife.date", "rdap.org", "urlhaus-api.abuse.ch",
               "api.securityscorecards.dev"}
POPULAR = {
    "npm": "react react-dom vue angular express lodash axios moment chalk commander debug request next typescript "
           "webpack babel-core eslint prettier jest mocha dotenv uuid yargs async bluebird underscore jquery "
           "body-parser cors mongoose redis pg mysql2 sequelize socket.io ws node-fetch cross-env rimraf glob "
           "minimist semver classnames prop-types tslib rxjs zod vite esbuild tailwindcss",
    "PyPI": "requests numpy pandas django flask fastapi pydantic sqlalchemy boto3 urllib3 setuptools pip six "
            "python-dateutil pyyaml jinja2 click pytest scipy matplotlib pillow cryptography certifi idna "
            "charset-normalizer attrs packaging httpx uvicorn celery redis psycopg2 torch tensorflow "
            "scikit-learn openai anthropic langchain transformers beautifulsoup4 lxml colorama",
}


# ---------------------------------------------------------------- sanitizer + http

def _private_host(host):
    host = (host or "").lower().strip("[]")
    if not host or host == "localhost" or host.endswith((".local", ".internal", ".localhost", ".test", ".lan",
                                                         ".corp", ".home.arpa")):
        return True
    for d in C.config().get("secure", {}).get("company_domains", []):
        if host == d or host.endswith("." + d):
            return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
    except ValueError:
        return "." not in host


def sanitize(value):
    """Refuse anything that is not public metadata."""
    if not isinstance(value, str) or not value or len(value) > 300 or value.startswith(("/", ".", "~")):
        return False
    return not any(rx.search(value) for _k, rx in SECRET_OUTPUT_RX)


def _cache_get(key, ttl):
    p = C.lfg_path("secintel", "cache", hashlib.sha1(key.encode()).hexdigest() + ".json")
    d = C.read_json(p, None)
    if d and time.time() - d.get("t", 0) < ttl:
        return d["v"]
    return None


def _cache_put(key, val):
    C.write_json(C.lfg_path("secintel", "cache", hashlib.sha1(key.encode()).hexdigest() + ".json"),
                 {"t": time.time(), "v": val})


def http_json(url, body=None, ttl=86400):
    host = urllib.parse.urlsplit(url).hostname
    if host not in INTEL_HOSTS:
        raise ValueError("host not on the /secure allowlist: %s" % host)
    key = url + (json.dumps(body, sort_keys=True) if body is not None else "")
    hit = _cache_get(key, ttl)
    if hit is not None:
        return hit
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "lfg-secure/%s" % C.VERSION,
                                                          "Accept": "application/json",
                                                          **({"Content-Type": "application/json"} if data else {})})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            val = json.loads(r.read().decode("utf-8", "replace") or "null")
    except urllib.error.HTTPError as e:
        val = {"_http_error": e.code}
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {"_error": type(e).__name__}
    _cache_put(key, val)
    return val


# ---------------------------------------------------------------- inventory

PKG_LINE = {
    "package.json": re.compile(r'^\s*"(@?[a-z0-9][\w.\-/]*)"\s*:\s*"[\^~>=<]*\s*(\d[\w.\-+]*)"'),
    "requirements": re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*==\s*([\w.\-+]+)"),
    "pyproject.toml": re.compile(r'^\s*"([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*[=~><]=\s*([\w.\-+]+)'),
    "go.mod": re.compile(r"^\s*(?:require\s+)?([a-z0-9.\-]+\.[a-z]{2,}/[\w.\-/]+)\s+(v[\w.\-+]+)"),
    "Cargo.toml": re.compile(r'^\s*([a-z0-9_-]+)\s*=\s*(?:\{[^}]*version\s*=\s*)?"[\^~=]*([\d][\w.\-+]*)"'),
    "Gemfile": re.compile(r"""^\s*gem\s+['"]([\w\-]+)['"]\s*,\s*['"][~>=\s]*([\d][\w.]*)['"]"""),
}
ECO = {"package.json": "npm", "requirements": "PyPI", "pyproject.toml": "PyPI", "go.mod": "Go",
       "Cargo.toml": "crates.io", "Gemfile": "RubyGems"}
URL_RX = re.compile(r"""\bhttps?://[^\s'"<>`)\]}]+""")
USES_RX = re.compile(r"^\s*-?\s*uses:\s*['\"]?([\w.\-]+/[\w.\-/]+)@([\w.\-/]+)")
FROM_RX = re.compile(r"^\s*FROM\s+(?:--platform=\S+\s+)?([^\s]+)", re.I)
IMAGE_RX = re.compile(r"^\s*image:\s*['\"]?([^\s'\"]+)")


def _kind(path):
    b = os.path.basename(path or "")
    if b == "package.json":
        return "package.json"
    if b.startswith("requirements") and b.endswith(".txt"):
        return "requirements"
    if b in ("pyproject.toml", "go.mod", "Cargo.toml", "Gemfile"):
        return b
    return None


def inventory(root, mode):
    """New items from the diff (mode diff) or from every manifest/workflow/Dockerfile (mode all)."""
    if mode == "all":
        lines = []
        for f in GT._git(root, "ls-files", "-z").stdout.split("\0"):
            if f and not guard.is_secret_path(f) and (_kind(f) or f.startswith(".github/workflows/") or
                                                       "Dockerfile" in f or "compose" in os.path.basename(f) or
                                                       f.endswith((".py", ".js", ".ts", ".go", ".rb"))):
                try:
                    with open(os.path.join(root, f), errors="replace") as fh:
                        lines += [(f, ln.rstrip("\n")) for ln in fh]
                except OSError:
                    pass
    else:
        lines = GT.added_lines(GT.diff_text(root))
    inv = {"packages": {}, "urls": {}, "images": {}, "actions": {}, "pickles": set(), "write_all": []}
    for f, line in lines:
        k = _kind(f)
        if k:
            m = PKG_LINE[k].match(line)
            if m and m.group(1) not in ("name", "version", "description", "main", "type", "license", "python",
                                        "requires-python", "edition", "rust-version"):
                inv["packages"][(ECO[k], m.group(1), m.group(2))] = f
        if f and f.startswith(".github/workflows/"):
            m = USES_RX.match(line)
            if m and not m.group(1).startswith("./"):
                inv["actions"][(m.group(1), m.group(2))] = f
            if re.search(r"permissions:\s*write-all", line):
                inv["write_all"].append(f)
        if f and ("Dockerfile" in f):
            m = FROM_RX.match(line)
            if m and m.group(1).lower() != "scratch" and not re.match(r"^[a-z0-9_-]+$", m.group(1)):
                inv["images"][m.group(1)] = f
        if f and "compose" in os.path.basename(f):
            m = IMAGE_RX.match(line)
            if m and "${" not in m.group(1):
                inv["images"][m.group(1)] = f
        if f and f.endswith((".pkl", ".pickle", ".pt", ".pth", ".bin", ".joblib")):
            inv["pickles"].add(f)
        for u in URL_RX.findall(line):
            u = u.rstrip(".,;:")
            host = urllib.parse.urlsplit(u).hostname
            if host and not _private_host(host) and "${" not in u and "{{" not in u:
                inv["urls"].setdefault(u, f)
    if mode != "all":
        for f in GT.changed_files(root):
            if f.endswith((".pkl", ".pickle", ".pt", ".pth", ".joblib")):
                inv["pickles"].add(f)
    return inv


# ---------------------------------------------------------------- intel

def _lev(a, b):
    if abs(len(a) - len(b)) > 2:
        return 9
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _days_since(iso):
    try:
        d = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")[:25])
        if d.tzinfo is None:
            d = d.replace(tzinfo=datetime.timezone.utc)
        return (datetime.datetime.now(datetime.timezone.utc) - d).days
    except (ValueError, AttributeError):
        return None


def kev_ids():
    d = http_json("https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json")
    return {v.get("cveID") for v in (d or {}).get("vulnerabilities", [])} if isinstance(d, dict) else set()


def check_packages(pkgs, findings, offline, licences_checked):
    if not pkgs or offline:
        return
    items = [(e, n, v, f) for (e, n, v), f in pkgs.items() if sanitize(n) and not
             any(n.startswith(s) for s in C.config().get("secure", {}).get("private_scopes", []))]
    res = http_json("https://api.osv.dev/v1/querybatch",
                    {"queries": [{"package": {"ecosystem": e, "name": n}, "version": v} for e, n, v, _f in items]})
    kev, seen_ids = None, set()
    for (e, n, v, f), r in zip(items, (res or {}).get("results", []) if isinstance(res, dict) else []):
        for vuln in (r or {}).get("vulns", [])[:25]:
            vid = vuln.get("id", "")
            det = http_json("https://api.osv.dev/v1/vulns/" + urllib.parse.quote(vid), ttl=86400 * 3)
            aliases = (det or {}).get("aliases", []) if isinstance(det, dict) else []
            cves = [a for a in aliases + [vid] if a.startswith("CVE-")]
            sev = ((det or {}).get("database_specific") or {}).get("severity", "") if isinstance(det, dict) else ""
            if vid in seen_ids:
                continue
            seen_ids.update([vid] + aliases)
            fixed = sorted({ev.get("fixed") for a in (det or {}).get("affected", []) for rg in a.get("ranges", [])
                            if rg.get("type") != "GIT" for ev in rg.get("events", []) if ev.get("fixed")},
                           key=lambda x: [int(p) if p.isdigit() else 0 for p in re.split(r"[.\-+]", x)]) \
                if isinstance(det, dict) else []
            if kev is None and cves:
                kev = kev_ids()
            in_kev = bool(kev and set(cves) & kev)
            malware = vid.startswith("MAL-")
            sev = "critical" if malware or in_kev else {"moderate": "medium"}.get((sev or "unknown").lower(),
                                                                                 (sev or "unknown").lower())
            epss = None
            if cves:
                ep = http_json("https://api.first.org/data/v1/epss?cve=" + cves[0])
                if isinstance(ep, dict) and ep.get("data"):
                    epss = float(ep["data"][0].get("epss", 0))
            findings.append({"id": vid, "type": "malware" if malware else "vuln", "item": "%s %s@%s" % (e, n, v),
                             "where": f, "severity": sev, "kev": in_kev, "epss": epss,
                             "blocking": malware or in_kev or sev in ("critical", "high"),
                             "reachable": None, "evidence": ["https://osv.dev/vulnerability/" + vid] + cves[:3],
                             "fix": ("upgrade to %s" % fixed[-1]) if fixed else "no fixed version; replace or remove",
                             "source": "osv"})
        meta_age, scripts = None, False
        if e == "npm":
            m = http_json("https://registry.npmjs.org/" + urllib.parse.quote(n, safe="@"))
            if isinstance(m, dict) and "time" in m:
                meta_age = _days_since(m["time"].get(v, ""))
                sc = ((m.get("versions") or {}).get(v) or {}).get("scripts") or {}
                scripts = any(k in sc for k in ("preinstall", "install", "postinstall"))
        elif e == "PyPI":
            m = http_json("https://pypi.org/pypi/%s/%s/json" % (urllib.parse.quote(n), urllib.parse.quote(v)))
            if isinstance(m, dict) and m.get("urls"):
                meta_age = _days_since(m["urls"][0].get("upload_time_iso_8601", ""))
                scripts = not any(u.get("packagetype") == "bdist_wheel" for u in m["urls"])
        if meta_age is not None and meta_age < 14:
            findings.append({"id": "young-%s" % n, "type": "supply-chain", "item": "%s@%s" % (n, v), "where": f,
                             "severity": "high" if scripts else "medium", "blocking": scripts,
                             "evidence": ["published %d days ago%s" % (meta_age, ", runs install scripts" if scripts
                                                                        else "")],
                             "fix": "pin an older, established version", "source": "registry"})
        system = {"npm": "npm", "PyPI": "pypi", "Go": "go", "crates.io": "cargo", "RubyGems": "rubygems"}.get(e)
        if system:
            dv = http_json("https://api.deps.dev/v3/systems/%s/packages/%s/versions/%s" % (
                system, urllib.parse.quote(n, safe=""), urllib.parse.quote(v, safe="")), ttl=86400 * 7)
            lic = (dv or {}).get("licenses") if isinstance(dv, dict) else None
            if lic is not None:
                copyleft = [x for x in lic if re.search(r"\b(A?GPL|SSPL|EUPL|OSL|CC-BY-NC)", x or "")]
                licences_checked.append(n)
                if copyleft or not lic:
                    findings.append({"id": "license-%s" % n, "type": "license", "item": "%s@%s" % (n, v), "where": f,
                                     "severity": "high" if copyleft else "medium", "blocking": bool(copyleft),
                                     "evidence": ["licences: %s (deps.dev)" % (", ".join(lic) or "none declared")],
                                     "fix": "confirm licence compatibility or pick another package",
                                     "source": "deps.dev"})
        pop = POPULAR.get(e, "").split()
        base = n.split("/")[-1].lower()
        near = [p for p in pop if p != base and _lev(base, p) <= (1 if len(base) < 6 else 2)]
        if near and base not in pop:
            findings.append({"id": "typosquat-%s" % n, "type": "typosquat", "item": n, "where": f,
                             "severity": "critical",
                             "blocking": True, "evidence": ["1-2 edits from popular package %s" % ", ".join(near)],
                             "fix": "did you mean %s?" % near[0], "source": "lfg"})


def check_urls(urls, findings, offline):
    seen = set()
    for u, f in urls.items():
        p = urllib.parse.urlsplit(u)
        if p.scheme == "http":
            findings.append({"id": "http-%s" % p.hostname, "type": "url", "item": u, "where": f, "severity": "high",
                             "blocking": True, "evidence": ["plain HTTP to a non-local host"],
                             "fix": "use https://", "source": "lfg"})
        dom = ".".join((p.hostname or "").split(".")[-2:])
        if offline or not dom or dom in seen or not sanitize(dom):
            continue
        seen.add(dom)
        r = http_json("https://rdap.org/domain/" + dom, ttl=86400 * 7)
        if isinstance(r, dict):
            reg = [e.get("eventDate") for e in r.get("events", []) if e.get("eventAction") == "registration"]
            age = _days_since(reg[0]) if reg else None
            if age is not None and age < 30:
                findings.append({"id": "young-domain-%s" % dom, "type": "url", "item": dom, "where": f,
                                 "severity": "high", "blocking": True,
                                 "evidence": ["domain registered %d days ago (RDAP)" % age],
                                 "fix": "verify the domain owner or remove", "source": "rdap"})


EOL_PRODUCTS = {"node": "nodejs", "python": "python", "golang": "go", "ruby": "ruby", "php": "php",
                "ubuntu": "ubuntu", "debian": "debian", "alpine": "alpine", "postgres": "postgresql",
                "redis": "redis", "mysql": "mysql", "nginx": "nginx", "openjdk": "java", "eclipse-temurin": "java"}


def check_images(images, findings, offline):
    for img, f in images.items():
        name, _, tag = img.split("@")[0].rpartition(":") if ":" in img.split("@")[0].split("/")[-1] else (img, "", "")
        if "@sha256:" not in img and (not tag or tag == "latest"):
            findings.append({"id": "image-unpinned-%s" % img, "type": "image", "item": img, "where": f,
                             "severity": "medium", "blocking": False, "evidence": ["no tag or :latest, no digest"],
                             "fix": "pin a version tag and digest", "source": "lfg"})
        prod = EOL_PRODUCTS.get(name.split("/")[-1])
        m = re.match(r"^(\d+(?:\.\d+)?)", tag or "")
        if offline or not prod or not m:
            continue
        cycles = http_json("https://endoflife.date/api/%s.json" % prod, ttl=86400 * 7)
        if not isinstance(cycles, list):
            continue
        ver = m.group(1)
        for c in cycles:
            cyc = str(c.get("cycle", ""))
            if ver == cyc or ver.startswith(cyc + ".") or cyc.startswith(ver + "."):
                eol = c.get("eol")
                if eol is True or (isinstance(eol, str) and eol < datetime.date.today().isoformat()):
                    findings.append({"id": "eol-%s" % img, "type": "eol", "item": img, "where": f,
                                     "severity": "high", "blocking": True,
                                     "evidence": ["%s %s end of life %s (endoflife.date)" % (prod, cyc, eol)],
                                     "fix": "move to a supported %s release" % prod, "source": "endoflife"})
                break


def check_actions(actions, write_all, findings):
    for (repo, ref), f in actions.items():
        if not re.match(r"^[0-9a-f]{40}$", ref):
            findings.append({"id": "action-unpinned-%s" % repo, "type": "action", "item": "%s@%s" % (repo, ref),
                             "where": f, "severity": "high", "blocking": True,
                             "evidence": ["action pinned to a tag/branch, not a full commit SHA"],
                             "fix": "pin to the full 40-char commit SHA (keep the tag as a comment)", "source": "lfg"})
    for f in write_all:
        findings.append({"id": "write-all-%s" % f, "type": "action", "item": "permissions: write-all", "where": f,
                         "severity": "high", "blocking": True, "evidence": ["over-broad workflow token"],
                         "fix": "grant only the scopes each job needs", "source": "lfg"})


# ---------------------------------------------------------------- local scanners

def local_scanners(root, mode, inv, diff):
    out, findings = [], []
    sec = GT.secret_scan(root, diff if mode != "all" else GT.diff_text(root))
    out.append({"tool": "gitleaks", "exit": sec["exit"], "note": sec.get("note", "")})
    for line in [ln for ln in sec["tail"].splitlines() if ln]:
        findings.append({"id": "secret-%s" % hashlib.sha1(line.encode()).hexdigest()[:8], "type": "secret",
                         "item": line, "where": line.split(":")[0], "severity": "critical", "blocking": True,
                         "evidence": ["secret pattern (value not shown)"], "fix": "remove it and rotate the secret",
                         "source": "gitleaks"})
    files = [f for f in GT.changed_files(root) if os.path.isfile(os.path.join(root, f))] if mode != "all" else None
    if C.which("semgrep") and (files is None or files):
        cp = C.run(["semgrep", "scan", "--config", "p/default", "--metrics=off", "--json", "--quiet",
                    "--severity", "ERROR", "--severity", "WARNING"] + (files or [root]), cwd=root, timeout=900)
        try:
            for r in json.loads(cp.stdout or "{}").get("results", []):
                sev = r.get("extra", {}).get("severity", "WARNING")
                findings.append({"id": "semgrep-%s" % r.get("check_id", "").split(".")[-1], "type": "code",
                                 "item": r.get("check_id"),
                                 "where": "%s:%s" % (r.get("path"), r.get("start", {}).get("line")),
                                 "severity": "high" if sev == "ERROR" else "medium", "blocking": False,
                                 "reachable": None, "evidence": [r.get("extra", {}).get("message", "")[:300]],
                                 "fix": "see rule %s" % r.get("check_id"), "source": "semgrep"})
            out.append({"tool": "semgrep", "exit": cp.returncode})
        except ValueError:
            out.append({"tool": "semgrep", "exit": cp.returncode, "note": "unparsed output"})
    else:
        out.append({"tool": "semgrep", "exit": None, "note": "not installed" if not C.which("semgrep") else "no files"})
    if C.which("osv-scanner"):
        cp = C.run(["osv-scanner", "scan", "source", "-r", "--format", "json", root], cwd=root, timeout=900)
        n = 0
        try:
            for res in json.loads(cp.stdout or "{}").get("results", []):
                for p in res.get("packages", []):
                    for v in p.get("vulnerabilities", []):
                        n += 1
                        pk = p.get("package", {})
                        findings.append({"id": v.get("id"), "type": "vuln", "item": "%s %s@%s" % (
                            pk.get("ecosystem"), pk.get("name"), pk.get("version")),
                            "where": os.path.relpath(res.get("source", {}).get("path", root), root),
                            "severity": ((v.get("database_specific") or {}).get("severity") or "unknown").lower(),
                            "blocking": v.get("id", "").startswith("MAL-") or
                            ((v.get("database_specific") or {}).get("severity") or "").upper() in ("HIGH", "CRITICAL"),
                            "reachable": None, "evidence": ["https://osv.dev/vulnerability/" + v.get("id", "")],
                            "fix": "upgrade (see advisory)", "source": "osv-scanner"})
        except ValueError:
            pass
        out.append({"tool": "osv-scanner", "exit": cp.returncode, "findings": n})
    else:
        out.append({"tool": "osv-scanner", "exit": None, "note": "not installed"})
    if C.which("trivy"):
        cp = C.run(["trivy", "fs", "--quiet", "--scanners", "misconfig", "--severity", "HIGH,CRITICAL",
                    "--format", "json", "--skip-dirs", "node_modules",
                    "--skip-dirs", "graphify-out", "--skip-dirs", ".code-review-graph", root], cwd=root, timeout=900)
        try:
            for res in json.loads(cp.stdout or "{}").get("Results", []) or []:
                for m in res.get("Misconfigurations", []) or []:
                    findings.append({"id": m.get("ID"), "type": "misconfig", "item": m.get("Title"),
                                     "where": res.get("Target"), "severity": m.get("Severity", "").lower(),
                                     "blocking": m.get("Severity") == "CRITICAL", "evidence": [m.get("PrimaryURL", "")],
                                     "fix": (m.get("Resolution") or "")[:300], "source": "trivy"})
        except ValueError:
            pass
        out.append({"tool": "trivy fs (misconfig)", "exit": cp.returncode})
    else:
        out.append({"tool": "trivy", "exit": None, "note": "not installed"})
    ci = GT.ci_local(root, list_only=True)
    out += [{"tool": w["tool"], "exit": w["exit"], "note": w["tail"][-300:]} for w in ci["workflows_lint"]]
    for f in sorted(inv["pickles"]):
        if C.which("picklescan"):
            cp = C.run(["picklescan", "--path", os.path.join(root, f)], timeout=300)
            bad = cp.returncode != 0
        else:
            bad = True
        findings.append({"id": "pickle-%s" % f, "type": "model", "item": f, "where": f,
                         "severity": "high" if bad else "low", "blocking": bad,
                         "evidence": ["picklescan flagged it" if C.which("picklescan") else
                                      "pickle weights; picklescan not installed"],
                         "fix": "use safetensors from a verified source", "source": "picklescan"})
    return out, findings


# ---------------------------------------------------------------- entry

def secure(root, rid, target="diff", offline=False):
    mode = target if target in ("diff", "all") else "thing"
    findings, scanners = [], []
    if mode == "thing":
        inv = {"packages": {}, "urls": {}, "images": {}, "actions": {}, "pickles": set(), "write_all": []}
        t = target.strip()
        if t.startswith(("http://", "https://")):
            if _private_host(urllib.parse.urlsplit(t).hostname):
                C.die("refusing to look up a private/internal URL online; it stays local", 2)
            inv["urls"][t] = "(asked)"
        elif re.match(r"^[\w.\-]+/[\w.\-/]+@[\w.\-]+$", t) and t.count("/") >= 1 and not t.startswith("@"):
            repo, ref = t.rsplit("@", 1)
            inv["actions"][(repo, ref)] = "(asked)"
        elif "@" in t.lstrip("@"):
            name, ver = t.rsplit("@", 1)
            eco = "PyPI" if name.lower() in POPULAR["PyPI"].split() or name.startswith("py") else "npm"
            if ":" in name:
                eco, name = name.split(":", 1)
            inv["packages"][(eco, name, ver)] = "(asked)"
        else:
            inv["images"][t] = "(asked)"
        diff = ""
    else:
        inv = inventory(root, mode)
        diff = GT.diff_text(root) if mode == "diff" else ""
        scanners, local = local_scanners(root, mode, inv, diff)
        findings += local
    licences_checked = []
    check_packages(inv["packages"], findings, offline, licences_checked)
    check_urls(inv["urls"], findings, offline)
    check_images(inv["images"], findings, offline)
    check_actions(inv["actions"], inv["write_all"], findings)
    on_main = 0
    if mode == "diff":  # scanners read the whole repo: what sits in files this branch doesn't touch was there before
        mine = set(GT.branch_files(root))
        for f in findings:
            path = str(f.get("where") or "").split(":")[0]
            if path and path not in mine:
                f["on_main"] = True
                on_main += 1
    counted = [f for f in findings if not f.get("on_main")]
    blocking = [f for f in counted if f.get("blocking")]
    warns = [f for f in counted if not f.get("blocking") and f.get("severity") in ("high", "medium", "critical")]
    result = {"ts": C.now_iso(), "mode": mode, "target": target if mode == "thing" else mode,
              "inventory": {"packages": ["%s %s@%s" % k for k in inv["packages"]], "urls": sorted(inv["urls"]),
                            "images": sorted(inv["images"]), "actions": ["%s@%s" % k for k in inv["actions"]],
                            "model_files": sorted(inv["pickles"])},
              "scanners": scanners, "findings": findings,
              "verdict": "don't" if blocking else ("safe with caveats" if warns else "safe"),
              "blocking": len(blocking), "on_main": on_main, "offline": offline,
              "licences_checked": licences_checked}
    run = C.current_run(root)
    if run and mode != "thing":
        C.write_json(os.path.join(run, "05-secure.json"), result)
    return result
