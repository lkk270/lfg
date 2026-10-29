# Guard: read or write

The guard judges a command to an outside system by what it does, never by its first word. The classifier is
`plugin/lib/lfgcore/outside.py`; `guard.py` calls it for every simple command it finds.

| Verdict | Meaning | What the guard does |
|---|---|---|
| read | Only looks: `gcloud run services list`, `kubectl get pods`, `select ...`, `gh api` with GET | Always allowed, on every environment including prod, no prompt |
| write | Changes something live, or cannot be classified | Blocked: rule 15 (deploys and infrastructure), rule 11 (SQL), rule 2 (`gh`) |
| secret | Reads a secret value: `gcloud secrets versions access`, `print-access-token`, `get-secret-value`, `kubectl get secret` | Blocked: rule 5. Secrets are never read |

## Rules of the model

- **Unknown is a write.** A verb the classifier does not know, a flag it cannot place or SQL it cannot see all block.
- **Any write makes the whole command a write.** The guard checks every piece: `&&`, `;`, pipes, `xargs`, `find -exec`,
  `$(...)`, backticks, `bash -c`, `eval`, heredocs and `for`/`while` bodies.
- **Impersonation flags change nothing.** `--impersonate-service-account` is ignored when deciding read or write.
- **SQL is judged by its statements.** Comments and string contents are ignored. One write among several statements,
  or a write hidden in a CTE (`WITH ... UPDATE ... RETURNING ... SELECT`), makes it a write. A `SELECT` that
  changes things also counts: `INTO`, `FOR UPDATE`, `nextval`, `pg_terminate_backend`, `\gexec`. SQL arrives from `-c`,
  `-f`, `<`, a heredoc, a here-string or an `echo` pipe. SQL it cannot see (`cat x.sql | psql`) is a write.
- **`gh api`** is a read only when it is a GET with no `-f`, `-F` or `--input` and no GraphQL mutation.
- **Local files** a read writes to (`> out.txt`) are not an outside write.
- **Supabase local development** (`supabase start`, `stop`, `init`, `db reset`, `migration up` without `--linked` or
  `--db-url`) is allowed. It is your machine.

Covered systems: gcloud, gsutil, bq, aws, az, kubectl, supabase, psql, mysql, clickhouse-client, `gh`, and the
Supabase and ClickHouse MCP tools. Git and GitHub actions keep their own Allow / Ask / Block rows (Preferences).

## Add a new system

1. In `outside.py`, write `_<tool>(argv)` returning `(READ | WRITE | SECRET, why)`. Use `_positionals(argv, value_flags)`
   to get the command words. Return READ only for verbs you listed; end with `return WRITE, ...`.
2. List its secret-printing commands and return SECRET for them before any read check.
3. Add the tool name to `CLIS` and a branch in `classify()`.
4. Remove it from `DEPLOY` in `guard.py` if it is listed there.
5. Add tests to `tests/test_outside.py`: one read, one write, one write piped from a read, one secret read. Add a
   line each to `SELFTEST` in `guard.py`.
6. Run `python3 -m unittest discover -s tests` and `plugin/bin/lfg doctor --selftest`.

A tool the guard does not know yet is not blocked by this model; only the old `DEPLOY` list applies to it.
