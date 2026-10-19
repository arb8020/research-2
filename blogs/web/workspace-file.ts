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
const MirroredFromPrimary = Annotation.define<boolean>();

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
  try { localStorage.setItem(key, JSON.stringify(draft)); } catch { return; }
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
  } catch { return; }
}

export type From = "workspace" | "browser";
export interface Conflict { browser: string; head: string }

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

const vimUndo = CodeMirror.commands.undo;
const vimRedo = CodeMirror.commands.redo;
CodeMirror.commands.undo = (cm) => { const f = owners.get(cm.cm6); if (f === undefined) vimUndo(cm); else f.undo(); };
CodeMirror.commands.redo = (cm) => { const f = owners.get(cm.cm6); if (f === undefined) vimRedo(cm); else f.redo(); };

export interface FileView { view: EditorView; host: HTMLElement; holds: (line: number) => boolean }

export class WorkspaceFile {
  private primary: EditorState;
  private readonly views = new Set<EditorView>();
  private readonly shown: FileView[] = [];
  private readonly listeners = new Set<() => void>();
  loaded = false;
  from: From | undefined;
  conflict: Conflict | undefined;
  head: string | undefined;
  lastSaveMs: number | undefined;
  saveError: string | undefined;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private saving: Promise<void> = Promise.resolve();
  private loading: Promise<void> | undefined;

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
        for (const tr of trs) if (tr.docChanged && tr.annotation(MirroredFromPrimary) !== true) this.fromView(tr, v);
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

  private fromView(tr: Transaction, origin: EditorView): void {
    const annotations = [];
    const event = tr.annotation(Transaction.userEvent);
    if (event !== undefined) annotations.push(Transaction.userEvent.of(event));
    if (tr.annotation(Transaction.addToHistory) === false) annotations.push(Transaction.addToHistory.of(false));
    this.primary = this.primary.update({ changes: tr.changes, annotations }).state;
    this.mirror(tr, origin);
  }

  private apply(spec: TransactionSpec): void {
    const tr = this.primary.update(spec);
    this.primary = tr.state;
    if (tr.docChanged) this.mirror(tr, undefined);
  }

  private mirror(tr: Transaction, origin: EditorView | undefined): void {
    for (const v of this.views) {
      if (v !== origin) v.dispatch({ changes: tr.changes, annotations: [MirroredFromPrimary.of(true), Transaction.addToHistory.of(false)] });
    }
    this.edited();
  }

  undo(): void { undo({ state: this.primary, dispatch: (tr) => { this.primary = tr.state; this.mirror(tr, undefined); } }); }
  redo(): void { redo({ state: this.primary, dispatch: (tr) => { this.primary = tr.state; this.mirror(tr, undefined); } }); }

  setText(text: string, undoable: boolean): void {
    if (text === this.text) return;
    this.apply({ changes: { from: 0, to: this.primary.doc.length, insert: text }, annotations: undoable ? [] : [Transaction.addToHistory.of(false)] });
  }

  private loadIsReplacingDoc = false;

  private edited(): void {
    if (this.loadIsReplacingDoc) return;
    writeDraft(this.draftKey, { text: this.text, acked: false, base: this.head });
    this.changed();
    if (!this.loaded) return;
    clearTimeout(this.timer);
    this.timer = setTimeout(() => { this.timer = undefined; void this.save(); }, SAVE_DEBOUNCE_MS);
  }

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
    this.loadIsReplacingDoc = true;
    try { this.setText(text, false); } finally { this.loadIsReplacingDoc = false; }
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

  resolve(useBrowser: boolean): void {
    const conflict = this.conflict;
    if (conflict === undefined) return;
    this.conflict = undefined;
    writeConflict(this.conflictKey, undefined);
    if (useBrowser) this.setText(conflict.browser, true);
    this.changed();
  }

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

  async flush(): Promise<void> {
    if (this.timer !== undefined) {
      clearTimeout(this.timer);
      this.timer = undefined;
      await this.save();
    }
    await this.saving;
  }
}
