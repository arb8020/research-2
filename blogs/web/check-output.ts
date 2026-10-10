// A workspace check's streamed output (the check command's contract, notes/ch01-design-2026-10-09.md) rendered under
// its cell: JSON lines become a verdict table (op, dtype, chip, outcome, key metric, notes; SKIP and BLOCKED styled
// apart, `where` a link that jumps the file's editor) and a summary line; log lines and anything that isn't JSON
// (a legacy check, a compiler, a traceback) are plain output with file:line links.
import { jump, LineSplitter, linkify } from "./out-links";
import { isJsonObject } from "./json";

export type Outcome = "pass" | "fail" | "skip" | "blocked";
export interface Where { file: string; line: number; region: string | undefined }
export interface Verdict {
  op: string; case: string; dtype: string; chip: string; outcome: Outcome;
  score: number | undefined; metrics: Record<string, number>; notes: string; where: Where | undefined;
}
export interface Summary { outcome: "pass" | "fail" | "blocked"; counts: Record<string, number>; run: string }

type Line = { kind: "log"; text: string } | { kind: "verdict"; verdict: Verdict } | { kind: "summary"; summary: Summary } | { kind: "text"; text: string };

const OUTCOMES: readonly Outcome[] = ["pass", "fail", "skip", "blocked"];
const str = (x: unknown): string => (typeof x === "string" ? x : "");
// The numeric entries of an object, in order (a metric that is null or a string has no number to show).
const numbers = (x: unknown): Record<string, number> => {
  const out: Record<string, number> = {};
  if (isJsonObject(x)) for (const [k, v] of Object.entries(x)) if (typeof v === "number") out[k] = v;
  return out;
};

function parseWhere(raw: unknown): Where | undefined {
  if (!isJsonObject(raw) || typeof raw["file"] !== "string" || typeof raw["line"] !== "number") return undefined;
  return { file: raw["file"], line: raw["line"], region: typeof raw["region"] === "string" ? raw["region"] : undefined };
}

// One line of output. Anything that isn't a well-formed contract line is plain text (shown, never dropped).
export function parseLine(line: string): Line {
  if (!line.startsWith("{")) return { kind: "text", text: line };
  let raw: unknown;
  try { raw = JSON.parse(line); } catch { return { kind: "text", text: line }; }
  if (!isJsonObject(raw)) return { kind: "text", text: line };
  if (raw["kind"] === "log" && typeof raw["text"] === "string") return { kind: "log", text: raw["text"] };
  if (raw["kind"] === "verdict" && typeof raw["op"] === "string") {
    const outcome = OUTCOMES.find((o) => o === raw["outcome"]);
    if (outcome === undefined) return { kind: "text", text: line };
    return { kind: "verdict", verdict: {
      op: raw["op"], case: str(raw["case"]), dtype: str(raw["dtype"]), chip: str(raw["chip"]), outcome,
      score: typeof raw["score"] === "number" ? raw["score"] : undefined, metrics: numbers(raw["metrics"]),
      notes: str(raw["notes"]), where: parseWhere(raw["where"]),
    } };
  }
  if (raw["kind"] === "summary") {
    const o = raw["outcome"];
    if ((o === "pass" || o === "fail" || o === "blocked") && isJsonObject(raw["counts"])) {
      return { kind: "summary", summary: { outcome: o, counts: numbers(raw["counts"]), run: str(raw["run"]) } };
    }
  }
  return { kind: "text", text: line };
}

// The one number a row shows: the first metric with a value, else the score.
function keyMetric(v: Verdict): string {
  const first = Object.entries(v.metrics)[0];
  if (first !== undefined) return `${first[0]} ${String(Number(first[1].toPrecision(3)))}`;
  return v.score === undefined ? "" : `score ${String(v.score)}`;
}

function whereLink(where: Where): HTMLElement {
  const a = document.createElement("a");
  a.href = "#";
  a.className = "out-link where";
  a.textContent = `${where.file}:${String(where.line)}${where.region === undefined ? "" : ` (${where.region})`}`;
  a.dataset["loc"] = `${where.file}:${String(where.line)}:1`;
  a.onclick = (e) => {
    e.preventDefault();
    try { jump(where.file, where.line, 1); } catch (err) { a.title = String(err); }
  };
  return a;
}

const cell = (text: string, cls = ""): HTMLTableCellElement => {
  const td = document.createElement("td");
  td.textContent = text;
  if (cls) td.className = cls;
  return td;
};

export class CheckOutput {
  readonly verdicts: Verdict[] = [];
  summary: Summary | undefined;
  refusal: string | undefined; // workspace.py refused to run the check (a `workspace: refused: ...` log line)
  private readonly lines = new LineSplitter((line) => { this.add(parseLine(line)); });
  private readonly table: HTMLTableElement;
  private readonly summaryEl: HTMLParagraphElement;
  private readonly log: HTMLPreElement;

  constructor(root: HTMLElement) {
    root.innerHTML = `<table class="verdicts" hidden><thead><tr><th>op</th><th>dtype</th><th>chip</th><th>outcome</th><th>metric</th><th>notes</th></tr></thead><tbody></tbody></table>
      <p class="check-summary" hidden></p><pre class="check-log"></pre>`;
    this.table = root.querySelector("table") ?? document.createElement("table");
    this.summaryEl = root.querySelector("p") ?? document.createElement("p");
    this.log = root.querySelector("pre") ?? document.createElement("pre");
  }

  feed(chunk: string): void { this.lines.feed(chunk); }
  end(): void { this.lines.end(); }

  private add(line: Line): void {
    switch (line.kind) {
      case "text":
      case "log": {
        const refused = /^workspace: refused: (.*)$/.exec(line.text);
        if (refused !== null) this.refusal = refused[1];
        this.log.append(linkify(line.text), "\n");
        this.log.scrollTop = this.log.scrollHeight;
        return;
      }
      case "verdict": { this.addVerdict(line.verdict); return; }
      case "summary": {
        this.summary = line.summary;
        const counts = Object.entries(line.summary.counts).map(([k, n]) => `${String(n)} ${k}`).join(", ");
        this.summaryEl.textContent = `${line.summary.outcome.toUpperCase()}: ${counts}${line.summary.run ? ` · run ${line.summary.run}` : ""}`;
        this.summaryEl.className = `check-summary ${line.summary.outcome}`;
        this.summaryEl.hidden = false;
        return;
      }
    }
  }

  private addVerdict(v: Verdict): void {
    this.verdicts.push(v);
    const tr = document.createElement("tr");
    tr.className = `verdict ${v.outcome}`;
    tr.dataset["op"] = v.op;
    tr.dataset["outcome"] = v.outcome;
    const notes = cell(v.notes);
    if (v.where !== undefined) notes.append(notes.textContent ? " " : "", whereLink(v.where));
    tr.append(cell(v.case ? `${v.op} · ${v.case}` : v.op), cell(v.dtype), cell(v.chip), cell(v.outcome.toUpperCase(), "outcome"), cell(keyMetric(v)), notes);
    this.table.tBodies[0]?.append(tr);
    this.table.hidden = false;
  }

  // The first verdict that points somewhere a reader should look (blocked, then fail).
  firstWhere(): Where | undefined {
    return (this.verdicts.find((v) => v.outcome === "blocked" && v.where) ?? this.verdicts.find((v) => v.outcome === "fail" && v.where))?.where;
  }
}
