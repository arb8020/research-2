# anti-slop (vendored subset)

- Source: https://github.com/dmmulroy/anti-slop
- Commit: c44ef22ca116d0ba62a3ff663a0bd13a3f3fa40b (2026-09-10)
- License: MIT, `LICENSE` copied verbatim.
- Copied: `src/rules/{no-unsafe-dictionary-type,no-chained-type-assertions,no-conditional-empty-object-spread,no-widen-then-assert}.ts`
  and their helpers `src/shared/{dictionary-types,type-alias-resolution,lexical-type-parameters}.ts`.
  Rule/helper bodies are unmodified; each file gained a two-line provenance header.
- Deviations: `index.ts` registers only the four rules above (upstream registers 18). Tests not copied.
- Runtime: loaded by oxlint `jsPlugins` from `.oxlintrc.json`; imports `@oxlint/plugins` (pinned to the oxlint version).
