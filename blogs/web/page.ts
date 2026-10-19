import { EditorView, basicSetup, minimalSetup } from "codemirror";
import { lineNumbers } from "@codemirror/view";
import { EditorState } from "@codemirror/state";
import { attr, must } from "./dom";
import { look, registerEditor, setVim, syntax, vimEnabled, vimExtension } from "./editor";
import { registerFile } from "./out-links";
import { interrupt, kernelState, onKernelState, runCode } from "./connect/kernel";
import type { RunResult as KernelResult } from "./connect/kernel";
import "./connect/ui";
import "./page-link";
import "./ws-cell";

interface SessionState {
  passed: Record<string, string>;
  wasm: Record<string, string>;
}

const isStringRecord = (x: unknown): x is Record<string, string> =>
  typeof x === "object" && x !== null && !Array.isArray(x) && Object.values(x).every((v) => typeof v === "string");

function parseState(raw: unknown): SessionState {
  if (typeof raw !== "object" || raw === null || !("passed" in raw) || !("wasm" in raw)) {
    throw new Error(`session /state: expected {passed, wasm}, got ${JSON.stringify(raw)}`);
  }
  const { passed, wasm } = raw;
  if (!isStringRecord(passed) || !isStringRecord(wasm)) {
    throw new Error(`session /state: passed and wasm must map cell names to strings, got ${JSON.stringify(raw)}`);
  }
  return { passed, wasm };
}

interface RunResult {
  passed: boolean;
  message: string;
}
type RunLine = { kind: "out"; text: string } | { kind: "result"; result: RunResult };

function parseRunLine(raw: unknown): RunLine {
  if (typeof raw === "object" && raw !== null) {
    if ("out" in raw && typeof raw.out === "string") return { kind: "out", text: raw.out };
    if ("result" in raw && typeof raw.result === "object" && raw.result !== null) {
      const r = raw.result;
      if ("passed" in r && typeof r.passed === "boolean" && "message" in r && typeof r.message === "string") {
        return { kind: "result", result: { passed: r.passed, message: r.message } };
      }
    }
  }
  throw new Error(`session /run: expected {out} or {result: {passed, message}}, got ${JSON.stringify(raw)}`);
}

async function* lines(body: ReadableStream<Uint8Array<ArrayBuffer>>): AsyncGenerator<string> {
  const reader = body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = "";
  for (let chunk = await reader.read(); !chunk.done; chunk = await reader.read()) {
    buf += chunk.value;
    const parts = buf.split("\n");
    buf = parts.pop() ?? "";
    yield* parts;
  }
  if (buf !== "") yield buf;
}

function sessionUrl(): string {
  const fromQuery = new URLSearchParams(location.search).get("session");
  return fromQuery !== null && fromQuery !== "" ? fromQuery : must(document, 'meta[name="session-url"]', HTMLMetaElement).content;
}

const SESSION = sessionUrl();
let state: SessionState = { passed: {}, wasm: {} };

