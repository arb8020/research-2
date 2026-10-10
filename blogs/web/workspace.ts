// The reader's workspace in the connected sandbox (workspace.py there; blogs/workspace.py here). Files go through the
// Contents API (connect/contents.ts); workspace.py runs on the kernel: status and boot as short cells, checks as
// background jobs.
//
//   boot    on every kernel attach: upload the page's _blogs/ (workspace.py + the trusted check code, listed in
//           _blogs/MANIFEST.sha256) and this chapter's ref bundle, then `workspace.py boot`: the repo as it is,
//           restored from the persisted bundle, or seeded from the chapter's start
//   status  pass tags -> which cells passed (and whether their file changed since), which files have drafts
//   check   `workspace.py check <chapter> <cell> --trusted <sha256>` as a job: it verifies _blogs/ and runs the
//           cell's cmd from checks/<chapter>.json; its output (JSON lines) streams to the cell that started it
import { makeDir, readText, writeBytes, writeText } from "./connect/contents";
import { killJob, onKernelState, runCode, runJob } from "./connect/kernel";
import type { JobResult } from "./connect/kernel";

const DIR = "workspace"; // workspace.py's REPO, relative to Jupyter's root (the kernel's cwd)
// Not a dot-dir: the Contents API refuses hidden paths (ContentsManager.allow_hidden is off), and its error replies
// carry no CORS headers, so the page would only see "Failed to fetch".
const STATE = "_blogs";
const TOOL = `${STATE}/workspace.py`;
const TRUST_MANIFEST = "MANIFEST.sha256";
const REF = `${STATE}/ref.bundle`;

export interface CellStatus {
  name: string;
  file: string;
  region: string | null;
  ops: string[];
  passed: boolean; // a pass/<chapter>/<cell> tag exists
  stale: boolean; // passed, but a later pass committed a different version of its file
  draft: boolean; // the workspace file differs from the latest passing version
}

export interface WorkspaceStatus {
  chapter: string;
  head: string;
  cells: CellStatus[];
  persist: { dir: string; bundleBytes: number } | null; // null: nothing outlives this sandbox
}

// seeded: a new workspace from the chapter's start. restored(-previous): from the persisted bundle (the sandbox is
// new, so drafts only this browser has may be newer than the workspace's). existing: this sandbox had it already.
export type Created = "seeded" | "restored" | "restored-previous" | "existing";
export interface Boot { created: Created; ms: number; status: WorkspaceStatus }

const isRecord = (x: unknown): x is Record<string, unknown> => typeof x === "object" && x !== null && !Array.isArray(x);
const fail = (what: string, raw: unknown): never => { throw new Error(`workspace.py: expected ${what}, got ${JSON.stringify(raw).slice(0, 300)}`); };
const isStrings = (x: unknown): x is string[] => Array.isArray(x) && x.every((s) => typeof s === "string");

function parseCell(raw: unknown): CellStatus {
  if (!isRecord(raw)) return fail("a cell status", raw);
  const { name, file, region, ops, passed, stale, draft } = raw;
  if (typeof name !== "string" || typeof file !== "string" || !(typeof region === "string" || region === null) || !isStrings(ops)
    || typeof passed !== "boolean" || typeof stale !== "boolean" || typeof draft !== "boolean") {
    return fail("{name, file, region, ops, passed, stale, draft}", raw);
  }
  return { name, file, region, ops, passed, stale, draft };
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

// `workspace.py <args>` as a short cell; its last stdout line is JSON. A failure raises in the kernel with its stderr.
async function wsJson(args: string[]): Promise<unknown> {
  const code = `import subprocess as _s, sys as _y
_r = _s.run([_y.executable, ${JSON.stringify(TOOL)}, *${JSON.stringify(args)}], capture_output=True, text=True)
if _r.returncode != 0:
    raise RuntimeError(f"workspace.py ${args[0] ?? ""} exited {_r.returncode}:\\n{_r.stdout[-2000:]}{_r.stderr[-4000:]}")
print(_r.stdout.strip().splitlines()[-1])`;
  let out = "";
  const result = await runCode(code, (t) => { out += t; });
  if (result.status === "error") throw new Error(`${result.ename}: ${result.evalue}`);
  if (result.status === "aborted") throw new Error(`workspace.py ${args[0] ?? ""}: ${result.reason}`);
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

async function fetchOk(path: string): Promise<Response> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`the page's ${path}: HTTP ${String(res.status)}`);
  return res;
}

