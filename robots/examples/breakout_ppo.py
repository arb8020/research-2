from __future__ import annotations

import argparse
import functools
from collections.abc import Callable
from dataclasses import dataclass, fields
from typing import Protocol

import torch
import torch.nn.functional as F

from observe import metrics, setup_logging
from observe.git import git_info
from robots.core import (
    AdamParams,
    AdamState,
    adam_scalars,
    adam_update_,
    init_adam,
    register_pytree,
    tensor_leaves,
    tree_map,
)
from robots.envs.probes import (
    Probe1Value,
    Probe2Obs,
    Probe3Discount,
    Probe4Policy,
    Probe5PolicyValue,
)


class Env(Protocol):
    num_envs: int
    obs_size: int
    num_actions: int

    def reset(self, seed: int) -> torch.Tensor: ...
    def step(self, actions: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]: ...
    def log(self) -> dict[str, float]: ...


@dataclass(frozen=True)
class Config:
    num_envs: int = 8
    num_steps: int = 128
    iters: int = 1000
    lr: float = 2.5e-4
    adam_eps: float = 1e-5
    gamma: float = 0.99
    gae_lambda: float = 0.95
    num_minibatches: int = 4
    update_epochs: int = 4
    clip_coef: float = 0.2
    ent_coef: float = 0.01
    vf_coef: float = 0.5
    max_grad_norm: float = 0.5
    hidden: int = 64
    seed: int = 0


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
    w = torch.empty(out_dim, in_dim)
    torch.nn.init.xavier_uniform_(w)
    return Linear(w=w, b=torch.zeros(out_dim))


def init_mlp(sizes: list[int]) -> MLP:
    return MLP(layers=tuple(init_linear(i, o) for i, o in zip(sizes[:-1], sizes[1:], strict=True)))


def mlp_forward(w: MLP, x: torch.Tensor) -> torch.Tensor:
    *hidden, last = w.layers
    for layer in hidden:
        x = torch.tanh(x @ layer.w.T + layer.b)
    return x @ last.w.T + last.b


Params = tuple[MLP, MLP]


def init_params(obs_size: int, num_actions: int, hidden: int) -> Params:
    policy = init_mlp([obs_size, hidden, hidden, num_actions])
    value_function = init_mlp([obs_size, hidden, hidden, 1])
    return (policy, value_function)


