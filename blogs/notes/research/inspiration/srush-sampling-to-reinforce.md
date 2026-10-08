# srush: From Sampling to Reinforce

Source: https://srush.github.io/sampling-to-reinforce/

## Distillation
- Static page, **no reader-editable code**. A Jupytext percent-format `puzzle.py` notebook is executed once at build time on GitHub Actions; all outputs, plots and slider states are baked into one ~10.6 MB HTML file (plotly.js inlined, MathJax from CDN).
- Generator is a custom ~130-line `build_html.py`: markdown cells → markdown-it; code cells → `exec` in one shared namespace with stdout captured; `display` monkeypatched to collect HTML; `## ` headings open sections. Cells tagged `hide` run but aren't shown.
- 41 Plotly figures (lots of 3D mesh "variance boxes"). **Sliders are precomputed animation frames**, so they only offer a few steps (e.g. b = 1..4). Readouts next to sliders are precomputed string arrays swapped on slider change. Hover highlighting via generated `Plotly.restyle` scripts.
- The `check(...)` calls on the page are **author build-time assertions**: they compare an estimator's whole output distribution to an independent reference; the build fails on mismatch.
- **Core idea: "no random numbers."** Every estimator is an exact distribution over all outcomes, so bias and variance are shown exactly, not estimated.
- A small reused vocabulary throughout: `op`, `cond`, `shared`, `indep`, `add`, `sub`, `mul`, `monte_carlo`, `expect`/`variance`.
- Sequence: discrete RVs → joint RVs → Monte Carlo → stratification → control variates → A/B tests → KL estimators (k1/k2/k3) → REINFORCE derivation → training a one-parameter temperature softmax with constant then leave-one-out baseline (equated with GRPO).
- No exercises, hidden solutions or reveals on the live page. File names (`puzzle.py`, `intro_answers.py`, "Puzzle 1" in a backup) suggest it began as a fill-in puzzle set (inferred; repo is one squashed commit).
- Tests pull the article's own function definitions out via `ast` and test them (e.g. `temperature_score` vs finite differences), so the published code is the tested code.
- Live preview: polls file mtimes, rebuilds, reloads the browser, shows build errors in a red banner while keeping the last good page.
- "The text and comments are written by a person; the code is written by AI."

## Relevance to the series
- Closest content neighbour: it derives REINFORCE with baselines. The series can lean on it or differentiate (it stops at a toy softmax; we go to real envs and PPO).
- "Exact distributions instead of sampling" is a strong idea for early REINFORCE chapters on tiny problems: readers' estimators could be checked exactly, not stochastically.
- Distribution-level `check()` is a model for grading gated cells robustly.
- Precomputed-frame sliders are cheap but coarse; our sandbox can do live compute, which is the differentiator.
- `ast`-extract-and-test and the live-reload preview are directly reusable authoring tooling.

## Caveats from the report
- Build not run locally; deployed page assumed to match repo HEAD. The "began as puzzles" story is inferred from filenames only.

source: subagent file agent-a1b162528ba038413.jsonl
