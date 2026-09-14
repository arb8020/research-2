#!/usr/bin/env python3
"""Test for the native messaging host protocol."""

import json
import struct
import subprocess
import sys
import os

HOST = os.path.join(os.path.dirname(__file__), "host.py")


def encode_native_msg(obj):
    data = json.dumps(obj).encode("utf-8")
    return struct.pack("<I", len(data)) + data


def decode_native_msgs(raw):
    msgs = []
    i = 0
    while i + 4 <= len(raw):
        length = struct.unpack("<I", raw[i:i+4])[0]
        i += 4
        if i + length > len(raw):
            break
        msgs.append(json.loads(raw[i:i+length]))
        i += length
    return msgs


def test_unknown_agent():
    """Agent not in the known list should return an error."""
    msg = encode_native_msg({
        "highlight": "test",
        "page_context": "",
        "page_url": "https://example.com",
        "question": "what is this?",
        "agent": "nonexistent_agent"
    })
    proc = subprocess.run(
        [sys.executable, HOST],
        input=msg, capture_output=True, timeout=10
    )
    msgs = decode_native_msgs(proc.stdout)
    assert len(msgs) >= 1, f"Expected at least 1 message, got {msgs}"
    assert msgs[0]["type"] == "error", f"Expected error, got {msgs[0]}"
    assert "Unknown agent" in msgs[0]["text"], f"Unexpected error text: {msgs[0]['text']}"
    print("PASS: unknown agent returns error")


def test_missing_binary():
    """Agent whose binary doesn't exist should return a not-found error."""
    sys.path.insert(0, os.path.dirname(HOST))
    import host as h
    import shutil

    # Find an agent whose binary is not installed; skip if all are present
    missing = None
    for name in h.AGENT_COMMANDS:
        cmd = h.AGENT_COMMANDS[name]("test")
        if not shutil.which(cmd[0]):
            missing = name
            break

    if missing is None:
        print("SKIP: all agent binaries are installed, cannot test missing-binary path")
        return

    msg = encode_native_msg({
        "highlight": "test", "page_context": "", "page_url": "https://example.com",
        "question": "what is this?", "agent": missing
    })
    proc = subprocess.run(
        [sys.executable, HOST], input=msg, capture_output=True, timeout=10
    )
    msgs = decode_native_msgs(proc.stdout)
    assert len(msgs) >= 1, f"Expected messages, got {msgs}"
    assert msgs[0]["type"] == "error" and "not found" in msgs[0]["text"]
    print("PASS: missing binary returns not-found error")


def test_protocol_encoding():
    """Verify our encode/decode round-trips."""
    obj = {"hello": "world", "n": 42}
    raw = encode_native_msg(obj)
    decoded = decode_native_msgs(raw)
    assert decoded == [obj], f"Round-trip failed: {decoded}"
    print("PASS: protocol encoding round-trip")


def test_extract_text():
    """Test _extract_text helper directly."""
    # Import the module
    sys.path.insert(0, os.path.dirname(HOST))
    import host as h

    # Claude streaming JSON
    line = json.dumps({"type": "content_block_delta", "delta": {"text": "hello"}})
    assert h._extract_text(line, "claude") == "hello"

    # Plain text fallback
    assert h._extract_text("some output", "codex") == "some output\n"

    # Empty
    assert h._extract_text("", "claude") is None

    print("PASS: _extract_text")


if __name__ == "__main__":
    test_protocol_encoding()
    test_extract_text()
    test_unknown_agent()
    test_missing_binary()
    print("\nAll tests passed.")
