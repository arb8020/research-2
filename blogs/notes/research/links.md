# Links between pages with hover previews: research (2026-10-09)

Want: `[[page]]` / `[[page#section]]` in a chapter; hover shows a preview, click navigates; one working link proves it
(flappy's "believe in neural networks" spot -> a small page holding `<nn-fit>`). Clones: `/tmp/link-preview-research/`.

## Decisions so far (with the author)
- **A:** the target page declares its default preview (per page and per section); the linking page can override it per link.
- Links always go to a page, optionally to a section (`[[page#heading]]`). A section is a heading inside a page, never its own file.
- Preview content: "maybe just render the page in miniature". Alignment Forum / LessWrong research pending.
- Syntax style (left to Claude, "fewest styles"): embeds stay fences (```` ```nn-fit file=… ````); `[[page#heading]]` is the only Obsidian syntax we adopt.

## Builder today (`build_page.py`, `embeds.py`, `web/page.ts`)
- One chapter per run -> `dist/<stem>/` (`build_page.py:127`; `rl/` dropped, so `rl/01-x.md` and `dl/01-x.md` would collide). No site index; nothing knows other pages exist. Pages share `dist/` on one server, so `../<stem>/` works.
- markdown-it-py 4.2, CommonMark + raw HTML (`build_page.py:71`); custom `fence` and `html_block` renderers. `[[x]]` currently prints literally. Extension point: `md.inline.ruler.before("link", "wikilink", fn)`. Must match only double brackets; single-bracket author placeholders (`rl/01-flappy.md:17`) stay literal.
- Bad input fails by `assert` with a line number (embeds, excerpts, cell cross-check, hidden-leak check).
- `page.ts`: light-DOM custom elements (`code-view`, `code-cell`, `env-play`); tokens in `page.css:11-53` (`--bg --fg --muted --rule --code-bg --active`, fonts `:56-60`); custom properties reach shadow roots. `data-not-typeset` opts out of prose styling.
- Papercuts: a page with no C cells still calls `build_web.ensure_raylib()` (`:138`) and runs `npm run build` per chapter (`:130`); `page.js` always fetches `{SESSION}/state` (`page.ts:236`), so a cell-less page logs "session unreachable"; each chapter dir gets its own copy of shared JS/CSS.

## Prior art (verified against source; corrects an earlier from-memory table)

| tool | syntax / ids | who knows other pages | preview content | author control | broken links |
|---|---|---|---|---|---|
| Obsidian (closed source; obsidian-help repo) | `[[p]]`, `[[p#H]]`, `[[p#H\|alias]]`, `[[p#A#B]]`, `[[#H]]`, `[[p#^block-id]]`, `![[p#H]]` embeds; links match heading text, not a slug | app indexes the vault | "a preview of the file content" (section-scoped hover is common observation, undocumented) | none in core (plugins only) | — ; "shortest path when possible" is the *write* format setting, read-side ambiguity undocumented |
| Quartz v4 | regex rewrite then mdast (`quartz/plugins/transformers/ofm.ts` L119); anchors via github-slugger `slug()` with no dedupe (`util/path.ts` L181), so `[[p#Dup]]` hits the first; `sluggify`: space -> `-`, `&` -> `-and-`, `%` -> `-percent`, drop `?` `#`, keep case; resolution `absolute`/`relative`/`shortest` | one pass: `ctx.allSlugs` from the glob before parsing (`quartz/build.ts` ~L80) | **whole page**: fetch target, keep `.popover-hint` elements; `#hash` only *scrolls* the popover (`components/scripts/popover.inline.ts`) | per link only opt-out `data-no-popover`; per page which components carry `popover-hint` | not checked; `disableBrokenWikilinks` renders greyed `a.internal.broken` (`ofm.ts` L280); anchors never checked; transclusion of a missing heading silently empty (`renderPage.tsx` ~L162). Supports `![[…]]` transclusion (page/heading/^block; L74-210, circular detection) |
| Wikipedia Page Previews (mediawiki-extensions-Popups) | page title | server index | lead paragraph + PageImages image; default gateway `mwApiPlain` (TextExtracts), REST summary is one of three (`extension.json` L62-68) | write the lead; exclude an image | **no section previews**: `Foo#bar` previews Foo's lead; `#frag`-only links excluded (`src/index.js` L29-50) |
| MyST / mystmd | `(label)=` before any block; `[](#label)`, `{ref}`, `{numref}`, `{eq}`, `{doc}`, `<xref:proj#label>`; embed `![](#label)` (`docs/cross-references.md`) | whole project; per-page mdast `.json` + `myst.xref.json` | client fetches JSON, `selectMdastNodes(tree, id, 3)`: heading + next two blocks, stops at next heading (`myst-common/src/selectNodes.ts` L88; `myst-to-react/src/crossReference.tsx`); whole-page link = LinkCard from frontmatter `title`/`description`/`thumbnail`, none if missing (`links/index.tsx` L41-60) | frontmatter description/thumbnail; labels | — |
| Gwern.net | links classed at build time | build | the page/section itself, or an "annotation" from `/metadata/annotation/`; own-page annotations built by `build/Annotation/Gwernnet.hs` from `<meta description>`, thumbnail + thumbnail-text, `.abstract`; a section's own abstract beats the page's (L182-189) | per link via classes: `link-annotated`, `link-annotated-partial`, `link-page`, `extract-not`, `include-*`, `data-include-selector[-not]` (`js/extracts*.js`, `annotations.js`, `transclude.js`) | — |

Slug conventions: github-slugger (lowercase, strip punctuation by Unicode regex, space -> `-`, dupes `-1`, `-2`); markdown-it-anchor (`encodeURIComponent(lowercase, \s+ -> -)`, dupes `-1`; `failOnNonUnique` only for user ids); `mdit_py_plugins.anchors` (drops non-`\w`/CJK/`-`, same dedupe, **`max_level` defaults to 2**, `anchors/index.py` L118). None survive renames; MyST `(label)=` is the only stable-id scheme seen.

Plugins: `mdit_py_plugins` has **no** wikilinks plugin (checked at 519953d, 2026-07). `mdformat-wikilink` is ~25 lines, one raw token, no `#`/`|`, no renderer: not worth depending on. JS has `markdown-it-wikilinks-plus`. Write our own rule.

**The novel part:** target-declared previews have precedent (Gwern, MyST, Wikipedia implicitly). A *linking page swapping in arbitrary content (a widget) per link* has none; only Gwern varies behaviour per link via classes. Sphinx-hoverxref may choose tooltip vs modal per role (unverified).

Hazards: Quartz-style mismatch between deduped heading ids and undeduped link slugs — resolve against the deduped map and fail on ambiguous heading text. Every system needs a global slug/id index to check links.

## Style docs (`~/dotfiles/docs/synthesis/CODING_STANDARDS.md` = CS) per question
1. **Who knows other pages.** Earned compression: one chapter exists, so no "build the site" layer yet. Add beside, don't reshape: a site build would wrap the per-chapter build. Parse don't validate + single source of truth: read target *Markdown sources*, not built `dist/` HTML. Fail-stop wants a global check. Middle ground satisfies both: build one chapter, parse every chapter's source for headings + preview declarations. `main()` is ~90 lines (over the 70-line rule); extract functions either way.
2. **Target declares preview.** Model the domain: a data shape like `Preview = Excerpt | Embed | Text`, not branching. Locality: declare next to the section. No invented terminology: reuse fence names and `key=value` info strings (`file=`, `excerpt=`, `cell=`). No dishonest fallbacks: a "first paragraph" default is OK only as a documented rule.
3. **Per-link override.** Write usage code first: draft the link in a real chapter before building. Unknown keys fail with a line. Earned compression suggests waiting for a second real override (an inference, not a stated rule). Syntax trap: Obsidian's `|` means shown text, so `[[p#H|preview=…]]` would break the convention.
4. **Live widgets.** style_reference.md's lazy-init conditions match exactly (expensive; may never be needed); carousel's click-to-load YouTube is the precedent. Conflict with fail-fast setup is resolved by validating everything at build time and loading on hover. Hover fetch needs an owner, cancel on leave; popover as a discriminated union (idle/delay/loading/shown/error, `raw/frontend/state_machines.md`); skip delay on subsequent hovers (emil, `skills/ext/emil-design-eng/SKILL.md:252`); gate on `@media (hover: hover) and (pointer: fine)`; Nielsen 0.1 s / 1 s. `EnvPlay` mounts its iframe eagerly in `connectedCallback`, so reusing it in a preview would be eager.
5. **Names.** Canonical form: the file stem is already the identity (`dist/<stem>`); a declared short name is a second source of truth. Numbered stems break on renumbering — loudly under fail-stop, which the docs accept. Sections: heading text is free but breaks on rename; labels survive but cost upkeep. Fail on renamed/duplicate headings either way.

Assert vs raise: the repo asserts on bad author input; CS says "raise at boundaries" and favorites.md warns `-O` strips asserts. Decide consciously.

## Claude's proposal (2026-10-09, not yet agreed)
- Build one chapter; index every chapter's source first (`{stem: {heading-id: Preview}}`); fail on missing page/heading, with the line.
- Default preview = the section's first paragraph (documented rule); a `preview` flag on a fence under the heading declares otherwise (```` ```nn-fit file=x.nnfit preview ````); a section with neither fails.
- Preview HTML goes in a `<template>` beside the link at build time; widget JS loads on first hover.
- Pages by file stem (fail on duplicate stems); sections by heading text, GitHub-style ids, fail on duplicates.

```
build_page.py rl/01-flappy.md
+ index = links.index(glob chapters)              # {stem: {heading-id: Preview}}, sources only
  MarkdownIt(...)
+   inline rule [[page#heading]] -> <page-link>   # fails on missing page/heading
+     preview HTML -> <template> beside the link
  install embeds: used + those named by previews  # loaded on hover
web/page.ts
+ <page-link>: hover -> popover from the template; click navigates
```

## Open
- Per-link override now, or wait for a second real use?
- Sections by heading text or explicit labels?
- Assert vs raise for link errors.
- Preview content after the AF research ("page in miniature"?).
- The target page needs author prose; a heading + widget + todo box is enough for the demo?
