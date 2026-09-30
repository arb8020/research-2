"""Model-free REINFORCE on CartPole. Uses the robots sdk."""

import argparse

import gymnasium
import torch

from observe import artifact, metrics, setup_logging, span
from observe.git import git_info
from robots.models import init_policy, policy_act, policy_params
from robots.optim import AdamParams, make_optimizer
from robots.rollout import policy_collector
from robots.train import evaluate, record_episode, reinforce_loss, train_step

p = argparse.ArgumentParser(description="Model-free REINFORCE on CartPole")
p.add_argument("--name", default=None, help="Run name")
p.add_argument("--iters", type=int, default=500)
p.add_argument("--lr", type=float, default=3e-4)
p.add_argument("--rollout-steps", type=int, default=200)
args = p.parse_args()

# --- setup ---
run_name = args.name or "modelfree"
setup_logging(
    log_file=f"runs/{run_name}.jsonl",
    static_fields={"run_name": run_name, **git_info()},
)

env = gymnasium.make("CartPole-v1")
pi = init_policy(obs_dim=4, act_dim=2)
opt = make_optimizer(policy_params(pi), AdamParams(lr=args.lr))
get_batch = policy_collector(env, pi, num_steps=args.rollout_steps)

# --- train ---
for i in range(1, args.iters + 1):
    m = train_step(get_batch, reinforce_loss, pi, opt)
    metrics(m, step=i)

    if i % 10 == 0:
        with span("robots.eval", attributes={"step": i}):
            eval_reward, eval_ep_len = evaluate(env, pi)
            trajectory = record_episode(env, pi)
        eval_m = {"eval_reward": eval_reward, "eval_ep_len": eval_ep_len}
        metrics(eval_m, step=i)
        artifact("rollout", trajectory, mime="application/x-trajectory+json", step=i)
        print(f"step {i}: eval_reward={eval_reward:.1f}")
