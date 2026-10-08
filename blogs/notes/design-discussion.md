# Design discussion: the why behind the blogs/ RL series

Distilled from the session that started the series (2026-10-07 to 2026-10-08). The decisions themselves are in [../HANDOFF.md](../HANDOFF.md). This note covers the reasoning, the options that were rejected, and the threads still open. Research findings are covered separately in `notes/research/`.

"(inferred)" marks my reading of the author's intent where the author did not say it outright. Anything not marked was stated by the author, or agreed by them when Claude proposed it.

## 1. Vision and reader experience

- **The starting brief.** The author wants a "blogs" category in research-2, in the spirit of srush's *Sampling to Reinforce*, ezyang's DeepSeek-V3 site, 3b1b's non-video SoME entries, and Nielsen. Mid-discussion they added Migdał's colorful equations and BetterExplained's complex-numbers article.
- **The core idea is that the reader has to write or fill in code to finish the explainer.** The author singled this out as the part they "especially like". The research later showed that none of the inspiration sites, and none of the SoME entries sampled, check code the reader writes. No notebook course that was looked at (nbgrader, otter, CS231n, HF) hands a stuck learner the reference solution so later sections still run. So both of these features are new ground and can't be copied from anywhere.
- **The first series ends at Breakout solved with PPO.** The author's first outline, which was the seed for the HANDOFF arc:
  1. a stripped-down flappy;
  2. a Karpathy-style REINFORCE derivation;
  3. pong or cartpole, bringing in PufferLib for speed;
  4. an RNN detour (Karpathy's char-RNN post, "or figure out a better way to do this pedagogically");
  5. Breakout;
  6. maybe LSTM;
  7. Breakout with PPO.

  The goal is to cover everything in the ICLR "37 PPO implementation details" post.
- **Explainer code is treated like code.** Shared pieces (optimizers and deep-learning basics were the expected repeats) get pulled out only once they appear more than once, not up front. The same rule came up again later, when deciding where the puffer files should live.
- **The reader's code should carry forward** from chapter to chapter "if we can make that work". From the start, the author named the main uncertainty as getting the reader's code running inside the site.
- **The reader writes both Python and C.** The env is in C and the algorithm in Python, and C starts in chapter 1. The author's stated reason for C is that readers should understand pointers, references, arrays, and the buffers behind PufferLib's architecture and speed. In their words, the reader should "write at least a little game logic so that i/they understand".
- **Reader stance.** For now the reader is assumed to already accept that deep learning works. The series doesn't have to argue for it.
- **The chapter 1 motivation went through two versions.**
  - First version: "we have an environment where we want an agent to take actions; we are pretty convinced deep learning is good at its job; can we frame the problem as a deep learning problem."
  - The author then simplified it: flappy env → the reader plays it → "can we get something autonomous to do it?" → an MLP.
  - Claude proposed a detour through supervised learning ("what's the label?"). The author dropped it as more than they meant.
- **Where flappy came from.** It traces back to a PufferLib onboarding guide the author pasted, which reads roughly:
  - read puffer's docs on writing an env and the `squared` sample;
  - map the intro terms onto the code ("observations, actions, rewards, and terminals are just arrays");
  - write an env "so simple as to not even be useful";
  - bind it and train, without yet knowing how training works.

  The author's plan is to write flappy themselves following that guide, give it to the reader, and later decide whether the reader should write it too, "if it's instructive".
- **The reader should be able to play the game and watch policies run in the browser**, even though training happens in a sandbox. The author felt this would be easier for the reader. This is why the env is compiled to wasm.

## 2. Inspiration blogs: what the author said and what was only guessed

The author said very little about *why* they liked each blog. Most of the reasons in the session were Claude's hypotheses and were never confirmed. Each source below is tagged accordingly.

- **srush, ezyang, 3b1b SoME, Nielsen (stated):** these were listed as the inspiration, together with the wish for jupyter-style cells and widgets, possibly built on wasm, WebGL or WebGPU, and Colab-style GPU access through Modal "at worst".
- **BetterExplained, Migdał (stated):** "i also like" each one. No reason was given.
- **Nielsen "discovery fiction" (unconfirmed):** Claude asked whether the draw was its naive idea → flaw → fix loop, and the author never answered.
  - Claude used the idea anyway. It suggested REINFORCE might be set up by trying random search over the weights first.
  - It also suggested the −1/0 → 0/+1 reward change could later lead into baselines.

  Neither was decided. Both were left as calls to make while writing.
- **BetterExplained (unconfirmed):** Claude guessed the appeal was "define a thing by what it does before notation", which would mean REINFORCE opens with "nudge up what worked" before ∇log π appears. The author didn't respond.
- **Migdał colored terms (proposed, not adopted):**
  - Claude suggested keeping a term's color fixed as ∇log π moves through a derivation, and colouring the author's backticked prose terms (`agent`, `policy`, ...) to match the equations.
  - Both spikes built hover-linked equations, and they work.
  - The author never said whether they want this. The pasted puffer guide's instruction to "map the terms from the introduction to this code" points the same way (inferred).
- **ezyang (stated, about structure):** the author agreed with Claude's suggestion that widgets be custom elements dropped into prose, ezyang-style. ezyang's `CLAUDE.md` rule against AI-written prose matches the author's own rule (see §4).
- **srush:** the srush-style precomputed demo was offered as a non-interactive opener in case readers would bounce off Modal setup. It was never taken up.
- **Dislikes:** none were stated about the blogs themselves.
  - The author called probe envs "a little too 'unit test' rather than 'actual game'". So probes appear only as check fixtures, never as content.
  - A reviewer's criticism of the SoME tic-tac-toe transformer post ("showing a trained model, not training") was relayed. The author didn't comment on it.

## 3. Why the major decisions went the way they did

### Checks are pass/fail, never graded
- The author's words: "we should not 'grade' the reader's code but we should have pass/fail."
- **Failure output is text only.** The author rejected structured failure types (Claude's dataclasses): "think of it like a marimo or jupyter notebook output pane. text is enough for now, can add more complexity later."
- **Why the reference can stand in for the reader's code.** This is the author's main argument. A later chapter can use either the reader's code or the reference, "whichever is easier to build", because "if we define our check()s correctly / at the right boundary it shouldn't matter." Claude framed this as a substitution contract: passing the check is the licence to swap the code in.
- **The contract includes speed and memory budgets.** This came from Claude's counter-example: code that is correct but 250× slower, which would make chapter 7 crawl. The author answered that checks should include a speed, memory and resource budget.
- **Absolute budgets work because the sandbox is fixed hardware.** Claude first worried that an absolute budget would test the reader's hardware, and asked whether budgets should be relative to the reference. The author pointed out that the env runs on the Modal sandbox anyway. That fixed hardware is what lets absolute budgets on a pinned machine type work.
- **Many small cells.** The training loop is split into small Python cells with one check each, using probes as fixtures. That way, the first check to fail tells the reader which piece is wrong.

### Gating: the latest passing version propagates
- Claude raised marimo-style questions about stale cells. The author asked why a reader would edit a chapter they had already passed, then settled it: "as long as they pass check() it's fine and i don't care."
- From that came the rule: a later cell depends on the latest *passing* version of an earlier one, and failing edits don't propagate.
- This rule is what separated the design from marimo's re-run-on-edit model. Claude pointed this out, and it later decided the format question.

### Sandbox-only runtime, browser later
- **The author asked for Claude's opinion** ("what do u think"). Claude recommended building the sandbox runtime first and making it the only one. The reasons:
  - the GPU chapters need a sandbox regardless;
  - building it also improves `box`;
  - one runtime means one way to check code, with fair absolute budgets;
  - Pyodide has no torch, so code written in the browser couldn't carry through to the PPO chapters;
  - a browser backend can be added later behind the same session interface.
- The author accepted ("ok sounds good").
- **What would have changed Claude's mind:** a CPU cold start well over ~10 s, or a strong worry about readers leaving at the Modal signup step. The measured cold start was ~2 s on CPU and ~4–5 s on a T4, so the recommendation stood.
- **Spike in parallel.** The author wanted the GPU-path uncertainty reduced in parallel rather than deferred: "decrease the uncertainty with the gpu path at least in parallel". So the riskiest infrastructure was spiked early, alongside the browser C spike.

### "Rolling our own Colab"; vmux; box
- The author shared vmux: Durable Object sessions, a log ring buffer, and token-gated preview URLs on Modal.
- They saw it as a "design to borrow for box but potentially a good fit for our core runtime. seems to fix some of the problems we had." They added: "we are lowkey rolling our own colab it feels like."
- They also said that making `box` do all of this well, including interop with SF autoresearch, "will make our lives easier here". This is why `box` is meant to become the remote half of the session.
- Research showed autoresearch can only be a *provider* under `box`, never the other way round.
- **Colab and marimo.** The author asked whether Colab or marimo were "decent fits". The answer was: they fit the cell-and-state *model*, but not embedding cells in our own page, C cells, or the gating rule.
- **Carry source, not memory.** No one checkpoints kernel memory. Colab, Modal Notebooks and Lightning don't, and Modal GPU sandboxes can't memory-snapshot. This supported carrying the reader's *source* forward and replaying it, not live kernel state.

### Who pays for compute: the reader's own Modal account
- The author's ideal is both options: our account (vmux-style) and the reader's own. They chose the reader's own account for now "to minimize complexity".
- The author asked what a reader would be comfortable letting us do with their Modal token. Claude didn't answer for readers. It listed what a token can do (everything in the workspace, with no scope or spend cap) and the ways a token could be handled, and suggested limiting the damage with a throwaway workspace with a budget. The author: "throwaway workspace with a budget seems fine?"
- **Still undecided:** whether the token is (i) stored encrypted on our side or (ii) never seen by us, with the reader running `modal deploy` into their own workspace. The GPU spike built both paths.

### Markdown over marimo
- **The author was drawn to marimo.** They first asked "sounds like marimo is the best model for us?", then "is marimo open source", then "why don't we use marimo again". Claude's case against it:
  - its main feature, reactive re-execution, is the one we chose not to use;
  - reader code would run in our sandbox, not in marimo's kernel;
  - prose would sit in `mo.md("""...""")` strings, and C++ stubs would be Python strings.
- **Both were spiked** at the author's request, to "see how far marimo can be customized".
- **The author's own authoring style didn't decide it.** Asked whether they draft notebook-style or document-style, they said they don't care, so the comparison came down to customization, gating, deployment and how much code we'd own.
- **What the spikes showed:**
  - marimo worked, but needed 4 hacks: internal class names, shadow-DOM CSS injection, its own KaTeX refusing `\htmlClass`, and a single-cell editor-plus-Run pattern;
  - its gating had two sources of truth;
  - its static build was 27 MB;
  - Markdown worked with no hacks and about 270 lines of code we own.
- The author didn't explicitly say "Markdown". They moved straight on to building on it (the page-builder spike, and writing prose in nvim), so the choice was accepted (inferred).
- **pi-durable** was raised by the author as a possible inline assistant to "help the user / answer qs": "i trust pi's developers." It was deferred. The author's next move was "i want to start writing the website to figure out what it ends up looking like."

### One file per chapter
- The author asked for fewer files: "can we have less leaves of files and put more stuff in single files? might be nice even to just have a chapter be a file."
- So stub, solution and check sit together in one Markdown file, nbgrader-style.
- **Solutions are visible in the repo.** The author accepted this ("a is fine"); the page build strips them.

### Flappy design choices
- **Is it too much of a toy?** The author asked this themselves. Claude noted it's a contextual bandit, which is ideal for a clean ∇log π·r with no credit assignment.
- **Catch** (bsuite) was the author's suggestion as a first *real* game. They floated "give them flappy but ask them to code catch". Then they deferred Catch in favour of getting "flappy env + train a policy" working end to end.
- **REINFORCE stays in chapter 1.** The author picked "the reader writes REINFORCE here" (b) over "hand them a trainer" or "random search first", but asked whether that was too early. Claude argued flappy is the best place for it: no delay in reward, so the core idea arrives alone, with Catch adding credit assignment later.
- **Rewards changed from −1/0 to 0/+1** at the author's request. With −1/0 the policy learns only from crashes. Claude noted the shift could later motivate baselines (same expected gradient, different variance).
- **The dino game** was floated and dropped within one exchange ("ok nvm"). Claude had pointed out that it brings in delayed consequences and rare actions in chapter 1.
- **The observation includes the pipe the agent is about to face.** The author confirmed this. Otherwise the game is pure luck.
- **"Whole state" became a pedagogical thread.** The author wrestled with what "the whole state" means. Claude's answer: in flappy the observation *is* the state that matters, while in Breakout one frame is less than the state, which is what motivates the RNN and LSTM chapters later.

### Envs in C, in PufferLib format, played in the browser via raylib→wasm
- **Real-time play with low latency.** Claude first said that drawing with raylib would "bring back a second runtime". It corrected itself: only compilation moves to the browser, not Pyodide. The author's answer: use the same toolchain, or diff-test the two builds, because playing and watching locally is better for the reader.
- **Why raylib→wasm.** The author picked it because it extends to more PufferLib ocean envs and to nanoG1. nanoG1 already does one C file with native and wasm builds, Modal training, and `puffernet.h` running the policy in the browser.
- **Why PufferLib format.** It followed from the pasted puffer guide (§1). Claude rewrote flappy in the `squared` shape: `Log`, `Env { Log; Agent agents[1]; ... }`, `puf_*` functions.
- **Turn-based play went back and forth.**
  - The author spotted that Claude's real-time widget added reaction time the agent doesn't face. They asked for a turn-based widget, with "position carries over" being fine.
  - In puffer format, Claude laid out two options: *waiting* inside `puf_render`, or *latching* the key like triple-triad. The author first chose waiting.
  - Then they asked "could we also just slow the game instead of blocking". Claude framed the trade-off as matching the agent's experience exactly versus just not feeling rushed. The author chose 1 step/s. That reversed the turn-based choice in favour of less machinery and puffer's own pattern.
- **rand_r differs between libcs.** The author asked "what does pufferlib do about this?" Puffer doesn't care, and has no native-vs-web tests. The author accepted the same stance: compare behaviour, not bits.
- **SKILL_ISSUES.md refactor.** The author found the guide's language "a bit harsh" but asked for the refactor. Claude agreed, on the grounds that shorter code is easier to teach and it's puffer's idiom. One tension was noted: `squared.h` itself breaks the guide.
- **Naming, which the author called pedagogically important.** "sorry i dont mean to naming bikeshed but its important pedagogically":
  - they wanted flappy's fields grouped as a sub-struct;
  - they rejected `FlappyState` in favour of `FlappyEnv`, so the code makes "puffer's wrapper `Env`" versus "my game `FlappyEnv`" visible;
  - `flappy` was renamed to `flappy_env`.
- **`next_pipe` became `spawn_pipe`.** The author had read `next_pipe` as "step the environment" and `puf_step` as "stepping the framework". That's a misreading readers will likely share (inferred), worth heading off in prose.
  - The author also tried removing the helper by having `puf_reset` call `puf_step`.
  - Tracing it showed the inner step overwrites `terminals[0]`, so episodes would never end. The helper stays.
- **Comments in code.** The author asked Claude to remove its comments from the code blocks. The exception they accepted: a comment showing puffer's `Agent` struct under the `#include`. Their words: "this is a good reason to have a comment", since the reader can't see that header.
- **One C cell for the whole env file.** The author said splitting C into several cells "doesn't make sense if they're not going to be runnable by themselves" and chose the whole env file as one editable cell (option c). Rendering is therefore no longer protected from the reader.
- **Constraining what the reader writes is still an open wish.** The author asked whether the reader could write only logic and control flow, while we keep rendering and checks. The answer has been deferred into "one whole-file cell for now".

### Standalone blogs/
- **The author proposed it:** vendor PufferLib into `blogs/` so it is "standalone other than box for now".
- Claude agreed and dropped its earlier recommendation of a shared top-level `puffer/`. The reasons:
  - most of the code is third-party, pinned to an upstream commit;
  - `blogs` will probably become public or its own repo;
  - robots wants fast training builds, while blogs wants stable published chapters.
- The cost accepted: a duplicated 160-line shim. If the two copies diverge enough to hurt, extract it then.

## 4. How the author wants to collaborate on this project

- **Prose is the author's alone.** "i dont want you to write any of the text. id like to do this collaboratively."
  - They'd "arguably" also prefer to write all the solution code, while Claude writes the tests, following the matklad testing doc.
  - Later split: the author owns stubs and text; Claude owns diagrams, interactive pieces, checks and cell machinery.
  - Exception: the author asked Claude to write the env for now and cut it back to stubs later.
  - Stubbed prose is a placeholder comment.
- **Prose feedback only if major.** The one major point raised was that Pavlov is classical conditioning, while RL is closer to operant conditioning.
- **Socratic, one question at a time.** The author asked "one question at a time" early on.
  - They often ask "wdyt" when they want Claude's opinion, and take recommendations when given with reasons.
  - They also push back: "why don't we use marimo again", "is there a reason spawn_pipe is its own thing".
- **Spikes in worktrees, run by subagents.** The author likes comparing options with spikes in separate worktrees, built by subagents "so we can discuss", for example marimo vs Markdown, and the page builder while they worked on `puf_step`.
- **Build early.** "id like to start coding/making it work if we're unblocked." "i want to start writing the website to figure out what it ends up looking like." Open questions get deferred rather than blocking the build.
- **The author plays the student.** They write `puf_step` themselves, with hints rather than answers.
  - They named their C gaps openly: pointers were "very vague", they thought structs were namespaces and that "a C type is a tagged union", and void functions confused them.
  - Claude's observation: if the author needs a C primer, readers will too.
  - The author wants inline comments or links out to a C guide, not a separate course. The C crash-course format (chat, artifact page, or explain as we go) was never chosen; the author moved straight to writing `puf_step`.
- **The hint ladder was the author's idea**, born while doing that exercise. Hints are derived from the annotated solution and shown beside the editor, with the `// hint_i` syntax.
- **Writing tools.** Prose is written in nvim, with `check.py` run in a terminal split.

## 5. Options considered and rejected (with the reason)

| option | why not |
|---|---|
| In-browser runtime first (Pyodide + YoWASP clang) | No torch in Pyodide; no crash isolation; 23 MB compiler; reader hardware varies, so budgets are unfair. Kept as a later backend (spike branch preserved). |
| marimo as format or framework | Fights the latest-passing gating; 4 hacks; prose and C as strings; 27 MB static build. |
| Hand-written HTML (ezyang) or Jupytext `.py` (srush) | Offered as format options; the author narrowed to Markdown or marimo without discussing these. |
| Relative speed budgets | Unnecessary once everything runs on pinned sandbox hardware. |
| Structured failure types | Text in an output pane is enough for now. |
| Supervised-learning detour before REINFORCE | The author wants the simpler play → "can something do this autonomously?" → MLP arc. |
| Black-box trainer in ch.1 (the puffer guide's order) | The author chose to have the reader write REINFORCE in ch.1. |
| Probe envs as content | Too "unit test"; used only as check fixtures. |
| Dino game | Dropped right away; it would add delayed consequences and rare actions to ch.1. |
| JS-canvas rendering | raylib→wasm reuses puffer's `c_render` and extends to the ocean envs and nanoG1. |
| Waiting inside `puf_render` for turn-based play | Slowing the harness to 1 step/s is less machinery and matches puffer's pattern. |
| Exact native-vs-wasm replay (own RNG or portable `rand_r`) | Puffer doesn't attempt it; behavioural equivalence is enough. |
| Several C cells stitched together | Not runnable on their own; one whole-file cell instead. |
| Hand-written hint levels; hints replacing the editor | They drift from the solution and overwrite the reader's work. |
| Private solutions file or private repo | Public solutions are acceptable. |
| Shared top-level `puffer/` for robots and blogs | blogs should be standalone; vendored third-party code duplicates cheaply. |
| `puf_reset` calling `puf_step` | Overwrites `terminals[0]`, so episodes never end. |
| Using vmux itself | Closed source, and it runs on its own Modal account. The design is borrowed instead. |

## 6. Open threads and floated ideas

**Pedagogy and content**
- Where Catch goes: (a) before the MLP, (b) after it as the harder game, or (c) at the start of chapter 2. It may become the env the reader writes.
- Whether the reader writes flappy at all. The author will decide "if it's instructive".
- Which parts of flappy the reader writes. Claude proposed the state struct, the obs encoding, reset and step, with plumbing and render given. The present answer is the whole file, with `puf_step` as the exercise.
- Ideas Claude raised for the author to settle while writing:
  - a C primer for the series;
  - random search over the weights as a lead-in to REINFORCE;
  - the 0/+1 reward shift as a hook for baselines;
  - observation vs state as the setup for RNNs;
  - a sentence saying "observations, actions, rewards, terminals are just arrays";
  - gym's `return obs, reward, done` against puffer's `void` plus out-arrays. The author asked "why are they all voids"; Tiger Style's "keep leaf functions pure" was offered as the partner idea.
- A list or grid of cool RL results in the intro. Claude offered to make the embeds; it's unclear whether the author wants that.
- Colored equations and terms: whether and where to use them.
- Whether the LSTM chapter comes before PPO (from the author's original outline: "maybe").

**Runtime and infrastructure**
- Token path: (i) we hold the reader's token, encrypted, or (ii) the reader runs `modal deploy` into their own workspace.
- Whether Modal's unpublished OAuth would be open to us (email Modal). Where Modal's terms draw the line on products built on top of it.
- Growing `box` into the session's remote half, with autoresearch as a provider.
- The inline assistant on pi-durable sharing the session's Durable Object, constrained to hints.
- Watching a trained policy in the browser via `puffernet.h`; check which layers it supports before designing the LSTM chapters.
- A browser backend later (the C+Pyodide spike branch is kept for this).
- Hosting the large compiler and assets on R2.
- A read-only `given` panel versus protecting render code from reader edits.
- Page-builder questions from the handoff:
  - unpassed edits are lost on reload;
  - stale marking downstream when an upstream cell re-passes with different code;
  - placeholders show on the page, with no draft/publish switch;
  - the reference wasm is visible before the reader's env passes.

**Funnel**
- Readers must set up Modal before seeing anything run. If that turns out to hurt, Claude's fallback was a precomputed demo opening chapter 1, srush-style. It hasn't been needed so far (inferred, given the 2 s cold starts).
