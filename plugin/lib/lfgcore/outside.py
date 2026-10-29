"""Read or write? The guard's classifier for commands that talk to outside systems (GCP, AWS, Azure, Kubernetes,
Supabase, SQL clients). A command is judged by what it does, never by its first word:

  read    only looks: always allowed, in every environment, prod included.
  write   changes something live, or could not be classified: blocked.
  secret  reads a secret value (a token, a key, a password): blocked, because secrets are never read.

Anything not recognized as a read is a write: this module fails toward blocking. docs/guard-read-write.md says how to
add a system. Pure functions, no I/O except through the `read_file` callable the guard passes in.
"""
import os
import re

READ, WRITE, SECRET = "read", "write", "secret"

# ------------------------------------------------------------------ SQL

READ_FIRST = {"select", "show", "explain", "describe", "desc", "values", "table", "with", "set", "reset", "use",
              "begin", "start", "commit", "rollback", "end", "abort", "exists", "check"}
# a word anywhere in a statement that makes it a write (a CTE can hide an UPDATE behind a trailing SELECT)
WRITE_ANYWHERE = {"insert", "update", "delete", "merge", "create", "drop", "alter", "truncate", "grant", "revoke",
                  "into", "copy", "optimize", "attach", "detach", "rename", "upsert", "undrop", "exchange"}
FUNCTION_FORM = {"insert", "truncate"}  # insert(...) and truncate(...) are plain functions
# statements that are only writes as the first word (`system.tables` and `replace(x)` are names), except after EXPLAIN
STATEMENT_ONLY = {"system", "kill", "call", "execute", "refresh", "replace", "lock", "vacuum", "reindex", "do"}
SIDE_EFFECT_FN = re.compile(r"\b(pg_terminate_backend|pg_cancel_backend|set_config|nextval|setval|pg_advisory\w*|"
                            r"lo_(import|export|unlink|create)|dblink\w*|pg_reload_conf|pg_rotate_logfile|"
                            r"pg_read_file|pg_read_binary_file|pg_ls_dir|pg_switch_wal|pg_create_\w+|pg_drop_\w+|"
                            r"pg_notify|pg_promote|pg_replication_\w+|txid_\w+)\b", re.I)
PSQL_READ_META = re.compile(r"^\\(d\w*|l\+?|conninfo|x|timing|pset|a|t|H|echo|qecho|q|c|connect|set|unset|encoding|"
                            r"\?|h|s|sf|sv|z|T)$", re.I)


