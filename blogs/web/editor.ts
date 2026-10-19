import { EditorView } from "codemirror";
import { Compartment, Prec } from "@codemirror/state";
import { acceptCompletion, autocompletion, completionStatus, startCompletion } from "@codemirror/autocomplete";
import { keymap } from "@codemirror/view";
import type { Extension } from "@codemirror/state";
import { cpp } from "@codemirror/lang-cpp";
import { python } from "@codemirror/lang-python";
import { syntaxHighlighting } from "@codemirror/language";
import { classHighlighter } from "@lezer/highlight";
import { vim } from "@replit/codemirror-vim";

export const syntax = (lang: string): Extension => (lang === "c" || lang === "cpp" ? cpp() : python());

const monoFont = EditorView.theme({ ".cm-scroller": { fontFamily: "var(--font-mono)" } });
const tabCompletion: Extension = [
  autocompletion({ activateOnTyping: false }),
  Prec.highest(keymap.of([{ key: "Tab", run: (view) => {
    if (completionStatus(view.state) === "active") return acceptCompletion(view);
    const sel = view.state.selection.main;
    const before = view.state.sliceDoc(Math.max(0, sel.head - 1), sel.head);
    return sel.empty && /\w/.test(before) ? startCompletion(view) : false;
  } }])),
];

const runKeys: Extension = Prec.highest(keymap.of(["Shift-Enter", "Mod-Enter"].map((key) => ({ key, run: (view) => {
  for (let el = view.dom.parentElement; el !== null; el = el.parentElement) {
    const button = el.querySelector<HTMLButtonElement>("button.run");
    if (button === null) continue;
    if (!button.disabled && button.textContent.trim() === "Run") button.click();
    return true;
  }
  return false;
} }))));

export const readingLook = (label: string): Extension[] => [
  monoFont,
  syntaxHighlighting(classHighlighter),
  EditorView.contentAttributes.of({ "aria-label": label }),
];

export const look = (label: string): Extension[] => [...readingLook(label), tabCompletion, runKeys];

const vimMode = new Compartment();
const vimKey = "blogs.vim";
let vimOn = false;
try { vimOn = localStorage.getItem(vimKey) === "1"; } catch { vimOn = false; }
const editors: EditorView[] = [];

export const vimEnabled = (): boolean => vimOn;
export const vimExtension = (): Extension => vimMode.of(vimOn ? vim() : []);

const rememberVim = (on: boolean): void => {
  try { localStorage.setItem(vimKey, on ? "1" : "0"); } catch { return; }
};

export function setVim(on: boolean): void {
  vimOn = on;
  rememberVim(on);
  for (const view of editors) view.dispatch({ effects: vimMode.reconfigure(on ? vim() : []) });
  for (const b of document.querySelectorAll(".vim-toggle")) b.setAttribute("aria-pressed", String(on));
}

export function registerEditor(view: EditorView): void {
  editors.push(view);
}
