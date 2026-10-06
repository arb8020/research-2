"""Model-based actor-critic on CartPole.

Self-contained: everything except Adam (robots.optim) and the pytree helpers
(robots.tree) is defined in this file.

Two training phases per iteration:
1. Train the world model on real transitions (supervised, wm_loss).
2. Train the policy (reinforce_loss) and the separate value function
   (value_loss) on imagined rollouts; the horizon cut bootstraps with V.

  PYTHONPATH=. robots/.venv/bin/python robots/examples/cartpole_modelbased.py --iters 200
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeAlias, TypeVar

import gymnasium
import torch
import torch.nn.functional as F

from observe import artifact, metrics, setup_logging, span
from observe.git import git_info
from robots.optim import AdamParams, AdamState, adam_scalars, adam_update_, init_adam
from robots.tree import register_pytree, tensor_leaves

# ---------------------------------------------------------------------------
# Model: policy and value networks (separate: no shared trunk)
# ---------------------------------------------------------------------------


def _linear(out_dim: int, in_dim: int) -> tuple[torch.Tensor, torch.Tensor]:
    """Xavier-uniform weight + zero bias, both with requires_grad=True."""
    w = torch.empty(out_dim, in_dim, requires_grad=True)
    torch.nn.init.xavier_uniform_(w)
    b = torch.zeros(out_dim, requires_grad=True)
    return w, b


@register_pytree
@dataclass(frozen=True)
class PolicyWeights:
    """2-layer MLP policy: obs -> action logits. No value head (see ValueWeights).

    Frozen dataclass — fields can't be reassigned, but the tensors themselves
    are mutable (the optimizer updates them in place).
    """

    # MLP trunk: two hidden layers
    w1: torch.Tensor  # (hidden, obs_dim)
    b1: torch.Tensor  # (hidden,)
    w2: torch.Tensor  # (hidden, hidden)
    b2: torch.Tensor  # (hidden,)
    # Action head
    w_action: torch.Tensor  # (act_dim, hidden)
    b_action: torch.Tensor  # (act_dim,)


def init_policy(obs_dim: int, act_dim: int, hidden: int = 64) -> PolicyWeights:
    """Initialize policy weights with Xavier uniform (matching nn.Linear defaults)."""
    w1, b1 = _linear(hidden, obs_dim)
    w2, b2 = _linear(hidden, hidden)
    w_action, b_action = _linear(act_dim, hidden)
    return PolicyWeights(w1=w1, b1=b1, w2=w2, b2=b2, w_action=w_action, b_action=b_action)


def policy_forward(w: PolicyWeights, obs: torch.Tensor) -> torch.Tensor:
    """obs (batch, obs_dim) -> logits (batch, act_dim)."""
    h = F.relu(obs @ w.w1.T + w.b1)  # (batch, hidden)
    h = F.relu(h @ w.w2.T + w.b2)  # (batch, hidden)
    return h @ w.w_action.T + w.b_action  # (batch, act_dim)


def policy_act(w: PolicyWeights, obs: torch.Tensor) -> int:
    """Sample one action from the policy. obs: (obs_dim,)."""
    with torch.no_grad():
        logits = policy_forward(w, obs.unsqueeze(0))  # (1, act_dim)
        dist = torch.distributions.Categorical(logits=logits)
        return dist.sample().item()


@register_pytree
@dataclass(frozen=True)
class ValueWeights:
    """2-layer MLP state-value function: obs -> V(obs). Own trunk."""

    # MLP trunk: two hidden layers
    w1: torch.Tensor  # (hidden, obs_dim)
    b1: torch.Tensor  # (hidden,)
    w2: torch.Tensor  # (hidden, hidden)
    b2: torch.Tensor  # (hidden,)
    # Value head
    w_value: torch.Tensor  # (1, hidden)
    b_value: torch.Tensor  # (1,)


def init_value(obs_dim: int, hidden: int = 64) -> ValueWeights:
    """Initialize value weights with Xavier uniform (matching nn.Linear defaults)."""
    w1, b1 = _linear(hidden, obs_dim)
    w2, b2 = _linear(hidden, hidden)
    w_value, b_value = _linear(1, hidden)
    return ValueWeights(w1=w1, b1=b1, w2=w2, b2=b2, w_value=w_value, b_value=b_value)


def value_forward(w: ValueWeights, obs: torch.Tensor) -> torch.Tensor:
    """obs (batch, obs_dim) -> value (batch,)."""
    h = F.relu(obs @ w.w1.T + w.b1)  # (batch, hidden)
    h = F.relu(h @ w.w2.T + w.b2)  # (batch, hidden)
    return (h @ w.w_value.T + w.b_value)[:, 0]  # (batch, 1) -> (batch,)


def get_value(w: ValueWeights, obs: torch.Tensor) -> float:
    """Detached V(obs) for one obs. obs: (obs_dim,)."""
    with torch.no_grad():
        return value_forward(w, obs.unsqueeze(0)).item()


# ---------------------------------------------------------------------------
# Model: world model
# ---------------------------------------------------------------------------

@register_pytree
@dataclass(frozen=True)
class WMWeights:
    """All tensors for a 2-layer MLP world model.

    Predicts next obs, reward, done from (obs, one_hot_action).
    """

    obs_dim: int
    act_dim: int
    # MLP trunk
    w1: torch.Tensor  # (hidden, obs_dim + act_dim)
    b1: torch.Tensor  # (hidden,)
    w2: torch.Tensor  # (hidden, hidden)
    b2: torch.Tensor  # (hidden,)
    # Heads
    w_obs: torch.Tensor  # (obs_dim, hidden)
    b_obs: torch.Tensor  # (obs_dim,)
    w_reward: torch.Tensor  # (1, hidden)
    b_reward: torch.Tensor  # (1,)
    w_done: torch.Tensor  # (1, hidden)
    b_done: torch.Tensor  # (1,)


def init_wm(obs_dim: int, act_dim: int, hidden: int = 64) -> WMWeights:
    """Initialize world model weights with Xavier uniform."""
    input_dim = obs_dim + act_dim
    w1, b1 = _linear(hidden, input_dim)
    w2, b2 = _linear(hidden, hidden)
    w_obs, b_obs = _linear(obs_dim, hidden)
    w_reward, b_reward = _linear(1, hidden)
    w_done, b_done = _linear(1, hidden)
    return WMWeights(
        obs_dim=obs_dim, act_dim=act_dim,
        w1=w1, b1=b1, w2=w2, b2=b2,
        w_obs=w_obs, b_obs=b_obs,
        w_reward=w_reward, b_reward=b_reward,
        w_done=w_done, b_done=b_done,
    )


def wm_forward(
    w: WMWeights,
    obs: torch.Tensor,
    action: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Predict next_obs, reward, done.

    obs: (batch, obs_dim), action: (batch,) int — one-hot encoded internally.
    """
    action_onehot = F.one_hot(action, w.act_dim).to(obs.dtype)  # (batch, act_dim)

    x = torch.cat([obs, action_onehot], dim=1)  # (batch, obs_dim + act_dim)
    h = F.relu(x @ w.w1.T + w.b1)  # (batch, hidden)
    h = F.relu(h @ w.w2.T + w.b2)  # (batch, hidden)

    pred_obs = h @ w.w_obs.T + w.b_obs  # (batch, obs_dim)
    pred_reward = (h @ w.w_reward.T + w.b_reward)[:, 0]  # (batch,)
    pred_done = (h @ w.w_done.T + w.b_done)[:, 0]  # (batch,)
    return pred_obs, pred_reward, pred_done


