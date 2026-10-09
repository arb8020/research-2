// Streamed check output -> text with links: every `path:line[:col]` (compilers, sanitizers, asserts, traces) and
// every Python `File "path", line N` that names a workspace file shown on the page becomes a link that scrolls to
// that file's editor and puts the cursor on the line (spike/workspace-cells exp6).
//
// Output arrives in chunks that split lines anywhere, so only complete lines are linkified (LineBuffer); the tail
// waits for its newline or the end. Paths match by suffix on a "/" boundary: the sandbox prints absolute paths
// (/root/_blogs/tree/ring.cpp), make prints relative ones (ring.cpp), both mean the workspace's ring.cpp.
import { EditorView } from "codemirror";

// file.ext:LINE[:COL] anywhere in a line; only source-ish extensions ("Makefile:22", "0x6020...:1" stay text).
const LOCATION = /((?:[\w.-]*\/)*[\w.-]+\.(?:cpp|cc|c|h|hpp|py|trace)):(\d+)(?::(\d+))?/g;
const PY_FRAME = /File "([^"]+)", line (\d+)/g;
const ANSI = /\x1b\[[0-9;]*[A-Za-z]/g; // eslint-disable-line no-control-regex

interface Shown { view: EditorView; host: HTMLElement }
const files = new Map<string, Shown>(); // workspace-relative path -> the editor showing it

export function registerFile(path: string, view: EditorView, host: HTMLElement): void {
  files.set(path, { view, host });
}

function resolve(printed: string): string | undefined {
  const clean = printed.replace(/^\.\//, "");
  let best: string | undefined;
  for (const path of files.keys()) {
    if ((clean === path || clean.endsWith(`/${path}`)) && (best === undefined || path.length > best.length)) best = path;
  }
  return best;
}

export function jump(path: string, line: number, col: number): void {
  const shown = files.get(path);
  if (shown === undefined) throw new Error(`jump: ${path} is not on this page`);
  const doc = shown.view.state.doc;
  const target = doc.line(Math.min(Math.max(line, 1), doc.lines)); // the file changed since the output: clamp
  const pos = Math.min(target.from + Math.max(col - 1, 0), target.to);
  shown.host.scrollIntoView({ block: "center" });
  shown.view.dispatch({ selection: { anchor: pos }, effects: EditorView.scrollIntoView(pos, { y: "center" }) });
  shown.view.focus();
}

interface Hit { start: number; end: number; path: string; line: number; col: number }

function hits(line: string): Hit[] {
  const found: Hit[] = [];
  for (const m of line.matchAll(LOCATION)) {
    const path = resolve(m[1] ?? "");
    if (path !== undefined) found.push({ start: m.index, end: m.index + m[0].length, path, line: Number(m[2]), col: m[3] === undefined ? 1 : Number(m[3]) });
  }
  for (const m of line.matchAll(PY_FRAME)) {
    const path = resolve(m[1] ?? "");
    if (path !== undefined) found.push({ start: m.index, end: m.index + m[0].length, path, line: Number(m[2]), col: 1 });
  }
  return found.sort((a, b) => a.start - b.start).filter((h, i, all) => i === 0 || h.start >= (all[i - 1]?.end ?? 0));
}

function linkify(line: string): DocumentFragment {
  const frag = document.createDocumentFragment();
  let last = 0;
  for (const h of hits(line)) {
    frag.append(line.slice(last, h.start));
    const a = document.createElement("a");
    a.href = "#";
    a.className = "out-link";
    a.textContent = line.slice(h.start, h.end);
    a.dataset["loc"] = `${h.path}:${String(h.line)}:${String(h.col)}`;
    a.onclick = (e) => { e.preventDefault(); jump(h.path, h.line, h.col); };
    frag.append(a);
    last = h.end;
  }
  frag.append(line.slice(last));
  return frag;
}

// Feeds one output element; call end() when the stream is over to flush a last line without a newline.
export class LineBuffer {
  private tail = "";
  constructor(private readonly out: HTMLElement) {}

  feed(chunk: string): void {
    const parts = (this.tail + chunk).split("\n");
    this.tail = parts.pop() ?? "";
    for (const line of parts) this.out.append(linkify(line.replace(ANSI, "")), "\n");
    this.out.scrollTop = this.out.scrollHeight;
  }

  end(): void {
    if (this.tail !== "") this.out.append(linkify(this.tail.replace(ANSI, "")), "\n");
    this.tail = "";
  }
}
