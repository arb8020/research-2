# policy gradients with a basic flappy bird

reinforcement learning can do a lot of cool things: 
[list/embed some cool things]
chess
autogo
robots
math reasoning language models

but what exactly is reinforcement learning? 

reinforcement learning is about teaching `agents` to behave in `environments` by giving them `rewards`. its pretty similar to learning by trial and error, or like pavlov's conditioning experiments. 

in particular, here we're going to study reinforcement learning using neural networks. neural networks are basically functions that are constructed of many smaller functions whose parameters are fit on on lots of data. it turns out these are very good at the general task of approximating a function f(x) when given a lot of data. 

deep reinforcement learning, in particular, is about trying to do reinforcement learning with deep learning methods. since we are pretty convinced that deep learning is really good at its job, we'd like to have neural networks that learn to take actions that maximize reward in their situations. we'll call this a `policy`, basically the brain of an agent

let's look at a very simple environment below, roughly a simplified flappy bird game with only two cells. the pipe can either appear in the top or bottom cell, and the goal is to train a policy that can learn how to play the game well. we'll also assume that the bird doesn't have gravity, and can freely inhabit either the upper or lower half of the game. so at each step the action is either 'move up' or 'move down'. at every step, the agent receives an `observation` about the `state` of the environment. the environment state contains the information about which row the pipe is in, and the prng key that dictates the random behavior of where the next pipe will spawn. the agent only gets an `observation` against this, and is only given the row where the next pipe is. 

<!-- write prose here: the env, and the reader plays it -->

<flappy-play></flappy-play>

```c env=flappy readonly
#include <stdlib.h>
#include "raylib.h"
typedef float obs_t;
#include "pufferenv.h"

#define ACT_SIZES {2}
#define OBS_SIZE 2
#define NUM_ATNS 1
#define FLAPPY_FRAMES 60

const int TOP = 0;
const int BOTTOM = 1;

struct Log {
    float perf;
    float score;
    float episode_return;
    float episode_length;
    float n;
};

struct Env {
    Log log;
    Agent agents[1];
    int num_agents;
    int episode_length;
    int tick;
    int pipe_row;
    int bird_row;
    float episode_return;
    unsigned int rng;
};
typedef Env Flappy;

void add_log(Flappy* env) {
    env->log.perf += env->episode_return / env->tick;
    env->log.score += env->episode_return;
    env->log.episode_return += env->episode_return;
    env->log.episode_length += env->tick;
    env->log.n++;
}

static void next_pipe(Flappy* env) {
    obs_t* obs = env->agents[0].observations;
    env->pipe_row = rand_r(&env->rng) % 2;
    obs[TOP] = env->pipe_row == TOP;
    obs[BOTTOM] = env->pipe_row == BOTTOM;
}

void puf_reset(Flappy* env) {
    env->tick = 0;
    env->episode_return = 0;
    env->bird_row = TOP;
    next_pipe(env);
}

static void flappy_human_controls(Flappy* env) {
    if (!IsWindowReady()) {
        return;
    }
    if (IsKeyPressed(KEY_UP) || IsKeyPressed(KEY_W)) {
        env->agents[0].actions[0] = TOP;
    }
    if (IsKeyPressed(KEY_DOWN) || IsKeyPressed(KEY_S)) {
        env->agents[0].actions[0] = BOTTOM;
    }
}

void puf_step(Flappy* env) {
    env->tick += 1;
    env->bird_row = (int)env->agents[0].actions[0];
    env->agents[0].terminals[0] = 0;
    env->agents[0].rewards[0] = env->bird_row != env->pipe_row;
    env->episode_return += env->agents[0].rewards[0];

    if (env->tick >= env->episode_length) {
        env->agents[0].terminals[0] = 1;
        add_log(env);
        puf_reset(env);
        return;
    }
    next_pipe(env);
}

void puf_render(Flappy* env) {
    int w = 480;
    int h = 240;
    int bird_x = 120;
    if (!IsWindowReady()) {
        InitWindow(w, h, "PufferLib Flappy");
        SetTargetFPS(60);
    }
    Color bird_color = env->agents[0].rewards[0] > 0 ? (Color){255, 203, 0, 255} : (Color){230, 41, 55, 255};
    for (int f = 0; f < FLAPPY_FRAMES; f++) {
        if (IsKeyDown(KEY_ESCAPE)) {
            exit(0);
        }
        flappy_human_controls(env);
        int pipe_x = w - ((w - bird_x) * f) / FLAPPY_FRAMES;
        int next_row = (int)env->agents[0].actions[0];
        Color bird = (env->tick > 0 && f < FLAPPY_FRAMES / 4) ? bird_color : (Color){0, 187, 187, 255};
        BeginDrawing();
        ClearBackground((Color){6, 24, 24, 255});
        DrawRectangle(pipe_x, env->pipe_row * h / 2, 40, h / 2, (Color){0, 187, 0, 255});
        DrawCircle(bird_x, env->bird_row * h / 2 + h / 4, 18, bird);
        DrawCircleLines(bird_x, next_row * h / 2 + h / 4, 18, (Color){0, 187, 187, 255});
        DrawText(TextFormat("%d / %d", (int)env->episode_return, env->tick), 10, 10, 20, RAYWHITE);
        EndDrawing();
        puf_web_vsync();
    }
}

void puf_close(Flappy* env) {
    if (IsWindowReady()) {
        CloseWindow();
    }
}

void puf_log(Log* log, Dict* out) {
    dict_set(out, "perf", log->perf);
    dict_set(out, "score", log->score);
    dict_set(out, "episode_return", log->episode_return);
    dict_set(out, "episode_length", log->episode_length);
    dict_set(out, "n", log->n);
}

void puf_init(Env* env, Dict* kwargs) {
    env->num_agents = 1;
    env->episode_length = dict_get(kwargs, "episode_length");
    env->agents[0].action_mask = NULL;
    env->agents[0].policy = 0;
}
```

