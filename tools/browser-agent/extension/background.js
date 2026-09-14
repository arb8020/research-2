/* background.js — service worker */

let nativePort = null;

function getNativePort() {
  if (!nativePort) {
    nativePort = chrome.runtime.connectNative("com.research.browser_agent");
    nativePort.onMessage.addListener((msg) => {
      // Relay to side panel
      chrome.runtime.sendMessage({ from: "native", ...msg });
    });
    nativePort.onDisconnect.addListener(() => {
      const err = chrome.runtime.lastError?.message || "disconnected";
      chrome.runtime.sendMessage({ from: "native", type: "error", text: `Native host ${err}` });
      nativePort = null;
    });
  }
  return nativePort;
}

// Context menu
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "ask-agent",
    title: "Ask agent...",
    contexts: ["selection"]
  });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== "ask-agent") return;

  // Store selection
  await chrome.storage.session.set({
    selection: info.selectionText,
    pageUrl: tab.url,
    pageTitle: tab.title
  });

  // Get page context from content script
  try {
    const [result] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => {
        const article = document.querySelector("article");
        const text = article ? article.innerText : document.body.innerText;
        return text.slice(0, 8000);
      }
    });
    await chrome.storage.session.set({ pageContext: result.result || "" });
  } catch {
    await chrome.storage.session.set({ pageContext: "" });
  }

  // Open side panel
  chrome.sidePanel.open({ tabId: tab.id });
});

// Messages from side panel
chrome.runtime.onMessage.addListener((msg, _sender, _sendResponse) => {
  if (msg.from === "sidepanel" && msg.action === "query") {
    try {
      const port = getNativePort();
      port.postMessage({
        highlight: msg.highlight,
        page_context: msg.page_context,
        page_url: msg.page_url,
        question: msg.question,
        agent: msg.agent
      });
    } catch (e) {
      chrome.runtime.sendMessage({ from: "native", type: "error", text: e.message });
    }
  }
  if (msg.from === "sidepanel" && msg.action === "disconnect") {
    if (nativePort) { nativePort.disconnect(); nativePort = null; }
  }
});
