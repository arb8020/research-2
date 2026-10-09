// What every CodeMirror on the page shares: the look (font, token classes), the language, the one vim switch.
import { EditorView } from "codemirror";
import { Compartment } from "@codemirror/state";
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
export const look = (label: string): Extension[] => [
  monoFont,
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