```python given
import ctypes
import weakref

import numpy as np
import torch

OBS_DIM, N_ACTIONS = 2, 2


class Flappy:
    def __init__(self, n: int, seed: int, episode_length: int = 32) -> None:
        lib = ctypes.CDLL(ENV_SO["flappy"])
        ptr = ctypes.c_void_p
        lib.vec_create.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint, ptr, ptr, ptr, ptr]
        lib.vec_create.restype = ptr
        lib.vec_reset.argtypes = [ptr, ctypes.c_uint]
        lib.vec_step.argtypes = [ptr]
        lib.vec_close.argtypes = [ptr]
        self.n, self.seed, self.lib = n, seed, lib
        self.obs = np.zeros((n, OBS_DIM), np.float32)
        self.actions = np.zeros(n, np.float32)
        self.rewards = np.zeros(n, np.float32)
        self.terminals = np.zeros(n, np.float32)
        kwargs = f"episode_length={episode_length}".encode()
        self.handle = lib.vec_create(
            n, kwargs, seed, self.obs.ctypes.data, self.actions.ctypes.data, self.rewards.ctypes.data, self.terminals.ctypes.data
        )
        assert self.handle, "vec_create returned null"
        weakref.finalize(self, lib.vec_close, self.handle)

    def reset(self) -> torch.Tensor:
        self.lib.vec_reset(self.handle, self.seed)
        return torch.from_numpy(self.obs.copy())

    def step(self, actions: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        assert actions.shape == (self.n,), f"actions must have shape ({self.n},), got {tuple(actions.shape)}"
        self.actions[:] = actions.numpy()
        self.lib.vec_step(self.handle)
        return (
            torch.from_numpy(self.obs.copy()),
            torch.from_numpy(self.rewards.copy()),
            torch.from_numpy(self.terminals.astype(bool)),
        )
```

<!-- write prose here: can something autonomous play this? -->

<!-- write prose here: a policy network, obs in, action probabilities out -->

```python cell=policy
# write stub here
def init_policy(obs_dim: int, n_actions: int, hidden: int, seed: int) -> dict[str, torch.Tensor]:
    raise NotImplementedError


def policy_probs(params: dict[str, torch.Tensor], obs: torch.Tensor) -> torch.Tensor:
    raise NotImplementedError
```

```python solution=policy
# write solution here
def init_policy(obs_dim: int, n_actions: int, hidden: int, seed: int) -> dict[str, torch.Tensor]:
    raise NotImplementedError


def policy_probs(params: dict[str, torch.Tensor], obs: torch.Tensor) -> torch.Tensor:
    raise NotImplementedError
```

