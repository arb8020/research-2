# Review: shared render/source toggle

Diagnostic only. Read current `app.tsx` / `html-viewer.tsx` / `html-quote.ts` / `annotate.py` / `webui.py` / tests / `proof/`.

## Verdict

The annotate vertical slice matches the intended behavior. Regular `mimir ui` does not: HTML render is gated off so the iframe never hits a missing `/preview/`. Markdown still gets the toggle in both servers.

Implementer notes, checked against this tree:

| Note | Result |
|---|---|
| HTML render no longer gated on `annotateMode`; `mimir ui` may 404 `/preview/` | **Refuted.** Source now has `canRenderHtml = isHtml && annotateMode` and a comment that `/preview/` exists only on the annotate server. |
| Playwright Python package not installed; UI tests not run | **Confirmed.** `tests/test_annotate_ui.py` imports `playwright.sync_api` and is also skipped unless `RUN_SLOW_TESTS=1`. JS Playwright exists in `mimir/ui/app/package.json`; that is a different package. |
| `mimir papercut` CLI missing in this worktree | **Confirmed.** No `papercut` symbol or subcommand in this tree. |

## Intended vs code

1. **`.html` and `.md` show render\|source in the file header.** Annotate: yes. `mimir ui`: markdown only. `.html`/`.htm` open as CodeMirror with no toggle.
2. **Default is render.** Yes. `useState("render")`.
3. **source → CodeMirror.** Yes. Final `else` is `<Editor>`.
4. **render html → same-origin iframe via `/preview/`.** Yes, and only when `canRenderHtml`. `sandbox="allow-same-origin"`.
5. **render md → existing `MessageViewer`.** Yes, after `mdContent` loads.
6. **Toggle resets to render on file change.** Yes. `useEffect(..., [selected])`.
7. **Iframe must not have `allow-scripts`.** Yes. Attribute is exactly `allow-same-origin`.
8. **Text-select annotate still works on rendered HTML.** Yes in code. Proof shots 03/05 show a kept `<mark>` after comment. Shot 02 is a native selection with no visible `comment` chip (timing or position; see holes).

## Viewer branch (as written)

```
previewView := "render"
on selected change: previewView = "render"

isMarkdown     := selected ~ \.(md|mdx|markdown)$
isHtml         := selected ~ \.html?$
canRenderHtml  := isHtml && annotateMode          # not isHtml alone
isPreviewable  := isMarkdown || canRenderHtml     # drives the header toggle

header:
  if touchedCount || isPreviewable:
    file-header-end (margin-left: auto)
      branch meta?
      if isPreviewable: [render | source]

body:
  if canRenderHtml && previewView == "render":
    HtmlViewer
      iframe src=/preview/{encoded path}  sandbox=allow-same-origin
      mouseup → comment toolbar → locateQuote(source) → onTextSelect
  else if isMarkdown && previewView == "render" && mdContent != null:
    MessageViewer(mdContent)          # onTextSelect only if annotateMode
  else:
    Editor                            # html in mimir ui lands here
                                      # md also lands here while fetch is in flight
```

`/preview/` is implemented only on `_AnnotateHandler` in `mimir/annotate.py`. `mimir/webui.py` has no such route. `tests/test_route_parity.py` only extracts `/api/...`, so this split is invisible to it.

## Bugs / contract holes

**`start_line: 0` is a real submit contract hole.** Submit does `start_line: a.startLine ?? 0`. HTML comments set `startLine` from `locateQuote(sourceRef.current, quote)`, which returns `null` (hence `0`) when:

- the selected string is not a contiguous substring of the raw source (almost any selection that crosses tags, e.g. `<strong>Try it.</strong> Select this sentence` in `proof/show-me-toggle.html`);
- `sourceRef` is still `""` because `fetchFile` has not returned (race; empty string never matches);
- `indexOf` misses after the three needles (raw / html-escaped / whitespace-collapsed). Prefix/suffix are stored for re-highlight but **not** used to pick the source occurrence, so a repeated phrase maps to the first hit.

The agent-facing JSON then has `start_line: 0, end_line: 0` plus `original_text`. Anything that treats lines as 1-indexed file coordinates will point at the wrong place. Markdown render comments have the same `?? 0` path (MessageViewer never sends lines).

**`/preview/` is annotate-only.** The client no longer 404s in `mimir ui` (gate added). The remaining hole is product, not a crash: the shared frontend cannot honor “html render in browse” until `webui.py` grows the same handler, or the two servers share one.

**Toggle layout is not broken.** `.file-header-end { margin-left: auto }` plus `.view-toggle` is a right-cluster. Proof shot 01 shows it parked next to `1 branch`, segmented, active state correct. Minor: `.file-header` is nowrap + `align-items: baseline`, so a long path can crowd the control; `.file-nav` still has its own unused `margin-left: auto`. Not a functional bug.

**Other nits**

- Markdown render waits on `mdContent != null`. Until then the default-render branch falls through to Editor — a source flash on every `.md` open.
- `HtmlViewer` always passes `onTextSelect`; harmless today because the iframe only mounts in annotate mode.
- Toolbar coords are `iframeRect + rangeRect - 36`. A selection at the top of the iframe can sit under the file header. Shot 02 does not show the chip.
- `locateQuote` / `wrapQuote` have no tests. Re-highlight is first-match in concatenated text nodes (prefix helps marks; not source lines).

## Test gaps (regressions that would slip through)

Default `pytest` only runs `tests/test_html_preview.py` (HTTP 200/404/escape on the annotate handler). It does not cover:

- `sandbox` is exactly `allow-same-origin` (adding `allow-scripts` would be silent);
- toggle default, source↔render swap, reset on file change;
- comment toolbar → submit payload (`start_line` / `original_text` / prefix);
- quote→line mapping, including tag-crossing selections and the empty-`sourceRef` race;
- `mimir ui` does not request `/preview/` (and still 404s if someone removes `canRenderHtml`);
- markdown header toggle in non-annotate browse;
- iframe relative assets beyond the one CSS case;
- `wrapQuote` re-applying marks after render↔source.

The Playwright tests in `tests/test_annotate_ui.py` would catch default-render + toggle swap for html and md, but they are double-gated (`playwright` Python + `RUN_SLOW_TESTS`) and do not assert sandbox, submit JSON, or file-change reset.

## Is the slice demoable via `proof/RUN.md`?

Yes, for **annotate**. The command starts `mimir annotate` on `proof/show-me-toggle.html` (handler has `/preview/`). Dist is present (`mimir/ui/dist/index.html` → `index-DiGE5s89.js`) and contains `HtmlViewer`. Expected: rendered page, header toggle, source → CM, render → iframe, select → comment.

Caveats:

- Rebuild the UI if you change `app/src` after this dist; `RUN.md` does not say so.
- Proof PNGs were taken on `docs/design/show-me-harness-layers.html`, not the RUN fixture. They still show the slice (render, mark kept, source).
- This path does **not** demo `mimir ui` HTML render. That is intentionally CodeMirror-only right now.
