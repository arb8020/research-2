// One workspace file on the page (e.g. gpt2.py): ONE document that every cell over that file is a view of
// (CodeMirror's split-view pattern). The primary state holds the doc and the undo history; each cell's EditorView is
// a follower: its edits go to the primary and on to the other views, and undo/redo (keys and vim's u / Ctrl-r) act
// on the primary, so undo is per file, not per cell.
//
// The file also owns its persistence:
//   before Connect  the doc starts as this browser's last draft (localStorage) or the chapter's start text; edits are
//                   kept in localStorage only
//   on load         (after workspace.py boot) reconcile the browser's draft with the workspace's file (reconcile())
//   loaded          every edit saved to the workspace (debounced, Contents API) and mirrored to localStorage
import { Annotation, EditorState, Prec, Transaction } from "@codemirror/state";
import type { Extension, TransactionSpec } from "@codemirror/state";
import { EditorView, keymap } from "@codemirror/view";
import { history, redo, undo } from "@codemirror/commands";
import { CodeMirror } from "@replit/codemirror-vim";
import { registerFileViews } from "./out-links";
import type { Shown } from "./out-links";
import { onKernelState } from "./connect/kernel";
import { onWorkspace, readFile, writeFile } from "./workspace";
import type { Boot } from "./workspace";

const SAVE_DEBOUNCE_MS = 300;
const Sync = Annotation.define<boolean>(); // a change mirrored from the primary: not the reader's in this view

// The browser's copy of a draft: the text last typed, whether the workspace acknowledged writing it, and the passing
// commit (workspace HEAD) it was last in sync with, if any.
export interface Draft { text: string; acked: boolean; base: string | undefined }

function readDraft(key: string): Draft | undefined {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(key) ?? "null");
    if (typeof raw !== "object" || raw === null || !("text" in raw) || !("acked" in raw)) return undefined;
    const base = "base" in raw && typeof raw.base === "string" ? raw.base : undefined;
    return typeof raw.text === "string" && typeof raw.acked === "boolean" ? { text: raw.text, acked: raw.acked, base } : undefined;
  } catch { return undefined; }
}
function writeDraft(key: string, draft: Draft): void {
  try { localStorage.setItem(key, JSON.stringify(draft)); } catch { /* storage blocked: the workspace still has it */ }
}
function readConflict(key: string): Conflict | undefined {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(key) ?? "null");
    if (typeof raw !== "object" || raw === null || !("browser" in raw) || !("head" in raw)) return undefined;
    return typeof raw.browser === "string" && typeof raw.head === "string" ? { browser: raw.browser, head: raw.head } : undefined;
  } catch { return undefined; }
}
function writeConflict(key: string, conflict: Conflict | undefined): void {
  try {
    if (conflict === undefined) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(conflict));
  } catch { /* storage blocked: the banner lasts until this page closes */ }
}

export type From = "workspace" | "browser";
// The workspace restored passing code this browser's draft wasn't built on: the editor shows the workspace's and the
// browser's draft waits here (and in localStorage, so a reload keeps asking) until the reader picks.
export interface Conflict { browser: string; head: string }

// Which text the doc takes when the workspace has `inWorkspace` and this browser has `local`:
//   no local copy, or the same text                  -> the workspace's
//   a new sandbox seeded from the chapter's start     -> this browser's (it is the reader's only work)
//   this sandbox already had it (existing)            -> this browser's if its last edit never reached the workspace,
//                                                        else the workspace's (it changed elsewhere since)
//   restored from the bundle, the draft was built on  -> this browser's (newer than the passing code)
//     the HEAD the sandbox restored
//   restored, any other HEAD                          -> the workspace's, and a Conflict: the sandbox has passing code
//                                                        this browser never saw; the reader decides (never silent)
export function reconcile(inWorkspace: string, local: Draft | undefined, boot: Pick<Boot, "created"> & { head: string }): { text: string; from: From; conflict?: Conflict } {
  if (local === undefined || local.text === inWorkspace) return { text: inWorkspace, from: "workspace" };
  switch (boot.created) {
    case "seeded": return { text: local.text, from: "browser" };
    case "existing": return local.acked ? { text: inWorkspace, from: "workspace" } : { text: local.text, from: "browser" };
    case "restored":
    case "restored-previous":
      if (local.base === boot.head) return { text: local.text, from: "browser" };
      return { text: inWorkspace, from: "workspace", conflict: { browser: local.text, head: boot.head } };
  }
}

