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

```cpp env=flappy readonly
#include <cstdint>
#include <cstdlib>

typedef int32_t s32;
typedef uint64_t u64;
typedef uint8_t u8;
typedef float f32;

constexpr s32 EPISODE_LEN = 32;
constexpr s32 OBS_DIM = 2;

struct Bird {
    s32 pipe_row;
    s32 bird_row;
    s32 t;
};

struct Flappy {
    s32 n;
    u64 rng;
    Bird *birds;
    f32 *obs;
    s32 *actions;
    f32 *rewards;
    u8 *dones;
};

static u64 rng_next(u64 *s) {
    *s ^= *s << 13;
    *s ^= *s >> 7;
    *s ^= *s << 17;
    return *s;
}

static void draw_pipe(Flappy *env, s32 i) {
    Bird *b = &env->birds[i];
    b->pipe_row = (s32)(rng_next(&env->rng) & 1);
    env->obs[i * OBS_DIM + 0] = b->pipe_row == 0 ? 1.0f : 0.0f;
    env->obs[i * OBS_DIM + 1] = b->pipe_row == 1 ? 1.0f : 0.0f;
}

extern "C" Flappy *flappy_create(s32 n, u64 seed, f32 *obs, s32 *actions, f32 *rewards, u8 *dones) {
    if (n <= 0 || !obs || !actions || !rewards || !dones) return nullptr;
    Flappy *env = (Flappy *)calloc(1, sizeof(Flappy));
    Bird *birds = (Bird *)calloc((size_t)n, sizeof(Bird));
    if (!env || !birds) {
        free(env);
        free(birds);
        return nullptr;
    }
    env->n = n;
    env->rng = seed * 0x9E3779B97F4A7C15ull + 1;
    env->birds = birds;
    env->obs = obs;
    env->actions = actions;
    env->rewards = rewards;
    env->dones = dones;
    return env;
}

extern "C" void flappy_reset(Flappy *env) {
    for (s32 i = 0; i < env->n; i++) {
        env->birds[i].bird_row = 0;
        env->birds[i].t = 0;
        env->rewards[i] = 0.0f;
        env->dones[i] = 0;
        draw_pipe(env, i);
    }
}

extern "C" void flappy_step(Flappy *env) {
    for (s32 i = 0; i < env->n; i++) {
        Bird *b = &env->birds[i];
        b->bird_row = env->actions[i] == 0 ? 0 : 1;
        env->rewards[i] = b->bird_row != b->pipe_row ? 1.0f : 0.0f;
        b->t += 1;
        env->dones[i] = b->t >= EPISODE_LEN;
        if (env->dones[i]) b->t = 0;
        draw_pipe(env, i);
    }
}

extern "C" void flappy_free(Flappy *env) {
    if (!env) return;
    free(env->birds);
    free(env);
}
```

