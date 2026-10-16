# Embeds and widgets

Chapters place interactive blocks with a fence named after the kind (`web/embeds/<kind>/`): the `carousel` of RL highlights on flappy and the `nn-fit` curve-fitting widget on neural-nets. `<flappy-play></flappy-play>` in a chapter becomes the `<env-play>` wasm play widget. nn-fit trains in the browser, or remotely on a Connect kernel.

## Sub-features

- `carousel-nav` shows slide `1 / N`; `Next slide` / `Previous slide` buttons, arrow keys, Home/End move it; videos are click-to-load facades.
- `env-play-reference` plays the reference env (`./flappy.js`) until the reader's flappy passes (then see `cells-play` in [cells](./cells.md)).
- `nn-fit-browser` trains the default wave (`dl/neural-nets-fit.nnfit`: sizes `[1, 12, 12, 1]`) in the page; Train toggles to stop; loss falls.
- `nn-fit-remote` with `Run on: remote` (only offered while connected) trains on the Connect kernel: wave + Stop, spiral to its step budget, the grokking dataset (remote only), disconnect mid-run fails cleanly.
- `nn-fit-in-card` a link preview card holds a live nn-fit (see [links](./links.md)).

## How to get to it (user POV)

- Open `/01-flappy/`: the carousel is at the top; the play widget follows the first prose (click it, then up/down or w/s).
- Open `/neural-nets/`: the nn-fit widget is under `## fitting a curve`; click `Train`.
- For remote: on `/neural-nets/?gateway=<gateway>`, Connect (see [connect](./connect.md)), pick `remote` in the widget's backend select, click `Train`.

## Driving it with vb

Preconditions:

- `vb doctor` reports ok. 01-flappy needs the session up (the page asks it for `/state`).
- For `nn-fit-remote`: nothing extra; `remote_e2e.py` starts its own `connect_dev.py` (with torch) and static server on free ports.

- **Carousel.** Run `vb drive embeds` (`pages.py embeds`). `embed-carousel .carousel-count` reads `1 / 8` and equals the `.slide` count; `get_by_role("button", name="Next slide")` -> `2 / 8`; `Previous slide` -> `1 / 8`. Screenshot `embeds/carousel.png`.
- **Play widget.** The drive reads the session's `/state` first. Fresh reader: `env-play[cell="flappy"] iframe` src ends `js=.%2Fflappy.js`, `.play-caption` starts `playing: reference env` (screenshot `embeds/env-play-reference.png`). After `vb drive cells` passed flappy: src ends with the session's `/wasm/<hash>/flappy.js` (URL-encoded), caption `playing: your env (latest passing version)` (screenshot `embeds/env-play-reader.png`).
- **nn-fit in the browser.** On `/neural-nets/`, read `document.querySelector('nn-fit').stats` (`dataset`, `sizes`, `steps`, `loss`), click `nn-fit button.train`, wait for `stats.steps >= 200`, click again. Loss drops more than 10x (seen `0.166 -> 0.00575`). Screenshot `embeds/nn-fit-trained.png`.
- **nn-fit remote.** Run `vb drive nn-fit-remote` (`uv run --with playwright python web/embeds/nn-fit/remote_e2e.py`). Every line `ok`, ending `ok: .../.evidence/nn-fit-remote/`; device `cpu (remote)`; grok runs 1000 steps on CPU (fits, doesn't grok). Video and screenshots copied to `nn-fit-remote/`; the drive then rebuilds `dist/neural-nets` with our gateway.
- **Proof.** `embeds/transcript.txt` ending `== embeds: PASS` with the loss numbers; the screenshots above; `nn-fit-remote/nn-fit-remote.mp4`.

## Gotchas

- Which env the play widget shows is session state, not page state: drive `embeds` before `cells` to see the reference, after to see the reader's (`vb drive all` runs embeds first).
- nn-fit renders in a shadow DOM; Playwright locators pierce it (`nn-fit button.train`, `nn-fit select.backend`), `document.querySelector` from the page does not.
- `stats` is the widget's test handle (`web/embeds/nn-fit/nn-fit.ts get stats()`); assert on it and on a screenshot, not on canvas pixels.
- The carousel's media are YouTube facades: clicking one loads youtube-nocookie.com (network). Don't click facades in a proof.
- `remote_e2e.py` takes ~3 minutes (grok 1000 steps at ~16 steps/s on CPU) and its first run installs torch into connect_dev's uv env. It rebuilds `dist/neural-nets` with the default gateway (`:8790`, the author's relay); `vb` rebuilds it afterwards.
- `remote_e2e.py --gateway URL` means a real gateway: it expects a Tesla T4 and reads `MODAL_TOKEN_ID`/`MODAL_TOKEN_SECRET`. Not for connect_dev.
- `npm run test:nn-fit` (34 unit checks + gradient check) and `test:nn-fit-remote` / `test:nn-fit-grok` (parity of the remote trainer) are the widget's non-browser proofs.