const files = new Map<string, WorkspaceFile>();
const owners = new WeakMap<EditorView, WorkspaceFile>();

// vim's u / Ctrl-r call CodeMirror's undo on the view; a follower's own history is empty, so route them here.
const vimUndo = CodeMirror.commands.undo;
const vimRedo = CodeMirror.commands.redo;
CodeMirror.commands.undo = (cm) => { const f = owners.get(cm.cm6); if (f === undefined) vimUndo(cm); else f.undo(); };
CodeMirror.commands.redo = (cm) => { const f = owners.get(cm.cm6); if (f === undefined) vimRedo(cm); else f.redo(); };

// A cell showing part of the file: jump-to-line picks the cell whose region holds the line.
export interface FileView { view: EditorView; host: HTMLElement; holds: (line: number) => boolean }

export class WorkspaceFile {
  private primary: EditorState;
  private readonly views = new Set<EditorView>();
  private readonly shown: FileView[] = [];
  private readonly listeners = new Set<() => void>();
  loaded = false;
  from: From | undefined; // where the text came from at the last load
  conflict: Conflict | undefined;
  head: string | undefined; // the workspace HEAD this doc was last in sync with
  lastSaveMs: number | undefined; // the latest save's round trip, for verify_workspace.py
  saveError: string | undefined; // the last save failed (the browser still has the draft)
  private timer: ReturnType<typeof setTimeout> | undefined;
  private saving: Promise<void> = Promise.resolve();
  private loading: Promise<void> | undefined;

  // The page's one document for `file`; the first cell to ask creates it from the start text it carries.
  static of(chapter: string, file: string, start: string): WorkspaceFile {
    const key = `${chapter}/${file}`;
    let f = files.get(key);
    if (f === undefined) {
      f = new WorkspaceFile(chapter, file, start);
      files.set(key, f);
    }
    return f;
  }

  private constructor(readonly chapter: string, readonly file: string, start: string) {
    const draft = readDraft(this.draftKey);
    this.head = draft?.base;
    this.conflict = readConflict(this.conflictKey);
    this.primary = EditorState.create({ doc: draft?.text ?? start, extensions: [history()] });
    registerFileViews(file, (line) => this.pick(line));
    onWorkspace((s) => {
      if (!this.loaded || s.chapter !== chapter) return;
      this.head = s.head;
      const d = readDraft(this.draftKey);
      if (d?.text === this.text) writeDraft(this.draftKey, { ...d, base: s.head });
    });
    onKernelState((state) => { if (state === "off" || state === "lost") { this.loaded = false; this.changed(); } });
  }

  private get draftKey(): string { return `blogs.ws.${this.chapter}.${this.file}`; }
  private get conflictKey(): string { return `${this.draftKey}.conflict`; }
  get text(): string { return this.primary.doc.toString(); }

  onChange(listener: () => void): void { this.listeners.add(listener); }
  private changed(): void { for (const listener of this.listeners) listener(); }

  // A new view of the doc, with the cell's own extensions (language, look, vim, region highlight, ...).
  view(extensions: Extension[], host: HTMLElement, holds: (line: number) => boolean): EditorView {
    const view = new EditorView({
      state: EditorState.create({ doc: this.primary.doc, extensions: [
        Prec.highest(keymap.of([
          { key: "Mod-z", run: () => { this.undo(); return true; }, preventDefault: true },
          { key: "Mod-y", mac: "Mod-Shift-z", run: () => { this.redo(); return true; }, preventDefault: true },
        ])),
        ...extensions,
      ] }),
      dispatchTransactions: (trs, v) => {
        v.update(trs);
        for (const tr of trs) if (tr.docChanged && tr.annotation(Sync) !== true) this.fromView(tr, v);
      },
    });
    this.views.add(view);
    owners.set(view, this);
    this.shown.push({ view, host, holds });
    return view;
  }

  private pick(line: number): Shown {
    const best = this.shown.find((s) => s.holds(line)) ?? this.shown[0];
    if (best === undefined) throw new Error(`${this.file}: no cell shows it`);
    return best;
  }

