"""Model-free actor-critic (REINFORCE + learned value baseline) on CartPole. Uses the robots sdk.

  PYTHONPATH=. robots/.venv/bin/python examples/cartpole_modelfree.py --name modelfree-fixed --iters 500
"""

import argparse
import functools

import gymnasium
import torch

from observe import artifact, metrics, setup_logging, span
from observe.git import git_info
from robots.collect import collect, rollout_init
from robots.models import init_policy
from robots.optim import AdamParams, init_adam
from robots.train import (
    actor_critic_loss,
    reinforce_loss,
    compute_loss_fn_inputs,
    evaluate,
    record_episode,
    to_floats,
    train_step,
)

p = argparse.ArgumentParser(description="Model-free actor-critic on CartPole")
p.add_argument("--name", default=None, help="Run name")
p.add_argument("--iters", type=int, default=500)
p.add_argument("--lr", type=float, default=3e-4)
p.add_argument("--rollout-steps", type=int, default=200)
p.add_argument("--gamma", type=float, default=0.99)
p.add_argument("--vf-coef", type=float, default=0.5)
p.add_argument("--seed", type=int, default=0)
p.add_argument("--loss", choices=["actor_critic", "reinforce"], default="actor_critic",
               help="reinforce = policy term only (value head untrained; for diagnostics)")
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
pi = init_policy(obs_dim=4, act_dim=2)
cfg = AdamParams(lr=args.lr)
opt_state = init_adam(pi)
loss_fn = functools.partial(actor_critic_loss, vf_coef=args.vf_coef) if args.loss == "actor_critic" else reinforce_loss
state = rollout_init(env, seed=args.seed)

# --- train ---
for i in range(1, args.iters + 1):
    state, batch = collect(env, pi, state, num_steps=args.rollout_steps)
    inputs = compute_loss_fn_inputs(batch, gamma=args.gamma)
    opt_state, m = train_step(loss_fn, pi, opt_state, inputs, cfg, step=i)

    m_log = to_floats(m)
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
            f"value_loss={m_log.get('value_loss', float('nan')):.2f} entropy={m_log['entropy']:.3f}"
        )
