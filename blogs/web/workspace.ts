// The reader's workspace in the connected sandbox (ws.py there; blogs/ws.py here). Files go through the Contents API
// (connect/contents.ts); ws.py runs on the kernel: status and boot as short cells, checks as background jobs.
//
//   boot  on every kernel attach: upload ws.py + this chapter's ref bundle (both served next to the page), then
//         `ws.py boot`: the repo as it is, restored from the persisted bundle, or seeded from the chapter's start
//   status  pass tags -> which cells passed / are locked; the one source of gating (not DOM order)
//   check   `ws.py check <chapter> <cell> -- <command>` as a job; its output streams to the cell that started it
import { makeDir, readText, writeBytes, writeText } from "./connect/contents";
import { killJob, onKernelState, runCode, runJob } from "./connect/kernel";
import type { JobResult } from "./connect/kernel";

const DIR = "workspace"; // ws.py's REPO, relative to Jupyter's root (the kernel's cwd)
// Not a dot-dir: the Contents API refuses hidden paths (ContentsManager.allow_hidden is off), and its error replies
// carry no CORS headers, so the page would only see "Failed to fetch".
const TOOL = "_blogs/ws.py";
const REF = "_blogs/ref.bundle";

export interface CellStatus {
  name: string;
  file: string;
  passed: boolean;
  locked: boolean;
  why: string; // "locked until ring passes"
  draft: boolean; // the workspace file differs from the latest passing version
}

export interface WorkspaceStatus {
  chapter: string;
  head: string;
  cells: CellStatus[];
  persist: { dir: string; bundleBytes: number } | null; // null: nothing outlives this sandbox
}

// seeded: a new workspace from the chapter's start. restored(-previous): from the persisted bundle (the sandbox is
// new, so drafts only this browser has are newer than the workspace's). existing: this sandbox had it already.
export type Created = "seeded" | "restored" | "restored-previous" | "existing";
export interface Boot { created: Created; ms: number; status: WorkspaceStatus }

const isRecord = (x: unknown): x is Record<string, unknown> => typeof x === "object" && x !== null && !Array.isArray(x);
const fail = (what: string, raw: unknown): never => { throw new Error(`ws.py: expected ${what}, got ${JSON.stringify(raw).slice(0, 300)}`); };

function parseCell(raw: unknown): CellStatus {
  if (!isRecord(raw)) return fail("a cell status", raw);
  const { name, file, passed, locked, why, draft } = raw;
  if (typeof name !== "string" || typeof file !== "string" || typeof passed !== "boolean" || typeof locked !== "boolean"
    || typeof why !== "string" || typeof draft !== "boolean") return fail("{name, file, passed, locked, why, draft}", raw);
  return { name, file, passed, locked, why, draft };
}

function parseStatus(raw: unknown): WorkspaceStatus {
  if (!isRecord(raw) || typeof raw["chapter"] !== "string" || typeof raw["head"] !== "string" || !Array.isArray(raw["cells"])) {
    return fail("{chapter, head, cells, persist}", raw);
  }
  const p = raw["persist"];
  let persist: WorkspaceStatus["persist"] = null;
  if (p !== null) {
    if (!isRecord(p) || typeof p["dir"] !== "string" || typeof p["bundle_bytes"] !== "number") return fail("persist {dir, bundle_bytes} or null", p);
    persist = { dir: p["dir"], bundleBytes: p["bundle_bytes"] };
  }
  return { chapter: raw["chapter"], head: raw["head"], cells: raw["cells"].map(parseCell), persist };
}

const CREATED: readonly Created[] = ["seeded", "restored", "restored-previous", "existing"];
function parseBoot(raw: unknown): Boot {
  if (!isRecord(raw) || typeof raw["ms"] !== "number") return fail("{created, ms, status}", raw);
  const created = CREATED.find((c) => c === raw["created"]);
  if (created === undefined) return fail(`created in ${CREATED.join("|")}`, raw["created"]);
  return { created, ms: raw["ms"], status: parseStatus(raw["status"]) };
}

// `ws.py <args>` as a short cell; its last stdout line is JSON. A failure raises in the kernel with ws.py's stderr.
async function wsJson(args: string[]): Promise<unknown> {
  const code = `import subprocess as _s, sys as _y
_r = _s.run([_y.executable, ${JSON.stringify(TOOL)}, *${JSON.stringify(args)}], capture_output=True, text=True)
if _r.returncode != 0:
    raise RuntimeError(f"ws.py ${args[0] ?? ""} exited {_r.returncode}:\\n{_r.stdout[-2000:]}{_r.stderr[-4000:]}")
print(_r.stdout.strip().splitlines()[-1])`;
  let out = "";
  const result = await runCode(code, (t) => { out += t; });
  if (result.status === "error") throw new Error(`${result.ename}: ${result.evalue}`);
  if (result.status === "aborted") throw new Error(`ws.py ${args[0] ?? ""}: ${result.reason}`);
  return JSON.parse(out);
}

let booting: Promise<Boot> | undefined; // one boot per kernel attach
let current: WorkspaceStatus | undefined;
const listeners = new Set<(s: WorkspaceStatus) => void>();

export const workspaceStatus = (): WorkspaceStatus | undefined => current;
export function onWorkspace(listener: (s: WorkspaceStatus) => void): void {
  listeners.add(listener);
}
function publish(s: WorkspaceStatus): void {
  current = s;
  for (const listener of listeners) listener(s);
}

async function doBoot(chapter: string): Promise<Boot> {
  const [tool, ref] = await Promise.all([fetch("./ws.py"), fetch("./ref.bundle")]);
  if (!tool.ok || !ref.ok) throw new Error(`the page's ws.py / ref.bundle: HTTP ${String(tool.status)} / ${String(ref.status)}`);
  await makeDir("_blogs");
  await Promise.all([writeText(TOOL, await tool.text()), writeBytes(REF, new Uint8Array(await ref.arrayBuffer()))]);
  const boot = parseBoot(await wsJson(["boot", chapter, "--ref", REF]));
  if (boot.status.chapter !== chapter) throw new Error(`ws.py booted ${boot.status.chapter}, not ${chapter}`);
  document.documentElement.dataset["workspaceBoot"] = `${boot.created} ${String(boot.ms)}ms`; // for debugging and verify_workspace.py
  publish(boot.status);
  return boot;
}

// The workspace for this attach (booted once; every cell on the page awaits the same promise).
export function bootWorkspace(chapter: string): Promise<Boot> {
  booting ??= doBoot(chapter);
  booting.catch(() => { booting = undefined; }); // a failed boot can be retried by the next caller
  return booting;
}
onKernelState((state) => { if (state === "off" || state === "lost") { booting = undefined; current = undefined; } });

export async function refreshStatus(chapter: string): Promise<WorkspaceStatus> {
  const s = parseStatus(await wsJson(["status", chapter]));
  publish(s);
  return s;
}

export const readFile = (file: string): Promise<string | undefined> => readText(`${DIR}/${file}`);
export const writeFile = (file: string, text: string): Promise<void> => writeText(`${DIR}/${file}`, text);

// Check one cell as a background job `id`. The command is the chapter's check fence, split on spaces
// (build_page.py allows no quoting in it).
export function checkCell(id: string, chapter: string, cell: string, command: string, onOutput: (text: string) => void): Promise<JobResult> {
  return runJob(id, ["@python", TOOL, "check", chapter, cell, "--", ...command.trim().split(/\s+/)], ".", onOutput);
}

export const stopCheck = (id: string): Promise<void> => killJob(id);
