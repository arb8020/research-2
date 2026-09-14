# Browser Agent

Chrome extension + native messaging host. Highlight text on a web page, ask a question, get an answer from Claude/Grok/Codex in a side panel.

## Install

```bash
# 1. Install the native messaging host
cd tools/browser-agent/host && ./install.sh

# 2. Load the extension
#    chrome://extensions → Developer mode → Load unpacked → select tools/browser-agent/extension/

# 3. Copy the extension ID from chrome://extensions

# 4. Edit the native host manifest and paste the extension ID
#    ~/Library/Application Support/Google/Chrome/NativeMessagingHosts/com.research.browser_agent.json
#    Replace EXTENSION_ID_PLACEHOLDER with your extension ID

# 5. Reload the extension
```

## Usage

1. Highlight text on any page
2. Right-click → "Ask agent..."
3. Side panel opens with your selection
4. Type a question (default: "Is there evidence for this claim?")
5. Choose agent (Claude/Grok/Codex) from dropdown
6. Click Send — the agent streams its answer

## Testing

```bash
python3 tools/browser-agent/host/test_host.py
```

## Requirements

- Python 3.8+
- At least one agent CLI installed: `claude`, `grok`, or `codex`
- macOS (Chrome native messaging host path is macOS-specific)
