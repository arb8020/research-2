# Journals: `mimir breadcrumb` and `mimir papercut`

Two append-only journals a working agent writes into as it goes:

- **`mimir breadcrumb -a "<name>" "<msg>"`** — significant decisions and events, appended to `BREADCRUMBS.md`.
- **`mimir papercut -m "<model>" "<msg>"`** — small frictions and uncertainties, appended to `PAPERCUTS.md`.

Both resolve their file relative to the git repo root (falling back to the cwd), overridable with `-f/--file`.

## Both are off by default

A fresh repo gets no journal files until someone opts in. With the command disabled, **every** subcommand path is gated — `--list`, `--path`, `--view` included — and exits non-zero with a one-line message naming the exact edit to make:

```
$ mimir breadcrumb -a bob "hi"
error: mimir breadcrumb is disabled — add `breadcrumb = true` under [tool.mimir] in /path/to/repo/pyproject.toml (or set MIMIR_BREADCRUMB=1 for this session)
$ echo $?
1
```

### Enabling per repo

Add the keys to the target repo's `pyproject.toml`. This is the same `[tool.mimir]` table `mimir audit` reads.

```toml
[tool.mimir]
breadcrumb = true
papercut = true
```

The two toggles are independent — enabling one leaves the other off.

### Enabling per session

`MIMIR_BREADCRUMB=1` / `MIMIR_PAPERCUT=1` turns a command on without editing any file:

```bash
MIMIR_BREADCRUMB=1 mimir breadcrumb -a scout "found it"
```

**Env wins over pyproject**, in both directions — `MIMIR_BREADCRUMB=0` turns the command off even where `breadcrumb = true` is configured. Accepted truthy values: `1`, `true`, `yes`, `on` (case-insensitive); anything else is false. An unset or empty variable defers to pyproject.

## Where the code lives

`mimir/journal.py` holds the shared implementation (git helpers, path resolution, append, list, and the gate), parameterized by a `JournalSpec`. `mimir/breadcrumb.py` and `mimir/papercut.py` are thin wrappers over it that bind a spec and keep their existing public API; `breadcrumb.py` additionally owns the `--view` HTTP viewer. `mimir/config.py` is the one reader for `[tool.mimir]`, shared with `mimir/audit.py`.

To add a third journal: define a `JournalSpec` in `journal.py`, add a wrapper module, and wire a subparser in `cli.py`.

## Proving it works

```bash
bash tests/manual/demo_journal_toggle.sh   # runnable end-to-end walkthrough
python -m pytest tests/test_journal_toggle.py -q
```