```cpp render=flappy
#include <emscripten/emscripten.h>
#include "raylib.h"

constexpr s32 W = 480;
constexpr s32 H = 240;
constexpr s32 ROW_H = H / 2;
constexpr s32 BIRD_X = 120;
constexpr s32 PIPE_W = 40;
constexpr f32 PIPE_WAIT_X = 330.0f;
constexpr f32 PIPE_SPEED = 700.0f;

enum Phase : u8 { WAITING, SLIDING };

struct Game {
    Flappy *env;
    f32 obs[OBS_DIM];
    s32 action;
    f32 reward;
    u8 done;
    Phase phase;
    s32 bird_row;
    s32 sliding_pipe_row;
    f32 pipe_x;
    s32 score;
    s32 steps;
    s32 last_score;
    s32 last_steps;
};

static Game game;

static s32 observed_pipe_row(Game *g) {
    return g->obs[0] == 1.0f ? 0 : 1;
}

static void take_action(Game *g, s32 row) {
    g->bird_row = row;
    g->sliding_pipe_row = observed_pipe_row(g);
    g->action = row;
    flappy_step(g->env);
    g->score += (s32)g->reward;
    g->steps += 1;
    g->phase = SLIDING;
}

static void tick(void) {
    Game *g = &game;
    if (g->phase == WAITING) {
        if (IsKeyPressed(KEY_UP) || IsKeyPressed(KEY_K)) take_action(g, 0);
        else if (IsKeyPressed(KEY_DOWN) || IsKeyPressed(KEY_J)) take_action(g, 1);
    } else {
        g->pipe_x -= PIPE_SPEED * GetFrameTime();
        if (g->pipe_x < -PIPE_W) {
            if (g->done) {
                g->last_score = g->score;
                g->last_steps = g->steps;
                g->score = 0;
                g->steps = 0;
            }
            g->pipe_x = PIPE_WAIT_X;
            g->phase = WAITING;
        }
    }

    s32 pipe_row = g->phase == SLIDING ? g->sliding_pipe_row : observed_pipe_row(g);
    bool passed_bird = g->phase == SLIDING && g->pipe_x < BIRD_X;
    Color bird = !passed_bird ? ORANGE : (g->reward == 0.0f ? RED : GOLD);

    BeginDrawing();
    ClearBackground(RAYWHITE);
    DrawLine(0, ROW_H, W, ROW_H, LIGHTGRAY);
    DrawRectangle((s32)g->pipe_x, pipe_row * ROW_H, PIPE_W, ROW_H, DARKGREEN);
    DrawCircle(BIRD_X, g->bird_row * ROW_H + ROW_H / 2, 18.0f, bird);
    DrawText(TextFormat("%d / %d", g->score, g->steps), 10, 10, 20, DARKGRAY);
    if (g->last_steps > 0) DrawText(TextFormat("last episode %d / %d", g->last_score, g->last_steps), 10, H - 26, 16, GRAY);
    if (g->phase == WAITING) DrawText("up or down?", W - 130, 10, 20, GRAY);
    EndDrawing();
}

int main(void) {
    InitWindow(W, H, "flappy");
    u64 seed = (u64)(emscripten_random() * 2147483647.0);
    game.env = flappy_create(1, seed, game.obs, &game.action, &game.reward, &game.done);
    if (!game.env) return 1;
    flappy_reset(game.env);
    game.pipe_x = PIPE_WAIT_X;
    game.phase = WAITING;
    emscripten_set_main_loop(tick, 0, 1);
    return 0;
}
```

```python given
import ctypes
import weakref

import numpy as np
import torch

OBS_DIM, N_ACTIONS = 2, 2


class Flappy:

    def __init__(self, n: int, seed: int) -> None:
        lib = ctypes.CDLL(ENV_SO["flappy"])
        ptr = ctypes.c_void_p
        lib.flappy_create.argtypes = [ctypes.c_int32, ctypes.c_uint64, ptr, ptr, ptr, ptr]
        lib.flappy_create.restype = ptr
        for fn in (lib.flappy_reset, lib.flappy_step, lib.flappy_free):
            fn.argtypes = [ptr]
            fn.restype = None
        self.n, self.lib = n, lib
        self.obs = np.zeros((n, OBS_DIM), np.float32)
        self.actions = np.zeros(n, np.int32)
        self.rewards = np.zeros(n, np.float32)
        self.dones = np.zeros(n, np.uint8)
        self.handle = lib.flappy_create(
            n, seed, self.obs.ctypes.data, self.actions.ctypes.data, self.rewards.ctypes.data, self.dones.ctypes.data
        )
        assert self.handle, "flappy_create returned null"
        weakref.finalize(self, lib.flappy_free, self.handle)

    def reset(self) -> torch.Tensor:
        self.lib.flappy_reset(self.handle)
        return torch.from_numpy(self.obs.copy())

    def step(self, actions: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        assert actions.shape == (self.n,), f"actions must have shape ({self.n},), got {tuple(actions.shape)}"
        self.actions[:] = actions.numpy()
        self.lib.flappy_step(self.handle)
        return (
            torch.from_numpy(self.obs.copy()),
            torch.from_numpy(self.rewards.copy()),
            torch.from_numpy(self.dones.astype(bool)),
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
