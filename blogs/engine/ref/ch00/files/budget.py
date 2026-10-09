"""budget.py: split a long prompt's prefill into chunks, so one request can't eat a whole step's token budget."""


def prefill_chunks(prompt_len: int, chunk: int) -> list[int]:
    """Token counts for each step of prefill: every chunk is `chunk` tokens except a shorter last one.

    prefill_chunks(10, 4) == [4, 4, 2]; prefill_chunks(0, 4) == [].
    """
    assert prompt_len >= 0, prompt_len
    assert chunk > 0, chunk
    full, rest = divmod(prompt_len, chunk)
    return [chunk] * full + ([rest] if rest else [])
