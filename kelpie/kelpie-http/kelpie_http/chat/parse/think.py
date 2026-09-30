"""Shared <think>...</think> splitter. Text in: (reasoning, content) deltas out, never a partial
tag. Qwen3 emits the opening tag itself; GLM / DeepSeek prompts end inside the block (`force`)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ThinkSplitter:
    open_tag: str = "<think>"
    close_tag: str = "</think>"
    force: bool = False  # the generation prompt already opened the block
    _buf: str = ""
    _state: str = "start"  # start (may open) | think | content
    _seen_close: bool = False

    def __post_init__(self) -> None:
        if self.force:
            self._state = "think"

    def feed(self, text: str) -> tuple[str, str]:
        self._buf += text
        reasoning, content = "", ""
        if self._state == "start":
            stripped = self._buf.lstrip()
            if stripped.startswith(self.open_tag):
                self._buf = stripped[len(self.open_tag) :]
                self._state = "think"
            elif self.open_tag.startswith(stripped):
                return "", ""  # still could be the opening tag
            else:
                self._state = "content"
        if self._state == "think":
            idx = self._buf.find(self.close_tag)
            if idx == -1:
                n = partial_len(self._buf, self.close_tag)
                reasoning, self._buf = (self._buf[:-n], self._buf[-n:]) if n else (self._buf, "")
                return reasoning, ""
            reasoning = self._buf[:idx]
            self._buf = self._buf[idx + len(self.close_tag) :]
            self._state = "content"
            self._seen_close = True
        assert self._state == "content"
        content, self._buf = self._buf, ""
        return reasoning, content

    def finish(self) -> tuple[str, str]:
        """Flush: an unclosed block is reasoning; a held prefix of <think> was plain text."""
        buf, self._buf = self._buf, ""
        if self._state == "think":
            return buf, ""
        return "", buf

    @property
    def in_think(self) -> bool:
        return self._state == "think"


def partial_len(text: str, marker: str) -> int:
    for length in range(min(len(marker) - 1, len(text)), 0, -1):
        if text.endswith(marker[:length]):
            return length
    return 0