# ---------------------------------------------------------------------------
# Rollout: experience records. A Batch is what the losses consume; imagine_rollout
# emits it. Transition is one real step, for world-model training.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Step:
    """One recorded step."""

    obs: torch.Tensor          # (obs_dim,) obs the action was chosen from
    action: int
    reward: float
    terminated: bool           # real ending (pole fell): future reward = 0
    truncated: bool            # time limit: future reward unknown -> bootstrap with V(next_obs)
    next_obs: torch.Tensor     # (obs_dim,) true next obs, BEFORE any reset
    value: float               # detached V(obs), from collection time
    bootstrap_value: float     # detached V(next_obs) if truncated (and not terminated), else 0.0


@dataclass(frozen=True)
class EpisodeEnd:
    """Emitted by collect_step when an episode finishes. For logging."""

    episode_return: float
    episode_len: int
    timed_out: bool   # ended by the time limit with the future unknown (bootstrapped).


@dataclass(frozen=True)
class Batch:
    steps: list[Step]
    episodes: list[EpisodeEnd]  # episodes that FINISHED during this batch
    last_obs: torch.Tensor      # (obs_dim,) obs the NEXT batch will act on
    last_value: float           # detached V(last_obs): bootstraps the cut at the batch end


@dataclass(frozen=True)
class Transition:
    """One real transition: state + action → result. Used for world-model training."""

    obs: torch.Tensor
    action: int
    next_obs: torch.Tensor
    reward: float
    done: bool