```python check=policy
p = init_policy(obs_dim=2, n_actions=2, hidden=32, seed=0)
assert isinstance(p, dict) and p, "init_policy should return a non-empty dict of tensors"
for k, v in p.items():
    assert isinstance(v, torch.Tensor), f"param {k!r} is {type(v).__name__}, expected a tensor"
    assert v.requires_grad, f"param {k!r} needs requires_grad=True so training can update it"

obs = torch.tensor([[1.0, 0.0], [0.0, 1.0]]).repeat(512, 1)
probs = policy_probs(p, obs)
assert probs.shape == (1024, 2), f"expected probs shape (1024, 2), got {tuple(probs.shape)}"
assert (probs >= 0).all(), "probabilities must be non-negative"
assert torch.allclose(probs.sum(-1), torch.ones(1024), atol=1e-5), "each row of probs must sum to 1"
assert policy_probs(p, obs[:1]).shape == (1, 2), "policy_probs must work for a batch of one"

same = init_policy(obs_dim=2, n_actions=2, hidden=32, seed=0)
other = init_policy(obs_dim=2, n_actions=2, hidden=32, seed=1)
assert all(torch.equal(p[k], same[k]) for k in p), "same seed must give identical params"
assert any(not torch.equal(p[k], other[k]) for k in p), "different seeds must give different params"

probs[:, 0].sum().backward()
for k, v in p.items():
    assert v.grad is not None and v.grad.abs().sum() > 0, f"no gradient reached param {k!r}"
```

<!-- write prose here: turning probabilities into actions -->

```python cell=sample
# write stub here
def sample_actions(probs: torch.Tensor, gen: torch.Generator) -> torch.Tensor:
    raise NotImplementedError
```

```python solution=sample
# write solution here
def sample_actions(probs: torch.Tensor, gen: torch.Generator) -> torch.Tensor:
    raise NotImplementedError
```

```python check=sample
import time

half = 50_000
probs = torch.tensor([[0.9, 0.1], [0.2, 0.8]]).repeat_interleave(half, 0)
a = sample_actions(probs, torch.Generator().manual_seed(0))
assert a.shape == (2 * half,), f"expected shape ({2 * half},), got {tuple(a.shape)}"
assert a.dtype == torch.long, f"actions should be integer (torch.long), got {a.dtype}"
assert a.min() >= 0 and a.max() <= 1, "actions must be valid indices into probs"
f_top, f_bottom = (a[:half] == 1).float().mean().item(), (a[half:] == 1).float().mean().item()
assert abs(f_top - 0.1) < 0.01, f"rows with p(action 1)=0.1 chose action 1 {f_top:.3f} of the time"
assert abs(f_bottom - 0.8) < 0.01, f"rows with p(action 1)=0.8 chose action 1 {f_bottom:.3f} of the time"

torch.manual_seed(123)
a1 = sample_actions(probs, torch.Generator().manual_seed(7))
torch.manual_seed(456)
a2 = sample_actions(probs, torch.Generator().manual_seed(7))
assert torch.equal(a1, a2), "sample_actions must draw from the generator it is given, not the global RNG"

big = torch.full((1_000_000, 2), 0.5)
start = time.perf_counter()
sample_actions(big, torch.Generator().manual_seed(0))
elapsed = time.perf_counter() - start
assert elapsed < 1.0, f"sampling 1M actions took {elapsed:.2f}s; budget is 1s (avoid a Python loop)"
```

<!-- write prose here: how likely was the action we took? -->

```python cell=logprob
# write stub here
def log_prob(probs: torch.Tensor, actions: torch.Tensor) -> torch.Tensor:
    raise NotImplementedError
```

```python solution=logprob
# write solution here
def log_prob(probs: torch.Tensor, actions: torch.Tensor) -> torch.Tensor:
    raise NotImplementedError
```

```python check=logprob
g = torch.Generator().manual_seed(0)
logits = torch.randn(1000, 3, generator=g, requires_grad=True)
probs = torch.softmax(logits, -1)
actions = torch.randint(0, 3, (1000,), generator=g)
lp = log_prob(probs, actions)
assert lp.shape == (1000,), f"expected one log-prob per row, shape (1000,), got {tuple(lp.shape)}"
expected = torch.log(probs[torch.arange(1000), actions])
worst = (lp - expected).abs().max().item()
assert worst < 1e-5, f"log_prob is off by up to {worst:.2e} from log(probs[action])"
assert lp.requires_grad, "log_prob must stay differentiable (no .detach(), .item() or numpy)"
lp.sum().backward()
assert logits.grad is not None and logits.grad.abs().sum() > 0, "no gradient flowed back through log_prob"
```

