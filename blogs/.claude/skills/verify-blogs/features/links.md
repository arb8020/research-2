# Page links

`[[page#Heading]]` in prose becomes a link to another chapter's section. On hover or keyboard focus it opens an Alignment-Forum-style preview card built at build time from the target's source, with live embeds loaded lazily; Escape closes it; a click navigates. Touch screens get no card.

## Sub-features

- `link-href` points at `../<stem>/#<heading-slug>` (01-flappy: one link, to `../neural-nets/#fitting-a-curve`).
- `link-card` opens on hover after a 200 ms grace (not hit-testable before), shows `.link-card-title` (target's title) and `.link-card-heading`, and mounts live embeds (nn-fit) on first open only.
- `link-escape` closes the card on Escape; focus stays on the link.
- `link-keyboard` opens the card on focus.
- `link-click` navigates and lands the heading near the top of the view.
- `link-touch` on `(pointer: coarse)` a tap navigates, no card.

## How to get to it (user POV)

- On `/01-flappy/`, hover or Tab to the `neural-nets#fitting a curve` link in the prose above the play widget; click it.

## Driving it with vb

Preconditions:

- `vb doctor` reports ok; `dist/01-flappy` and `dist/neural-nets` are built from the same run.

- **The link.** Run `vb drive links` (`pages.py links`). `page-link > a` count 1, `href` `../neural-nets/#fitting-a-curve`; `customElements.get('nn-fit')` is undefined before any card opens.
- **Hover card.** Click the `h1` (takes focus off the play iframe), hover the link. `.link-card` appears; `.link-card-title` `neural networks`, `.link-card-heading` `fitting a curve`; `.link-card nn-fit` gets `stats.loss`. Screenshot `links/link-card.png`.
- **Escape.** Press Escape. `.link-card` count 0.
- **Click.** Click the link. URL ends `/neural-nets/#fitting-a-curve`. Screenshot `links/link-target.png`.
- **Fuller cases.** The grace timing, keyboard focus, training inside the card, card width/overflow, light + dark and touch are in `verify_page.py` (`vb drive cells` runs it).
- **Proof.** `links/transcript.txt` ending `== links: PASS`, the two screenshots.

## Gotchas

- On 01-flappy the play iframe takes keyboard focus on page load, so Escape goes to the game and the card stays open until the reader clicks the page (`pages.py` prints `info focus after load: <iframe>`). Possibly a product gap; confirm in a real browser before filing.
- The card is `position: fixed` and re-placed on scroll/resize; screenshot the page, not the card element alone, to show placement.
- Missing pages/headings fail the build, not the page; see [build](./build.md).
