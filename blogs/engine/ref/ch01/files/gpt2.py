"""Chapter 1: the GPT-2 forward pass, in functional torch.

One sequence, no batch, no KV cache: `generate` recomputes the whole prefix
every step. Every tensor name ends in its shape, in these letters:

    T  query length      S  key/value length     D  d_model (768)
    N  heads (12)        H  head dim (64)        F  mlp hidden (3072)
    V  vocab (50257)     L  layers (12)

so `x_TD` is [T, D] and `w_qkv_D3NH` is [D, 3, N, H]. Contractions are
`einsum`s spelled in those letters ("T D, D F -> T F").

The code between `# region: <name>` and `# endregion` is yours to write;
everything else is given.
"""

import json
import math
import sys
from dataclasses import dataclass

import torch
from einops import einsum, rearrange, reduce
from huggingface_hub import hf_hub_download
from safetensors.torch import load_file
from tokenizers import Tokenizer

CHECKPOINT = "openai-community/gpt2"


@dataclass(frozen=True)
class Config:
    L: int  # layers
    N: int  # heads
    D: int  # d_model
    H: int  # head dim: D / N
    F: int  # mlp hidden: 4 D
    V: int  # vocab
    T_max: int  # context: rows in the position table
    eps: float  # layer norm epsilon


@dataclass(frozen=True)
class Layer:
    """One block's weights, in the layouts the einsums below want."""

    ln1_w_D: torch.Tensor
    ln1_b_D: torch.Tensor
    w_qkv_D3NH: torch.Tensor  # q, k, v projections, all heads
    b_qkv_3NH: torch.Tensor
    w_o_NHD: torch.Tensor  # heads back to d_model
    b_o_D: torch.Tensor
    ln2_w_D: torch.Tensor
    ln2_b_D: torch.Tensor
    w_up_DF: torch.Tensor
    b_up_F: torch.Tensor
    w_down_FD: torch.Tensor
    b_down_D: torch.Tensor


@dataclass(frozen=True)
class Weights:
    wte_VD: torch.Tensor  # token embeddings, also the lm head (tied)
    wpe_TD: torch.Tensor  # position embeddings: T_max rows
    layers: list[Layer]
    lnf_w_D: torch.Tensor
    lnf_b_D: torch.Tensor


def load(
    dtype: torch.dtype = torch.float32, device: str = "cpu"
) -> tuple[Weights, Config]:
    """GPT-2 small from the HF hub (downloaded once to its cache).

    The checkpoint stores each linear as a Conv1D, [in, out], with q, k, v
    fused into one: c_attn is [D, 3 * N * H]. Here they get named axes."""
    with open(hf_hub_download(CHECKPOINT, "config.json")) as f:
        hf = json.load(f)
    assert hf["activation_function"] == "gelu_new"  # the tanh GELU
    D, N = hf["n_embd"], hf["n_head"]
    cfg = Config(L=hf["n_layer"], N=N, D=D, H=D // N, F=4 * D,
                 V=hf["vocab_size"], T_max=hf["n_positions"],
                 eps=hf["layer_norm_epsilon"])
    sd = load_file(hf_hub_download(CHECKPOINT, "model.safetensors"))

    def get(name: str, pattern: str = "", **sizes: int) -> torch.Tensor:
        t = sd[name].to(device=device, dtype=dtype)
        return rearrange(t, pattern, **sizes).contiguous() if pattern else t

    def layer(i: int) -> Layer:
        p = f"h.{i}."
        return Layer(
            ln1_w_D=get(p + "ln_1.weight"),
            ln1_b_D=get(p + "ln_1.bias"),
            w_qkv_D3NH=get(p + "attn.c_attn.weight",
                           "D (k N H) -> D k N H", k=3, N=N),
            b_qkv_3NH=get(p + "attn.c_attn.bias", "(k N H) -> k N H", k=3, N=N),
            w_o_NHD=get(p + "attn.c_proj.weight", "(N H) D -> N H D", N=N),
            b_o_D=get(p + "attn.c_proj.bias"),
            ln2_w_D=get(p + "ln_2.weight"),
            ln2_b_D=get(p + "ln_2.bias"),
            w_up_DF=get(p + "mlp.c_fc.weight"),
            b_up_F=get(p + "mlp.c_fc.bias"),
            w_down_FD=get(p + "mlp.c_proj.weight"),
            b_down_D=get(p + "mlp.c_proj.bias"),
        )

    w = Weights(wte_VD=get("wte.weight"), wpe_TD=get("wpe.weight"),
                layers=[layer(i) for i in range(cfg.L)],
                lnf_w_D=get("ln_f.weight"), lnf_b_D=get("ln_f.bias"))
    return w, cfg