def _strip_sql(text):
    """The statement text with comments, string literals, quoted identifiers and dollar-quoted bodies blanked, so a
    keyword inside a string never counts. Raises ValueError when a quote never closes (then it is a write)."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if text.startswith("--", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            if j < 0:
                raise ValueError("unterminated comment")
            i = j + 2
        elif c in ("'", '"', "`"):
            j = i + 1
            while True:
                j = text.find(c, j)
                if j < 0:
                    raise ValueError("unterminated quote")
                if text.startswith(c * 2, j):  # a doubled quote is an escape
                    j += 2
                elif c == "'" and text[j - 1] == "\\":  # ClickHouse and MySQL also accept \'
                    j += 1
                else:
                    break
            out.append(" " + c + c + " ")
            i = j + 1
        elif c == "$" and re.match(r"\$([A-Za-z_]\w*)?\$", text[i:]):
            tag = re.match(r"\$([A-Za-z_]\w*)?\$", text[i:]).group(0)
            j = text.find(tag, i + len(tag))
            if j < 0:
                raise ValueError("unterminated dollar quote")
            out.append(" $$ ")
            i = j + len(tag)
        else:
            out.append(c)
            i += 1
    return "".join(out)


def sql_kind(text):
    """(READ|WRITE, why) for SQL text that may hold several statements. One write makes the whole text a write."""
    if text is None:
        return WRITE, "the SQL could not be read"
    try:
        clean = _strip_sql(text)
    except ValueError as e:
        return WRITE, "the SQL is malformed (%s)" % e
    # psql backslash commands: a line that starts with one is all command; one inside a line (`select 1 \gexec`)
    # runs from there. Only the display and connection ones are reads (`\copy`, `\gexec`, `\!`, `\i` are not).
    kept = []
    for line in clean.split("\n"):
        if line.lstrip().startswith("\\"):
            metas = re.findall(r"\\[^\s\\]*", line)
            line = ""
        else:
            metas = re.findall(r"\\[^\s\\]+", line)
            line = re.sub(r"\\[^\s\\]+.*$", "", line)
        for m in metas:
            if not PSQL_READ_META.match(m):
                return WRITE, "the psql command %s is not a read" % m
        kept.append(line)
    for raw in "\n".join(kept).split(";"):
        stmt = raw.strip()
        if not stmt:
            continue
        words = re.findall(r"[A-Za-z_]\w*", stmt.lower())
        first = words[0]
        if first not in READ_FIRST:
            return WRITE, "`%s` statements change data or schema" % first
        if first == "explain" and STATEMENT_ONLY & set(words[1:4]):
            return WRITE, "EXPLAIN of a statement that changes data"
        for m in re.finditer(r"[A-Za-z_]\w*", stmt.lower()):
            w = m.group(0)
            if w in WRITE_ANYWHERE and not (w in FUNCTION_FORM and re.match(r"\s*\(", stmt[m.end():])):
                return WRITE, "`%s` inside the statement changes data" % w.upper()
        fn = SIDE_EFFECT_FN.search(stmt)
        if fn:
            return WRITE, "the statement calls a function with side effects (%s)" % fn.group(0)
    return READ, "only SELECT-style statements"


def _flag_values(argv, short, long_):
    """Values of repeated flags like `-c SQL`, `-cSQL`, `--command SQL`, `--command=SQL`."""
    out, i = [], 1
    while i < len(argv):
        a = argv[i]
        if a in short or a in long_:
            if i + 1 < len(argv):
                out.append(argv[i + 1])
            i += 2
            continue
        for s in short:
            if len(s) == 2 and a.startswith(s) and len(a) > 2 and not a.startswith("--"):
                out.append(a[2:])
        for l in long_:
            if a.startswith(l + "="):
                out.append(a.split("=", 1)[1])
        i += 1
    return out


SQL_SOURCES = {  # client -> (inline short flags, inline long flags, file short flags, file long flags)
    "psql": (("-c",), ("--command",), ("-f",), ("--file",)),
    "mysql": (("-e",), ("--execute",), (), ()),
    "clickhouse-client": (("-q",), ("--query",), (), ("--queries-file",)),
}
SQL_CLIENTS = set(SQL_SOURCES) | {"clickhouse"}


LOCAL_HOST = re.compile(r"^(localhost|127(\.\d+){3}|\[?::1\]?|0\.0\.0\.0|[a-z0-9.-]+\.localhost|"
                        r"host\.docker\.internal|/.*)$", re.I)


def local_target(base, argv, envs=()):
    """True when a SQL client is pointed at your own machine (localhost, a socket path), so its writes are fine.
    No host given is not local: the host may come from PGHOST or a service file, so that stays a normal check."""
    if any(e.split("=", 1)[0] in ("PGHOST", "PGSERVICE", "PGHOSTADDR") for e in envs):
        return False
    hosts, i = [], 1
    while i < len(argv):
        a = argv[i]
        if a in ("-h", "--host") and i + 1 < len(argv):
            hosts.append(argv[i + 1])
            i += 1
        elif a.startswith("--host="):
            hosts.append(a.split("=", 1)[1])
        elif a.startswith("-h") and len(a) > 2 and not a.startswith("--"):
            hosts.append(a[2:])
        else:
            m = re.match(r"^[a-z]+(?:ql)?://(?:[^@/]*@)?(\[[^\]]+\]|[^:/?]+)", a, re.I)
            if m:
                hosts.append(m.group(1))
            hosts += re.findall(r"\bhost=([^\s]+)", a)
            if re.search(r"\bservice=", a):
                return False
        i += 1
    return bool(hosts) and all(LOCAL_HOST.match(h) for h in hosts)


def sql_client(base, argv, stdin, read_file, envs=()):
    """A psql / mysql / clickhouse-client command. stdin: the SQL text it is fed (a here-string or `echo` pipe), or
    None when unknown. Every statement the command will run must be a read, unless it targets your own machine."""
    if local_target(base, argv, envs):
        return READ, "your own machine (localhost); writes there are fine"
    if base == "clickhouse":
        if argv[1:2] not in (["client"],):
            return WRITE, "`clickhouse %s` is not a plain read" % " ".join(argv[1:2])
        argv = ["clickhouse-client"] + argv[2:]
        base = "clickhouse-client"
    inline_s, inline_l, file_s, file_l = SQL_SOURCES[base]
    if any(a in ("--version", "-V", "--help", "-?") for a in argv[1:]) or (base == "psql" and any(
            a in ("-l", "--list") for a in argv[1:]) and not _flag_values(argv, inline_s, inline_l)):
        return READ, "lists or prints help"
    texts = _flag_values(argv, inline_s, inline_l)
    for path in _flag_values(argv, file_s, file_l):
        body = read_file(path)
        if body is None:
            return WRITE, "the SQL file %s could not be read, so its statements are unknown" % path
        texts.append(body)
    if stdin is not None:
        texts.append(stdin)
    if not texts:
        return WRITE, "the SQL it will run is not visible (piped or interactive); pass it with -c or a file"
    for t in texts:
        kind, why = sql_kind(t)
        if kind != READ:
            return kind, why
    return READ, "only SELECT-style statements"


# ------------------------------------------------------------------ cloud CLIs

def _positionals(argv, value_flags):
    """Words that are not flags, not the value of a known flag, and before a bare `--`."""
    out, i = [], 1
    while i < len(argv):
        a = argv[i]
        if a == "--":
            break
        if a.startswith("-") and len(a) > 1:
            if "=" not in a and a in value_flags:
                i += 1
        else:
            out.append(a)
        i += 1
    return out


def _has_help(argv):
    return any(a in ("--help", "-h", "help") for a in argv[1:]) and not any(
        a for a in argv[1:] if a == "--")


# ---- gcloud
GCLOUD_VALUE_FLAGS = {"--project", "--region", "--zone", "--format", "--filter", "--impersonate-service-account",
                      "--account", "--limit", "--sort-by", "--configuration", "--location", "--billing-project",
                      "--page-size", "--flatten", "--verbosity", "--cluster", "--namespace", "--organization",
                      "--folder", "--service-account", "--log-http", "--trace-token"}
GCLOUD_READ_VERB = re.compile(r"^(list|describe|get-iam-policy|get-value|get|read|tail|search|lookup|explain|"
                              r"test-iam-permissions|get-serial-port-output|get-health|get-effective-\w+|"
                              r"get-nat-\w+|get-guest-attributes|get-status|get-config|list-\w+|show|info|version|"
                              r"check-\w+|diagnose)$")
GCLOUD_NOT_READ = {"get-credentials", "get-auth-string", "get-ssh-key", "get-login-profile"}
GCLOUD_WRITE_WORD = re.compile(
    r"^(create|delete|update|add|remove|set|enable|disable|deploy|apply|import|export|submit|start|stop|resume|"
    r"suspend|restart|reset|resize|attach|detach|move|rename|patch|replace|rollback|promote|migrate|failover|upgrade|"
    r"rotate|revoke|grant|undelete|restore|cancel|abort|terminate|invoke|call|trigger|execute|ssh|scp|connect|tunnel|"
    r"login|logout|activate|configure|install|uninstall|bind|unbind|insert|publish|push|clone|copy|cp|mv|rm|sync|"
    r"rsync|write|upload|sign|encrypt|reimage|run|repair|clear|flush|purge|truncate|snapshot|pause|"
    r"increment|swap|join|leave|accept|reject|approve|deny|drain|cordon|uncordon|taint|label|tag|untag|"
    r"start-iap-tunnel|get-credentials)(-[\w-]+)?$")
GCLOUD_SECRET_VERB = {"print-access-token", "print-identity-token", "config-helper", "get-auth-string",
                      "generate-login-token", "decrypt", "print-refresh-token", "get-iam-token"}


def _gcloud(argv):
    if _has_help(argv):
        return READ, "help text"
    pos = [p for p in _positionals(argv, GCLOUD_VALUE_FLAGS) if p not in ("alpha", "beta", "preview")]
    if not pos:
        return READ, "no command (version or help)"
    path = " ".join(pos)
    if any(p in GCLOUD_SECRET_VERB for p in pos) or re.search(r"\bsecrets versions access\b", path):
        return SECRET, "prints a secret value or credential"
    if pos[0] in ("help", "version", "info", "topic", "feedback", "cheat-sheet"):
        return READ, "help or version"
    for i, p in enumerate(pos):
        if p in GCLOUD_NOT_READ or (GCLOUD_WRITE_WORD.match(p) and not (i == 0 and p == "run")):  # `run` first is Cloud Run
            return WRITE, "`%s` changes live infrastructure" % p
    for i, p in enumerate(pos):
        if GCLOUD_READ_VERB.match(p) and i >= 1 and len(pos) - i - 1 <= 2:
            return READ, "`%s` only reads" % p
    return WRITE, "`gcloud %s` is not a known read" % path


# ---- gsutil, bq
def _gsutil(argv):
    pos = _positionals(argv, {"-o", "-h", "-i", "-u"})
    if any(p == "signurl" for p in pos):
        return SECRET, "creates a signed URL (a credential)"
    if pos and pos[0] in ("ls", "cat", "stat", "du", "hash", "version", "help", "ver"):
        return READ, "`gsutil %s` only reads" % pos[0]
    return WRITE, "`gsutil %s` is not a known read" % (pos[0] if pos else "")


def _bq(argv, stdin, read_file):
    pos = _positionals(argv, {"--project_id", "--location", "--format", "--max_rows", "--api", "--dataset_id",
                              "--job_id", "--api_version", "--bigquery_discovery_api_key"})
    if not pos:
        return READ, "help or version"
    if pos[0] in ("ls", "show", "head", "version", "info", "help", "wait", "ver"):
        return READ, "`bq %s` only reads" % pos[0]
    if pos[0] == "query":
        if any(a.startswith(("--destination_table", "--replace", "--append_table", "--schedule", "--target_dataset"))
               for a in argv):
            return WRITE, "`bq query` writes its result to a table"
        return sql_kind(" ".join(pos[1:]))
    return WRITE, "`bq %s` is not a known read" % pos[0]


# ---- aws
AWS_VALUE_FLAGS = {"--profile", "--region", "--output", "--endpoint-url", "--query", "--color", "--ca-bundle",
                   "--cli-read-timeout", "--cli-connect-timeout", "--cli-binary-format", "--cli-auto-prompt"}
AWS_READ_OP = re.compile(r"^(describe|list|get|head|batch-get|lookup|search|query|scan|filter-log-events|tail|wait|"
                         r"simulate|validate|estimate|check|detect|preview|select-object-content|ls)(-[\w-]+)?$")
AWS_SECRET_OP = re.compile(r"^(get-secret-value|batch-get-secret-value|get-session-token|get-federation-token|"
                           r"assume-role\w*|get-login-password|get-authorization-token|get-token|"
                           r"generate-db-auth-token|export-credentials|get-role-credentials|decrypt|"
                           r"get-credentials-for-identity|presign|get-login|get-parameter-secret\w*)$")


def _aws(argv):
    pos = _positionals(argv, AWS_VALUE_FLAGS)
    if _has_help(argv) or not pos or pos[0] in ("help",):
        return READ, "help text"
    service, op = pos[0], (pos[1] if len(pos) > 1 else "")
    if AWS_SECRET_OP.match(op) or (service, op) == ("configure", "get") or (
            service == "configure" and op == "export-credentials"):
        return SECRET, "returns a secret value or credential"
    if re.match(r"^get-parameter", op) and "--with-decryption" in argv:
        return SECRET, "decrypts a stored secret"
    if service == "configure":
        return (READ, "lists configuration") if op in ("list", "list-profiles") else (WRITE, "changes AWS config")
    if service == "s3":
        return (READ, "`aws s3 ls` only reads") if op == "ls" else (WRITE, "`aws s3 %s` changes objects" % op)
    if service == "sts" and op == "get-caller-identity":
        return READ, "shows who you are"
    if AWS_READ_OP.match(op):
        return READ, "`%s` only reads" % op
    return WRITE, "`aws %s %s` is not a known read" % (service, op)


# ---- az
AZ_VALUE_FLAGS = {"--subscription", "--resource-group", "-g", "--name", "-n", "--output", "-o", "--query",
                  "--location", "-l", "--only-show-errors", "--tenant"}
AZ_READ_VERB = re.compile(r"^(show|list|list-\w+|get-\w+|exists|find|search|query|version|check-\w+|"
                          r"show-\w+|download-\w+)$")
AZ_SECRET = re.compile(r"(\bget-access-token\b|list-keys|list-credentials|list-publishing-\w+|show-connection-string|"
                       r"show-publish-profile|\bkeyvault secret (show|download)\b|\bkeys list\b|\bcredential show\b|"
                       r"\bappsettings list\b|\bconnection-string list\b|\bsecret (show|list)\b|\bcertificate download\b|"
                       r"\bkeyvault key download\b|--expose-token|--show-values|list-sas|generate-sas|\bsas\b)")


AZ_WRITE_WORD = re.compile(r"^(create|delete|update|set|add|remove|start|stop|restart|deploy|import|upload|"
                           r"login|logout|invoke|swap|scale|purge|reset|regenerate-\w+|assign|revoke|grant)(-[\w-]+)?$")


def _az(argv):
    if _has_help(argv) or "--version" in argv:
        return READ, "help or version"
    pos = _positionals(argv, AZ_VALUE_FLAGS)
    path = " ".join(pos) + " " + " ".join(a for a in argv[1:] if a in ("--expose-token", "--show-values"))
    if AZ_SECRET.search(path):
        return SECRET, "returns a secret value or credential"
    if pos[:1] == ["rest"]:
        method = None
        for i, a in enumerate(argv):
            if a in ("--method", "-m") and i + 1 < len(argv):
                method = argv[i + 1].upper()
        if method in (None, "GET") and not any(a in ("--body", "-b") for a in argv):
            return READ, "`az rest` GET"
        return WRITE, "`az rest` with a body or non-GET method"
    if pos and AZ_READ_VERB.match(pos[-1]) and not any(AZ_WRITE_WORD.match(p) for p in pos):
        return READ, "`%s` only reads" % pos[-1]
    return WRITE, "`az %s` is not a known read" % " ".join(pos)


# ---- kubectl
KUBECTL_VALUE_FLAGS = {"-n", "--namespace", "--context", "--cluster", "--user", "--kubeconfig", "--as",
                       "--as-group", "-s", "--server", "-l", "--selector", "-o", "--output", "--field-selector",
                       "-c", "--container", "--tail", "--since", "-f", "--filename"}
KUBECTL_READ = {"get", "describe", "logs", "top", "explain", "api-resources", "api-versions", "version",
                "cluster-info", "events", "diff", "wait"}
SECRET_KIND = re.compile(r"(^|,)secrets?(\.|/|,|$)", re.I)


def _kubectl(argv):
    if _has_help(argv):
        return READ, "help text"
    pos = _positionals(argv, KUBECTL_VALUE_FLAGS)
    if any(a in ("--token", "--password") or a.startswith(("--token=", "--password=")) for a in argv):
        return SECRET, "puts a credential on the command line"
    if not pos:
        return READ, "no command"
    verb = pos[0]
    if verb in ("get", "describe") and any(SECRET_KIND.search(p) for p in pos[1:]):
        return SECRET, "shows Kubernetes secret values"
    if verb == "config":
        sub = pos[1] if len(pos) > 1 else ""
        if sub == "view" and any(a in ("--raw",) for a in argv):
            return SECRET, "`config view --raw` prints cluster credentials"
        if sub in ("view", "get-contexts", "current-context", "get-clusters", "get-users"):
            return READ, "reads kubeconfig"
        return WRITE, "`kubectl config %s` changes kubeconfig" % sub
    if verb == "auth" and pos[1:2] in (["can-i"], ["whoami"]):
        return READ, "checks permissions"
    if verb in KUBECTL_READ:
        return READ, "`kubectl %s` only reads" % verb
    return WRITE, "`kubectl %s` is not a known read" % verb


# ---- supabase
SUPABASE_VALUE_FLAGS = {"--project-ref", "--db-url", "-p", "--password", "--workdir", "--schema", "-s", "--file",
                        "-f", "--linked-project", "--output", "-o", "--experimental"}
SUPABASE_REMOTE = ("--linked", "--db-url", "--project-ref")


def _supabase(argv, read_file):
    if _has_help(argv) or "--version" in argv or "-v" in argv:
        return READ, "help or version"
    pos = _positionals(argv, SUPABASE_VALUE_FLAGS)
    path = " ".join(pos)
    remote = any(a in SUPABASE_REMOTE or a.startswith(tuple(r + "=" for r in SUPABASE_REMOTE)) for a in argv)
    if re.match(r"^projects api-keys\b", path) or re.match(r"^(secrets|vault)\b.*\b(get|reveal)\b", path):
        return SECRET, "returns project API keys or secret values"
    if pos[:2] == ["db", "query"] or pos[:1] == ["query"]:
        texts = [p for p in pos[2:]] + [read_file(f) if read_file(f) is not None else None
                                         for f in _flag_values(argv, ("-f",), ("--file",))]
        if not texts or any(t is None for t in texts):
            return WRITE, "the SQL it will run is not visible"
        return sql_kind(";".join(texts))
    if re.match(r"^(projects|orgs|branches|functions|migration|secrets|snippets|sso|domains|storage|services|"
                r"network-restrictions|network-bans|ssl-enforcement|postgres-config|vanity-subdomains|backups|"
                r"sso|inspect)\s+(list|get|show|download|fetch|ls|db\b.*|report)$", path) or re.match(
            r"^(status|gen types.*|inspect db.*|db (diff|lint|dump)|migration list|projects list|"
            r"orgs list|services|bootstrap)$", path):
        return READ, "only reads"
    if not remote and path in ("start", "stop", "init", "db reset", "migration up", "migration new",
                               "db start", "test db"):
        return READ, "local development database (no --linked or --db-url)"
    return WRITE, "`supabase %s` is not a known read" % path


# ------------------------------------------------------------------ entry point

CLIS = {"gcloud", "gsutil", "bq", "aws", "az", "kubectl", "supabase"} | SQL_CLIENTS


def classify(base, argv, stdin=None, read_file=lambda p: None, envs=()):
    """(READ|WRITE|SECRET, why) for one simple command, or None when `base` is not a covered outside system."""
    if base not in CLIS:
        return None
    if base == "gcloud":
        return _gcloud(argv)
    if base == "gsutil":
        return _gsutil(argv)
    if base == "bq":
        return _bq(argv, stdin, read_file)
    if base == "aws":
        return _aws(argv)
    if base == "az":
        return _az(argv)
    if base == "kubectl":
        return _kubectl(argv)
    if base == "supabase":
        return _supabase(argv, read_file)
    return sql_client(base, argv, stdin, read_file, envs)


# MCP tools of the systems above: the tool's own name says what it does.
MCP_SYSTEMS = re.compile(r"^mcp__(claude_ai_)?(supabase|clickhouse)__(?P<tool>.+)$")
MCP_READ = re.compile(r"^(list|get|search|describe|read|generate_typescript_types|run_select_query|"
                      r"run_postgres_select_query)\w*$")
MCP_SECRET = re.compile(r"(api_key|secret|credential|password|token)", re.I)


def classify_mcp(tool_name, tool_input):
    m = MCP_SYSTEMS.match(tool_name or "")
    if not m:
        return None
    tool = m.group("tool")
    if MCP_SECRET.search(tool) and not tool.startswith(("authenticate", "complete_authentication")):
        return SECRET, "returns a secret value"
    if tool in ("authenticate", "complete_authentication"):
        return READ, "signs in"
    if tool == "execute_sql":
        return sql_kind((tool_input or {}).get("query") or (tool_input or {}).get("sql"))
    if MCP_READ.match(tool):
        return READ, "only reads"
    return WRITE, "`%s` changes %s" % (tool, m.group(2))
