import { EditorView, basicSetup } from "codemirror";
import { EditorState, Compartment } from "@codemirror/state";
import { cpp } from "@codemirror/lang-cpp";
import { python } from "@codemirror/lang-python";

const SESSION = new URLSearchParams(location.search).get("session") || document.querySelector('meta[name="session-url"]').content;
let state = { passed: {}, wasm: {} };

const syntax = (lang) => (lang === "c" ? cpp() : python());

async function refresh() {
  state = await (await fetch(`${SESSION}/state`)).json();
  document.dispatchEvent(new Event("session-state"));
}

class CodeView extends HTMLElement {
  connectedCallback() {
    const doc = this.querySelector("pre").textContent;
    this.innerHTML = "";
    new EditorView({ parent: this, state: EditorState.create({ doc, extensions: [basicSetup, syntax(this.getAttribute("lang")), EditorState.readOnly.of(true)] }) });
  }
}
customElements.define("code-view", CodeView);

class CodeCell extends HTMLElement {
  connectedCallback() {
    this.name = this.getAttribute("name");
    this.stub = this.querySelector("pre").textContent;
    this.innerHTML = `
      <div class="cell-head"><span>${this.name} · ${this.getAttribute("lang")}</span>
        <span class="cell-status"></span><button class="run">Run</button></div>
      <div class="cell-editor"></div>
      <pre class="cell-out" hidden></pre>`;
    this.editable = new Compartment();
    this.view = new EditorView({
      parent: this.querySelector(".cell-editor"),
      state: EditorState.create({ doc: this.stub, extensions: [basicSetup, syntax(this.getAttribute("lang")), this.editable.of(EditorView.editable.of(true))] }),
    });
    this.querySelector(".run").onclick = () => this.run();
    document.addEventListener("session-state", () => this.gate());
    this.gate();
  }

  gate() {
    const cells = [...document.querySelectorAll("code-cell")];
    const prev = cells[cells.indexOf(this) - 1]?.getAttribute("name");
    const locked = prev !== undefined && !(prev in state.passed);
    this.classList.toggle("locked", locked);
    this.querySelector(".run").disabled = locked;
    this.view.dispatch({ effects: this.editable.reconfigure(EditorView.editable.of(!locked)) });
    if (!this.restored && this.name in state.passed) {
      this.restored = true;
      this.view.dispatch({ changes: { from: 0, to: this.view.state.doc.length, insert: state.passed[this.name] } });
      this.verdict = ["passed (your last passing version, restored)", "pass"];
    }
    this.status(...(locked ? [`locked until ${prev} passes`, ""] : this.verdict ?? ["", ""]));
  }

  status(text, cls) {
    const s = this.querySelector(".cell-status");
    s.textContent = text;
    s.className = `cell-status ${cls}`;
  }

  async run() {
    const out = this.querySelector(".cell-out");
    out.hidden = false;
    out.textContent = "";
    out.className = "cell-out";
    this.status("running…", "");
    this.querySelector(".run").disabled = true;
    try {
      const res = await fetch(`${SESSION}/run`, { method: "POST", body: JSON.stringify({ cell: this.name, source: this.view.state.doc.toString() }) });
      const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
      for (let chunk = await reader.read(); !chunk.done; chunk = await reader.read()) {
        out.textContent += chunk.value;
        out.scrollTop = out.scrollHeight;
      }
    } catch (e) {
      out.textContent += `\n[session unreachable: ${e}]\nFAIL\n`;
    }
    const ok = out.textContent.trimEnd().split("\n").pop() === "PASS";
    out.classList.add(ok ? "pass" : "fail");
    const fallback = this.name in state.passed ? "; later cells keep using your last passing version" : "";
    this.restored = true;
    this.verdict = ok ? ["passed", "pass"] : [`failed${fallback}`, "fail"];
    this.status(...this.verdict);
    this.querySelector(".run").disabled = false;
    if (ok) await refresh();
  }
}
customElements.define("code-cell", CodeCell);

class EnvPlay extends HTMLElement {
  connectedCallback() {
    this.cell = this.getAttribute("cell");
    this.innerHTML = `<iframe title="${this.cell}"></iframe><div class="play-caption"></div>`;
    this.mount(`./${this.cell}.js`, "reference env");
    document.addEventListener("session-state", () => {
      const url = state.wasm[this.cell];
      if (url && url !== this.url) this.mount(url, "your env (latest passing version)");
    });
  }

  mount(js, label) {
    this.url = js;
    this.querySelector("iframe").src = `play.html?js=${encodeURIComponent(js.startsWith("/") ? SESSION + js : js)}`;
    this.querySelector(".play-caption").textContent = `playing: ${label}. click it, then up/down (or w/s) picks your row`;
  }
}
customElements.define("env-play", EnvPlay);

refresh().catch((e) => console.warn("session unreachable", e));
