"""SmolVLM (Idefics3): SigLIP vision encoder + pixel-shuffle connector + SmolLM2 (Llama) decoder.

Text tower runs through `models.torch.llama`; `forward` here IS llama's forward over
`weights.text`. The vision encoder runs OUTSIDE the step -- `encode()` is eager torch over
pixels, driven once per request by `sdk/multimodal.py` -- and its rows enter the step at exactly
one place: `Tokens.embeds`, applied by `Tokens.embed(table)`. No pixel reaches the forward.

Preprocessing follows HF Idefics3ImageProcessor: resize longest edge, round up to multiples of
the tile, split into tile x tile crops, append the whole image resized to one tile; every crop
is exactly tile x tile so SigLIP's NaViT position buckets collapse to 0..n_patches-1.
"""

from __future__ import annotations

import io
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import torch
import torch.nn.functional as torch_f
from PIL import Image

from kelpie_models.models.torch import llama
from kelpie_models.sdk.device import Requests, Tokens
from kelpie_models.sdk.groups import AttnSpec
from kelpie_models.sdk.hf import load_safetensors, resolve_hf
from kelpie_models.sdk.kv import KV
from kelpie_models.sdk.taps import Taps

CHECKPOINT = "HuggingFaceTB/SmolVLM-256M-Instruct"
CHAT_FAMILY = "default"
DTYPE = "float32"
ADAPTER = "kelpie_http.vlm:SmolVLMAdapter"
IMAGE_TOKEN = "<image>"
FAKE_IMAGE_TOKEN = "<fake_token_around_image>"
GLOBAL_IMAGE_TAG = "<global-img>"
END_OF_UTTERANCE = 49279  # generation_config eos; the text config's eos (2) never ends a turn
MAX_IMAGE_SIZE = 4096  # HF hard cap after the longest-edge resize


@dataclass(frozen=True)
class SigLIPConfig:
    n_layers: int
    n_heads: int
    hidden: int
    intermediate: int
    patch: int
    image_size: int  # tile side; n_patches = (image_size // patch) ** 2
    eps: float