const ANSI = /\x1b\[[0-9;]*[A-Za-z]/g; // oxlint-disable-line no-control-regex

async function refresh(): Promise<void> {
  state = parseState(await (await fetch(`${SESSION}/state`)).json());
  document.dispatchEvent(new Event("session-state"));
}

async function runOnSession(name: string, source: string, onOut: (text: string) => void): Promise<RunResult> {
  try {
    const res = await fetch(`${SESSION}/run`, { method: "POST", body: JSON.stringify({ cell: name, source }) });
    if (!res.ok || res.body === null) throw new Error(`POST /run answered ${String(res.status)}${res.body === null ? " with no body" : ""}`);
    let result: RunResult | undefined;
    for await (const text of lines(res.body)) {
      if (text === "") continue;
      const line = parseRunLine(JSON.parse(text));
      if (line.kind === "out") onOut(line.text);
      else if (result === undefined) result = line.result;
      else throw new Error("session /run: a second result line");
    }
    return result ?? { passed: false, message: "the session stopped before giving a result" };
  } catch (cause) {
    const unreachable = cause instanceof TypeError;
    const message = unreachable ? "session unreachable" : "the session sent a reply the page can't read";
    onOut(`\n[${message}: ${String(cause)}]\n`);
    return { passed: false, message };
  }
}

const runOnKernel = (source: string, onOut: (text: string) => void): Promise<KernelResult> => runCode(source, onOut, onOut);

const BACKENDS = { checked: runOnSession, scratch: runOnKernel } as const;

class CodeView extends HTMLElement {
  connectedCallback(): void {
    const doc = must(this, "pre", HTMLPreElement).textContent;
    this.innerHTML = "";
    const lang = attr(this, "data-lang");
    const isExcerpt = this.hasAttribute("data-first-line");
    const first = Number(this.getAttribute("data-first-line") ?? "1");
    const setup = isExcerpt
      ? [minimalSetup, lineNumbers({ formatNumber: (n) => String(n + first - 1) })]
      : [basicSetup];
    const view = new EditorView({ parent: this, state: EditorState.create({ doc, extensions: [...setup, syntax(lang), look(this.getAttribute("data-label") ?? `given code (${lang})`), EditorState.readOnly.of(true)] }) });
    view.scrollDOM.tabIndex = 0;
    const file = this.getAttribute("data-file");
    if (file !== null) registerFile(file, view, this);
  }
}
customElements.define("code-view", CodeView);

type Verdict = readonly [text: string, cls: string];

class CodeCell extends HTMLElement {
  readonly view = new EditorView();
  private restored = false;
  private verdict: Verdict | undefined;

  get cellName(): string {
    return attr(this, "name");
  }

  connectedCallback(): void {
    const name = this.cellName;
    const lang = attr(this, "data-lang");
    const stub = must(this, "pre", HTMLPreElement).textContent;
    this.innerHTML = `
      <div class="cell-head"><span>${name} · ${lang}</span>
        <span class="cell-status"></span><button class="vim-toggle" aria-pressed="${String(vimEnabled())}">vim</button><button class="run">Run</button></div>
      <div class="cell-editor"></div>
      <pre class="cell-out" tabindex="0" aria-label="${name} output" hidden></pre>`;
    this.view.setState(EditorState.create({ doc: stub, extensions: [
      vimExtension(), basicSetup, syntax(lang),
      look(`${name} code (${lang})`),
    ] }));
    must(this, ".cell-editor", HTMLDivElement).append(this.view.dom);
    this.view.scrollDOM.tabIndex = 0;
    registerEditor(this.view);
    must(this, ".vim-toggle", HTMLButtonElement).onclick = () => { setVim(!vimEnabled()); };
    must(this, ".run", HTMLButtonElement).onclick = () => { void this.run(); };
    document.addEventListener("session-state", () => { this.gate(); });
    this.gate();
  }

  gate(): void {
    const name = this.cellName;
    const cells = [...document.querySelectorAll("code-cell")];
    const prev = cells[cells.indexOf(this) - 1]?.getAttribute("name") ?? undefined;
    const locked = prev !== undefined && !(prev in state.passed);
    this.classList.toggle("locked", locked);
    must(this, ".run", HTMLButtonElement).disabled = locked;
    const passed = state.passed[name];
    if (!this.restored && passed !== undefined) {
      this.restored = true;
      this.view.dispatch({ changes: { from: 0, to: this.view.state.doc.length, insert: passed } });
      this.verdict = ["passed (your last passing version, restored)", "pass"];
    }
    const [text, cls]: Verdict = locked ? [`locked until ${prev} passes`, ""] : this.verdict ?? ["", ""];
    this.status(text, cls);
  }

  status(text: string, cls: string): void {
    const s = must(this, ".cell-status", HTMLSpanElement);
    s.textContent = text;
    s.className = `cell-status ${cls}`;
  }

  async run(): Promise<void> {
    const name = this.cellName;
    const out = must(this, ".cell-out", HTMLPreElement);
    const button = must(this, ".run", HTMLButtonElement);
    out.hidden = false;
    out.textContent = "";
    out.className = "cell-out";
    this.status("running…", "");
    button.disabled = true;
    const result = await BACKENDS.checked(name, this.view.state.doc.toString(), (text) => {
      out.textContent += text;
      out.scrollTop = out.scrollHeight;
    });
    out.classList.add(result.passed ? "pass" : "fail");
    const fallback = name in state.passed ? "; later cells keep using your last passing version" : "";
    this.restored = true;
    this.verdict = result.passed ? [result.message, "pass"] : [`${result.message}${fallback}`, "fail"];
    this.status(...this.verdict);
    button.disabled = false;
    if (result.passed) await refresh();
  }
}
customElements.define("code-cell", CodeCell);

class ScratchCell extends HTMLElement {
  readonly view = new EditorView();
  private running = false;

  connectedCallback(): void {
    const lang = attr(this, "data-lang");
    const code = must(this, "pre", HTMLPreElement).textContent;
    this.innerHTML = `
      <div class="cell-head"><span>scratch · ${lang}</span>
        <span class="cell-status"></span><button class="connect-to-run" type="button">Connect to run</button>
        <button class="vim-toggle" aria-pressed="${String(vimEnabled())}">vim</button><button class="run">Run</button></div>
      <div class="cell-editor"></div>
      <pre class="cell-out scratch-out" tabindex="0" aria-label="scratch output" hidden></pre>`;
    this.view.setState(EditorState.create({ doc: code, extensions: [vimExtension(), basicSetup, syntax(lang), look(`scratch code (${lang})`)] }));
    must(this, ".cell-editor", HTMLDivElement).append(this.view.dom);
    this.view.scrollDOM.tabIndex = 0;
    registerEditor(this.view);
    must(this, ".vim-toggle", HTMLButtonElement).onclick = () => { setVim(!vimEnabled()); };
    must(this, ".connect-to-run", HTMLButtonElement).onclick = () => { document.dispatchEvent(new Event("connect:open")); };
    must(this, ".run", HTMLButtonElement).onclick = () => {
      if (this.running) interrupt().catch((cause: unknown) => { this.status(`interrupt failed: ${String(cause)}`, "fail"); });
      else void this.run();
    };
    onKernelState(() => { this.gate(); });
    this.gate();
  }

  gate(): void {
    const ready = kernelState() === "idle" || kernelState() === "busy";
    must(this, ".run", HTMLButtonElement).disabled = !ready && !this.running;
    must(this, ".connect-to-run", HTMLButtonElement).hidden = ready || this.running;
    this.classList.toggle("locked", !ready);
  }

  status(text: string, cls: string): void {
    const s = must(this, ".cell-status", HTMLSpanElement);
    s.textContent = text;
    s.className = `cell-status ${cls}`;
  }

  async run(): Promise<void> {
    const out = must(this, ".cell-out", HTMLPreElement);
    const button = must(this, ".run", HTMLButtonElement);
    out.hidden = false;
    out.textContent = "";
    out.className = "cell-out scratch-out";
    this.running = true;
    button.textContent = "Stop";
    this.status("running…", "");
    const started = performance.now();
    const result = await BACKENDS.scratch(this.view.state.doc.toString(), (text) => {
      out.textContent += text.replace(ANSI, "");
      out.scrollTop = out.scrollHeight;
    });
    const took = `${((performance.now() - started) / 1000).toFixed(2)}s`;
    this.running = false;
    button.textContent = "Run";
    if (result.status === "error") out.textContent += `${out.textContent === "" ? "" : "\n"}${result.traceback}\n`;
    const [text, cls] = result.status === "ok" ? [`done (${took})`, "pass"]
      : result.status === "error" ? [`${result.ename}${result.evalue ? `: ${result.evalue}` : ""} (${took})`, "fail"] : [result.reason, "fail"];
    out.classList.add(cls);
    this.status(text, cls);
    this.gate();
  }
}
customElements.define("scratch-cell", ScratchCell);

class EnvPlay extends HTMLElement {
  private url: string | undefined;

  connectedCallback(): void {
    const cell = attr(this, "cell");
    this.innerHTML = `<iframe title="${cell}"></iframe><div class="play-caption"></div>`;
    this.mount(`./${cell}.js`, "reference env");
    document.addEventListener("session-state", () => {
      const url = state.wasm[cell];
      if (url && url !== this.url) this.mount(url, "your env (latest passing version)");
    });
  }

  mount(js: string, label: string): void {
    this.url = js;
    must(this, "iframe", HTMLIFrameElement).src = `play.html?js=${encodeURIComponent(js.startsWith("/") ? SESSION + js : js)}`;
    must(this, ".play-caption", HTMLDivElement).textContent = `playing: ${label}. click it, then up/down (or w/s) picks your row`;
  }
}
customElements.define("env-play", EnvPlay);

const talksToSession = document.querySelector("code-cell, env-play") !== null;
if (talksToSession) {
  refresh().catch((cause: unknown) => { console.warn("session unreachable", cause); });
}
