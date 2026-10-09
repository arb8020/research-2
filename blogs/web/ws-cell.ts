// <ws-cell>: a cell over the reader's workspace (```python cell=X file=F in the chapter). Its editor is one view of
// the page's shared document for F (workspace-file.ts): every cell over gpt2.py edits the same text. The cell shows
// its region (checks/chNN.json "region": the lines between `# region: X` and `# endregion`) scrolled into view and
// highlighted, in a bounded height, with a toggle to show the whole file; a missing marker only costs that (the cell
// shows the top of the file and says so). Run saves the file, then `workspace.py check` runs the cell's cmd as a
// background job; its JSON lines render as a verdict table (check-output.ts). No gating: every cell can run.
import { basicSetup } from "codemirror";
import type { EditorView } from "codemirror";
import { Decoration, EditorView as View, ViewPlugin } from "@codemirror/view";
import type { DecorationSet, ViewUpdate } from "@codemirror/view";
import { RangeSetBuilder } from "@codemirror/state";
import type { Extension, Text } from "@codemirror/state";
import { attr, must } from "./dom";
import { look, registerEditor, setVim, syntax, vimEnabled, vimExtension } from "./editor";
import { kernelState, onKernelState } from "./connect/kernel";
import type { JobResult } from "./connect/kernel";
import { currentPhase, onPhase } from "./connect/session";
import { CheckOutput } from "./check-output";
import { WorkspaceFile } from "./workspace-file";
import { bootWorkspace, checkCell, onWorkspace, refreshStatus, stopCheck, workspaceStatus } from "./workspace";

const MAX_LINES = 40; // a bounded cell is at most this many lines tall (its region + a line of context each side)
const MIN_LINES = 20; // ...and at least this many: a stub region is a few lines, and the reader needs room to write
const UNREGIONED_LINES = 18; // a region cell whose markers are missing (at load) shows this much of the top of the file

interface Span { first: number; last: number } // 1-based lines, markers included

// The `# region: <name>` ... `# endregion` lines in doc, or undefined if either marker is missing.
export function findRegion(doc: Text, name: string): Span | undefined {
  for (let i = 1; i <= doc.lines; i++) {
    if (doc.line(i).text.trim() !== `# region: ${name}`) continue;
    for (let j = i + 1; j <= doc.lines; j++) if (doc.line(j).text.trim() === "# endregion") return { first: i, last: j };
    return undefined;
  }
  return undefined;
}

const regionLine = Decoration.line({ class: "cm-region" });
function regionHighlight(name: string): Extension {
  const build = (doc: Text): DecorationSet => {
    const span = findRegion(doc, name);
    if (span === undefined) return Decoration.none;
    const b = new RangeSetBuilder<Decoration>();
    for (let i = span.first; i <= span.last; i++) b.add(doc.line(i).from, doc.line(i).from, regionLine);
    return b.finish();
  };
  return ViewPlugin.fromClass(class {
    decorations: DecorationSet;
    constructor(view: EditorView) { this.decorations = build(view.state.doc); }
    update(u: ViewUpdate): void { if (u.docChanged) this.decorations = build(u.state.doc); }
  }, { decorations: (v) => v.decorations });
}

type Verdict = readonly [text: string, cls: string];

function verdictOf(result: JobResult, out: CheckOutput, seconds: string): Verdict {
  if (result.status === "exited") {
    if (result.exit === 0) return [`passed (${seconds})`, "pass"];
    if (result.exit === 1) {
      const where = out.firstWhere();
      const at = where === undefined ? "" : `: ${where.file}:${String(where.line)}${where.region === undefined ? "" : ` (${where.region})`}`;
      return [out.summary?.outcome === "blocked" ? `blocked (${seconds})${at}` : `failed (${seconds})${at}`, "fail"];
    }
    if (result.exit === 2) return [`not run (infrastructure): ${out.refusal ?? "see the output"}`, "fail"];
    if (result.exit < 0) return [`stopped (${seconds})`, "fail"];
    return [`check exited ${String(result.exit)}: see the output`, "fail"];
  }
  return result.status === "error" ? [`couldn't start the check: ${result.ename}: ${result.evalue}`, "fail"] : [result.reason, "fail"];
}

class WorkspaceCell extends HTMLElement {
  view!: EditorView; // verify_workspace.py drives it as `.view`
  private doc!: WorkspaceFile;
  private job: string | undefined; // the running check's job id
  private queued = false; // Run pressed before the sandbox was ready: runs once it is
  private expanded = false;
  private verdict: Verdict | undefined;
  private loadError: string | undefined;

  private get chapter(): string { return attr(this, "data-chapter"); }
  private get file(): string { return attr(this, "data-file"); }
  private get name(): string { return attr(this, "name"); }
  private get region(): string | null { return this.getAttribute("data-region"); }
  get lastSaveMs(): number | undefined { return this.doc.lastSaveMs; } // for verify_workspace.py