const hex = (buf: ArrayBuffer): string => [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");

// The page's _blogs/ into the sandbox's: every file MANIFEST.sha256 lists (as served next to the page, checked
// against its line here too), then the manifest itself. `trusted` is the manifest's sha256 the build stamped on the
// cells: a page whose files don't match it (a stale cache) refuses to upload.
async function uploadTrusted(trusted: string): Promise<void> {
  const manifest = new Uint8Array(await (await fetchOk(`./${STATE}/${TRUST_MANIFEST}`)).arrayBuffer());
  const got = hex(await crypto.subtle.digest("SHA-256", manifest));
  if (got !== trusted) throw new Error(`the page's ${TRUST_MANIFEST} (sha256 ${got.slice(0, 12)}) is not the one it was built with (${trusted.slice(0, 12)}); reload`);
  const entries = new TextDecoder().decode(manifest).split("\n").filter((l) => l !== "").map((line) => {
    const [sha, path] = line.split("  ");
    if (sha?.length !== 64 || path === undefined || path === "") throw new Error(`${TRUST_MANIFEST}: bad line ${JSON.stringify(line)}`);
    return { sha, path };
  });
  const dirs = new Set<string>([STATE]);
  for (const { path } of entries) {
    const parts = path.split("/").slice(0, -1);
    for (let i = 1; i <= parts.length; i++) dirs.add(`${STATE}/${parts.slice(0, i).join("/")}`);
  }
  for (const dir of [...dirs].sort((a, b) => a.length - b.length)) await makeDir(dir); // parents first
  await Promise.all(entries.map(async ({ sha, path }) => {
    const bytes = new Uint8Array(await (await fetchOk(`./${STATE}/${path}`)).arrayBuffer());
    if (hex(await crypto.subtle.digest("SHA-256", bytes)) !== sha) throw new Error(`the page's ${STATE}/${path} doesn't match ${TRUST_MANIFEST}; reload`);
    await writeBytes(`${STATE}/${path}`, bytes);
  }));
  await writeBytes(`${STATE}/${TRUST_MANIFEST}`, manifest); // last: a half-done upload fails verification
}

async function doBoot(chapter: string, trusted: string): Promise<Boot> {
  await uploadTrusted(trusted);
  await writeBytes(REF, new Uint8Array(await (await fetchOk("./ref.bundle")).arrayBuffer()));
  const boot = parseBoot(await wsJson(["boot", chapter, "--ref", REF]));
  if (boot.status.chapter !== chapter) throw new Error(`workspace.py booted ${boot.status.chapter}, not ${chapter}`);
  document.documentElement.dataset["workspaceBoot"] = `${boot.created} ${String(boot.ms)}ms`; // for debugging and verify_workspace.py
  publish(boot.status);
  return boot;
}

// The workspace for this attach (booted once; every cell on the page awaits the same promise).
export function bootWorkspace(chapter: string, trusted: string): Promise<Boot> {
  booting ??= doBoot(chapter, trusted);
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

// Check one cell as a background job `id`: workspace.py runs the cell's cmd from the manifest (the page never names it).
export function checkCell(id: string, chapter: string, cell: string, trusted: string, onOutput: (text: string) => void): Promise<JobResult> {
  return runJob(id, ["@python", TOOL, "check", chapter, cell, "--trusted", trusted], ".", onOutput);
}

export const stopCheck = (id: string): Promise<void> => killJob(id);