@dataclass(frozen=True)
class SmolVLMConfig:
    vision: SigLIPConfig
    text: llama.LlamaConfig
    image_token: int
    scale_factor: int  # pixel shuffle; tokens per tile = n_patches / scale_factor**2
    longest_edge: int  # preprocessing: resize longest edge to this before tiling

    @property
    def n_layers(self) -> int:
        return self.text.n_layers

    @property
    def n_kv_heads(self) -> int:
        return self.text.n_kv_heads

    @property
    def head_dim(self) -> int:
        return self.text.head_dim

    @property
    def max_seq_len(self) -> int:
        return self.text.max_seq_len

    @property
    def eos_token(self) -> int:
        return self.text.eos_token

    @property
    def vocab(self) -> int:
        return self.text.vocab

    @property
    def tokens_per_tile(self) -> int:
        n_patches = (self.vision.image_size // self.vision.patch) ** 2
        return n_patches // self.scale_factor**2


@dataclass(frozen=True)
class SigLIPLayer:
    ln_1_w: torch.Tensor
    ln_1_b: torch.Tensor
    q_w: torch.Tensor  # [hidden, hidden]
    q_b: torch.Tensor
    k_w: torch.Tensor
    k_b: torch.Tensor
    v_w: torch.Tensor
    v_b: torch.Tensor
    o_w: torch.Tensor
    o_b: torch.Tensor
    ln_2_w: torch.Tensor
    ln_2_b: torch.Tensor
    fc1_w: torch.Tensor  # [intermediate, hidden]
    fc1_b: torch.Tensor
    fc2_w: torch.Tensor  # [hidden, intermediate]
    fc2_b: torch.Tensor


@dataclass(frozen=True)
class SigLIP:
    patch_w: torch.Tensor  # [hidden, 3, patch, patch]
    patch_b: torch.Tensor
    pos_embed: torch.Tensor  # [n_patches, hidden]
    layers: tuple[SigLIPLayer, ...]
    post_ln_w: torch.Tensor
    post_ln_b: torch.Tensor


@dataclass(frozen=True)
class SmolVLM:
    vision: SigLIP
    connector: torch.Tensor  # [text.hidden, vision.hidden * scale_factor**2]
    text: llama.Llama


@dataclass(frozen=True)
class ImageTiles:
    """One image after preprocessing: [n_tiles, 3, tile, tile] float32 (normalized), and the
    split grid (rows == cols == 0 means a single global tile)."""

    pixels: torch.Tensor
    rows: int
    cols: int


def attn_specs(cfg: SmolVLMConfig) -> list[AttnSpec]:
    return llama.attn_specs(cfg.text)


def forward(  # noqa: PLR0913, PLR0917
    weights: SmolVLM,
    config: SmolVLMConfig,
    tokens: Tokens,
    requests: Requests,
    kv: list[KV],
    taps: Taps,
) -> torch.Tensor:
    """The text tower, whole. The image rows are already on `tokens.embeds`."""
    return llama.forward(weights.text, config.text, tokens, requests, kv, taps)


def warm_payload(cfg: SmolVLMConfig) -> list[ImageTiles]:
    """The smallest thing `encode` takes: one image, one global tile of zeros. build's warm pass
    encodes it so the vision tower's ops resolve before the kernel table freezes."""
    tile = cfg.vision.image_size
    return [ImageTiles(torch.zeros(1, 3, tile, tile), rows=0, cols=0)]


def encode(w: SmolVLM, cfg: SmolVLMConfig, images: list[ImageTiles]) -> torch.Tensor:
    """All of a request's images -> [sum(n_tiles) * tokens_per_tile, text.hidden], in prompt
    order (tiles row-major then the global tile, images in order). Eager torch, outside the step,
    run once per request."""
    assert images, "encode with no images"
    pixels = torch.cat([im.pixels for im in images], dim=0)
    pixels = pixels.to(w.connector.device, w.connector.dtype)
    feats = siglip_forward(w.vision, cfg.vision, pixels)  # [n_tiles, n_patches, vh]
    shuffled = pixel_shuffle(feats, cfg.scale_factor)  # [n_tiles, tokens_per_tile, vh * s*s]
    out = shuffled @ w.connector.T
    out = out.reshape(-1, out.shape[-1])
    assert out.shape[0] == pixels.shape[0] * cfg.tokens_per_tile, out.shape
    return out


def siglip_forward(w: SigLIP, cfg: SigLIPConfig, pixels: torch.Tensor) -> torch.Tensor:
    """pixels [n, 3, image_size, image_size] -> [n, n_patches, hidden]."""
    n = pixels.shape[0]
    assert pixels.shape[2] == pixels.shape[3] == cfg.image_size, pixels.shape
    x = torch_f.conv2d(pixels, w.patch_w, w.patch_b, stride=cfg.patch)
    x = x.flatten(2).transpose(1, 2)  # [n, n_patches, hidden]
    assert x.shape[1] == w.pos_embed.shape[0], (x.shape, w.pos_embed.shape)
    x = x + w.pos_embed[None]
    head_dim = cfg.hidden // cfg.n_heads
    for layer in w.layers:
        h = torch.ops.kelpie.layer_norm(x, layer.ln_1_w, layer.ln_1_b, cfg.eps)
        q = (h @ layer.q_w.T + layer.q_b).view(n, -1, cfg.n_heads, head_dim).transpose(1, 2)
        k = (h @ layer.k_w.T + layer.k_b).view(n, -1, cfg.n_heads, head_dim).transpose(1, 2)
        v = (h @ layer.v_w.T + layer.v_b).view(n, -1, cfg.n_heads, head_dim).transpose(1, 2)
        a = torch_f.scaled_dot_product_attention(q, k, v)  # bidirectional
        a = a.transpose(1, 2).reshape(n, -1, cfg.hidden)
        x = x + (a @ layer.o_w.T + layer.o_b)
        h = torch.ops.kelpie.layer_norm(x, layer.ln_2_w, layer.ln_2_b, cfg.eps)
        h = torch.ops.kelpie.gelu(h @ layer.fc1_w.T + layer.fc1_b)
        x = x + (h @ layer.fc2_w.T + layer.fc2_b)
    return torch.ops.kelpie.layer_norm(x, w.post_ln_w, w.post_ln_b, cfg.eps)


def pixel_shuffle(x: torch.Tensor, s: int) -> torch.Tensor:
    """[b, hw, d] -> [b, hw / s^2, d * s^2]. Deliberately follows HF Idefics3Connector's exact
    view/permute order, not the canonical space-to-depth -- must match HF bit for bit."""
    b, seq, d = x.shape
    side = int(math.isqrt(seq))
    assert side * side == seq, seq
    x = x.view(b, side, side, d)
    x = x.view(b, side, side // s, d * s)
    x = x.permute(0, 2, 1, 3)
    x = x.reshape(b, side // s, side // s, d * s * s)
    x = x.permute(0, 2, 1, 3)
    return x.reshape(b, seq // (s * s), d * s * s)


def preprocess(
    image: Image.Image, cfg: SmolVLMConfig, longest_edge: int | None = None
) -> ImageTiles:
    tile = cfg.vision.image_size
    le = longest_edge or cfg.longest_edge
    img = image.convert("RGB")
    h, w = resize_output_size(img.height, img.width, le)
    img = img.resize((w, h), Image.LANCZOS)
    h, w = round_up_to_tiles(img.height, img.width, tile)
    img = img.resize((w, h), Image.LANCZOS)
    if h > tile or w > tile:
        rows, cols = math.ceil(h / tile), math.ceil(w / tile)
        crops = [
            img.crop((c * tile, r * tile, (c + 1) * tile, (r + 1) * tile))
            for r in range(rows)
            for c in range(cols)
        ]
        crops.append(img.resize((tile, tile), Image.LANCZOS))
    else:
        rows, cols = 0, 0
        crops = [img]
    pixels = torch.stack([normalize(c) for c in crops])
    assert pixels.shape[1:] == (3, tile, tile), pixels.shape
    return ImageTiles(pixels=pixels, rows=rows, cols=cols)


def resize_output_size(height: int, width: int, max_len: int) -> tuple[int, int]:
    """HF get_resize_output_image_size: longest edge -> max_len, capped at MAX_IMAGE_SIZE."""
    aspect = width / height
    if width >= height:
        width = max_len
        height = int(width / aspect)
        height += height % 2
    else:
        height = max_len
        width = int(height * aspect)
        width += width % 2
    height, width = max(height, 1), max(width, 1)
    aspect = width / height
    if width >= height and width > MAX_IMAGE_SIZE:
        width = MAX_IMAGE_SIZE
        height = int(width / aspect)
    elif height > width and height > MAX_IMAGE_SIZE:
        height = MAX_IMAGE_SIZE
        width = int(height * aspect)
    return max(height, 1), max(width, 1)


def round_up_to_tiles(height: int, width: int, tile: int) -> tuple[int, int]:
    """HF resize_for_vision_encoder."""
    aspect = width / height
    if width >= height:
        width = math.ceil(width / tile) * tile
        height = int(width / aspect)
        height = math.ceil(height / tile) * tile
    else:
        height = math.ceil(height / tile) * tile
        width = int(height * aspect)
        width = math.ceil(width / tile) * tile
    return height, width


def normalize(img: Image.Image) -> torch.Tensor:
    """uint8 HWC -> float32 CHW in [-1, 1]."""
    arr = np.asarray(img, dtype=np.float32) / 255.0
    return torch.from_numpy((arr - 0.5) / 0.5).permute(2, 0, 1).contiguous()


def decode_image(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def image_prompt(tiles: ImageTiles, cfg: SmolVLMConfig) -> str:
    n = cfg.tokens_per_tile
    glob = f"{FAKE_IMAGE_TOKEN}{GLOBAL_IMAGE_TAG}{IMAGE_TOKEN * n}{FAKE_IMAGE_TOKEN}"
    if tiles.rows == 0 and tiles.cols == 0:
        return glob
    out = ""
    for r in range(tiles.rows):
        for c in range(tiles.cols):
            out += f"{FAKE_IMAGE_TOKEN}<row_{r + 1}_col_{c + 1}>{IMAGE_TOKEN * n}"
        out += "\n"
    return out + "\n" + glob


def chat_prompt(messages: list[tuple[str, list[str | ImageTiles]]], cfg: SmolVLMConfig) -> str:
    """messages: [(role, [text | ImageTiles, ...])]. add_generation_prompt=True."""
    out = "<|im_start|>"
    for role, parts in messages:
        assert parts, "empty message"
        out += role.capitalize() + (":" if isinstance(parts[0], ImageTiles) else ": ")
        for part in parts:
            out += image_prompt(part, cfg) if isinstance(part, ImageTiles) else part
        out += "<end_of_utterance>\n"
    return out + "Assistant:"


def load(
    device: torch.device | str = "cpu",
    dtype: torch.dtype = torch.float32,
    checkpoint: str = CHECKPOINT,
) -> tuple[SmolVLM, SmolVLMConfig]:
    cfg_path, st_paths = resolve_hf(checkpoint)
    with open(cfg_path) as f:
        cfg = config_from_hf(json.load(f))
    return from_state_dict(load_safetensors(st_paths), cfg, device, dtype), cfg


def config_from_hf(c: Mapping[str, Any]) -> SmolVLMConfig:
    v = c["vision_config"]
    vision = SigLIPConfig(
        n_layers=v["num_hidden_layers"],
        n_heads=v["num_attention_heads"],
        hidden=v["hidden_size"],
        intermediate=v["intermediate_size"],
        patch=v["patch_size"],
        image_size=v["max_image_size"]["longest_edge"],
        eps=v["layer_norm_eps"],
    )
    assert vision.image_size == v["image_size"], (vision.image_size, v["image_size"])
    return SmolVLMConfig(
        vision=vision,
        text=llama.config_from_hf(c["text_config"], eos_token=END_OF_UTTERANCE),
        image_token=c["image_token_id"],
        scale_factor=c["scale_factor"],
        longest_edge=v["size"]["longest_edge"],
    )


def from_state_dict(
    sd: Mapping[str, torch.Tensor],
    cfg: SmolVLMConfig,
    device: torch.device | str,
    dtype: torch.dtype,
) -> SmolVLM:
    def t(name: str) -> torch.Tensor:
        return sd[name].to(device=device, dtype=dtype)

    def layer(i: int) -> SigLIPLayer:
        p = f"model.vision_model.encoder.layers.{i}"
        return SigLIPLayer(
            ln_1_w=t(f"{p}.layer_norm1.weight"),
            ln_1_b=t(f"{p}.layer_norm1.bias"),
            q_w=t(f"{p}.self_attn.q_proj.weight"),
            q_b=t(f"{p}.self_attn.q_proj.bias"),
            k_w=t(f"{p}.self_attn.k_proj.weight"),
            k_b=t(f"{p}.self_attn.k_proj.bias"),
            v_w=t(f"{p}.self_attn.v_proj.weight"),
            v_b=t(f"{p}.self_attn.v_proj.bias"),
            o_w=t(f"{p}.self_attn.out_proj.weight"),
            o_b=t(f"{p}.self_attn.out_proj.bias"),
            ln_2_w=t(f"{p}.layer_norm2.weight"),
            ln_2_b=t(f"{p}.layer_norm2.bias"),
            fc1_w=t(f"{p}.mlp.fc1.weight"),
            fc1_b=t(f"{p}.mlp.fc1.bias"),
            fc2_w=t(f"{p}.mlp.fc2.weight"),
            fc2_b=t(f"{p}.mlp.fc2.bias"),
        )

    vision = SigLIP(
        patch_w=t("model.vision_model.embeddings.patch_embedding.weight"),
        patch_b=t("model.vision_model.embeddings.patch_embedding.bias"),
        pos_embed=t("model.vision_model.embeddings.position_embedding.weight"),
        layers=tuple(layer(i) for i in range(cfg.vision.n_layers)),
        post_ln_w=t("model.vision_model.post_layernorm.weight"),
        post_ln_b=t("model.vision_model.post_layernorm.bias"),
    )
    w = SmolVLM(
        vision=vision,
        connector=t("model.connector.modality_projection.proj.weight"),
        text=llama.from_state_dict(sd, cfg.text, device, dtype, prefix="model.text_model"),
    )
    n_patches = (cfg.vision.image_size // cfg.vision.patch) ** 2
    assert w.vision.pos_embed.shape == (n_patches, cfg.vision.hidden), w.vision.pos_embed.shape
    assert w.connector.shape == (cfg.text.hidden, cfg.vision.hidden * cfg.scale_factor**2)
    return w
