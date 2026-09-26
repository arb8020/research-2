"""Model-based REINFORCE on CartPole. Uses the robots sdk.

Two training steps per iteration:
1. Train the world model on real transitions (supervised).
2. Train the policy on imagined rollouts (REINFORCE).
"""

import argparse

import gymnasium
import torch

from observe import artifact, metrics, setup_logging, span
from observe.git import git_info
from robots.models import (
    init_policy,
    init_wm,
    policy_act,
    policy_params,
    wm_params,
    wm_train_step,
)
from robots.optim import AdamParams, make_optimizer
from robots.rollout import collect_transitions, imagine_rollout
from robots.train import (
    compute_returns,
    evaluate,
    record_episode,
    reinforce_loss,
    train_step,
)

p = argparse.ArgumentParser(description="Model-based REINFORCE on CartPole")
p.add_argument("--name", default=None, help="Run name")
p.add_argument("--iters", type=int, default=200)
p.add_argument("--rollout-steps", type=int, default=200)
p.add_argument("--wm-steps", type=int, default=10)
p.add_argument("--horizon", type=int, default=15)
p.add_argument("--num-imagined", type=int, default=4)
args = p.parse_args()

# --- setup ---
run_name = args.name or "modelbased"
setup_logging(
    log_file=f"runs/{run_name}.jsonl",
    static_fields={"run_name": run_name, **git_info()},
)

env = gymnasium.make("CartPole-v1")
obs_dim = env.observation_space.shape[0]
act_dim = env.action_space.n

wm = init_wm(obs_dim=obs_dim, act_dim=act_dim)
pi = init_policy(obs_dim=obs_dim, act_dim=act_dim)
wm_opt = make_optimizer(wm_params(wm), AdamParams(lr=1e-3))
pi_opt = make_optimizer(policy_params(pi), AdamParams(lr=3e-4))

# --- train ---
for i in range(1, args.iters + 1):
    # Step 1: collect real transitions, train world model
    with span("robots.rollout", attributes={"step": i}):
        transitions = collect_transitions(env, num_steps=args.rollout_steps)

    with span("robots.world_model_train", attributes={"step": i}):
        wm_loss = 0.0
        for _ in range(args.wm_steps):
            wm_loss = wm_train_step(wm, wm_opt, transitions)

    # Step 2: imagine rollouts, train policy
    with span("robots.policy_train", attributes={"step": i}):
        pi_loss_total = 0.0
        n_imagined = 0
        for _ in range(args.num_imagined):
            start = transitions[torch.randint(len(transitions), (1,)).item()].obs
            imagined = imagine_rollout(wm, pi, start, args.horizon)
            if len(imagined) == 0:
                continue
            loss, m = reinforce_loss(pi, imagined)
            pi_opt.zero()
            loss.backward()
            pi_opt.step()
            pi_loss_total += loss.item()
            n_imagined += 1

    metrics({"wm_loss": wm_loss, "pi_loss": pi_loss_total / max(n_imagined, 1)}, step=i)

    if i % 10 == 0:
        with span("robots.eval", attributes={"step": i}):
            eval_reward, eval_ep_len = evaluate(env, pi)
            trajectory = record_episode(env, pi)
        metrics({"eval_reward": eval_reward, "eval_ep_len": eval_ep_len}, step=i)
        artifact("rollout", trajectory, mime="application/x-trajectory+json", step=i)
        print(f"step {i}: eval_reward={eval_reward:.1f}")
