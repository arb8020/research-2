import { makeDir, readText, writeBytes, writeText } from "./connect/contents";
import { killJob, onKernelState, runCode, runJob } from "./connect/kernel";
import type { JobResult } from "./connect/kernel";
import { isJsonObject } from "./json";

const DIR = "workspace";
const STATE = "_blogs";
const TOOL = `${STATE}/workspace.py`;
const TRUST_MANIFEST = "MANIFEST.sha256";
const REF = `${STATE}/ref.bundle`;

export interface CellStatus {
  name: string;
  file: string;
  region: string | null;
  ops: string[];
  passed: boolean;
  stale: boolean;
  draft: boolean;
}

export interface WorkspaceStatus {
  chapter: string;
  head: string;
  cells: CellStatus[];
  persist: { dir: string; bundleBytes: number } | null;
}

export type Created = "seeded" | "restored" | "restored-previous" | "existing";
export interface Boot { created: Created; ms: number; status: WorkspaceStatus }

const fail = (what: string, raw: unknown): never => { throw new Error(`workspace.py: expected ${what}, got ${JSON.stringify(raw).slice(0, 300)}`); };
const isStrings = (x: unknown): x is string[] => Array.isArray(x) && x.every((s) => typeof s === "string");

function parseCell(raw: unknown): CellStatus {
  if (!isJsonObject(raw)) return fail("a cell status", raw);
  const { name, file, region, ops, passed, stale, draft } = raw;
  if (typeof name !== "string" || typeof file !== "string" || !(typeof region === "string" || region === null) || !isStrings(ops)
    || typeof passed !== "boolean" || typeof stale !== "boolean" || typeof draft !== "boolean") {
    return fail("{name, file, region, ops, passed, stale, draft}", raw);
  }
  return { name, file, region, ops, passed, stale, draft };
}

function parseStatus(raw: unknown): WorkspaceStatus {
  if (!isJsonObject(raw) || typeof raw["chapter"] !== "string" || typeof raw["head"] !== "string" || !Array.isArray(raw["cells"])) {
    return fail("{chapter, head, cells, persist}", raw);
  }
  const p = raw["persist"];
  let persist: WorkspaceStatus["persist"] = null;
  if (p !== null) {
    if (!isJsonObject(p) || typeof p["dir"] !== "string" || typeof p["bundle_bytes"] !== "number") return fail("persist {dir, bundle_bytes} or null", p);
    persist = { dir: p["dir"], bundleBytes: p["bundle_bytes"] };
  }
  return { chapter: raw["chapter"], head: raw["head"], cells: raw["cells"].map(parseCell), persist };
}

const CREATED: readonly Created[] = ["seeded", "restored", "restored-previous", "existing"];
function parseBoot(raw: unknown): Boot {
  if (!isJsonObject(raw) || typeof raw["ms"] !== "number") return fail("{created, ms, status}", raw);
  const created = CREATED.find((c) => c === raw["created"]);
  if (created === undefined) return fail(`created in ${CREATED.join("|")}`, raw["created"]);
  return { created, ms: raw["ms"], status: parseStatus(raw["status"]) };
}

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

let booting: Promise<Boot> | undefined;
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
  const parentsFirst = [...dirs].sort((a, b) => a.length - b.length);
  for (const dir of parentsFirst) await makeDir(dir);
  await Promise.all(entries.map(async ({ sha, path }) => {
    const bytes = new Uint8Array(await (await fetchOk(`./${STATE}/${path}`)).arrayBuffer());
    if (hex(await crypto.subtle.digest("SHA-256", bytes)) !== sha) throw new Error(`the page's ${STATE}/${path} doesn't match ${TRUST_MANIFEST}; reload`);
    await writeBytes(`${STATE}/${path}`, bytes);
  }));
  await writeBytes(`${STATE}/${TRUST_MANIFEST}`, manifest);
}

async function doBoot(chapter: string, trusted: string): Promise<Boot> {
  await uploadTrusted(trusted);
  await writeBytes(REF, new Uint8Array(await (await fetchOk("./ref.bundle")).arrayBuffer()));
  const boot = parseBoot(await wsJson(["boot", chapter, "--ref", REF]));
  if (boot.status.chapter !== chapter) throw new Error(`workspace.py booted ${boot.status.chapter}, not ${chapter}`);
  document.documentElement.dataset["workspaceBoot"] = `${boot.created} ${String(boot.ms)}ms`;
  publish(boot.status);
  return boot;
}

export function bootWorkspace(chapter: string, trusted: string): Promise<Boot> {
  booting ??= doBoot(chapter, trusted);
  booting.catch(() => { booting = undefined; });
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

export function checkCell(id: string, chapter: string, cell: string, trusted: string, onOutput: (text: string) => void): Promise<JobResult> {
  return runJob(id, ["@python", TOOL, "check", chapter, cell, "--trusted", trusted], ".", onOutput);
}

export const stopCheck = (id: string): Promise<void> => killJob(id);
