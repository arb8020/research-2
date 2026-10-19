import { EditorView } from "codemirror";

const LOCATION = /((?:[\w.-]*\/)*[\w.-]+\.(?:cpp|cc|c|h|hpp|py|trace)):(\d+)(?::(\d+))?/g;
const PY_FRAME = /File "([^"]+)", line (\d+)/g;
const ANSI = /\x1b\[[0-9;]*[A-Za-z]/g; // oxlint-disable-line no-control-regex

export interface Shown { view: EditorView; host: HTMLElement }
const files = new Map<string, (line: number) => Shown>();

export function registerFile(path: string, view: EditorView, host: HTMLElement): void {
  files.set(path, () => ({ view, host }));
}
export function registerFileViews(path: string, pick: (line: number) => Shown): void {
  files.set(path, pick);
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
  const pick = files.get(path);
  if (pick === undefined) throw new Error(`jump: ${path} is not on this page`);
  const shown = pick(line);
  const doc = shown.view.state.doc;
  const lineInCurrentDoc = Math.min(Math.max(line, 1), doc.lines);
  const target = doc.line(lineInCurrentDoc);
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

export function linkify(line: string): DocumentFragment {
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

export class LineSplitter {
  private tail = "";
  constructor(private readonly onLine: (line: string) => void) {}

  feed(chunk: string): void {
    const parts = (this.tail + chunk).split("\n");
    this.tail = parts.pop() ?? "";
    for (const line of parts) this.onLine(line.replace(ANSI, ""));
  }

  end(): void {
    if (this.tail !== "") this.onLine(this.tail.replace(ANSI, ""));
    this.tail = "";
  }
}