  // A reader's edit in one view: into the primary (its history), then mirrored into every other view.
  private fromView(tr: Transaction, origin: EditorView): void {
    const annotations = [];
    const event = tr.annotation(Transaction.userEvent);
    if (event !== undefined) annotations.push(Transaction.userEvent.of(event));
    if (tr.annotation(Transaction.addToHistory) === false) annotations.push(Transaction.addToHistory.of(false));
    this.primary = this.primary.update({ changes: tr.changes, annotations }).state;
    this.mirror(tr, origin);
  }

  // A change made on the primary (undo, redo, load): into every view.
  private apply(spec: TransactionSpec): void {
    const tr = this.primary.update(spec);
    this.primary = tr.state;
    if (tr.docChanged) this.mirror(tr, undefined);
  }

  private mirror(tr: Transaction, origin: EditorView | undefined): void {
    for (const v of this.views) {
      if (v !== origin) v.dispatch({ changes: tr.changes, annotations: [Sync.of(true), Transaction.addToHistory.of(false)] });
    }
    this.edited();
  }

  undo(): void { undo({ state: this.primary, dispatch: (tr) => { this.primary = tr.state; this.mirror(tr, undefined); } }); }
  redo(): void { redo({ state: this.primary, dispatch: (tr) => { this.primary = tr.state; this.mirror(tr, undefined); } }); }

  // Replace the whole doc (as one undoable edit when it is the reader's choice, e.g. "use my browser draft").
  setText(text: string, undoable: boolean): void {
    if (text === this.text) return;
    this.apply({ changes: { from: 0, to: this.primary.doc.length, insert: text }, annotations: undoable ? [] : [Transaction.addToHistory.of(false)] });
  }

  private applying = false; // load() is replacing the doc: not the reader's edit

  private edited(): void {
    if (this.applying) return;
    writeDraft(this.draftKey, { text: this.text, acked: false, base: this.head });
    this.changed();
    if (!this.loaded) return; // not connected: the browser keeps it; load() reconciles it once the workspace is up
    clearTimeout(this.timer);
    this.timer = setTimeout(() => { this.timer = undefined; void this.save(); }, SAVE_DEBOUNCE_MS);
  }

  // Load once per kernel attach (every cell of the file asks; the first does it).
  ensureLoaded(boot: () => Promise<Boot>): Promise<void> {
    if (this.loaded) return Promise.resolve();
    this.loading ??= this.load(boot).finally(() => { this.loading = undefined; });
    return this.loading;
  }

  private async load(boot: () => Promise<Boot>): Promise<void> {
    const b = await boot();
    const inWorkspace = await readFile(this.file);
    if (inWorkspace === undefined) throw new Error(`the workspace has no ${this.file}`);
    const { text, from, conflict } = reconcile(inWorkspace, readDraft(this.draftKey), { created: b.created, head: b.status.head });
    this.applying = true;
    try { this.setText(text, false); } finally { this.applying = false; }
    this.head = b.status.head;
    if (conflict !== undefined) {
      this.conflict = conflict;
      writeConflict(this.conflictKey, conflict);
    }
    if (from === "browser") await writeFile(this.file, text);
    writeDraft(this.draftKey, { text, acked: true, base: this.head });
    this.from = from;
    this.loaded = true;
    this.changed();
  }

  // The reader's answer to a conflict: their browser draft (one undoable edit, saved), or the workspace's (drop it).
  resolve(useBrowser: boolean): void {
    const conflict = this.conflict;
    if (conflict === undefined) return;
    this.conflict = undefined;
    writeConflict(this.conflictKey, undefined);
    if (useBrowser) this.setText(conflict.browser, true);
    this.changed();
  }

  // Saves run one after another, so the workspace ends with the last text even if two overlap.
  private save(): Promise<void> {
    const text = this.text;
    this.saving = this.saving.then(async () => {
      const t0 = performance.now();
      await writeFile(this.file, text);
      this.lastSaveMs = performance.now() - t0;
      this.saveError = undefined;
      if (this.text === text) writeDraft(this.draftKey, { text, acked: true, base: this.head });
    }).catch((cause: unknown) => { this.saveError = String(cause); this.changed(); });
    return this.saving;
  }

  // Every edit so far is in the workspace (Run calls this before checking).
  async flush(): Promise<void> {
    if (this.timer !== undefined) {
      clearTimeout(this.timer);
      this.timer = undefined;
      await this.save();
    }
    await this.saving;
  }
}