  connectedCallback(): void {
    const lang = attr(this, "data-lang");
    const ops = this.getAttribute("data-ops") ?? "";
    const start = must(this, "pre", HTMLPreElement).textContent;
    const region = this.region;
    this.innerHTML = `
      <div class="cell-head"><span>${this.name} · ${this.file}${ops ? ` · ${ops}` : ""}</span>
        <span class="cell-status"></span><button class="connect-to-run" type="button">Connect to run</button>
        <button class="expand" type="button" aria-pressed="false"${region === null ? " hidden" : ""}>whole file</button>
        <button class="vim-toggle" aria-pressed="${String(vimEnabled())}">vim</button><button class="run">Run</button></div>
      <p class="cell-note" hidden></p>
      <div class="cell-conflict" role="alert" hidden><span></span>
        <button type="button" class="use-browser">Use this browser's draft</button><button type="button" class="keep-workspace">Keep the sandbox's</button></div>
      <div class="cell-editor${region === null ? "" : " bounded"}"></div>
      <div class="cell-out" tabindex="0" aria-label="${this.name} output" hidden></div>`;
    this.doc = WorkspaceFile.of(this.chapter, this.file, start);
    this.view = this.doc.view([
      vimExtension(), basicSetup, syntax(lang), look(`${this.name}: ${this.file} (${lang})`),
      View.lineWrapping, // never a sideways scroll: a reader's long line wraps; shipped code is held to 80 columns
      region === null ? [] : regionHighlight(region),
    ], this, (line) => this.holds(line));
    must(this, ".cell-editor", HTMLDivElement).append(this.view.dom);
    this.view.scrollDOM.tabIndex = 0;
    registerEditor(this.view);
    must(this, ".vim-toggle", HTMLButtonElement).onclick = () => { setVim(!vimEnabled()); };
    must(this, ".connect-to-run", HTMLButtonElement).onclick = () => { document.dispatchEvent(new Event("connect:open")); };
    must(this, ".run", HTMLButtonElement).onclick = () => { void this.runOrStop(); };
    must(this, ".expand", HTMLButtonElement).onclick = () => { this.expanded = !this.expanded; this.fit(); };
    must(this, ".use-browser", HTMLButtonElement).onclick = () => { this.doc.resolve(true); };
    must(this, ".keep-workspace", HTMLButtonElement).onclick = () => { this.doc.resolve(false); };
    this.doc.onChange(() => { this.note(); this.gate(); });
    onWorkspace(() => { this.gate(); });
    onPhase(() => { this.gate(); });
    onKernelState((state) => {
      if (state === "idle") this.ensureLoaded();
      this.gate();
    });
    if (kernelState() === "idle" || kernelState() === "busy") this.ensureLoaded();
    this.fit();
    this.gate();
  }

  private span(): Span | undefined {
    const region = this.region;
    return region === null ? undefined : findRegion(this.view.state.doc, region);
  }

  private holds(line: number): boolean {
    const span = this.span();
    return span !== undefined && line >= span.first && line <= span.last;
  }

  // "region X not found" while its markers are missing (checks don't care: they pick ops by name).
  private note(): void {
    const el = must(this, ".cell-note", HTMLParagraphElement);
    const region = this.region;
    const missing = region !== null && this.span() === undefined;
    el.hidden = !missing;
    el.textContent = missing ? `no "# region: ${region}" ... "# endregion" in ${this.file}: nothing to highlight (Run still checks ${this.name}'s ops)` : "";
  }

  // Size the editor to the region (bounded) or the whole file (expanded), and scroll the region to the top. Runs at
  // mount, after each load and on expand/collapse; never on an edit (it would fight the reader's scrolling).
  private fit(): void {
    this.note();
    const editor = must(this, ".cell-editor", HTMLDivElement);
    must(this, ".expand", HTMLButtonElement).setAttribute("aria-pressed", String(this.expanded));
    if (this.region === null) return;
    editor.classList.toggle("bounded", !this.expanded);
    editor.classList.toggle("expanded", this.expanded);
    const v = this.view;
    // Measured after the frame: a load that replaced the whole doc resets the scroller in its own measure pass.
    requestAnimationFrame(() => {
      v.requestMeasure({
        read: () => {
          const span = this.span();
          const doc = v.state.doc;
          const first = span === undefined ? 1 : Math.max(span.first - 1, 1);
          const last = span === undefined ? Math.min(UNREGIONED_LINES, doc.lines) : Math.min(span.last + 1, doc.lines);
          const top = v.lineBlockAt(doc.line(first).from).top;
          const bottom = v.lineBlockAt(doc.line(last).from).bottom;
          return { top: span === undefined ? 0 : top, height: Math.min(Math.max(bottom - top, MIN_LINES * v.defaultLineHeight), MAX_LINES * v.defaultLineHeight) };
        },
        write: ({ top, height }) => {
          editor.style.setProperty("--cell-h", `${String(Math.ceil(height + 10))}px`); // + the content's padding
          v.requestMeasure({ read: () => null, write: () => { v.scrollDOM.scrollTop = this.expanded ? 0 : top; } });
        },
      });
    });
  }

