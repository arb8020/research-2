---
title: "mimir web UI: code viewer + diff review surface"
type: task
status: claimed
assignee: chiraag+claude
blocked-by: [001]
---
## Goal
Web surface for mimir — code browsing with `--at` sideways-blame overlay,
and unified diff review with per-file navigation. Replaces the original
single-file HTML design spike.

## Done so far (2026-08-01 session)

### Stack
- Vite + Preact 11 + CodeMirror 6 (read-only viewer, syntax highlighting)
- Python stdlib server (`webui.py`) serves Vite `dist/` with SPA fallback
- Design tokens: light-first, monospace, single gold accent
- Syntax colors derived from design tokens via OKLCH mixing (`palette.ts`)

### Features built
1. **File tree** — collapsible dirs, empty-dir flattening, badge rollup.
   Collapsed by default, expands to selected file. Browse mode shows
   "N branches", diff mode shows "+N −M".
2. **`--at` popover** — click gold gutter pip → popover lists branches
   touching that line with age. Click branch → peek panel slides in
   showing that branch's code. "enter →" swaps main to that branch.
3. **Diff viewer** — CM6 document with line decorations (same approach as
   diff-syntax.nvim). `+`/`-` backgrounds, sign gutter, fold by file/hunk.
   Per-file navigation via tree sidebar.
4. **`/api/file?ref=branch`** — read files from git refs
5. **`/api/diff?ref=branch`** — unified diff output

### Design language
- Light ground, one accent (warm gold `#9e7c1a`), monospace everything
- Hierarchy via weight + size + letter-spacing, not font-family changes
- Inspired by Thinking Machines / Tilde Research / Humans& editorial style
- Dark theme via `prefers-color-scheme` + CSS custom properties
- Syntax hues derived from ink color via OKLCH hue rotation at low chroma

## Remaining work

### High priority
- **Annotation** — highlight code in diff, write comments, send structured
  feedback back to agent (plannotator-style stdin→stdout protocol)
- **LSP** — WebSocket bridge to language servers (pyright, ts_ls). CM6
  `codemirror-languageserver` handles the client side. Gets us go-to-def,
  find-refs, hover, diagnostics. ~80 line bridge.
- **Diff highlighting in peek** — peek shows branch code but doesn't mark
  what changed vs current. Needs line-level diff markers.

### Medium priority
- **CLI entrypoint** — `mimir open path`, `mimir diff branch`, reading
  patch files from stdin
- **Agent integration** — stdin→serve→block→stdout protocol like plannotator
- **View modes** — unified / stacked / new / old (port diff-syntax.nvim's
  `gm`/`gt`/`g=` keybinds)
- **Line count on hover** in file tree

### Parked
- Pierre/trees was tried and ripped out (shadow DOM fights design system,
  Preact 11 beta dep). Revisit if virtualization needed (10k+ files).
- `@codemirror/merge` was tried and ripped out (merge conflict UI, not a
  diff viewer — Accept/Reject buttons, wrong abstraction).

## Key files
```
mimir/ui/
├── index.html          # legacy spike (preserved)
├── app/                # Vite + Preact + CM6
│   ├── src/
│   │   ├── main.tsx     # entry
│   │   ├── app.tsx      # shell: browse/diff mode routing
│   │   ├── tree.tsx     # collapsible file tree
│   │   ├── editor.tsx   # CM6 viewer + peek split
│   │   ├── at-gutter.ts # popover extension
│   │   ├── diff-viewer.tsx  # unified diff renderer
│   │   ├── diff-parse.ts    # patch → per-file chunks
│   │   ├── theme.ts     # design tokens + CM6 theme
│   │   ├── palette.ts   # OKLCH syntax color derivation
│   │   ├── lang.ts      # file ext → CM6 language
│   │   ├── api.ts       # fetch wrappers
│   │   └── styles.css   # layout + design tokens
│   └── package.json
├── dist/               # built output
mimir/webui.py          # Python server (API + static serving)
```

## References
- diff-syntax.nvim (`~/diff-syntax.nvim`) — nvim plugin with same diff
  rendering approach (two-stream treesitter, graphite theme, view modes)
- plannotator (`ext/plannotator`) — stdin→serve→stdout protocol reference
- Design reference artifact: https://claude.ai/code/artifact/0ee12eeb-5347-4aa4-826c-a41b55b0bc5e
