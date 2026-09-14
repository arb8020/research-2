/* sidepanel.js */

const chat = document.getElementById("chat");
const questionEl = document.getElementById("question");
const sendBtn = document.getElementById("send");
const agentSelect = document.getElementById("agent-select");
const statusEl = document.getElementById("status");

let currentAgentMsg = null;

// Restore last agent choice
chrome.storage.local.get("agent", (d) => {
  if (d.agent) agentSelect.value = d.agent;
});
agentSelect.addEventListener("change", () => {
  chrome.storage.local.set({ agent: agentSelect.value });
});

// On load, read stored selection
chrome.storage.session.get(["selection", "pageUrl", "pageTitle", "pageContext"], (data) => {
  if (data.selection) {
    questionEl.value = "Is there evidence for this claim?";
    addMsg("user", `"${data.selection}"\n— ${data.pageTitle || data.pageUrl || ""}`);
  }
});

function addMsg(role, text) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = text;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
  return div;
}

function addSpinner() {
  const div = document.createElement("div");
  div.className = "msg agent";
  div.innerHTML = '<span class="spinner"></span>';
  div.id = "spinner";
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

function removeSpinner() {
  document.getElementById("spinner")?.remove();
}

function renderAgentText(div, text) {
  // Minimal markdown: code blocks and inline code
  let html = text
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/```(\w*)\n([\s\S]*?)```/g, "<pre><code>$2</code></pre>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');
  div.innerHTML = html;
}

sendBtn.addEventListener("click", send);
questionEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
});

async function send() {
  const q = questionEl.value.trim();
  if (!q) return;

  const data = await chrome.storage.session.get(["selection", "pageUrl", "pageContext"]);
  addMsg("user", q);
  questionEl.value = "";
  sendBtn.disabled = true;
  addSpinner();
  currentAgentMsg = null;

  chrome.runtime.sendMessage({
    from: "sidepanel",
    action: "query",
    highlight: data.selection || "",
    page_context: data.pageContext || "",
    page_url: data.pageUrl || "",
    question: q,
    agent: agentSelect.value
  });
}

// Listen for native host messages relayed by background
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.from !== "native") return;

  if (msg.type === "chunk") {
    removeSpinner();
    if (!currentAgentMsg) {
      currentAgentMsg = addMsg("agent", "");
    }
    currentAgentMsg.dataset.raw = (currentAgentMsg.dataset.raw || "") + msg.text;
    renderAgentText(currentAgentMsg, currentAgentMsg.dataset.raw);
    chat.scrollTop = chat.scrollHeight;
  } else if (msg.type === "done") {
    removeSpinner();
    sendBtn.disabled = false;
    currentAgentMsg = null;
    statusEl.textContent = "";
  } else if (msg.type === "error") {
    removeSpinner();
    addMsg("error", msg.text);
    sendBtn.disabled = false;
    currentAgentMsg = null;
  } else if (msg.type === "status") {
    statusEl.textContent = msg.text;
  }
});
