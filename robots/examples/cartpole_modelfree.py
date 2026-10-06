"""Model-free actor-critic on CartPole: separate policy and value networks, two train_steps.

Self-contained: everything except Adam (robots.core) and the pytree helpers
(robots.core) is defined in this file.

  PYTHONPATH=. robots/.venv/bin/python robots/examples/cartpole_modelfree.py --name modelfree-fixed --iters 500
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, TypeAlias, TypeVar

import gymnasium
import torch
import torch.nn.functional as F

from observe import artifact, metrics, setup_logging, span
from observe.git import git_info
from robots.core import AdamParams, AdamState, adam_scalars, adam_update_, init_adam
from robots.core import register_pytree, tensor_leaves

# ---------------------------------------------------------------------------
# Model: one MLP type; policy (pi) and value (vf) are separate MLPs (no shared trunk)
# ---------------------------------------------------------------------------


@register_pytree
@dataclass(frozen=True)
class Linear:
    """Affine layer in nn.Linear layout: x @ w.T + b.

    Frozen dataclass — fields can't be reassigned, but the tensors themselves
    are mutable (the optimizer updates them in place).
    """

    w: torch.Tensor  # (out, in)
    b: torch.Tensor  # (out,)


@register_pytree
@dataclass(frozen=True)
class MLP:
    """Stack of Linear layers: ReLU between layers, none after the last."""

    layers: tuple[Linear, ...]


def init_linear(in_dim: int, out_dim: int) -> Linear:
    """Xavier-uniform weight + zero bias, both with requires_grad=True."""
    w = torch.empty(out_dim, in_dim, requires_grad=True)
    torch.nn.init.xavier_uniform_(w)
    b = torch.zeros(out_dim, requires_grad=True)
    return Linear(w=w, b=b)


def init_mlp(sizes: list[int]) -> MLP:
    """sizes = [in, hidden..., out], e.g. [4, 64, 64, 2]. Layers initialized in order."""
    return MLP(layers=tuple(init_linear(i, o) for i, o in zip(sizes[:-1], sizes[1:], strict=True)))


def mlp_forward(w: MLP, x: torch.Tensor) -> torch.Tensor:
    """x (batch, sizes[0]) -> (batch, sizes[-1])."""
    *hidden, last = w.layers
    for layer in hidden:
        x = F.relu(x @ layer.w.T + layer.b)  # (batch, hidden)
    return x @ last.w.T + last.b  # (batch, out)


def policy_act(pi: MLP, obs: torch.Tensor) -> int:
    """Sample one action from the policy MLP (obs -> logits). obs: (obs_dim,)."""
    with torch.no_grad():
        logits = mlp_forward(pi, obs.unsqueeze(0))  # (1, act_dim)
        dist = torch.distributions.Categorical(logits=logits)
        return dist.sample().item()


def get_value(vf: MLP, obs: torch.Tensor) -> float:
    """Detached V(obs) for one obs from the value MLP (obs -> (1,)). obs: (obs_dim,)."""
    with torch.no_grad():
        return mlp_forward(vf, obs.unsqueeze(0))[:, 0].item()


# ---------------------------------------------------------------------------
# Collection: on-policy experience from the real env. State in, state out.
#
# Layers (each built from the one above it):
#     rollout_init(env, seed)      -> RolloutState                         # reset once, at the start
#     collect_step(env, pi, vf, state) -> (state, Step, EpisodeEnd | None)   # one env step
#     collect(env, pi, vf, state, n)   -> (state, Batch)                     # n steps, continues episodes
#
# pi picks actions; vf supplies every recorded value (Step.value, bootstrap_value, last_value).
#
# Nothing here resets between batches: the only resets happen in rollout_init and
# inside collect_step when an episode ends. So an episode can span many batches.
#
# Every value needed to compute training targets is recorded here, at collection
# time, so turning a Batch into loss inputs is a pure function (no network calls):
#     Step.bootstrap_value = V(next_obs) on a truncated step, else 0.0
#     Batch.last_value     = V(obs the next batch acts on), for the cut at the batch end
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RolloutState:
    """What must survive between batches."""

    obs: torch.Tensor          # (obs_dim,) the obs the next step acts on
    episode_return: float      # running reward total of the unfinished episode
    episode_len: int           # steps so far in the unfinished episode


@dataclass(frozen=True)
class Step:
    """One recorded step."""

    obs: torch.Tensor          # (obs_dim,) obs the action was chosen from
    action: int
    reward: float
    terminated: bool           # real ending (pole fell): future reward = 0
    truncated: bool            # time limit: future reward unknown -> bootstrap with V(next_obs)
    value: float               # detached V(obs), from collection time
    bootstrap_value: float     # detached V(next_obs) if truncated (and not terminated), else 0.0


@dataclass(frozen=True)
class EpisodeEnd:
    """Emitted by collect_step when an episode finishes. For logging."""

    episode_return: float
    episode_len: int


@dataclass(frozen=True)
class Batch:
    steps: list[Step]
    episodes: list[EpisodeEnd]  # episodes that FINISHED during this batch
    last_value: float           # detached V(obs the NEXT batch acts on): bootstraps the cut at the batch end


def _to_tensor(obs) -> torch.Tensor:
    return torch.tensor(obs, dtype=torch.float32)


def rollout_init(env: gymnasium.Env, seed: int | None = None) -> RolloutState:
    obs, _ = env.reset(seed=seed)
    return RolloutState(obs=_to_tensor(obs), episode_return=0.0, episode_len=0)


def collect_step(
    env: gymnasium.Env,
    pi: MLP,
    vf: MLP,
    state: RolloutState,
) -> tuple[RolloutState, Step, EpisodeEnd | None]:
    """Act once, step the env, record it. Resets the env if the episode ended."""
    with torch.no_grad():
        logits = mlp_forward(pi, state.obs.unsqueeze(0))  # (1, act_dim)
        dist = torch.distributions.Categorical(logits=logits)
        action = dist.sample()

    value = get_value(vf, state.obs)
    next_obs, reward, terminated, truncated, _ = env.step(action.item())
    next_obs_t = _to_tensor(next_obs)

    # gymnasium can report terminated AND truncated on the time-limit step.
    # A real ending wins: the future is known to be zero, nothing to bootstrap.
    needs_bootstrap = bool(truncated) and not bool(terminated)
    bootstrap_value = get_value(vf, next_obs_t) if needs_bootstrap else 0.0

    step = Step(
        obs=state.obs,
        action=action.item(),
        reward=float(reward),
        terminated=bool(terminated),
        truncated=bool(truncated),
        value=value,
        bootstrap_value=bootstrap_value,
    )

    ep_return = state.episode_return + float(reward)
    ep_len = state.episode_len + 1

    if terminated or truncated:
        ended = EpisodeEnd(episode_return=ep_return, episode_len=ep_len)
        return rollout_init(env), step, ended

    return replace(state, obs=next_obs_t, episode_return=ep_return, episode_len=ep_len), step, None


def collect(
    env: gymnasium.Env,
    pi: MLP,
    vf: MLP,
    state: RolloutState,
    num_steps: int,
) -> tuple[RolloutState, Batch]:
    """num_steps of experience. Picks up exactly where `state` left off."""
    assert num_steps > 0
    steps: list[Step] = []
    episodes: list[EpisodeEnd] = []
    for _ in range(num_steps):
        state, step, ended = collect_step(env, pi, vf, state)
        steps.append(step)
        if ended is not None:
            episodes.append(ended)
    return state, Batch(steps=steps, episodes=episodes, last_value=get_value(vf, state.obs))


# ---------------------------------------------------------------------------
# Algorithm: batch -> loss inputs (pure)
# ---------------------------------------------------------------------------

# A processed Batch (Tinker style: named tensors, losses read the keys they need).
# compute_loss_fn_inputs produces:
#   "obs"        (T, obs_dim) float
#   "actions"    (T,) long
#   "returns"    (T,) value target
#   "advantages" (T,) returns - collected V(obs); constants, no grad
LossFnInputs: TypeAlias = dict[str, torch.Tensor]


def compute_returns(steps: list[Step], last_value: float, gamma: float) -> list[float]:
    """Discounted, bootstrapped returns, computed backwards.

    Where the future comes from, per step:
        episode ended here (terminated or truncated) -> step.bootstrap_value
            (0.0 on termination, V(next_obs) on truncation — recorded at collection)
        otherwise -> the next step's return (last_value for the batch's final step)
    """
    assert 0.0 <= gamma <= 1.0
    returns: list[float] = []
    g = last_value
    for step in reversed(steps):
        # Invalid state: a real ending has no future to bootstrap from.
        assert not step.terminated or step.bootstrap_value == 0.0, step
        ended = step.terminated or step.truncated
        future = step.bootstrap_value if ended else g
        g = step.reward + gamma * future
        returns.append(g)
    returns.reverse()
    return returns


def compute_loss_fn_inputs(batch: Batch, gamma: float) -> LossFnInputs:
    """Batch -> LossFnInputs. Pure: no network calls, everything was recorded at collection."""
    assert len(batch.steps) > 0
    returns = torch.tensor(compute_returns(batch.steps, batch.last_value, gamma), dtype=torch.float32)
    values = torch.tensor([s.value for s in batch.steps], dtype=torch.float32)
    return {
        "obs": torch.stack([s.obs for s in batch.steps]),
        "actions": torch.tensor([s.action for s in batch.steps], dtype=torch.long),
        "returns": returns,
        "advantages": returns - values,
    }


# ---------------------------------------------------------------------------
# Algorithm: losses. All (weights, inputs) -> (loss, metrics), torch.func-safe:
# no .item(), no data-dependent Python control flow, metrics are tensors.
# Policy and value are separate weight objects, trained by separate train_steps.
# ---------------------------------------------------------------------------

def reinforce_loss(
    pi: MLP,
    inputs: LossFnInputs,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    """Policy-gradient term: mean(-log pi(a|s) * advantage). Reads obs, actions, advantages."""
    logits = mlp_forward(pi, inputs["obs"])                                         # (T, act_dim)
    log_probs_all = F.log_softmax(logits, dim=-1)                                   # (T, act_dim)
    logprob = log_probs_all.gather(1, inputs["actions"].unsqueeze(1)).squeeze(1)    # (T,)
    entropy = -(log_probs_all.exp() * log_probs_all).sum(dim=-1)                    # (T,)
    advantages = inputs["advantages"]
    loss = -(logprob * advantages).mean()
    metrics = {
        "pi_loss": loss.detach(),
        "entropy": entropy.mean().detach(),
        "advantage_mean": advantages.mean(),
        "advantage_std": advantages.std(correction=0),
    }
    return loss, metrics


def value_loss(
    vf: MLP,
    inputs: LossFnInputs,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    """Value regression: mean((V(obs) - return)^2). Reads obs, returns."""
    values = mlp_forward(vf, inputs["obs"])[:, 0]                                   # (T,)
    returns = inputs["returns"]
    loss = ((values - returns) ** 2).mean()
    metrics = {
        "value_loss": loss.detach(),
        "value_mean": values.mean().detach(),
        "return_mean": returns.mean(),
    }
    return loss, metrics


# ---------------------------------------------------------------------------
# Train: one generic step
#
#   train_step(loss_fn, weights, opt_state, inputs, cfg, step)
#     = forward_backward(loss_fn, weights, inputs)             -> grads, metrics
#     + adam_update_(weights, grads, opt_state, cfg, adam_scalars(cfg, step, device_of(weights)))
# ---------------------------------------------------------------------------

W = TypeVar("W")
I = TypeVar("I")

# (weights, inputs) -> (scalar loss, metrics). Metrics are tensors so a LossFn
# stays torch.func-safe (no .item()); convert with to_floats at the logging edge.
LossFn = Callable[[W, I], tuple[torch.Tensor, dict[str, torch.Tensor]]]
Metrics = dict[str, torch.Tensor]


def forward_backward(
    loss_fn: LossFn[W, I],
    weights: W,
    inputs: I,
) -> tuple[W, Metrics]:
    """Gradients of loss_fn w.r.t. weights, plus the loss_fn's metrics.

    grads has the same dataclass type as weights (one grad tensor per weight
    tensor). Nothing is mutated: no .grad, no optimizer. Requires the weight
    dataclass to be a registered pytree (robots.core.register_pytree).
    The scalar loss itself is not returned: loss_fns report it in their metrics.
    """
    grad_fn = torch.func.grad_and_value(loss_fn, argnums=0, has_aux=True)
    grads, (_loss, metrics) = grad_fn(weights, inputs)
    assert type(grads) is type(weights)
    return grads, metrics


def device_of(weights: Any) -> torch.device:
    """The device of a weight tree (asserts all leaves agree)."""
    leaves = tensor_leaves(weights)
    assert len(leaves) > 0
    device = leaves[0].device
    assert all(x.device == device for x in leaves), "weights span multiple devices"
    return device


def train_step(
    loss_fn: LossFn[W, I],
    weights: W,
    opt_state: AdamState[W],
    inputs: I,
    cfg: AdamParams,
    step: int,
) -> tuple[AdamState[W], Metrics]:
    """One update: forward_backward, then Adam in place on weights. step is 1-based."""
    grads, metrics = forward_backward(loss_fn, weights, inputs)
    scalars = adam_scalars(cfg, step, device_of(weights))
    new_state = adam_update_(weights, grads, opt_state, cfg, scalars)
    return new_state, metrics


def to_floats(metrics: Metrics) -> dict[str, float]:
    """Logging edge: tensor metrics -> Python floats (one host sync per metric)."""
    return {k: v.item() for k, v in metrics.items()}


# ---------------------------------------------------------------------------
# Eval + record
# ---------------------------------------------------------------------------

def evaluate(env: gymnasium.Env, pi: MLP, num_episodes: int = 3) -> tuple[float, float]:
    """Run policy in real env, return (mean reward, mean episode length)."""
    total = 0.0
    total_len = 0
    for _ in range(num_episodes):
        obs, _ = env.reset()
        obs_t = torch.tensor(obs, dtype=torch.float32)
        ep_reward = 0.0
        ep_len = 0
        done = False
        while not done:
            action = policy_act(pi, obs_t)
            obs, reward, terminated, truncated, _ = env.step(action)
            obs_t = torch.tensor(obs, dtype=torch.float32)
            ep_reward += reward
            ep_len += 1
            done = terminated or truncated
        total += ep_reward
        total_len += ep_len
    return total / num_episodes, total_len / num_episodes


def record_episode(env: gymnasium.Env, pi: MLP) -> dict[str, Any]:
    """Play one greedy episode and return it as a trajectory artifact payload."""
    obs, _ = env.reset()
    observations: list[list[float]] = [[float(x) for x in obs]]
    actions: list[int] = []
    rewards: list[float] = []

    done = False
    while not done:
        action = policy_act(pi, torch.tensor(obs, dtype=torch.float32))
        obs, reward, terminated, truncated, _ = env.step(action)
        actions.append(int(action))
        rewards.append(float(reward))
        observations.append([float(x) for x in obs])
        done = terminated or truncated

    return {
        "env": env.spec.id if env.spec is not None else "unknown",
        "obs": observations,
        "actions": actions,
        "rewards": rewards,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description="Model-free actor-critic on CartPole")
    p.add_argument("--name", default=None, help="Run name")
    p.add_argument("--iters", type=int, default=500)
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--rollout-steps", type=int, default=200)
    p.add_argument("--gamma", type=float, default=0.99)
    p.add_argument("--vf-lr", type=float, default=None, help="Value-function lr (default: --lr)")
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()

    # --- setup ---
    run_name = args.name or "modelfree"
    setup_logging(
        log_file=f"runs/{run_name}.jsonl",
        static_fields={"run_name": run_name, **git_info()},
    )
    torch.manual_seed(args.seed)

    # Two envs: the collector's episode state lives across iterations, so eval
    # (which resets its env) must not share it.
    env = gymnasium.make("CartPole-v1")
    eval_env = gymnasium.make("CartPole-v1")
    eval_env.reset(seed=args.seed + 1)  # later unseeded resets continue this RNG: runs are reproducible
    pi = init_mlp([4, 64, 64, 2])  # obs -> action logits
    vf = init_mlp([4, 64, 64, 1])  # obs -> V(obs)
    pi_cfg = AdamParams(lr=args.lr)
    vf_cfg = AdamParams(lr=args.vf_lr if args.vf_lr is not None else args.lr)
    pi_opt, vf_opt = init_adam(pi), init_adam(vf)
    state = rollout_init(env, seed=args.seed)

    # --- train ---
    for i in range(1, args.iters + 1):
        state, batch = collect(env, pi, vf, state, num_steps=args.rollout_steps)
        inputs = compute_loss_fn_inputs(batch, gamma=args.gamma)  # advantages use the pre-update vf
        pi_opt, m_pi = train_step(reinforce_loss, pi, pi_opt, inputs, pi_cfg, step=i)
        vf_opt, m_vf = train_step(value_loss, vf, vf_opt, inputs, vf_cfg, step=i)

        m_log = to_floats({**m_pi, **m_vf})
        m_log["train_episodes"] = float(len(batch.episodes))
        if batch.episodes:
            m_log["train_ep_return"] = sum(e.episode_return for e in batch.episodes) / len(batch.episodes)
            m_log["train_ep_len"] = sum(e.episode_len for e in batch.episodes) / len(batch.episodes)
        metrics(m_log, step=i)

        if i % 10 == 0:
            with span("robots.eval", attributes={"step": i}):
                eval_reward, eval_ep_len = evaluate(eval_env, pi)
                trajectory = record_episode(eval_env, pi)
            metrics({"eval_reward": eval_reward, "eval_ep_len": eval_ep_len}, step=i)
            artifact("rollout", trajectory, mime="application/x-trajectory+json", step=i)
            print(
                f"step {i}: eval_reward={eval_reward:.1f} "
                f"train_ep_return={m_log.get('train_ep_return', float('nan')):.1f} "
                f"value_loss={m_log['value_loss']:.2f} entropy={m_log['entropy']:.3f}"
            )


if __name__ == "__main__":
    main()
