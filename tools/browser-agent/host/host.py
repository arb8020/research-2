#!/usr/bin/env python3
"""Native messaging host for Browser Agent.

Reads Chrome native messaging protocol (4-byte LE length + JSON),
spawns a coding agent CLI, streams output back.
"""

import json
import shutil
import struct
import subprocess
import sys


def read_message():
    """Read one native message from stdin."""
    raw = sys.stdin.buffer.read(4)
    if len(raw) < 4:
        return None
    length = struct.unpack("<I", raw)[0]
    data = sys.stdin.buffer.read(length)
    if len(data) < length:
        return None
    return json.loads(data)


def send_message(obj):
    """Write one native message to stdout."""
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(data)))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def build_prompt(msg):
    parts = []
    if msg.get("page_url"):
        parts.append(f'The user is reading {msg["page_url"]}.')
    if msg.get("page_context"):
        ctx = msg["page_context"][:6000]
        parts.append(f"Page context:\n{ctx}")
    if msg.get("highlight"):
        parts.append(f'They highlighted: "{msg["highlight"]}"')
    if msg.get("question"):
        parts.append(f'Their question: {msg["question"]}')
    parts.append("Use web search and other tools to answer thoroughly. Cite sources with URLs.")
    return "\n\n".join(parts)


AGENT_COMMANDS = {
    "claude": lambda prompt: [
        "claude", "-p", prompt,
        "--allowedTools", "WebSearch,WebFetch",
        "--output-format", "streaming-json",
    ],
    "grok": lambda prompt: [
        "grok", "-p", prompt,
        "--output-format", "streaming-json",
    ],
    "codex": lambda prompt: [
        "codex", "--quiet", prompt,
    ],
}


def run_agent(msg):
    agent = msg.get("agent", "claude")
    prompt = build_prompt(msg)

    builder = AGENT_COMMANDS.get(agent)
    if not builder:
        send_message({"type": "error", "text": f"Unknown agent: {agent}"})
        return

    cmd = builder(prompt)
    binary = cmd[0]
    if not shutil.which(binary):
        send_message({"type": "error", "text": f"{binary} not found on PATH. Install it or choose a different agent."})
        return

    send_message({"type": "status", "text": f"Running {agent}..."})

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
        )

        # Stream stdout line by line
        for raw_line in proc.stdout:
            line = raw_line.decode("utf-8", errors="replace")
            # For streaming-json, each line is a JSON object; extract text content
            text = _extract_text(line, agent)
            if text:
                send_message({"type": "chunk", "text": text})

        proc.wait()
        stderr = proc.stderr.read().decode("utf-8", errors="replace").strip()
        if proc.returncode != 0 and stderr:
            send_message({"type": "error", "text": stderr[:2000]})

        send_message({"type": "done"})

    except Exception as e:
        send_message({"type": "error", "text": str(e)})


def _extract_text(line, agent):
    """Extract displayable text from a stdout line."""
    line = line.strip()
    if not line:
        return None

    # Try parsing as streaming JSON (claude / grok format)
    try:
        obj = json.loads(line)
        # Claude streaming-json emits content_block_delta with text
        if obj.get("type") == "content_block_delta":
            delta = obj.get("delta", {})
            return delta.get("text", "")
        # Also handle assistant message result
        if obj.get("type") == "result" and obj.get("result"):
            return obj["result"]
        # Grok may use different keys
        if "text" in obj:
            return obj["text"]
        if "content" in obj:
            return obj["content"]
        return None
    except (json.JSONDecodeError, TypeError):
        # Plain text output (codex, fallback)
        return line + "\n"


def main():
    """Main loop: read messages, dispatch agents."""
    while True:
        msg = read_message()
        if msg is None:
            break
        run_agent(msg)


if __name__ == "__main__":
    main()
