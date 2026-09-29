# Handoff — robots sdk + RL learning (2026-09-20)

All on `main`. Design notes in `robots/docs/notes.md`.

## What exists

**SDK** (`robots/`) — a minimal training toolkit. Data + functions, no nn.Module.

- **`tree.py`** — `register_pytree(cls)` (weight dataclasses are torch pytrees, so
  `torch.func.grad` takes/returns them), `tree_map`, `tree_copy_`, `tensor_leaves`.
- **`optim.py`** — Adam as data + pure functions. `AdamParams` (config), `AdamState(m, v)`,
  `init_adam(params)`, `adam_scalars(cfg, step, device)` (host side, 1-based),
  `adam_update` (pure) / `adam_update_` (in place). The loop owns the int step.
- **`train.py`** — generic: `forward_backward(loss_fn, w, inputs) -> (grads: W, metrics)`,
  `train_step(loss_fn, w, opt_state, inputs, cfg, step) -> (opt_state, metrics)`
  (= forward_backward + adam_update_), `train_loop`, `to_floats`. Loss fns return
  `(loss, dict[str, Tensor])`, no `.item()`. RL: `compute_loss_fn_inputs(batch, gamma)
  -> LossFnInputs` (dict: obs/actions/returns/advantages; bootstrapped, pure),
  `reinforce_loss(pi, inputs)`, `value_loss(vf, inputs)` (separate weights, separate
  train_steps), `evaluate`, `record_episode`.
- **`collect.py`** — on-policy collection, state in / state out:
  `rollout_init(env)`, `collect(env, pi, vf, state, n) -> (state, Batch)`. Episodes span batches;
  records `bootstrap_value` (truncation) and `last_value` (batch cut).
- **`models.py`** — `PolicyWeights` (logits only), `ValueWeights` (own trunk), `WMWeights` +
  free forward functions (`policy_forward`, `value_forward`, `wm_forward`), `policy_value`,
  `wm_loss`, `transitions_to_inputs`.
- **`rollout.py`** — `collect_transitions` (world-model data), `imagine_rollout(wm, pi, vf, ...) -> Batch`.
- **`lm.py`** — GPT-2 frozen dataclasses + forward, `cross_entropy_loss`, `token_loader`,
  `generate`. Self-contained, no kelpie dependency.

**Examples** (`examples/`):
- `cartpole_modelfree.py` — model-free actor-critic: collect → compute_loss_fn_inputs → two
  train_steps (policy, value). With a shared trunk (2026-09-27) the value loss swamped the policy;
  policy and value are now separate networks. Learning quality not re-measured yet.
- `compare_runs.py` — compare run jsonl files (eval curves + metric trends).
- `cartpole_modelbased.py` — model-based (world model + imagined rollouts). Runs on the new API; doesn't learn yet.
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
- **Optimizer is config + state data** (`AdamParams`, `AdamState`) and pure functions; the loop
  owns the step counter and calls `train_step(..., cfg, step)`.
- **Examples own their loops.** No `run()` or `train_loop` in the sdk. The example writes
  `for i in range(n): m = train_step(...)`. Simpler to read, extend, modify.
- **Inputs are whatever the loss reads.** Model-free: `collect` + `compute_loss_fn_inputs`.
  Model-based: `imagine_rollout` + `compute_loss_fn_inputs`. LLM: `(token_loader(...)(), config)`.
  Same `train_step`.
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
   kelpie + leviathan + robots). `tree_map`, `forward_backward`, `train_step`, `AdamParams`,
   `adam_update_` are already generic.
4. **Muon optimizer.** Write `MuonParams` + `muon_step`. Needed for LLM training at scale
   (nanochat/modded-nanogpt style).
5. **RL understanding doc.** Discovery-fiction style (like the LLM/GPT notes on arb8020.github.io).
   Start from "I built a training loop that doesn't converge" and write toward understanding.
6. **Dashboard verification script.** Poteto-mode scripted feature proofs via agent-browser
   instead of ad-hoc screenshots. Feature map: run picker, metric panels, log drawer, rollout
   playback, step picker.
