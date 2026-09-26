# observe/dashboard

Vite + React 19 + TypeScript (strict) viewer for observe JSONL runs.

```
bun install
bun run dev        # :5173, proxies /runs -> http://127.0.0.1:8384
bun run typecheck  # tsc --noEmit
bun run lint       # eslint (strict + import boundaries + no `as`)
bun run test       # vitest
bun run build      # -> dist/
```

## Layout

- `src/core/` — pure. `parse.ts` (boundary), `tail.ts` (byte-cursor Range tailer),
  `series.ts` (projections), `views.ts` (discovery), `events.ts` (vocabulary).
  Never imports `app/` or `views/`.
- `src/app/` — React chrome: layout, run picker, raw table, and `ViewSlot`,
  the only place React touches a view.
- `src/views/<name>/view.ts` — imperative surfaces, auto-discovered. Adding a
  view means adding a folder; nothing registers it.

## Without a server

`public/fixtures/golden.jsonl` is a copy of the golden test fixture (regenerate with observe/scripts/golden.py). Point the tailer
straight at it:

    bun run dev
    open 'http://localhost:5173/?url=/fixtures/golden.jsonl'

`?file=<name>` pins a run from `/runs` instead.
