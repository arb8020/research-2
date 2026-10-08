# 3Blue1Brown SoME non-video entries

Source: https://some.3b1b.co/archive?category=non-video (platform repo: github.com/fcrozatier/SoME)

## Distillation
- some.3b1b.co builds no posts. It is the voting and archive site (SvelteKit) for the Summer of Math Exposition. Each entry is a link plus a description, scores and reviewer feedback.
- The ~45 non-video entries are hosted all over: hand-written HTML/JS, Next.js, Astro, Jekyll, Quarto, Substack, Desmos, PDFs/Overleaf, itch.io, one Binder notebook, one Voici/JupyterLite page. There is no shared format.
- **"How a Transformer Plays Tic-Tac-Toe"** (sbondaryev.dev/articles/transformer), the most ML-relevant entry:
  - Trained offline in PyTorch. Six small ONNX models (~64KB each, including ablations like no-positional, no-MLP, no-residual) run in the browser via onnxruntime-web on WASM.
  - The ONNX graph exposes internal activations (embeddings, attention, MLP in/out, logits) as named outputs, so one forward pass feeds every visualisation.
  - The reader plays the game first. That game drives every later section ("Play a few moves in the game to visualize" until they do). State sharing across sections is inferred, not confirmed.
  - Order: play → architecture block by block → ablation comparisons → training details last.
  - Reviewer criticism: it shows how to use a trained model, not how to train one; "consider showing how the weights change as training progresses."
  - The site wraps pages in a Pyodide-in-Web-Worker provider, but this article doesn't appear to use it.
- **Voici/JupyterLite entry** (dynamical systems): numpy runs in the browser through a xeus WASM kernel. Heavy data ships precomputed as `.npz`. Sliders are Plotly steps built at load time, so dragging doesn't re-run Python (inferred). Code is hidden. The author warns figures may not show and suggests reloading or switching to Chrome, which suggests the setup is fragile.
- **"The Math of Losing Weight"**: plain HTML/JS, no build. The HTML has `data-widget="name"` slots, mapped to mount functions. Widgets share values over a small pub/sub, and each value has a default, so later widgets still work if the reader skips earlier ones (intentional, per code comments).
- Across all entries looked at: **readers never write code that gets checked.** They play, drag, type or pick items. The closest is an unguided Binder Jupyter session.
- Compute splits three ways: train offline and run inference in the browser (ONNX/WASM), ship precomputed data, or run Python in the browser (Pyodide/xeus). Binder is the only server compute.

## Relevance to the series
- Nobody here does gated, checked reader code, so that part of our design has no precedent in this set.
- Steal: "play first, then dissect" (fits the flappy wasm play widget opening); exposing internals as named outputs from one forward pass; pub/sub state between widgets with defaults so skipped sections don't break later ones (close to our carry-forward problem).
- Heed the reviewer note: showing training, not just a trained model, is what readers wanted. That is the series' core.
- Avoid: fragile in-browser Python stacks that need "try Chrome" notes.

## Caveats from the report
- Sites inspected with curl/grep, not a real browser. Transformer page source isn't public; cross-section state is inferred. Two archive entries returned errors; PDFs/Docs entries not opened.

source: subagent file agent-a60f97832b966cd9b.jsonl
