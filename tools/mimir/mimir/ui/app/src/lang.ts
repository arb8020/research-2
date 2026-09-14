/**
 * Map file extensions to CodeMirror language support.
 */

import { python } from "@codemirror/lang-python";
import { javascript } from "@codemirror/lang-javascript";
import { json } from "@codemirror/lang-json";
import { html } from "@codemirror/lang-html";
import { css } from "@codemirror/lang-css";
import { markdown } from "@codemirror/lang-markdown";
import type { Extension } from "@codemirror/state";

const EXT_MAP: Record<string, () => Extension> = {
  py: python,
  pyi: python,
  js: () => javascript(),
  jsx: () => javascript({ jsx: true }),
  ts: () => javascript({ typescript: true }),
  tsx: () => javascript({ jsx: true, typescript: true }),
  json: json,
  html: html,
  htm: html,
  css: css,
  md: markdown,
  mdx: markdown,
};

export function langForPath(path: string): Extension[] {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  const factory = EXT_MAP[ext];
  return factory ? [factory()] : [];
}
