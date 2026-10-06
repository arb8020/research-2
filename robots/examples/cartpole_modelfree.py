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
from robots.core import register_pytree


@register_pytree
@dataclass(frozen=True)
class Linear:
    w: torch.Tensor
    b: torch.Tensor


@register_pytree
@dataclass(frozen=True)
class MLP:
    layers: tuple[Linear, ...]


def init_linear(in_dim: int, out_dim: int) -> Linear:
    w = torch.empty(out_dim, in_dim, requires_grad=True)
    torch.nn.init.xavier_uniform_(w)
    b = torch.zeros(out_dim, requires_grad=True)
    return Linear(w=w, b=b)


def init_mlp(sizes: list[int]) -> MLP:
    return MLP(layers=tuple(init_linear(i, o) for i, o in zip(sizes[:-1], sizes[1:], strict=True)))


def mlp_forward(w: MLP, x: torch.Tensor) -> torch.Tensor:
    *hidden, last = w.layers
    for layer in hidden:
        x = F.relu(x @ layer.w.T + layer.b)
    return x @ last.w.T + last.b


def policy_act(pi: MLP, obs: torch.Tensor) -> int:
    with torch.no_grad():
        logits = mlp_forward(pi, obs.unsqueeze(0))
        dist = torch.distributions.Categorical(logits=logits)
        return dist.sample().item()


def get_value(vf: MLP, obs: torch.Tensor) -> float:
    with torch.no_grad():
        return mlp_forward(vf, obs.unsqueeze(0))[:, 0].item()


@dataclass(frozen=True)
class RolloutState:
    obs: torch.Tensor
    episode_return: float
    episode_len: int


@dataclass(frozen=True)
class Outcome:
    reward: float
    terminated: bool
    truncated: bool
    bootstrap_value: float


@dataclass(frozen=True)
class Step:
    obs: torch.Tensor
    action: int
    value: float
    outcome: Outcome


@dataclass(frozen=True)
class EpisodeEnd:
    episode_return: float
    episode_len: int