def tokenizer() -> Tokenizer:
    """GPT-2's byte-level BPE: .encode(text).ids, .decode(ids)."""
    return Tokenizer.from_file(hf_hub_download(CHECKPOINT, "tokenizer.json"))


# region: linear
def linear(x_TD, w_DF, b_F):
    """Each row of x times w, plus b: [T, D] -> [T, F]."""
    return einsum(x_TD, w_DF, "T D, D F -> T F") + b_F
# endregion


# region: gelu
def gelu(x_TF):
    """GPT-2's GELU, the tanh approximation, elementwise."""
    inner_TF = math.sqrt(2 / math.pi) * (x_TF + 0.044715 * x_TF**3)
    return 0.5 * x_TF * (1 + torch.tanh(inner_TF))
# endregion


# region: layer_norm
def layer_norm(x_TD, w_D, b_D, eps):
    """Normalize each row over D (biased variance), then scale and shift."""
    mean_T1 = reduce(x_TD, "T D -> T 1", "mean")
    var_T1 = reduce((x_TD - mean_T1) ** 2, "T D -> T 1", "mean")
    return (x_TD - mean_T1) / torch.sqrt(var_T1 + eps) * w_D + b_D
# endregion


# region: attention
def attention(q_TNH, k_SNH, v_SNH):
    """Causal attention, all heads at once: query t sees keys s <= t."""
    T, S, H = q_TNH.shape[0], k_SNH.shape[0], q_TNH.shape[2]
    scores_NTS = einsum(q_TNH, k_SNH, "T N H, S N H -> N T S")
    scores_NTS = scores_NTS / math.sqrt(H)
    future_TS = torch.ones(T, S, dtype=torch.bool, device=q_TNH.device)
    future_TS = future_TS.triu(1)
    scores_NTS = scores_NTS.masked_fill(future_TS, float("-inf"))
    probs_NTS = torch.softmax(scores_NTS, dim=-1)  # over S
    return einsum(probs_NTS, v_SNH, "N T S, S N H -> T N H")


def self_attention(x_TD, layer):
    """One block's attention: x -> q, k, v -> attend -> back to D.
    Keys and values come from the same tokens as the queries: S = T."""
    qkv_3TNH = einsum(x_TD, layer.w_qkv_D3NH, "T D, D k N H -> k T N H")
    q_TNH, k_SNH, v_SNH = qkv_3TNH + layer.b_qkv_3NH[:, None]
    out_TNH = attention(q_TNH, k_SNH, v_SNH)
    return einsum(out_TNH, layer.w_o_NHD, "T N H, N H D -> T D") + layer.b_o_D
# endregion


# region: block
def mlp(x_TD, layer):
    """Up to F, GELU, back down to D."""
    h_TF = gelu(linear(x_TD, layer.w_up_DF, layer.b_up_F))
    return linear(h_TF, layer.w_down_FD, layer.b_down_D)


def block(x_TD, layer, cfg):
    """A pre-norm residual block: x + attention(ln(x)), then + mlp(ln(.))."""
    h_TD = layer_norm(x_TD, layer.ln1_w_D, layer.ln1_b_D, cfg.eps)
    x_TD = x_TD + self_attention(h_TD, layer)
    h_TD = layer_norm(x_TD, layer.ln2_w_D, layer.ln2_b_D, cfg.eps)
    return x_TD + mlp(h_TD, layer)
# endregion


# region: forward
def forward(w, cfg, tokens_T):
    """Token ids [T] -> logits [T, V]: row t scores the token after t."""
    T = tokens_T.shape[0]
    x_TD = w.wte_VD[tokens_T] + w.wpe_TD[:T]
    for layer in w.layers:
        x_TD = block(x_TD, layer, cfg)
    x_TD = layer_norm(x_TD, w.lnf_w_D, w.lnf_b_D, cfg.eps)
    return einsum(x_TD, w.wte_VD, "T D, V D -> T V")  # the tied lm head
# endregion


# region: generate
@torch.no_grad()
def generate(w, cfg, prompt, n):
    """Greedy: append the most likely next token, n times. Returns the n
    new token ids. Each step runs forward on the whole sequence."""
    ids = list(prompt)
    for _ in range(n):
        tokens_T = torch.tensor(ids, device=w.wte_VD.device)
        logits_TV = forward(w, cfg, tokens_T)
        ids.append(int(logits_TV[-1].argmax()))
    return ids[len(prompt):]
# endregion


if __name__ == "__main__":  # python gpt2.py "Some text to continue"
    text = sys.argv[1] if len(sys.argv) > 1 else "The meaning of life is"
    tok = tokenizer()
    w, cfg = load()
    print(text + tok.decode(generate(w, cfg, tok.encode(text).ids, 20)))
