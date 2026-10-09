import { EditorView, basicSetup, minimalSetup } from "codemirror";
import { lineNumbers } from "@codemirror/view";
import { EditorState, Compartment } from "@codemirror/state";
import type { Extension } from "@codemirror/state";
import { cpp } from "@codemirror/lang-cpp";
import { python } from "@codemirror/lang-python";
import { syntaxHighlighting } from "@codemirror/language";
import { classHighlighter } from "@lezer/highlight";
import { vim } from "@replit/codemirror-vim";
import { attr, must } from "./dom";
import "./page-link";

// GET {SESSION}/state (session.py): the reader's latest passing source per cell, and per C cell the
// session path of a play widget built from it.
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

// POST {SESSION}/run (session.py) streams one JSON object per line: {"out"} as output arrives, then
// exactly one {"result"}. The verdict comes only from "result"; reader code can only print into "out".
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

// Yields each complete line of a text stream (the last one even without a trailing newline).
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

// TODO(page): ports and the session URL in one place (now: build_page.py --session-url default, session.py --port,
// dev.sh, verify_page.py/a11y.py default URLs).
function sessionUrl(): string {
  const fromQuery = new URLSearchParams(location.search).get("session");
  return fromQuery !== null && fromQuery !== "" ? fromQuery : must(document, 'meta[name="session-url"]', HTMLMetaElement).content;
}

const SESSION = sessionUrl();
let state: SessionState = { passed: {}, wasm: {} };

const syntax = (lang: string): Extension => (lang === "c" ? cpp() : python());

// Token colours come from page.css (.tok-* classes), so light/dark follow the page's CSS variables.
const look = (label: string): Extension[] => [
  syntaxHighlighting(classHighlighter),
  EditorView.contentAttributes.of({ "aria-label": label }),
];

// One vim switch for every editor on the page, remembered per reader.
const vimMode = new Compartment();
const vimKey = "blogs.vim";
let vimOn = false;
try { vimOn = localStorage.getItem(vimKey) === "1"; } catch { /* storage blocked: vim stays off */ }
const editors: EditorView[] = [];
function setVim(on: boolean): void {
  vimOn = on;
  try { localStorage.setItem(vimKey, on ? "1" : "0"); } catch { /* storage blocked: not remembered */ }
  for (const view of editors) view.dispatch({ effects: vimMode.reconfigure(on ? vim() : []) });
  for (const b of document.querySelectorAll(".vim-toggle")) b.setAttribute("aria-pressed", String(on));
}

async function refresh(): Promise<void> {
  state = parseState(await (await fetch(`${SESSION}/state`)).json());
  document.dispatchEvent(new Event("session-state"));
}

class CodeView extends HTMLElement {
  connectedCallback(): void {
    const doc = must(this, "pre", HTMLPreElement).textContent;
    this.innerHTML = "";
    const lang = attr(this, "data-lang");
    // An excerpt (data-first-line) numbers its lines as in the source file; `given` code numbers from 1.
    const first = Number(this.getAttribute("data-first-line") ?? "1");
    const setup = this.hasAttribute("data-first-line")
      ? [minimalSetup, lineNumbers({ formatNumber: (n) => String(n + first - 1) })]
      : [basicSetup];
    const view = new EditorView({ parent: this, state: EditorState.create({ doc, extensions: [...setup, syntax(lang), look(this.getAttribute("data-label") ?? `given code (${lang})`), EditorState.readOnly.of(true)] }) });
    view.scrollDOM.tabIndex = 0;
  }
}
customElements.define("code-view", CodeView);

type Verdict = readonly [text: string, cls: string];

class CodeCell extends HTMLElement {
  // Created detached; connectedCallback gives it the stub and mounts it. verify_page.py drives it as `.view`.
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
    // TODO(page): show-solution button here: fetched from the session on click (the page stays solution-free),
    // shown read-only with copy blocked.
    this.innerHTML = `
      <div class="cell-head"><span>${name} · ${lang}</span>
        <span class="cell-status"></span><button class="vim-toggle" aria-pressed="${String(vimOn)}">vim</button><button class="run">Run</button></div>
      <div class="cell-editor"></div>
      <pre class="cell-out" hidden></pre>`;
    this.view.setState(EditorState.create({ doc: stub, extensions: [
      vimMode.of(vimOn ? vim() : []), basicSetup, syntax(lang),
      look(`${name} code (${lang})`),
    ] }));
    must(this, ".cell-editor", HTMLDivElement).append(this.view.dom);
    this.view.scrollDOM.tabIndex = 0;
    editors.push(this.view);
    must(this, ".vim-toggle", HTMLButtonElement).onclick = () => { setVim(!vimOn); };
    must(this, ".run", HTMLButtonElement).onclick = () => { void this.run(); };
    document.addEventListener("session-state", () => { this.gate(); });
    this.gate();
  }

  // TODO(page): drafts survive reload: keep unpassed edits in localStorage, show "draft" in the status, add
  // "revert to last passing". Fold in: cell order is decided twice (check.py cell_order on the server, DOM order here).
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
    let result: RunResult | undefined;
    try {
      const res = await fetch(`${SESSION}/run`, { method: "POST", body: JSON.stringify({ cell: name, source: this.view.state.doc.toString() }) });
      if (!res.ok || res.body === null) throw new Error(`POST /run answered ${String(res.status)}${res.body === null ? " with no body" : ""}`);
      for await (const text of lines(res.body)) {
        if (text === "") continue;
        const line = parseRunLine(JSON.parse(text));
        if (line.kind === "result") {
          result = line.result;
        } else {
          out.textContent += line.text;
          out.scrollTop = out.scrollHeight;
        }
      }
      result ??= { passed: false, message: "the session stopped before giving a result" };
    } catch (e) {
      // fetch and a dropped stream throw TypeError; a malformed line throws from JSON.parse / parseRunLine.
      const message = e instanceof TypeError ? "session unreachable" : "the session sent a reply the page can't read";
      out.textContent += `\n[${message}: ${String(e)}]\n`;
      result = { passed: false, message };
    }
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

// Only pages with cells or play widgets talk to the session (a prose-only page like neural-nets has nothing to ask).
if (document.querySelector("code-cell, env-play") !== null) {
  refresh().catch((e: unknown) => { console.warn("session unreachable", e); });
}
