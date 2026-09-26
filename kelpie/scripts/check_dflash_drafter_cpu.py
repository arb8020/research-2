"""CPU smoke of check_dflash_drafter: real drafter weights, random taps + a 512-row fake vocab,
fp32. No target model, no GPU (~2 min, downloads the 1.6 GB drafter). Run from kelpie/:
    PYTHONPATH=kelpie-models:kelpie-engine uv run --no-project --with torch --with transformers==4.57.1 \
        --with datasets --with safetensors --with huggingface_hub --with numpy --with pillow \
        python scripts/check_dflash_drafter_cpu.py
"""
import sys, torch
# reference code: trust_remote_code from the HF repo
from kelpie_models.kernels.op import bind
from kelpie_models.models.torch import dflash
bind("cpu")
sys.path.insert(0, __import__("os").path.dirname(__file__))
import check_dflash_drafter as chk
from transformers import AutoModel
torch.manual_seed(0)
dt = torch.float32
ref = AutoModel.from_pretrained("z-lab/gpt-oss-20b-DFlash", trust_remote_code=True, dtype=dt, attn_implementation="sdpa").eval()
w, cfg = dflash.load(device="cpu", dtype=dt, checkpoint="z-lab/gpt-oss-20b-DFlash")
V = 512
embed = torch.randn(V, 2880) * 0.02
lm = torch.randn(V, 2880) * 0.02
C = 6
taps = {l: torch.randn(C, 2880) * (1 + l) for l in cfg.tap_layers}
block = torch.tensor([5] + [7] * 7)
r = chk.reference_logits(ref, taps, list(cfg.tap_layers), embed[block], lm, C, dt)
k = chk.kelpie_logits(dflash, w, cfg, taps, block, embed, lm, C, "cpu")
print("max diff", (r - k).abs().max().item(), "scale", r.abs().max().item())
print(r.argmax(-1), k.argmax(-1))
