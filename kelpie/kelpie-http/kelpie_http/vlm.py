"""Chat messages -> (token ids with image placeholders expanded, multimodal payload, mm_hash).

One adapter per VLM family; SmolVLM is the only one. The adapter owns preprocessing (decode +
resize + tile) so the handler stays at submit/poll/cancel, and the tokenizer sees the same text
HF's processor would build.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from tokenizers import Tokenizer

from kelpie_http import wire


@dataclass(frozen=True)
class Prepared:
    token_ids: list[int]
    payload: object | None  # kelpie_models.multimodal.MultimodalInput, None for text-only chats
    mm_hash: int
    mm_start: int = 0  # prompt position of the first placeholder; the prefix hash fold starts there
    json_schema: dict | None = None  # response_format schema, compiled by the handler before submit


class SmolVLMAdapter:
    def __init__(self, cfg: object) -> None:
        from kelpie_models.models.torch import smolvlm  # torch import is slow; keep it off the stub path

        self._m = smolvlm
        self.cfg = cfg

    def prepare(self, req: wire.ChatRequest, tokenizer: Tokenizer) -> Prepared:
        from kelpie_models.multimodal import MultimodalInput

        tiles = []
        messages = []
        for msg in req.messages:
            parts: list = []
            for part in msg.parts:
                if isinstance(part, wire.ImagePart):
                    t = self._m.preprocess(self._m.decode_image(part.data), self.cfg)
                    tiles.append(t)
                    parts.append(t)
                else:
                    parts.append(part)
            messages.append((msg.role, parts))
        text = self._m.chat_prompt(messages, self.cfg)
        ids = tokenizer.encode(text).ids
        if not tiles:
            assert self.cfg.image_token not in ids  # type: ignore[attr-defined]
            return Prepared(ids, None, 0)
        pp = np.flatnonzero(np.asarray(ids) == self.cfg.image_token)  # type: ignore[attr-defined]
        expected = sum(t.pixels.shape[0] for t in tiles) * self.cfg.tokens_per_tile  # type: ignore[attr-defined]
        assert pp.shape[0] == expected, (pp.shape, expected)
        payload = MultimodalInput(placeholder_positions=pp.astype(np.int64), data=tiles)
        return Prepared(ids, payload, wire.mm_hash(req.images), int(pp[0]))