def forward(params: Params, obs: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    policy, value_function = params
    return mlp_forward(policy, obs), mlp_forward(value_function, obs)[:, 0]


@dataclass(frozen=True)
class Rollout:
    obs: torch.Tensor
    action: torch.Tensor
    logprob: torch.Tensor
    value: torch.Tensor
    reward: torch.Tensor
    terminal: torch.Tensor


def init_rollout(num_steps: int, num_envs: int, obs_size: int) -> Rollout:
    def zeros(*shape: int, dtype: torch.dtype = torch.float32) -> torch.Tensor:
        return torch.zeros(*shape, dtype=dtype)

    return Rollout(
        obs=zeros(num_steps, num_envs, obs_size),
        action=zeros(num_steps, num_envs, dtype=torch.long),
        logprob=zeros(num_steps, num_envs),
        value=zeros(num_steps, num_envs),
        reward=zeros(num_steps, num_envs),
        terminal=zeros(num_steps, num_envs),
    )


def rollout(env: Env, params: Params, obs: torch.Tensor, roll: Rollout) -> tuple[Rollout, torch.Tensor]:
    """Fills roll in place. obs is the env's first observation; returns the obs after the last step."""
    num_steps, num_envs = roll.action.shape
    assert obs.shape == (num_envs, env.obs_size), obs.shape
    # Gumbel-max: argmax(logits + Gumbel noise) samples softmax(logits). Noise drawn once per rollout.
    uniform = torch.rand(num_steps, num_envs, env.num_actions)
    gumbel = -torch.log(-torch.log(uniform))
    with torch.no_grad():
        for t in range(num_steps):
            roll.obs[t].copy_(obs)
            logits, value = forward(params, roll.obs[t])
            action = (logits + gumbel[t]).argmax(dim=-1)
            roll.action[t].copy_(action)
            roll.logprob[t].copy_(F.log_softmax(logits, dim=-1).gather(1, action[:, None])[:, 0])
            roll.value[t].copy_(value)
            obs, reward, terminal = env.step(roll.action[t])
            roll.reward[t].copy_(reward)
            roll.terminal[t].copy_(terminal)
    return roll, obs


def gae(roll: Rollout, last_value: torch.Tensor, gamma: float, lam: float) -> tuple[torch.Tensor, torch.Tensor]:
    """terminal[t] means the episode ended after step t: no bootstrap across it. No truncation exists."""
    num_steps, num_envs = roll.reward.shape
    assert last_value.shape == (num_envs,), last_value.shape
    assert 0.0 <= gamma <= 1.0
    advantages = torch.zeros_like(roll.reward)
    running = torch.zeros(num_envs)
    for t in reversed(range(num_steps)):
        next_value = last_value if t == num_steps - 1 else roll.value[t + 1]
        alive = 1.0 - roll.terminal[t]
        delta = roll.reward[t] + gamma * next_value * alive - roll.value[t]
        running = delta + gamma * lam * alive * running
        advantages[t] = running
    return advantages, advantages + roll.value


Minibatch = dict[str, torch.Tensor]
Metrics = dict[str, torch.Tensor]


def ppo_loss(params: Params, mb: Minibatch, cfg: Config) -> tuple[torch.Tensor, Metrics]:
    logits, value = forward(params, mb["obs"])
    logprobs_all = F.log_softmax(logits, dim=-1)
    logprob = logprobs_all.gather(1, mb["action"][:, None])[:, 0]
    entropy = -(logprobs_all.exp() * logprobs_all).sum(dim=-1).mean()

    adv = mb["advantage"]
    adv_normed = (adv - adv.mean()) / (adv.std() + 1e-8)
    log_ratio = logprob - mb["logprob"]
    ratio = log_ratio.exp()
    surrogate = adv_normed * ratio
    surrogate_clipped = adv_normed * ratio.clamp(1.0 - cfg.clip_coef, 1.0 + cfg.clip_coef)
    pi_loss = -torch.min(surrogate, surrogate_clipped).mean()
    # Unclipped value loss: cleanrl's clip_vloss is on by default, but Andrychowicz et al. 2021 find it does not help.
    value_loss = 0.5 * ((value - mb["return"]) ** 2).mean()

    loss = pi_loss + cfg.vf_coef * value_loss - cfg.ent_coef * entropy
    with torch.no_grad():
        out = {
            "pi_loss": pi_loss,
            "value_loss": value_loss,
            "entropy": entropy,
            "approx_kl": ((ratio - 1.0) - log_ratio).mean(),
            "clipfrac": ((ratio - 1.0).abs() > cfg.clip_coef).float().mean(),
        }
    return loss, out


def clip_grad_norm(grads: Params, max_norm: float) -> tuple[Params, torch.Tensor]:
    assert max_norm > 0.0
    norm = torch.stack([g.pow(2).sum() for g in tensor_leaves(grads)]).sum().sqrt()
    scale = (max_norm / (norm + 1e-6)).clamp(max=1.0)
    return tree_map(lambda g: g * scale, grads), norm


LossFn = Callable[[Params, Minibatch], tuple[torch.Tensor, Metrics]]


def train_step(
    params: Params,
    opt: AdamState[Params],
    loss_fn: LossFn,
    inputs: Minibatch,
    cfg: Config,
    step: int,
    device: torch.device,
) -> tuple[Params, AdamState[Params], Metrics]:
    """Updates params and opt in place (adam_update_); returns them so the caller rebinds."""
    grad_fn = torch.func.grad_and_value(loss_fn, argnums=0, has_aux=True)
    grads, (_loss, step_metrics) = grad_fn(params, inputs)
    clipped, grad_norm = clip_grad_norm(grads, cfg.max_grad_norm)
    adam_cfg = AdamParams(lr=cfg.lr, eps=cfg.adam_eps)
    opt = adam_update_(params, clipped, opt, adam_cfg, adam_scalars(adam_cfg, step, device))
    return params, opt, {**step_metrics, "grad_norm": grad_norm}


def flatten_rollout(roll: Rollout, advantages: torch.Tensor, returns: torch.Tensor) -> Minibatch:
    obs_size = roll.obs.shape[-1]
    return {
        "obs": roll.obs.reshape(-1, obs_size),
        "action": roll.action.reshape(-1),
        "logprob": roll.logprob.reshape(-1),
        "advantage": advantages.reshape(-1),
        "return": returns.reshape(-1),
    }


def train(
    env: Env, cfg: Config, on_iter: Callable[[int, dict[str, float]], None] | None = None
) -> tuple[Params, list[dict[str, float]]]:
    assert cfg.num_envs == env.num_envs, (cfg.num_envs, env.num_envs)
    batch_size = cfg.num_steps * cfg.num_envs
    assert batch_size % cfg.num_minibatches == 0, (batch_size, cfg.num_minibatches)
    minibatch_size = batch_size // cfg.num_minibatches
    torch.manual_seed(cfg.seed)  # rollout sampling and minibatch shuffles use the global RNG
    device = torch.get_default_device()
    params = init_params(env.obs_size, env.num_actions, cfg.hidden)
    opt = init_adam(params)
    loss_fn = functools.partial(ppo_loss, cfg=cfg)
    roll = init_rollout(cfg.num_steps, cfg.num_envs, env.obs_size)
    obs = env.reset(cfg.seed)
    history: list[dict[str, float]] = []
    step = 0
    for i in range(1, cfg.iters + 1):
        roll, obs = rollout(env, params, obs, roll)
        with torch.no_grad():
            _, last_value = forward(params, obs)
        advantages, returns = gae(roll, last_value, cfg.gamma, cfg.gae_lambda)
        batch = flatten_rollout(roll, advantages, returns)
        step_metrics: list[Metrics] = []
        for _epoch in range(cfg.update_epochs):
            perm = torch.randperm(batch_size)
            for start in range(0, batch_size, minibatch_size):
                idx = perm[start : start + minibatch_size]
                mb = {k: v[idx] for k, v in batch.items()}
                step += 1
                params, opt, m = train_step(params, opt, loss_fn, mb, cfg, step, device)
                step_metrics.append(m)
        entry = {k: torch.stack([m[k] for m in step_metrics]).mean().item() for k in step_metrics[0]}
        entry = {**entry, **env.log()}
        history.append(entry)
        if on_iter is not None:
            on_iter(i, entry)
    return params, history


PROBES: dict[str, Callable[[int], Env]] = {
    "probe1": Probe1Value,
    "probe2": Probe2Obs,
    "probe3": Probe3Discount,
    "probe4": Probe4Policy,
    "probe5": Probe5PolicyValue,
}


def make_env(name: str, num_envs: int) -> Env:
    if name == "breakout":
        raise NotImplementedError("breakout: next task vendors PufferLib 5.0 breakout via ctypes")
    return PROBES[name](num_envs)


def parse_config() -> tuple[argparse.Namespace, Config]:
    p = argparse.ArgumentParser(description="PPO (cleanrl-style) on probe envs; Breakout next")
    p.add_argument("--env", default="probe1", choices=[*PROBES, "breakout"])
    p.add_argument("--name", default=None, help="Run name (default: ppo-<env>)")
    for f in fields(Config):
        p.add_argument(f"--{f.name.replace('_', '-')}", type=type(f.default), default=f.default)
    args = p.parse_args()
    cfg = Config(**{f.name: getattr(args, f.name) for f in fields(Config)})
    return args, cfg


def main() -> None:
    args, cfg = parse_config()
    run_name = args.name or f"ppo-{args.env}"
    setup_logging(
        log_file=f"runs/{run_name}.jsonl",
        static_fields={"run_name": run_name, "env": args.env, **git_info()},
    )
    env = make_env(args.env, cfg.num_envs)

    def log_iter(i: int, entry: dict[str, float]) -> None:
        metrics(entry, step=i)
        print(
            f"iter {i}: return={entry.get('episode_return', float('nan')):.3f} "
            f"value_loss={entry['value_loss']:.4f} entropy={entry['entropy']:.3f} approx_kl={entry['approx_kl']:.4f}"
        )

    params, _history = train(env, cfg, on_iter=log_iter)
    if env.obs_size == 1:
        with torch.no_grad():
            logits, value = forward(params, torch.tensor([[-1.0], [0.0], [1.0]]))
        print(f"obs -1/0/+1: V={value.tolist()} P={F.softmax(logits, dim=-1).tolist()}")


if __name__ == "__main__":
    main()