  private ensureLoaded(): void {
    this.doc.ensureLoaded(() => bootWorkspace(this.chapter, attr(this, "data-trusted"))).then(() => {
      this.loadError = undefined;
      this.fit();
      this.setAttribute("data-loaded", this.doc.from ?? "workspace");
      if (this.queued) { this.queued = false; void this.start(); }
      this.gate();
    }, (e: unknown) => {
      this.loadError = `couldn't load the workspace: ${String(e)}`;
      this.gate();
    });
  }

  private ready(): boolean {
    return (kernelState() === "idle" || kernelState() === "busy") && this.doc.loaded;
  }

  private async runOrStop(): Promise<void> {
    if (this.job !== undefined) {
      await stopCheck(this.job).catch((e: unknown) => { this.status(`stop failed: ${String(e)}`, "fail"); });
      return;
    }
    if (this.queued) { this.queued = false; this.gate(); return; } // a second click cancels the queued run
    if (!this.ready()) {
      this.queued = true;
      if (currentPhase().kind === "disconnected") document.dispatchEvent(new Event("connect:open"));
      this.gate();
      return;
    }
    await this.start();
  }

  private async start(): Promise<void> {
    const out = must(this, ".cell-out", HTMLDivElement);
    out.hidden = false;
    out.className = "cell-out";
    out.removeAttribute("data-outcome");
    const output = new CheckOutput(out);
    const id = crypto.randomUUID();
    this.job = id;
    this.setAttribute("data-job", id);
    this.verdict = ["checking…", ""];
    this.gate();
    const started = performance.now();
    await this.doc.flush();
    const result = this.doc.saveError === undefined
      ? await checkCell(id, this.chapter, this.name, attr(this, "data-trusted"), (t) => { output.feed(t); })
      : { status: "aborted" as const, reason: `couldn't save ${this.file} to the workspace: ${this.doc.saveError}` };
    output.end();
    this.job = undefined;
    this.removeAttribute("data-job");
    this.verdict = verdictOf(result, output, `${((performance.now() - started) / 1000).toFixed(2)}s`);
    out.dataset["outcome"] = result.status === "exited" ? output.summary?.outcome ?? (result.exit === 2 ? "infra" : String(result.exit)) : result.status;
    out.classList.add(this.verdict[1] === "pass" ? "pass" : "fail");
    this.gate();
    await refreshStatus(this.chapter).catch((e: unknown) => { this.verdict = [`status failed: ${String(e)}`, "fail"]; });
    this.gate();
  }

  private gate(): void {
    const kernelUp = kernelState() === "idle" || kernelState() === "busy";
    const phase = currentPhase();
    const run = must(this, ".run", HTMLButtonElement);
    must(this, ".connect-to-run", HTMLButtonElement).hidden = kernelUp || phase.kind !== "disconnected";
    run.textContent = this.job !== undefined ? "Stop" : this.queued ? "Cancel" : "Run";
    this.toggleAttribute("data-queued", this.queued);
    const conflict = this.doc.conflict;
    const banner = must(this, ".cell-conflict", HTMLDivElement);
    banner.hidden = conflict === undefined;
    must(banner, "span", HTMLSpanElement).textContent = conflict === undefined ? ""
      : `Your sandbox restored passing code (commit ${conflict.head}) that this browser's draft of ${this.file} wasn't built on. Showing the sandbox's version.`;
    if (this.doc.saveError !== undefined) { this.status(`couldn't save to the workspace: ${this.doc.saveError}`, "fail"); return; }
    if (this.job !== undefined) { this.status(...(this.verdict ?? ["checking…", ""])); return; }
    if (this.queued) {
      const step = phase.kind === "connecting" ? ` (${phase.step})` : "";
      this.status(phase.kind === "disconnected" ? "waiting for sandbox: connect to run" : `waiting for sandbox${step}… runs when it's up`, "");
      return;
    }
    if (this.loadError !== undefined) { this.status(this.loadError, "fail"); return; }
    if (!kernelUp) {
      this.status(phase.kind === "connecting" ? `sandbox starting (${phase.step}); keep editing, your edits are kept`
        : "not connected: edits are kept in this browser", "");
      return;
    }
    const mine = workspaceStatus()?.cells.find((c) => c.name === this.name);
    if (!this.doc.loaded || mine === undefined) { this.status("loading your workspace…", ""); return; }
    const standing: Verdict = !mine.passed ? ["not passed yet", ""]
      : mine.stale ? [`passed earlier; ${this.file} changed since (Run to check it again)`, "pass"]
      : mine.draft ? ["passed; edited since (Run to check the edit)", "pass"] : ["passed", "pass"];
    this.toggleAttribute("data-passed", mine.passed);
    this.status(...(this.verdict ?? standing));
  }

  private status(text: string, cls: string): void {
    const s = must(this, ".cell-status", HTMLSpanElement);
    s.textContent = text;
    s.className = `cell-status ${cls}`;
  }
}
customElements.define("ws-cell", WorkspaceCell);
