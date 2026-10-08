# Nielsen: Discovery fiction

Source: https://michaelnotebook.com/df/index.html (Michael Nielsen, 2023-01-03). Linked: https://michaelnielsen.org/ddi/how-the-bitcoin-protocol-actually-works/ , https://cognitivemedium.com/srs-mathematics (not opened)

## Distillation
- **Not interactive.** A short static Pandoc-generated essay (26 KB). No code, widgets, figures or exercises; only Disqus comments. No public repo.
- "Discovery fiction" is "a plausible story of how I could have discovered that result": an arc of small questions, false starts, backtracking and incremental steps.
- Start with a natural question the intended reader would ask (Bitcoin example: "how could we design a digital currency?").
- Every step should be "simple, almost-obvious", one the reader "could plausibly have taken"; nothing out of thin air.
- Core loop: obvious naive idea → obvious flaw → simple fix → next flaw, repeated until the real result.
- Accept that it runs 2-5x longer than a conventional explanation; he finds it faster to read.
- No allegiance to history; the story only has to be plausible and satisfying.
- Variant: multiple discovery fiction (several paths to the same result).
- Mainly a tool for the writer's own understanding; writing it publicly raises the bar.
- Warning: explorable explanations often failed because authors cared more about form than content.
- Other examples he names: Lakatos's *Proofs and Refutations*, a StackExchange collection of casual proof tours, Gowers on normal subgroups.

## Relevance to the series
- The naive → flaw → fix loop maps onto REINFORCE → baseline → advantage → PPO (the report flags this as its inference). Each flaw could be something the reader observes in a gated cell run (e.g. high variance), not just reads about.
- The form-over-content warning applies directly to us: the sandbox and widgets must serve the derivation, not replace it.

## Caveats from the report
- The agent took the URL literally. If a different, interactive Nielsen piece was meant, candidates are Quantum Country or Neural Networks and Deep Learning; neither was researched.

source: subagent file agent-a325f32d39760e0d4.jsonl