# ---------------------------------------------------------------------------
# Rollout: collect from real env
# ---------------------------------------------------------------------------

def collect_transitions(
    env: gymnasium.Env,
    num_steps: int,
    act: Callable[[torch.Tensor], int] | None = None,
) -> list[Transition]:
    """Step through env for num_steps, return transitions.

    act: given an obs tensor, return an action int.
         None = random actions (for world-model pre-training).
    """
    transitions: list[Transition] = []
    obs, _ = env.reset()
    obs_t = torch.tensor(obs, dtype=torch.float32)

    for _ in range(num_steps):
        action = act(obs_t) if act is not None else env.action_space.sample()
        next_obs, reward, terminated, truncated, _ = env.step(action)
        next_obs_t = torch.tensor(next_obs, dtype=torch.float32)
        done = terminated or truncated

        transitions.append(
            Transition(
                obs=obs_t,
                action=action,
                next_obs=next_obs_t,
                reward=float(reward),
                done=done,
            )
        )

        if done:
            obs, _ = env.reset()
            obs_t = torch.tensor(obs, dtype=torch.float32)
        else:
            obs_t = next_obs_t

    return transitions


# ---------------------------------------------------------------------------
# Rollout: imagine from world model
# ---------------------------------------------------------------------------

def imagine_rollout(
    wm: WMWeights,
    pi: PolicyWeights,
    vf: ValueWeights,
    start_obs: torch.Tensor,
    horizon: int,
) -> Batch:
    """Roll out pi inside the world model (vf supplies the recorded values) for up to `horizon` steps.

    Emits the same Batch as robots.collect.collect, so compute_loss_fn_inputs
    works unchanged:
      terminated      = predicted done (sigmoid > 0.5); the rollout stops there
      truncated       = False (imagination has no time limit)
      bootstrap_value = 0.0 (only truncation bootstraps)
      last_value      = V(final imagined obs): the horizon is a batch cut. Unused
                        when the last step terminated.
    """
    assert horizon > 0
    steps: list[Step] = []
    episodes: list[EpisodeEnd] = []
    obs = start_obs.detach()
    episode_return = 0.0

    for _ in range(horizon):
        with torch.no_grad():
            logits = policy_forward(pi, obs.unsqueeze(0))  # (1, act_dim)
            action = torch.distributions.Categorical(logits=logits).sample()  # (1,)
            pred_obs, pred_reward, pred_done = wm_forward(wm, obs.unsqueeze(0), action)
        next_obs = pred_obs.squeeze(0)
        terminated = pred_done.sigmoid().item() > 0.5
        steps.append(
            Step(
                obs=obs,
                action=action.item(),
                reward=pred_reward.item(),
                terminated=terminated,
                truncated=False,
                next_obs=next_obs,
                value=get_value(vf, obs),
                bootstrap_value=0.0,
            )
        )
        episode_return += pred_reward.item()
        obs = next_obs
        if terminated:
            episodes.append(EpisodeEnd(episode_return=episode_return, episode_len=len(steps), timed_out=False))
            break

    return Batch(steps=steps, episodes=episodes, last_obs=obs, last_value=get_value(vf, obs))


