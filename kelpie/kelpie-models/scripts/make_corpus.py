"""Generate tests/oracle/corpus/<model>/<case>.npz: StepBatch arrays + HF fp32 eager logits.

    uv run python scripts/make_corpus.py [gpt2] [qwen3]

Cases (per model): prefill_decode (two requests prefilled together, then two decode steps) and
chunked (one 9-token request prefilled as 4 + 5). The file name carries the first 12 hex of the
batch sha256 so a changed scenario is a new file, never a silently rewritten one.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from conftest import Seq  # noqa: E402
from oracle.corpus import BATCH_KEYS, CORPUS, Step, batch_sha256, write_case  # noqa: E402

from kelpie_models.sdk.groups import derive_groups  # noqa: E402
from kelpie_models.models.torch import gpt2, gpt_oss, qwen3  # noqa: E402

MODELS = {"gpt2": gpt2.MODEL_ID, "qwen3": qwen3.MODEL_ID, "gpt_oss": "openai/gpt-oss-20b@layers=2"}
LONG = 200  # gpt-oss: longer than the 128-token sliding window
PROMPT_A = [464, 3290, 7586, 21831, 18045, 625, 262]
PROMPT_B = [11, 290, 262]
PROMPT_C = [464, 3290, 7586, 21831, 18045, 625, 262, 11, 290]


def main(names: list[str]) -> None:
    import transformers

    for name in names:
        model_id = MODELS[name]
        if name == "gpt_oss":
            hf, groups = hf_gpt_oss(model_id)
            scenarios = (("swa_long", swa_long), ("swa_chunked", swa_chunked))
        else:
            hf = transformers.AutoModelForCausalLM.from_pretrained(
                model_id, torch_dtype=torch.float32, attn_implementation="eager"
            ).eval()
            groups = None
            scenarios = (("prefill_decode", prefill_decode), ("chunked", chunked))
        for case_name, scenario in scenarios:
            steps = scenario(hf) if groups is None else scenario(hf, groups)
            sha = batch_sha256([s.arrays for s in steps])
            path = CORPUS / name / f"{case_name}-{sha[:12]}.npz"
            write_case(path, model_id, steps)
            print(f"wrote {path} ({path.stat().st_size // 1024} KiB, {len(steps)} steps)")


def prefill_decode(hf) -> list[Step]:
    a, b = Seq(PROMPT_A, 1), Seq(PROMPT_B, 1 + 8)
    steps = [step(hf, [a, b], [7, 3])]
    for _ in range(2):
        a.tokens.append(int(steps[-1].logits[0].argmax()))
        b.tokens.append(int(steps[-1].logits[1].argmax()))
        steps.append(step(hf, [a, b], [1, 1]))
    return steps


def chunked(hf) -> list[Step]:
    c = Seq(PROMPT_C, 1)
    return [step(hf, [c], [4]), step(hf, [c], [5])]


def hf_gpt_oss(model_id: str):
    from oracle.synthetic import hf_gpt_oss_from_pytree

    w, cfg = gpt_oss.load(model_id, device="cpu", dtype=torch.float32)
    return hf_gpt_oss_from_pytree(w, model_id), derive_groups(gpt_oss.attn_specs(cfg))[0]


def long_seq() -> Seq:
    g = torch.Generator().manual_seed(0)
    s = Seq(torch.randint(1000, 100000, (LONG,), generator=g).tolist(), 1)
    s.blocks = list(range(1, 1 + 16))  # 256 tokens of room
    return s


def swa_long(hf, groups) -> list[Step]:
    """200-token prefill in one chunk (> window), then two decode steps with slid-out rows."""
    s = long_seq()
    steps = [step(hf, [s], [LONG], groups)]
    for _ in range(2):
        s.tokens.append(int(steps[-1].logits[0].argmax()))
        steps.append(step(hf, [s], [1], groups))
    return steps


def swa_chunked(hf, groups) -> list[Step]:
    """Same prompt as 128 + 72: the second chunk starts past the window."""
    s = long_seq()
    return [step(hf, [s], [128], groups), step(hf, [s], [72], groups)]


def step(hf, seqs: list[Seq], n_work: list[int], groups=None) -> Step:
    """Same construction as tests/conftest.build_batch, kept as numpy; logits from HF.
    With `groups`, slot_mapping / block_tables carry a leading group axis and a window group's
    rows below request.zig firstLiveRow are 0 (the core's slid-out holes)."""
    ids, pos, slots, qsl, seq_lens, tables = [], [], [], [0], [], []
    for s, n in zip(seqs, n_work, strict=True):
        lo, hi = s.n_computed, s.n_computed + n
        ids += s.tokens[lo:hi]
        pos += list(range(lo, hi))
        slots += s.slots(lo, hi)
        qsl.append(qsl[-1] + n)
        seq_lens.append(hi)
        tables.append([slid_table(s.blocks, lo, g.window) for g in groups] if groups else s.blocks)
        s.n_computed = hi
    slot_arr = np.array(slots, dtype=np.int64)
    table_arr = np.array(tables, dtype=np.int32)
    if groups:
        slot_arr = np.stack([slot_arr] * len(groups))  # [G, T]
        table_arr = table_arr.transpose(1, 0, 2)  # [G, R, B]
    arrays = dict(
        zip(
            BATCH_KEYS,
            (
                np.array(ids, dtype=np.int32),
                np.array(pos, dtype=np.int64),
                slot_arr,
                np.array(qsl, dtype=np.int32),
                np.array(seq_lens, dtype=np.int32),
                table_arr,
            ),
            strict=True,
        )
    )
    with torch.no_grad():
        logits = np.stack(
            [hf(torch.tensor([s.tokens[: s.n_computed]])).logits[0, -1].numpy() for s in seqs]
        ).astype(np.float32)
    return Step(arrays=arrays, logits=logits)


def slid_table(blocks: list[int], n_computed: int, window: int) -> list[int]:
    from conftest import BLOCK_SIZE

    row = list(blocks)
    if window and n_computed >= window:
        first_live = (n_computed - window + 1) // BLOCK_SIZE
        row[:first_live] = [0] * first_live
    return row


if __name__ == "__main__":
    main(sys.argv[1:] or list(MODELS))
