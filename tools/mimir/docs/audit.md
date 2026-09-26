# `mimir audit`: a pass/fail gate for Python and TypeScript

```
mimir audit [TARGET] [--only a,b] [--fix] [--json] [--config TOML]
```

Exit 0 clean, 1 violations, 2 misconfigured (bad `[tool.mimir]`, unknown or disabled
`--only` name). The text report goes to stderr; `--json` also prints the same report
to stdout as `{"ok": bool, "checks": [{name, passed, details, violations, stats}]}`.

## Checks

| name | runs when | what |
|---|---|---|
| `ruff`, `ruff-format` | `python` in languages | `ruff check` / `ruff format --check` on `src` (`--fix` fixes) |
| `pyright` | python + a pyright config | `pyright` on `src` |
| `tsc` | `typescript` in languages + `tsconfigs` | `tsc --noEmit -p <tsconfig>` using the project's `node_modules/.bin/tsc` |
| `style`, `structure` | python | AST function length / void returns; nesting, cyclomatic, args |
| `directories` | always | no directory under a width root has more than `max_dir_entries` names |
| `boundaries` | always | files matching `src` import nothing under a `forbid` prefix |
| `layers` | `[[tool.mimir.layout.layers]]` | a layer imports only itself and earlier layers |
| `comments`, `docstrings` | `comments.enabled` | only tool directives and `EXTERNAL(...)` citations |
| `citations` | `comments.citations` | citation format; package versions match a lockfile; count per package |

The last five read code through ast-grep rules shipped in `mimir/audit/sg/` (Python,
TypeScript, TSX), so they work the same for both languages. Run the rules alone with
`ast-grep scan -c mimir/audit/sg/sgconfig.yml`; test them with
`ast-grep test -c mimir/audit/sg/sgconfig.yml`. mimir pins `ast-grep-cli`.

All listing-based checks see `git ls-files --cached --others --exclude-standard` (a
plain walk outside git), minus `data_trees`.

## Config

```toml
[tool.mimir]
languages = ["python", "typescript"]        # default ["python"]
tsconfigs = ["app/tsconfig.json"]           # enables tsc
boundaries = [{ src = "annotate/**/*.py", forbid = ["scripts", "tests", "examples"] }]

[tool.mimir.comments]
enabled = true                              # default false: no-comments + no-docstrings
allow_directives = ["type: ignore[", "noqa:", "fmt: skip", "@ts-expect-error"]  # prefixes
citations = true                            # default: same as enabled
locks = ["uv.lock", "app/bun.lock"]         # default: every listed uv.lock / bun.lock / package-lock.json

[tool.mimir.layout]
max_dir_entries = 7                         # default: legacy max-dir-entries, else 7
dir_roots = ["."]                           # default: src
exempt = ["."]
data_trees = ["tests/fixtures"]             # not code: skipped by every check
skip_dirs = []                              # default ["tests", "test"]
skip_files = ["__init__.py", "__main__.py", "package.json", "bun.lock", "tsconfig.json",
              "pyproject.toml", "uv.lock", "index.html"]
skip_suffixes = [".d.ts"]

[tool.mimir.layout.allow]                   # ratchet: may not grow; stale entries fail
"some/wide/dir" = 9

[[tool.mimir.layout.layers]]                # one table per root: a python package or a TS src dir
root = "annotate"
order = ["store", "shapes", "games", "run", "experiment", "__main__"]

[[tool.mimir.layout.layers]]
root = "app/src"
order = ["lib", "ui"]
```

A file's layer is its first path segment under `root` (`store.py` -> `store`). The
root's own `__init__.py` is exempt. Python imports resolve through module names
(relative imports included), TypeScript relative specifiers through the file tree
(`./x`, `./x.js`, `./x/index`); tsconfig `paths` aliases are not resolved.

The existing kebab-case keys (`src`, `exclude`, `max-function-lines`, ...) are unchanged.

## Citations

One line each; block comments are never citations.

```
# EXTERNAL(<pkg>==<ver> <path>:<start>-<end>): <fact>     version must be in a lockfile
# EXTERNAL(<owner>/<repo>@<sha> <path>:L<a>-L<b>): <fact>  format only
# EXTERNAL(<https-url> @<YYYY-MM-DD>): <fact>              format only (a real date)
```