@dataclass(frozen=True)
class Batch:
    steps: list[Step]
    episodes: list[EpisodeEnd]
    last_value: float


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
    with torch.no_grad():
        logits = mlp_forward(pi, state.obs.unsqueeze(0))
        dist = torch.distributions.Categorical(logits=logits)
        action = dist.sample()

    value = get_value(vf, state.obs)
    next_obs, reward, terminated, truncated, _ = env.step(action.item())
    next_obs_t = _to_tensor(next_obs)

    # gymnasium's TimeLimit can report terminated AND truncated on the same step; termination wins.
    needs_bootstrap = bool(truncated) and not bool(terminated)
    bootstrap_value = get_value(vf, next_obs_t) if needs_bootstrap else 0.0

    step = Step(
        obs=state.obs,
        action=action.item(),
        value=value,
        outcome=Outcome(
            reward=float(reward),
            terminated=bool(terminated),
            truncated=bool(truncated),
            bootstrap_value=bootstrap_value,
        ),
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
    assert num_steps > 0
    steps: list[Step] = []
    episodes: list[EpisodeEnd] = []
    for _ in range(num_steps):
        state, step, ended = collect_step(env, pi, vf, state)
        steps.append(step)
        if ended is not None:
            episodes.append(ended)
    return state, Batch(steps=steps, episodes=episodes, last_value=get_value(vf, state.obs))


LossFnInputs: TypeAlias = dict[str, torch.Tensor]


def compute_returns(outcomes: list[Outcome], last_value: float, gamma: float) -> list[float]:
    assert 0.0 <= gamma <= 1.0
    returns: list[float] = []
    g = last_value
    for o in reversed(outcomes):
        assert not o.terminated or o.bootstrap_value == 0.0, o
        ended = o.terminated or o.truncated
        future = o.bootstrap_value if ended else g
        g = o.reward + gamma * future
        returns.append(g)
    returns.reverse()
    return returns


def compute_loss_fn_inputs(batch: Batch, gamma: float) -> LossFnInputs:
    assert len(batch.steps) > 0
    returns = torch.tensor(compute_returns([s.outcome for s in batch.steps], batch.last_value, gamma), dtype=torch.float32)
    values = torch.tensor([s.value for s in batch.steps], dtype=torch.float32)
    return {
        "obs": torch.stack([s.obs for s in batch.steps]),
        "actions": torch.tensor([s.action for s in batch.steps], dtype=torch.long),
        "returns": returns,
        "advantages": returns - values,
    }


def reinforce_loss(
    pi: MLP,
    inputs: LossFnInputs,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    logits = mlp_forward(pi, inputs["obs"])
    log_probs_all = F.log_softmax(logits, dim=-1)
    logprob = log_probs_all.gather(1, inputs["actions"].unsqueeze(1)).squeeze(1)
    entropy = -(log_probs_all.exp() * log_probs_all).sum(dim=-1)
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
    values = mlp_forward(vf, inputs["obs"])[:, 0]
    returns = inputs["returns"]
    loss = ((values - returns) ** 2).mean()
    metrics = {
        "value_loss": loss.detach(),
        "value_mean": values.mean().detach(),
        "return_mean": returns.mean(),
    }
    return loss, metrics


W = TypeVar("W")
I = TypeVar("I")

LossFn = Callable[[W, I], tuple[torch.Tensor, dict[str, torch.Tensor]]]
Metrics = dict[str, torch.Tensor]


def forward_backward(
    loss_fn: LossFn[W, I],
    weights: W,
    inputs: I,
) -> tuple[W, Metrics]:
    grad_fn = torch.func.grad_and_value(loss_fn, argnums=0, has_aux=True)
    grads, (_loss, metrics) = grad_fn(weights, inputs)
    assert type(grads) is type(weights)
    return grads, metrics


def train_step(
    loss_fn: LossFn[W, I],
    weights: W,
    opt_state: AdamState[W],
    inputs: I,
    cfg: AdamParams,
    step: int,
    device: torch.device,
) -> tuple[AdamState[W], Metrics]:
    grads, metrics = forward_backward(loss_fn, weights, inputs)
    scalars = adam_scalars(cfg, step, device)
    new_state = adam_update_(weights, grads, opt_state, cfg, scalars)
    return new_state, metrics


def to_floats(metrics: Metrics) -> dict[str, float]:
    return {k: v.item() for k, v in metrics.items()}


def evaluate(env: gymnasium.Env, pi: MLP, num_episodes: int = 3) -> list[dict[str, Any]]:
    """Returns application/x-trajectory+json payloads; the format is defined in observe/DESIGN.md."""
    assert num_episodes > 0
    env_id = env.spec.id if env.spec is not None else "unknown"
    trajectories: list[dict[str, Any]] = []
    for _ in range(num_episodes):
        obs, _ = env.reset()
        observations: list[list[float]] = [[float(x) for x in obs]]
        actions: list[int] = []
        rewards: list[float] = []
        done = False
        while not done:
            action = policy_act(pi, _to_tensor(obs))
            obs, reward, terminated, truncated, _ = env.step(action)
            actions.append(int(action))
            rewards.append(float(reward))
            observations.append([float(x) for x in obs])
            done = terminated or truncated
        trajectories.append({"env": env_id, "obs": observations, "actions": actions, "rewards": rewards})
    return trajectories


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

    run_name = args.name or "modelfree"
    setup_logging(
        log_file=f"runs/{run_name}.jsonl",
        static_fields={"run_name": run_name, **git_info()},
    )
    torch.manual_seed(args.seed)

    env = gymnasium.make("CartPole-v1")
    eval_env = gymnasium.make("CartPole-v1")
    eval_env.reset(seed=args.seed + 1)  # later unseeded resets continue this RNG: runs are reproducible
    pi = init_mlp([4, 64, 64, 2])
    vf = init_mlp([4, 64, 64, 1])
    device = torch.get_default_device()
    pi_cfg = AdamParams(lr=args.lr)
    vf_cfg = AdamParams(lr=args.vf_lr if args.vf_lr is not None else args.lr)
    pi_opt, vf_opt = init_adam(pi), init_adam(vf)
    state = rollout_init(env, seed=args.seed)

    for i in range(1, args.iters + 1):
        state, batch = collect(env, pi, vf, state, num_steps=args.rollout_steps)
        inputs = compute_loss_fn_inputs(batch, gamma=args.gamma)
        pi_opt, m_pi = train_step(reinforce_loss, pi, pi_opt, inputs, pi_cfg, step=i, device=device)
        vf_opt, m_vf = train_step(value_loss, vf, vf_opt, inputs, vf_cfg, step=i, device=device)

        m_log = to_floats({**m_pi, **m_vf})
        m_log["train_episodes"] = float(len(batch.episodes))
        if batch.episodes:
            m_log["train_ep_return"] = sum(e.episode_return for e in batch.episodes) / len(batch.episodes)
            m_log["train_ep_len"] = sum(e.episode_len for e in batch.episodes) / len(batch.episodes)
        metrics(m_log, step=i)

        if i % 10 == 0:
            with span("robots.eval", attributes={"step": i}):
                trajectories = evaluate(eval_env, pi)
            eval_reward = sum(sum(t["rewards"]) for t in trajectories) / len(trajectories)
            eval_ep_len = sum(len(t["actions"]) for t in trajectories) / len(trajectories)
            metrics({"eval_reward": eval_reward, "eval_ep_len": eval_ep_len}, step=i)
            artifact("rollout", trajectories[0], mime="application/x-trajectory+json", step=i)
            print(
                f"step {i}: eval_reward={eval_reward:.1f} "
                f"train_ep_return={m_log.get('train_ep_return', float('nan')):.1f} "
                f"value_loss={m_log['value_loss']:.2f} entropy={m_log['entropy']:.3f}"
            )


if __name__ == "__main__":
    main()
