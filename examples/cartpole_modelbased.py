"""Model-based actor-critic on CartPole. Uses the robots sdk.

Two training phases per iteration:
1. Train the world model on real transitions (supervised, wm_loss).
2. Train the policy on imagined rollouts (actor_critic_loss; the horizon cut
   bootstraps with V, so the value head must be trained too).

  PYTHONPATH=. robots/.venv/bin/python examples/cartpole_modelbased.py --iters 200
"""

import argparse
import functools

import gymnasium
import torch

from observe import artifact, metrics, setup_logging, span
from observe.git import git_info
from robots.models import init_policy, init_wm, transitions_to_inputs, wm_loss
from robots.optim import AdamParams, init_adam
from robots.rollout import collect_transitions, imagine_rollout
from robots.train import (
    actor_critic_loss,
    compute_loss_fn_inputs,
    evaluate,
    record_episode,
    to_floats,
    train_step,
)

p = argparse.ArgumentParser(description="Model-based actor-critic on CartPole")
p.add_argument("--name", default=None, help="Run name")
p.add_argument("--iters", type=int, default=200)
p.add_argument("--rollout-steps", type=int, default=200)
p.add_argument("--wm-steps", type=int, default=10)
p.add_argument("--horizon", type=int, default=15)
p.add_argument("--num-imagined", type=int, default=4)
p.add_argument("--gamma", type=float, default=0.99)
p.add_argument("--vf-coef", type=float, default=0.5)
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
env.reset(seed=args.seed)
obs_dim = env.observation_space.shape[0]
act_dim = env.action_space.n

wm = init_wm(obs_dim=obs_dim, act_dim=act_dim)
pi = init_policy(obs_dim=obs_dim, act_dim=act_dim)
wm_cfg, pi_cfg = AdamParams(lr=1e-3), AdamParams(lr=3e-4)
wm_state, pi_state = init_adam(wm), init_adam(pi)
wm_step, pi_step = 0, 0  # each optimizer owns its own 1-based step counter
pi_loss_fn = functools.partial(actor_critic_loss, vf_coef=args.vf_coef)

# --- train ---
for i in range(1, args.iters + 1):
    # Phase 1: collect real transitions (random actions), train world model
    with span("robots.rollout", attributes={"step": i}):
        transitions = collect_transitions(env, num_steps=args.rollout_steps)
    wm_inputs = transitions_to_inputs(transitions)

    with span("robots.world_model_train", attributes={"step": i}):
        for _ in range(args.wm_steps):
            wm_step += 1
            wm_state, wm_m = train_step(wm_loss, wm, wm_state, wm_inputs, wm_cfg, wm_step)

    # Phase 2: imagine rollouts from real start states, train policy
    with span("robots.policy_train", attributes={"step": i}):
        pi_ms, imagined_lens = [], []
        for _ in range(args.num_imagined):
            start = transitions[torch.randint(len(transitions), (1,)).item()].obs
            batch = imagine_rollout(wm, pi, start, args.horizon)
            inputs = compute_loss_fn_inputs(batch, gamma=args.gamma)
            pi_step += 1
            pi_state, m = train_step(pi_loss_fn, pi, pi_state, inputs, pi_cfg, pi_step)
            pi_ms.append(to_floats(m))
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