<!-- write prose here: deriving the policy gradient -->

```python cell=loss
# write stub here
def reinforce_loss(logp: torch.Tensor, rewards: torch.Tensor) -> torch.Tensor:
    raise NotImplementedError
```

```python solution=loss
# write solution here
def reinforce_loss(logp: torch.Tensor, rewards: torch.Tensor) -> torch.Tensor:
    raise NotImplementedError
```

```python check=loss
logp = torch.log(torch.full((8,), 0.5)).requires_grad_()
loss = reinforce_loss(logp, torch.zeros(8))
assert loss.shape == (), f"loss must be a scalar, got shape {tuple(loss.shape)}"
loss.backward()
assert logp.grad is not None and logp.grad.abs().sum() == 0, "with zero reward everywhere, the gradient must be zero"

obs = torch.ones(512, 1)
for seed in range(5):
    params = init_policy(obs_dim=1, n_actions=2, hidden=16, seed=seed)
    before = policy_probs(params, obs[:1])[0, 0].item()
    probs = policy_probs(params, obs)
    actions = sample_actions(probs, torch.Generator().manual_seed(seed))
    rewards = (actions == 0).float()
    loss = reinforce_loss(log_prob(probs, actions), rewards)
    grads = torch.autograd.grad(loss, list(params.values()))
    stepped = {k: v - 0.1 * g for (k, v), g in zip(params.items(), grads)}
    after = policy_probs(stepped, obs[:1])[0, 0].item()
    assert after > before, (
        f"seed {seed}: p(rewarded action) went {before:.3f} -> {after:.3f} after one step; "
        "minimizing the loss should make rewarded actions more likely"
    )
```

<!-- write prose here: the training loop -->

```python cell=train
# write stub here
def train(env: Flappy, params: dict[str, torch.Tensor], n_updates: int, lr: float) -> dict[str, torch.Tensor]:
    raise NotImplementedError
```

```python solution=train
# write solution here
def train(env: Flappy, params: dict[str, torch.Tensor], n_updates: int, lr: float) -> dict[str, torch.Tensor]:
    raise NotImplementedError
```

```python check=train
import resource
import sys
import time


class TwoStateProbe:

    def __init__(self, n: int, seed: int) -> None:
        self.n, self.gen = n, torch.Generator().manual_seed(seed)
        self.state = torch.zeros(n, dtype=torch.long)

    def _obs(self) -> torch.Tensor:
        self.state = torch.randint(0, 2, (self.n,), generator=self.gen)
        return torch.nn.functional.one_hot(self.state, 2).float()

    def reset(self) -> torch.Tensor:
        return self._obs()

    def step(self, actions: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        rewards = (actions == self.state).float()
        return self._obs(), rewards, torch.ones(self.n, dtype=torch.bool)


def mean_reward(env, params, steps: int) -> float:
    gen = torch.Generator().manual_seed(1)
    obs, total = env.reset(), 0.0
    with torch.no_grad():
        for _ in range(steps):
            obs, rewards, _ = env.step(sample_actions(policy_probs(params, obs), gen))
            total += rewards.mean().item()
    return total / steps


probe_params = train(TwoStateProbe(n=256, seed=0), init_policy(2, 2, 32, seed=0), n_updates=300, lr=1e-2)
probe_score = mean_reward(TwoStateProbe(n=1024, seed=2), probe_params, steps=20)
assert probe_score > 0.9, (
    f"on a probe where the right action is just the observed state, mean reward is {probe_score:.3f} "
    "(random is 0.5, perfect is 1.0); the loop isn't learning from observations"
)

start = time.perf_counter()
params = train(Flappy(n=1024, seed=0), init_policy(2, 2, 32, seed=0), n_updates=300, lr=1e-2)
elapsed = time.perf_counter() - start
score = mean_reward(Flappy(n=1024, seed=3), params, steps=50)
assert score > 0.95, f"flappy mean reward per step is {score:.3f} (random 0.5, perfect 1.0); need > 0.95"
assert elapsed < 20.0, f"training took {elapsed:.1f}s; budget is 20s"
peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (2**20 if sys.platform == "darwin" else 2**10)
assert peak_mb < 2048, f"peak memory {peak_mb:.0f} MB; budget is 2048 MB"
```

<!-- widget: watch the trained policy play (TODO: claude) -->
