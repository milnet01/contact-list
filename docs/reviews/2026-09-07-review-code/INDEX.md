# Review sweep, 2026-09-07 — lane reports

Nine cold-review lanes over the whole tree, plus a `check-code` static pass and
a `verify-delivery` run against a live and a frozen build. These are the lanes'
own returns, kept because the roadmap bullets they produced are summaries and
several open items point back at detail that exists only here.

**These are records.** Nothing is built from them and nobody conforms to them;
they are evidence of what was checked on one day, not a contract. A finding here
that has since been fixed is not edited — read the roadmap for current status.

## Lanes

| File | Subject | C/H/M |
|---|---|---|
| `01-data-layer.md` | `models.py`, `db.py`, `migrations/` | 0/0/6 |
| `02-routes-contacts.md` | `routes/contacts.py`, `routes/merge.py` | 0/0/6 |
| `03-routes-io.md` | import/export, sync and settings routes, `importer.py`, `vcard.py` | 0/4/8 |
| `04-app-core.md` | `app.py`, `config.py`, `settings.py`, `phoneutil.py` | 0/1/6 |
| `05-google-sync.md` | `google_sync.py`, `google_auth.py`, `photos.py` | 0/5/9 |
| `06-process-lifecycle.md` | `launcher.py`, `tray.py`, `browser.py`, `server_control.py` | 1/2/3 |
| `07-frontend-js.md` | `static/app.js` | 0/3/5 |
| `08-templates.md` | `templates/` | 0/1/6 |
| `09-shell-ci.md` | `run.sh`, `local-ci.sh`, `packaging/`, workflows, `.githooks/` | 0/4/7 |

Not reviewed, deliberately: `tests/` (that is `review-tests`' subject) and
`static/style.css` (no bug, contract or security surface).

## Where each lane's findings went

Fixed and shipped this session: the Critical and every High. See `CHANGELOG.md`
`[Unreleased]` and the ✅ bullets — CL-0048, CL-0058, CL-0044, CL-0071, CL-0072,
CL-0080.

Everything else was filed by subject rather than one bullet per finding, because
a hundred and fifty bullets would make the roadmap unusable:

- **CL-0063** AppImage restart · **CL-0064** clearing a field vs Google
- **CL-0065** output-encoding rule · **CL-0066** contact-list scan
- **CL-0067** buffered exports · **CL-0068** unbounded input *(partly done)*
- **CL-0069** secret key and config dir *(partly done)* · **CL-0070** sync robustness
- **CL-0073** dialog semantics · **CL-0074** stale route table
- **CL-0075** vCard fidelity · **CL-0076** mypy coverage *(partly done)*
- **CL-0077** untooled languages · **CL-0078** shell/CI failure paths
- **CL-0079** the Low tail · **CL-0081** config-dir isolation trap

## Findings dismissed as false positives — recorded here because the ledger is not committed

`audit_dismiss` writes `.audit_cache/learned-fp.jsonl`, which `.gitignore`
excludes. So the triage below lives only on the machine that ran it, and a fresh
clone's next sweep will re-report all of it. Kept here so the reasoning survives:

- **bandit B608 / ruff S608 ×5, `models.py`** — every f-string SQL site composes
  literal fragments only. `id_filter` is a fixed literal chosen by a branch,
  `placeholders` is `?` repeated, `order_col` comes from the `allowed_sorts`
  whitelist, and `_build_contact_query` binds every user value. No user data
  reaches SQL text.
- **bandit B310 / semgrep dynamic-urllib, `google_sync.py`** — `_fetch_photo_bytes`
  is reached only from `_store_person_photo`, which rejects any non-https or
  non-`*.googleusercontent.com` URL first. *(The guard does not survive a
  redirect — that half is real and is CL-0070.)*
- **semgrep insecure-file-permissions ×2** — flags `0o700` as "widely
  permissive". It is owner-only, the most restrictive useful directory mode, and
  applied deliberately to the credential directory.
- **semgrep dangerous-subprocess-use-tainted-env-args, `server_control.py`** —
  fixed argv of `sys.executable` plus the process's own path; what the rule reads
  as tainted is `env=os.environ`.
- **sqlfluff PRS ×2, `migrations/`** — its sqlite dialect cannot parse
  `CREATE INDEX IF NOT EXISTS`, which SQLite accepts and `db.py` relies on for
  idempotent migrations. Tool limitation.
- **ruff S101 ×683** — pytest's `assert` idiom. *(Two in `models.py` are
  production asserts and are real; they are in CL-0079.)*
- **vulture ×54** — Flask route handlers and config class attributes, all reached
  by decorator or by Flask itself.
- **typos: `gir` ×27, `datas` ×23** — GTK introspection package names
  (`gir1.2-*`) and PyInstaller's own `datas=` parameter. Domain vocabulary.

## Tool coverage gaps this sweep exposed

Reported as gaps in the static-analysis tool set rather than as review wins:
no JavaScript tooling at all (no `package.json`, so `static/app.js` is analysed
by nothing), no template- or HTML-aware tool, `packaging/contact-list.spec`
recognised by neither ruff nor mypy, and a ruff `select` too narrow to reach
`BLE001`, `PLW1514`, `PTH` or `ANN`. Tracked as **CL-0077**; the ruff half is
**CL-0062**.
