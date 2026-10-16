# Google Colab architecture and relatives

Sources: github.com/googlecolab/colab-vscode (official extension source), github.com/googlecolab/jupyter_http_over_ws , https://research.google.com/colaboratory/faq.html , https://research.google.com/colaboratory/local-runtimes.html , https://docs.cloud.google.com/colab/docs/idle-shutdown , https://deepnote.com/docs/restoring-variables , https://docs.marimo.io/guides/reactivity/ , https://docs.marimo.io/guides/wasm/ , https://modal.com/docs/guide/notebooks-modal , https://nbgrader.readthedocs.io/ , https://otter-grader.readthedocs.io/ , https://huggingface.co/learn/deep-rl-course/en/communication/certification

## Distillation
- **Transport**: standard Jupyter kernel protocol over websocket through a Google proxy (`/tun/m/...`), with an `X-Colab-Runtime-Proxy-Token` header. Colab-specific RPC (eval_js, Drive auth, widgets) rides as extra `colab_request`/`colab_reply` messages on top of Jupyter, not a replacement.
- **Allocation API** (beta, `colaboratory.googleapis.com/v1beta`): create runtime is a long-running operation; connection info has a URL, a short-lived proxy token and an expiry; clients must refresh the token before expiry. No published allocation latency.
- **Local runtime mode**: Colab's hosted page can connect to your own Jupyter. The old `jupyter_http_over_ws` extension tunnels HTTP over a websocket because browsers block cross-origin HTTP to localhost but allow websockets.
- **Lifetime**: free VMs max ~12h, Pro+ up to 24h. Consumer idle timeout unpublished (~90 min is folklore). Colab Enterprise: default 180 min idle, configurable 10-1440.
- **State**: notebook in Drive, disk lives with the VM, memory with the kernel. **No checkpoint/restore of kernel memory**; recovery is re-running cells. Deepnote, by contrast, serializes variables on idle shutdown and offers a restore.
- **Execution model**: Colab is classic out-of-order Jupyter with hidden-state risk. marimo, Observable and Hex build a dependency graph and re-run downstream cells; marimo forbids defining a global in two cells and deleting a cell deletes its variables (mutations aren't tracked).
- **Abuse control**: free tier has unpublished dynamic limits and favours users actively programming; it is metered by a refilling token bucket of milli-compute-units (inferred from API fields). Banned: web serving, proxies, mining, SSH/remote desktops, "bypassing the notebook UI", deepfakes; Gradio-style web UIs blocked on free tier. Enforcement mechanism isn't public.
- Pricing (third-party): $9.99/100 units pay-as-you-go or Pro; Pro+ $49.99/mo; units expire after 90 days.
- **Relatives**: Kaggle "Save Version" re-runs the whole notebook as a batch job (persisted thing is a reproducible run, not memory). JupyterLite/marimo-WASM run Pyodide in the browser (marimo WASM: 2GB memory, no threads). Modal Notebooks: only Volumes persist, 10 min idle default, hardware switch restarts kernel. Lightning Studios: home dir/packages persist across sleep and CPU↔GPU switches.
- **Courses with exercises**: nbgrader (solution stubs, hidden tests, checksummed read-only test cells, all-or-nothing per cell); otter-grader (`grader.check("q1")` public tests while working, hidden tests at grade time); CS231n (code in `.py` modules, notebooks check against reference values, so state carries through files); HF Deep RL course (pass by pushing a model that clears a leaderboard threshold).
- **No system found hands the learner the reference solution after a failure so later sections can run.** Earlier failures cascade.

## Relevance to the series
- Carry-forward of a failed gated cell is an open problem: we would be inventing the "substitute reference solution" mechanism, not copying it.
- CS231n's "reader code lives in files, notebooks import it" is the nearest precedent for carrying C/Python edits forward, and fits a sandbox with a filesystem.
- Dependency-graph execution (marimo) avoids hidden state; worth weighing against Colab-style free ordering for gated cells.
- Colab's proxy-token-with-expiry and Jupyter-over-websocket are a known-good shape for a browser ↔ sandbox link.
- Abuse lessons: give users compute, and people will run web UIs, miners and proxies; budget for a token-bucket meter and pattern restrictions.
- No memory restore anywhere except Deepnote: plan on re-execution or file checkpoints, not kernel snapshots.

## Caveats from the report
- Colab internals come from the VS Code extension's beta API; browser Colab may differ. Idle timeout, allocation latency, Pro+ units, otter behaviour on earlier failures, marimo WASM persistence, and the CS231n/fast.ai/d2l claims are unverified or from familiarity.

source: subagent file agent-aae5c267ea21c9237.jsonl