# ---------------------------------------------------------------------------
# Algorithm: world-model loss (supervised, on real transitions)
# ---------------------------------------------------------------------------

def transitions_to_inputs(transitions: list[Transition]) -> dict[str, torch.Tensor]:
    """list[Transition] -> named tensors for wm_loss (keys: obs, actions, next_obs, rewards, dones)."""
    assert len(transitions) > 0
    return {
        "obs": torch.stack([t.obs for t in transitions]),
        "actions": torch.tensor([t.action for t in transitions], dtype=torch.long),
        "next_obs": torch.stack([t.next_obs for t in transitions]),
        "rewards": torch.tensor([t.reward for t in transitions], dtype=torch.float32),
        "dones": torch.tensor([t.done for t in transitions], dtype=torch.float32),
    }


def wm_loss(
    w: WMWeights,
    inputs: dict[str, torch.Tensor],
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    """Supervised world-model loss: MSE(next_obs) + MSE(reward) + BCE(done). torch.func-safe."""
    pred_obs, pred_reward, pred_done = wm_forward(w, inputs["obs"], inputs["actions"])
    loss_obs = F.mse_loss(pred_obs, inputs["next_obs"])
    loss_reward = F.mse_loss(pred_reward, inputs["rewards"])
    loss_done = F.binary_cross_entropy_with_logits(pred_done, inputs["dones"])
    metrics = {
        "wm_obs_loss": loss_obs.detach(),
        "wm_reward_loss": loss_reward.detach(),
        "wm_done_loss": loss_done.detach(),
    }
    return loss_obs + loss_reward + loss_done, metrics


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
    pi: PolicyWeights,
    inputs: LossFnInputs,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    """Policy-gradient term: mean(-log pi(a|s) * advantage). Reads obs, actions, advantages."""
    logits = policy_forward(pi, inputs["obs"])                                      # (T, act_dim)
    log_probs_all = F.log_softmax(logits, dim=-1)                                   # (T, act_dim)
    logprob = log_probs_all.gather(1, inputs["actions"].unsqueeze(1)).squeeze(1)    # (T,)
    entropy = -(log_probs_all.exp() * log_probs_all).sum(dim=-1)                    # (T,)
    advantages = inputs["advantages"].detach()
    loss = -(logprob * advantages).mean()
    metrics = {
        "pi_loss": loss.detach(),
        "entropy": entropy.mean().detach(),
        "advantage_mean": advantages.mean(),
        "advantage_std": advantages.std(correction=0),
    }
    return loss, metrics


def value_loss(
    vf: ValueWeights,
    inputs: LossFnInputs,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    """Value regression: mean((V(obs) - return)^2). Reads obs, returns."""
    values = value_forward(vf, inputs["obs"])                                       # (T,)
    returns = inputs["returns"].detach()
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
    dataclass to be a registered pytree (robots.tree.register_pytree).
    metrics gains a "loss" entry.
    """
    grad_fn = torch.func.grad_and_value(loss_fn, argnums=0, has_aux=True)
    grads, (loss, metrics) = grad_fn(weights, inputs)
    assert type(grads) is type(weights)
    assert "loss" not in metrics
    return grads, {**metrics, "loss": loss.detach()}


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

def evaluate(env: gymnasium.Env, pi: PolicyWeights, num_episodes: int = 3) -> tuple[float, float]:
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


def record_episode(env: gymnasium.Env, pi: PolicyWeights) -> dict[str, Any]:
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
    p = argparse.ArgumentParser(description="Model-based actor-critic on CartPole")
    p.add_argument("--name", default=None, help="Run name")
    p.add_argument("--iters", type=int, default=200)
    p.add_argument("--rollout-steps", type=int, default=200)
    p.add_argument("--wm-steps", type=int, default=10)
    p.add_argument("--horizon", type=int, default=15)
    p.add_argument("--num-imagined", type=int, default=4)
    p.add_argument("--gamma", type=float, default=0.99)
    p.add_argument("--lr", type=float, default=3e-4, help="Policy lr")
    p.add_argument("--vf-lr", type=float, default=None, help="Value-function lr (default: --lr)")
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()

    # --- setup ---
    run_name = args.name or "modelbased"
    setup_logging(
        log_file=f"runs/{run_name}.jsonl",
        static_fields={"run_name": run_name, **git_info()},
    )
    torch.manual_seed(args.seed)

    env = gymnasium.make("CartPole-v1")
    eval_env = gymnasium.make("CartPole-v1")
    eval_env.reset(seed=args.seed + 1)  # later unseeded resets continue this RNG: runs are reproducible
    env.reset(seed=args.seed)
    obs_dim = env.observation_space.shape[0]
    act_dim = env.action_space.n

    wm = init_wm(obs_dim=obs_dim, act_dim=act_dim)
    pi = init_policy(obs_dim=obs_dim, act_dim=act_dim)
    vf = init_value(obs_dim=obs_dim)
    wm_cfg = AdamParams(lr=1e-3)
    pi_cfg = AdamParams(lr=args.lr)
    vf_cfg = AdamParams(lr=args.vf_lr if args.vf_lr is not None else args.lr)
    wm_opt, pi_opt, vf_opt = init_adam(wm), init_adam(pi), init_adam(vf)
    # 1-based step counters: the world model steps wm_steps times per iter;
    # pi and vf step together once per imagined rollout, so they share one.
    wm_step, ac_step = 0, 0

    # --- train ---
    for i in range(1, args.iters + 1):
        # Phase 1: collect real transitions (random actions), train world model
        with span("robots.rollout", attributes={"step": i}):
            transitions = collect_transitions(env, num_steps=args.rollout_steps)
        wm_inputs = transitions_to_inputs(transitions)

        with span("robots.world_model_train", attributes={"step": i}):
            for _ in range(args.wm_steps):
                wm_step += 1
                wm_opt, wm_m = train_step(wm_loss, wm, wm_opt, wm_inputs, wm_cfg, wm_step)

        # Phase 2: imagine rollouts from real start states, train policy and value
        with span("robots.policy_train", attributes={"step": i}):
            pi_ms, imagined_lens = [], []
            for _ in range(args.num_imagined):
                start = transitions[torch.randint(len(transitions), (1,)).item()].obs
                batch = imagine_rollout(wm, pi, vf, start, args.horizon)
                inputs = compute_loss_fn_inputs(batch, gamma=args.gamma)
                ac_step += 1
                pi_opt, m_pi = train_step(reinforce_loss, pi, pi_opt, inputs, pi_cfg, ac_step)
                vf_opt, m_vf = train_step(value_loss, vf, vf_opt, inputs, vf_cfg, ac_step)
                # Each "loss" duplicates pi_loss / value_loss; drop it so the keys don't collide.
                pi_ms.append({k: v for k, v in to_floats({**m_pi, **m_vf}).items() if k != "loss"})
                imagined_lens.append(len(batch.steps))

        wm_log = {f"wm_{k}" if not k.startswith("wm_") else k: v for k, v in to_floats(wm_m).items()}
        pi_log = {k: sum(m[k] for m in pi_ms) / len(pi_ms) for k in pi_ms[0]}
        metrics({**wm_log, **pi_log, "imagined_len": sum(imagined_lens) / len(imagined_lens)}, step=i)

        if i % 10 == 0:
            with span("robots.eval", attributes={"step": i}):
                eval_reward, eval_ep_len = evaluate(eval_env, pi)
                trajectory = record_episode(eval_env, pi)
            metrics({"eval_reward": eval_reward, "eval_ep_len": eval_ep_len}, step=i)
            artifact("rollout", trajectory, mime="application/x-trajectory+json", step=i)
            print(
                f"step {i}: eval_reward={eval_reward:.1f} wm_loss={wm_log['wm_loss']:.3f} "
                f"imagined_len={sum(imagined_lens) / len(imagined_lens):.1f} value_loss={pi_log['value_loss']:.3f}"
            )


if __name__ == "__main__":
    main()
