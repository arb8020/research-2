# mimir issues

## Done (2026-08-02 / 08-03)

- [x] **annotate-last: session discovery** — match `CLAUDE_CODE_SESSION_ID` env var, skip tool-use-only messages, respect turn boundaries
- [x] **annotate-last: markdown rendering** — `marked` + `highlight.js`, text-selection annotations via Selection API
- [x] **annotate-last: annotation sidebar** — right panel with CRUD (edit/delete), click-to-scroll
- [x] **annotate-last: bottom bar** — annotation count, format toggle (md/json), copy + send buttons
- [x] **annotate-last: message browser** — sidebar listing 20 recent messages, click to switch
- [x] **annotate skills: fix blocking** — rewrite skills to use Bash tool instead of `!` bang syntax (was getting killed by timeout)
- [x] **annotate-diff: stdin pipe support** — `git diff | meat | mimir annotate --diff -`
- [x] **annotate-diff: multi-file scrollable view** — sticky file headers, lazy CM6 editor mounting via IntersectionObserver
- [x] **annotate-diff: file tree scroll-to** — click file in tree scrolls to that section
- [x] **annotate-diff: line highlighting** — vivid add/del/hunk/file colors, semi-transparent for selection visibility
- [x] **annotate-diff: selection highlighting** — rgba backgrounds so CM6's z-index:-2 selection layer shows through
- [x] **editor: skeleton loading** — pulsing placeholder while file content fetches
- [x] **self-verification** — headless Playwright for inspecting computed styles + screenshots without user interaction
- [x] **reference repos** — cloned `ext/meat` (diff abridging) and `ext/react-scan` (component inspector)

## Next up

### Diff preprocessing / reading aid
- [ ] **meat-style diff abridging** — integrate a preprocessing step that strips noise from diffs before showing in annotate. Could be `meat` directly, or a lighter mimir-native version. The pipeline `git diff | meat | mimir annotate --diff -` works but should be a single command.
- [ ] **semantic grouping** — group hunks by semantic purpose (refactor vs feature vs bugfix) between the file header and the hunks. Requires LLM pass or heuristic analysis of the diff.

### Diff viewer polish
- [ ] **fold file headers** — click sticky header to collapse/expand that file's diff
- [ ] **split view** — side-by-side old/new instead of unified
- [ ] **syntax highlighting within diff** — language-aware highlighting for the code content (not just diff +/- coloring)
- [ ] **delete line highlighting** — verify red backgrounds look good (current diff was all-adds, untested with mixed add/del)

### Annotation UX
- [ ] **scroll-to-annotation** — clicking annotation in sidebar should scroll the diff/message viewer to the annotated location
- [ ] **highlight persistence** — visually mark annotated text regions in the viewer
- [ ] **annotation on diff lines** — diff mode currently uses line-number-based annotations, could switch to text-selection like message mode

### Architecture
- [ ] **output format** — support structured markdown feedback string alongside JSON (plannotator emits plain text by default)
- [ ] **annotate-diff on git ref** — `mimir annotate --diff HEAD~3` currently works but the multi-file viewer has issues with the git ref flow vs stdin flow
- [ ] **computer use integration** — open-computer-use MCP is installed but not wired as an MCP server for this session. Need to add to `.claude.json` mcpServers and restart.

### Research / ideas
- [ ] **react component inspector** — react-scan-style sidebar for annotating running web UIs, not just code/diffs
- [ ] **PR review workflow** — `mimir review PR_URL` that fetches the diff, optionally runs meat, opens annotate
