// <ws-cell>: a whole-file cell over the reader's workspace (```cpp cell=X file=F in the chapter). The editor is a view
// of workspace/F in the sandbox: loaded from it on connect, every edit saved back (debounced, Contents API) and
// mirrored to localStorage (the sandbox can die; the browser keeps the draft). Run checks the latest passing tree
// + this file as a background job; its output streams below with file:line links. Gating comes from workspace.py status.
import { EditorView, basicSetup } from "codemirror";
import { EditorState } from "@codemirror/state";
import { attr, must } from "./dom";
import { look, registerEditor, setVim, syntax, vimEnabled, vimExtension } from "./editor";
import { kernelState, onKernelState } from "./connect/kernel";
import type { JobResult } from "./connect/kernel";
import { LineBuffer, registerFile } from "./out-links";
import { bootWorkspace, checkCell, onWorkspace, readFile, refreshStatus, stopCheck, workspaceStatus, writeFile } from "./workspace";
import type { Boot } from "./workspace";

const SAVE_DEBOUNCE_MS = 300;

// The browser's copy of a draft: the text last typed, and whether the workspace acknowledged writing it.
interface Draft { text: string; acked: boolean }

function readDraft(key: string): Draft | undefined {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(key) ?? "null");
    if (typeof raw !== "object" || raw === null || !("text" in raw) || !("acked" in raw)) return undefined;
    return typeof raw.text === "string" && typeof raw.acked === "boolean" ? { text: raw.text, acked: raw.acked } : undefined;
  } catch { return undefined; }
}
function writeDraft(key: string, draft: Draft): void {
  try { localStorage.setItem(key, JSON.stringify(draft)); } catch { /* storage blocked: the workspace still has it */ }
}

// Which text the editor starts from when the workspace has `inWorkspace` and this browser has `local`:
//   no local copy, or the same text            -> the workspace's
//   the sandbox is new (seeded/restored)        -> this browser's: the workspace lost its drafts with the old sandbox
//   this browser's last edit never got written  -> this browser's: it is newer
//   otherwise                                   -> the workspace's: it changed elsewhere since (another tab, a terminal)
export function pickText(inWorkspace: string, local: Draft | undefined, created: Boot["created"]): { text: string; from: "workspace" | "browser" } {
  if (local === undefined || local.text === inWorkspace) return { text: inWorkspace, from: "workspace" };
  if (created !== "existing" || !local.acked) return { text: local.text, from: "browser" };
  return { text: inWorkspace, from: "workspace" };
}

type Verdict = readonly [text: string, cls: string];

function verdictOf(result: JobResult, seconds: string): Verdict {
  if (result.status === "exited") {
    if (result.exit === 0) return [`passed (${seconds})`, "pass"];
    if (result.exit === 2) return ["not run: see the output", "fail"];
    if (result.exit < 0) return [`stopped (${seconds})`, "fail"];
    return [`failed (${seconds}): see the output; later cells keep your last passing version`, "fail"];
  }
  return result.status === "error" ? [`couldn't start the check: ${result.ename}: ${result.evalue}`, "fail"] : [result.reason, "fail"];
}

class WorkspaceCell extends HTMLElement {
  readonly view = new EditorView(); // verify_workspace.py drives it as `.view`
  lastSaveMs: number | undefined; // the latest save's round trip, for verify_workspace.py
  private loaded = false;
  private loading: Promise<void> | undefined;
  private applying = false; // a doc change made by load(), not the reader: not a draft
  private timer: ReturnType<typeof setTimeout> | undefined;
  private saving: Promise<void> = Promise.resolve();
  private job: string | undefined; // the running check's job id
  private verdict: Verdict | undefined;

  private get chapter(): string { return attr(this, "data-chapter"); }
  private get file(): string { return attr(this, "data-file"); }
  private get draftKey(): string { return `blogs.ws.${this.chapter}.${this.file}`; }

  connectedCallback(): void {
    const name = attr(this, "name");
    const lang = attr(this, "data-lang");
    const start = must(this, "pre", HTMLPreElement).textContent;
    this.innerHTML = `
      <div class="cell-head"><span>${name} · ${this.file}</span>
        <span class="cell-status"></span><button class="connect-to-run" type="button">Connect to run</button>
        <button class="vim-toggle" aria-pressed="${String(vimEnabled())}">vim</button><button class="run">Run</button></div>
      <div class="cell-editor"></div>
      <pre class="cell-out" tabindex="0" aria-label="${name} output" hidden></pre>`;
    this.view.setState(EditorState.create({ doc: start, extensions: [
      vimExtension(), basicSetup, syntax(lang), look(`${name}: ${this.file} (${lang})`),
      EditorView.updateListener.of((u) => { if (u.docChanged && !this.applying) this.edited(); }),
    ] }));
    must(this, ".cell-editor", HTMLDivElement).append(this.view.dom);
    this.view.scrollDOM.tabIndex = 0;
    registerEditor(this.view);
    registerFile(this.file, this.view, this);
    must(this, ".vim-toggle", HTMLButtonElement).onclick = () => { setVim(!vimEnabled()); };
    must(this, ".connect-to-run", HTMLButtonElement).onclick = () => { document.dispatchEvent(new Event("connect:open")); };
    must(this, ".run", HTMLButtonElement).onclick = () => { void this.runOrStop(); };
    onWorkspace(() => { this.gate(); });
    onKernelState((state) => {
      if (state === "idle") this.ensureLoaded();
      if (state === "off" || state === "lost") this.loaded = false;
      this.gate();
    });
    if (kernelState() === "idle" || kernelState() === "busy") this.ensureLoaded();
    this.gate();
  }

