# Handoff — robots sdk + RL learning (2026-09-20)

All on `main`. Design notes in `robots/docs/notes.md`.

## What exists

**SDK** (`robots/`) — a minimal training toolkit. Data + functions, no nn.Module.

- **`optim.py`** — Adam from scratch (15 lines of math, parity-tested against torch.optim).
  `AdamParams` config dataclass (tinker-style). `OptimizerHandle` (zero/step pair).
  LR scheduling, gradient accumulation, param groups.
- **`train.py`** — `train_step(get_batch, loss_fn, weights, opt)` — one training step.
  `reinforce_loss`, `evaluate`, `record_episode` for RL.
- **`models.py`** — `PolicyWeights`, `WMWeights` frozen dataclasses + free forward functions.
  Explicit matmuls (`obs @ w.w1.T + w.b1`), no nn.Module.
- **`rollout.py`** — `PolicyStep`, `Transition`, `collect_transitions`, `imagine_rollout`,
  `policy_collector` (returns a `() -> batch` callable for model-free RL).
- **`tree.py`** — `tensor_leaves(tree)` walks any frozen dataclass, returns all tensors.
  `trainable(tree)` clones with requires_grad. Replaces hand-written `*_params()`.
- **`lm.py`** — GPT-2 frozen dataclasses + training forward (standard causal attention,
  `F.scaled_dot_product_attention(is_causal=True)`). `cross_entropy_loss`, `token_loader`,
  `generate`. Self-contained, no kelpie dependency.

**Examples** (`examples/`):
- `cartpole_modelfree.py` — model-free REINFORCE. Learns: eval_reward 25 → 300.
- `cartpole_modelbased.py` — model-based (world model + imagined rollouts). Doesn't learn yet.
- `gpt2_pretrain.py` — GPT-2 (124M) on tiny shakespeare. Loss 4.87 → 4.54 in 10 steps.

**Dashboard** (`observe/dashboard/`) — Vega-Lite charts, DuckDB queries, CartPole rollout
renderer with step picker. See `observe/HANDOFF.md` for details.

**Clip tool** (`tools/clip`) — Bun/TS web clipper. Defuddle first, browser fallback for
JS-rendered pages.

## Run it

```bash
# Model-free CartPole (learns)
PYTHONPATH=. robots/.venv/bin/python examples/cartpole_modelfree.py --name test --iters 500

# GPT-2 pretrain (CPU, small)
PYTHONPATH=. robots/.venv/bin/python examples/gpt2_pretrain.py --iters 10

# Dashboard (separate terminal)
cd observe/dashboard && bun install && bun run build && bun run serve
```

Gates: `cd robots && uv run pytest`, `cd observe/dashboard && bun run typecheck && bun run lint && bun run test`.

## Key design decisions

- **Weights are data, forward is a function.** Frozen dataclasses + free functions. No nn.Module,
  no self, no .parameters(). Dotfiles say: "classes are for enforcing invariants across shared
  mutable state. If you don't have that, a function and a dataclass are simpler."
- **Loss function returns `(loss, metrics_dict)`.** Tinker/leviathan pattern. The dashboard
  auto-discovers metric names.
- **Optimizer is a config dataclass** (`AdamParams`), not a closure or an object. Matches tinker's
  `optim_step(AdamParams(...))`. `make_optimizer` dispatches on config type.
- **Examples own their loops.** No `run()` or `train_loop` in the sdk. The example writes
  `for i in range(n): m = train_step(...)`. Simpler to read, extend, modify.
- **`get_batch` is pluggable.** Model-free: `policy_collector(env, pi)`. Model-based: imagine
  from world model. LLM: `token_loader(text, seq_len, batch_size)`. Same `train_step`.
- **Mutation now, functional signature later.** Adam mutates tensors in place. The API shape
  (return metrics, could return new weights) is designed for torch.compile/JIT later, where
  the compiler can reuse memory automatically.

## What we learned

- **Model-based RL failed because the world model was bad.** Advantages were all positive
  (value function underpredicting), policy got "do more of everything" signal. Model-free
  REINFORCE on real experience works immediately.
- **The Tworek quote** ("more questions are deep learning questions than people realized") is
  the north star. Hyperparameter tuning often papers over real problems.
- **Policy churn** (Carmack/Schaul): in deep RL, SGD on dense ReLUs randomly rewrites the
  greedy policy ~10% of states per update. Exploration hyperparameters are swamped by this
  implicit churn. See `robots/docs/notes.md`.

## Next

1. **Debug why model-based doesn't learn.** World model predicts episodes too short? Rewards
   wrong? Log imagined vs real episode lengths to diagnose.
2. **PPO.** Write `ppo_loss` with same `LossFn` signature. Clipping is a fix for REINFORCE's
   high variance. The functional refactor makes this a ~30 line addition.
3. **Extract the training sdk** into its own package (working name: the intersection of
   kelpie + leviathan + robots). `tensor_leaves`, `trainable`, `train_step`, `AdamParams`,
   `make_optimizer` are already generic.
4. **Muon optimizer.** Write `MuonParams` + `muon_step`. Needed for LLM training at scale
   (nanochat/modded-nanogpt style).
5. **RL understanding doc.** Discovery-fiction style (like the LLM/GPT notes on arb8020.github.io).
   Start from "I built a training loop that doesn't converge" and write toward understanding.
6. **Dashboard verification script.** Poteto-mode scripted feature proofs via agent-browser
   instead of ad-hoc screenshots. Feature map: run picker, metric panels, log drawer, rollout
   playback, step picker.
