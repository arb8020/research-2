# Research notes index

Distilled from subagent reports of a previous Claude Code session (a9f505dc). Each note cites its subagent file.

## Inspiration
- [3b1b SoME non-video](inspiration/3b1b-some-non-video.md): no entry grades reader code; "play first, then dissect" and pub/sub widget state with defaults are worth stealing.
- [BetterExplained complex numbers](inspiration/betterexplained-complex.md): static text, but "predict, compute, check", a cheatsheet map up top, and one running example are strong patterns.
- [ezyang DeepSeek-V3](inspiration/ezyang-deepseek-v3.md): plain JS, displayed formula is the executed formula, URL-hash state, heavy build-time tests; no reader code, no cross-page state.
- [Migdał colorful equations](inspiration/migdal-colorful-equations.md): KaTeX `\htmlClass` term colouring linked to prose with build-time validation; good for the PPO objective, no derivation support.
- [Nielsen discovery fiction](inspiration/nielsen-discovery-fiction.md): not interactive; the naive idea → flaw → fix loop fits REINFORCE → baseline → PPO.
- [srush sampling to reinforce](inspiration/srush-sampling-to-reinforce.md): build-time-only notebook with precomputed sliders; exact distributions instead of sampling make estimators checkable exactly.

## Infra
- [vmux + Modal auth](infra/vmux-modal-auth.md): vmux runs on its own Modal account; Modal OAuth exists but is undocumented; Modal's JS SDK can't run in Workers/DOs.
- [Colab architecture](infra/colab-architecture.md): Jupyter over a token-proxied websocket, no kernel-memory restore, and no course system carries a reference solution forward after a failure.
- [SF Compute autoresearch](infra/sfcompute-autoresearch.md): H100-only agent-first compute with token-gated ports and fast-fork sandboxes; poll-only logs; framed around `box`, so indirect relevance.
- [pi durable](infra/pi-durable.md): durable agent harness with a brand-new, mock-tested Cloudflare DO SQLite backend; candidate for an in-DO tutor agent.

## Code style
- [Asserts: TigerBeetle + matklad](asserts-tigerbeetle-matklad.md): TigerBeetle has two runtime assert tiers: plain asserts that ship in release builds, and `constants.verify` checks for tests (5% prod budget, 5x test budget). Hot loops get O(1) asserts before and after the loop, not inside. Outside input is handled, not asserted. Flappy's action check should move to the batch boundary or behind a VERIFY flag rather than be dropped.