  private ensureLoaded(): void {
    if (this.loaded || this.loading !== undefined) return;
    this.loading = this.load().finally(() => { this.loading = undefined; });
  }

  private async load(): Promise<void> {
    try {
      const boot = await bootWorkspace(this.chapter);
      const inWorkspace = await readFile(this.file);
      if (inWorkspace === undefined) throw new Error(`the workspace has no ${this.file}`);
      const { text, from } = pickText(inWorkspace, readDraft(this.draftKey), boot.created);
      this.applying = true;
      this.view.dispatch({ changes: { from: 0, to: this.view.state.doc.length, insert: text } });
      this.applying = false;
      if (from === "browser") {
        await writeFile(this.file, text);
        writeDraft(this.draftKey, { text, acked: true });
      }
      this.loaded = true;
      this.setAttribute("data-loaded", from);
      this.verdict = from === "browser" ? ["your draft from this browser, saved to the workspace", ""] : undefined;
    } catch (e) {
      this.verdict = [`couldn't load the workspace: ${String(e)}`, "fail"];
    }
    this.gate();
  }

  private edited(): void {
    writeDraft(this.draftKey, { text: this.view.state.doc.toString(), acked: false });
    if (!this.loaded) return; // not connected: the browser keeps it; load() writes it once the workspace is up
    clearTimeout(this.timer);
    this.timer = setTimeout(() => { this.timer = undefined; void this.save(); }, SAVE_DEBOUNCE_MS);
  }

  // Saves run one after another, so the workspace ends with the last text even if two overlap.
  private save(): Promise<void> {
    const text = this.view.state.doc.toString();
    this.saving = this.saving.then(async () => {
      const t0 = performance.now();
      await writeFile(this.file, text);
      this.lastSaveMs = performance.now() - t0;
      if (this.view.state.doc.toString() === text) writeDraft(this.draftKey, { text, acked: true });
    }).catch((e: unknown) => { this.status(`couldn't save to the workspace: ${String(e)}`, "fail"); });
    return this.saving;
  }

  private async flush(): Promise<void> {
    if (this.timer !== undefined) {
      clearTimeout(this.timer);
      this.timer = undefined;
      await this.save();
    }
    await this.saving;
  }

  private async runOrStop(): Promise<void> {
    if (this.job !== undefined) {
      await stopCheck(this.job).catch((e: unknown) => { this.status(`stop failed: ${String(e)}`, "fail"); });
      return;
    }
    const out = must(this, ".cell-out", HTMLPreElement);
    const buffer = new LineBuffer(out);
    out.hidden = false;
    out.textContent = "";
    out.className = "cell-out";
    const id = crypto.randomUUID();
    this.job = id;
    this.setAttribute("data-job", id);
    this.verdict = ["checking…", ""];
    this.gate();
    const started = performance.now();
    await this.flush();
    const result = await checkCell(id, this.chapter, attr(this, "name"), attr(this, "data-check"), (t) => { buffer.feed(t); });
    buffer.end();
    this.job = undefined;
    this.removeAttribute("data-job");
    this.verdict = verdictOf(result, `${((performance.now() - started) / 1000).toFixed(2)}s`);
    out.classList.add(this.verdict[1] === "pass" ? "pass" : "fail");
    this.gate();
    await refreshStatus(this.chapter).catch((e: unknown) => { this.verdict = [`status failed: ${String(e)}`, "fail"]; });
    this.gate();
  }

  private gate(): void {
    const ready = kernelState() === "idle" || kernelState() === "busy";
    const run = must(this, ".run", HTMLButtonElement);
    const mine = workspaceStatus()?.cells.find((c) => c.name === attr(this, "name"));
    must(this, ".connect-to-run", HTMLButtonElement).hidden = ready;
    run.textContent = this.job !== undefined ? "Stop" : "Run";
    const locked = mine?.locked ?? true;
    run.disabled = this.job === undefined && (!ready || !this.loaded || locked);
    this.classList.toggle("locked", ready && this.loaded && locked);
    if (!ready) { this.status("connect to load your workspace", ""); return; }
    if (!this.loaded || mine === undefined) { this.status(this.verdict?.[0] ?? "loading your workspace…", this.verdict?.[1] ?? ""); return; }
    if (this.job === undefined && mine.locked) { this.status(mine.why, ""); return; }
    const standing: Verdict = mine.passed ? [mine.draft ? "passed; edited since (Run to check the edit)" : "passed", "pass"] : ["not passed yet", ""];
    this.status(...(this.verdict ?? standing));
  }

  private status(text: string, cls: string): void {
    const s = must(this, ".cell-status", HTMLSpanElement);
    s.textContent = text;
    s.className = `cell-status ${cls}`;
  }
}
customElements.define("ws-cell", WorkspaceCell);
