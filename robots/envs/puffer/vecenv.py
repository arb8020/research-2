"""PufferLib 5.0 CPU envs via ctypes over shim.c.

The returned obs/reward/terminal tensors ARE the env's buffers: the next step()
overwrites them in place. Callers that keep them (rollout storage) must copy.
Envs that end during step() reset themselves; their obs row is the post-reset obs.
Actions are not range-checked (breakout treats unknown actions as no-op; cartpole
clamps to [-1, 1] and treats > 0.5 as push-right).
"""

import configparser
import ctypes
import weakref

import torch
from torch import Tensor

from robots.envs.puffer.build import HERE, build

_LOG_CAP = 4096


def _load(name: str) -> ctypes.CDLL:
    lib = ctypes.CDLL(str(build(name)))
    lib.vec_create.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint] + [ctypes.c_void_p] * 4
    lib.vec_create.restype = ctypes.c_void_p
    lib.vec_reset.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    lib.vec_reset.restype = None
    lib.vec_step.argtypes = [ctypes.c_void_p]
    lib.vec_step.restype = None
    lib.vec_log.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    lib.vec_log.restype = ctypes.c_int
    lib.vec_close.argtypes = [ctypes.c_void_p]
    lib.vec_close.restype = None
    return lib


def default_kwargs(name: str) -> dict[str, str]:
    ini = configparser.ConfigParser()
    ini.read_string((HERE / name / f"{name}.ini").read_text())
    return dict(ini["env"])


class VecEnv:
    """Owns the C vec handle and the four buffers it reads/writes."""

    def __init__(self, name: str, num_envs: int, seed: int, kwargs: dict[str, float]) -> None:
        lib = _load(name)
        assert lib.vec_num_atns() == 1
        env_kwargs = default_kwargs(name)
        unknown = set(kwargs) - set(env_kwargs)
        # unknown keys are harmless, but a key puf_init needs and doesn't get exit(1)s the process
        assert not unknown, f"unknown {name} kwargs {sorted(unknown)}; known: {sorted(env_kwargs)}"
        env_kwargs.update({k: str(v) for k, v in kwargs.items()})
        kw = ";".join(f"{k}={v}" for k, v in env_kwargs.items())

        self.name = name
        self.num_envs = num_envs
        self.obs_size: int = lib.vec_obs_size()
        self.num_actions: int = lib.vec_num_actions()
        self.obs = torch.zeros(num_envs, self.obs_size, dtype=torch.float32)
        self.actions = torch.zeros(num_envs, dtype=torch.float32)
        self.rewards = torch.zeros(num_envs, dtype=torch.float32)
        self.terminals = torch.zeros(num_envs, dtype=torch.float32)
        ptrs = (t.data_ptr() for t in (self.obs, self.actions, self.rewards, self.terminals))
        self.handle: int = lib.vec_create(num_envs, kw.encode(), seed, *ptrs)
        assert self.handle
        self.lib = lib
        # frees the C side on close() or GC, exactly once
        self._finalizer = weakref.finalize(self, lib.vec_close, self.handle)
        self.reset(seed)  # upstream envs are not steppable before puf_reset

    def reset(self, seed: int) -> Tensor:
        self.lib.vec_reset(self.handle, seed)
        return self.obs

    def step(self, actions: Tensor) -> tuple[Tensor, Tensor, Tensor]:
        self.actions.copy_(actions)
        self.lib.vec_step(self.handle)
        return self.obs, self.rewards, self.terminals

    def log(self) -> dict[str, float]:
        buf = ctypes.create_string_buffer(_LOG_CAP)
        n = self.lib.vec_log(self.handle, buf, _LOG_CAP)
        assert n >= 0, "vec_log output exceeded buffer"
        lines = buf.raw[:n].decode().splitlines()
        return {k: float(v) for k, v in (line.split("=", 1) for line in lines)}

    def close(self) -> None:
        self._finalizer()


def make(name: str, num_envs: int, seed: int = 0, **kwargs: float) -> VecEnv:
    return VecEnv(name, num_envs, seed, kwargs)
