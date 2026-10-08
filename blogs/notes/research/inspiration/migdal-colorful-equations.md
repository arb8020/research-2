# Migdał: Equations Explained Colorfully

Source: https://p.migdal.pl/equations-explained-colorfully/#navier-stokes (repo: https://github.com/stared/equations-explained-colorfully, MIT)

## Distillation
- Static Vue 3 + TypeScript + Vite app with KaTeX, deployed to GitHub Pages. Runs no code beyond rendering; interactivity is hover and click on coloured terms.
- **Authoring format**: one Markdown file per equation with three additions: `\mark[name]{latex}` marks a term in the `$$` block; `[prose]{.name}` in the Description refers to it; a `## .name` heading holds that term's definition.
- Mechanism: `\mark` is rewritten to KaTeX's built-in `\htmlClass{term-name}{...}` (needs `trust: true`). Colour is applied afterwards in the DOM, so swapping palettes doesn't re-render math.
- Colours are assigned by order of first appearance; authors never pick colours. Four palettes, including colourblind-safe and no-colour.
- Equation pieces and prose spans share a `term-*` class and one piece of state (`activeTerm = clicked ?? hovered`). Hover highlights; click locks.
- Highlight boxes behind terms are unions of `getClientRects()` over KaTeX's nested spans, so they stay tight across fractions.
- Live editor re-renders as you type. Exports to standalone interactive HTML (vanilla JS, no Vue), LaTeX/Beamer and Typst.
- **Build-time validation**: errors for prose terms not marked in the equation or terms with no definition; warnings for unused ones. The editor flags these inline too.
- Pedagogy, three layers per equation: the coloured equation; one "sentence version" where each coloured phrase is a term (e.g. Bayes: "Your [updated belief] is your [prior view] re-weighted by its [predictive power]"); per-term definitions on demand, often with "when is this zero / what does the sign mean".
- No derivations: one finished equation explained term by term.
- Limitations: one `$$` block per file, single-paragraph description, definitions likely show raw `**`/`_` (inferred, not seen).
- Credits BetterExplained's colourised equations and Stuart Riffle's colour-coded Fourier transform.

## Relevance to the series
- Strong fit for the policy-gradient / PPO objective: colour log-prob, return/advantage, ratio, clip terms and tie them to prose and code.
- The three-way validation (equation ↔ prose ↔ definitions) is a pattern we could extend to equation ↔ code cell, so a term coloured in the math is the same colour in the torch code.
- Cheap to adopt: KaTeX `\htmlClass` + DOM colouring, no plugin.
- Gap: no derivation support, and our series is derivation-heavy, so this would be a component inside a chapter, not a chapter format.

## Caveats from the report
- Behaviour claims come from source, not from using the page in a browser. Typst/Beamer exporters not read deeply.

source: subagent file agent-a196bed4fee9f11cd.jsonl
