// What every CodeMirror on the page shares: the look (font, token classes), the language, the one vim switch.
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

// Token colours come from page.css (.tok-* classes), so light/dark follow the page's CSS variables.
// The font has to be a theme: CodeMirror's base theme (.ͼ1 .cm-scroller { font-family: monospace }) outranks a
// plain .cm-scroller rule in page.css, and a theme is scoped and mounted after it, so this one wins.
const monoFont = EditorView.theme({ ".cm-scroller": { fontFamily: "var(--font-mono)" } });
// Completion opens on Tab, never by itself while typing: Tab right after a word character opens the list (or
// accepts the selected option once it is open; Enter accepts too). Tab anywhere else does what it did before
// (moves focus), so the editor never traps keyboard users.
const tabCompletion: Extension = [
  autocompletion({ activateOnTyping: false }),
  Prec.highest(keymap.of([{ key: "Tab", run: (view) => {
    if (completionStatus(view.state) === "active") return acceptCompletion(view);
    const sel = view.state.selection.main;
    const before = view.state.sliceDoc(Math.max(0, sel.head - 1), sel.head);
    return sel.empty && /\w/.test(before) ? startCompletion(view) : false;
  } }])),
];

export const look = (label: string): Extension[] => [
  monoFont,
  tabCompletion,
  syntaxHighlighting(classHighlighter),
  EditorView.contentAttributes.of({ "aria-label": label }),
];

// One vim switch for every editor on the page, remembered per reader.
const vimMode = new Compartment();
const vimKey = "blogs.vim";
let vimOn = false;
try { vimOn = localStorage.getItem(vimKey) === "1"; } catch { /* storage blocked: vim stays off */ }
const editors: EditorView[] = [];

export const vimEnabled = (): boolean => vimOn;
export const vimExtension = (): Extension => vimMode.of(vimOn ? vim() : []);

export function setVim(on: boolean): void {
  vimOn = on;
  try { localStorage.setItem(vimKey, on ? "1" : "0"); } catch { /* storage blocked: not remembered */ }
  for (const view of editors) view.dispatch({ effects: vimMode.reconfigure(on ? vim() : []) });
  for (const b of document.querySelectorAll(".vim-toggle")) b.setAttribute("aria-pressed", String(on));
}

// An editable editor joins the vim switch.
export function registerEditor(view: EditorView): void {
  editors.push(view);
}
