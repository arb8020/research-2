/**
 * The store. The ONLY module that knows runs live in a directory of JSONL files.
 *
 * Everything above this file talks in terms of run names, header bytes and byte
 * ranges. Swap this module to put runs in S3 or a database; nothing else moves.
 */

import { readdir, stat } from "node:fs/promises";
import { open } from "node:fs/promises";
import { isAbsolute, resolve, sep } from "node:path";

export const JSONL_SUFFIX = ".jsonl";

/**
 * A first line longer than this is not a run header — refuse to read an
 * unbounded amount of a possibly-huge file (mirrors serve.py's bound).
 */
export const MAX_HEADER_BYTES = 1_000_000;

export interface RunFile {
  /** Bare file name, e.g. "alpha.jsonl". This is the id in every URL. */
  readonly file: string;
  readonly path: string;
  readonly sizeBytes: number;
}

/** A byte range opened for streaming: the body plus the facts the caller needs. */
export type OpenedRange =
  | { readonly kind: "slice"; readonly body: Blob; readonly start: number; readonly size: number }
  /** Start is at or past EOF: the caller owes a 416 with `bytes * /size`. */
  | { readonly kind: "unsatisfiable"; readonly size: number };

function isInside(dir: string, candidate: string): boolean {
  return candidate === dir || candidate.startsWith(dir.endsWith(sep) ? dir : dir + sep);
}

/**
 * Resolve one run file inside `dir`, or null when it escapes / is missing / is
 * not a .jsonl. Traversal guard: the resolved path must be inside `dir`.
 */
export async function resolveRun(dir: string, file: string): Promise<RunFile | null> {
  if (!isAbsolute(dir)) throw new Error(`store dir must be absolute, got ${dir}`);
  if (!file.endsWith(JSONL_SUFFIX)) return null;
  const path = resolve(dir, file);
  if (!isInside(dir, path)) return null;
  const info = await stat(path).catch(() => null);
  if (!info?.isFile()) return null;
  return { file, path, sizeBytes: info.size };
}

/** Every run in the store, sorted by file name. */
export async function listRuns(dir: string): Promise<RunFile[]> {
  if (!isAbsolute(dir)) throw new Error(`store dir must be absolute, got ${dir}`);
  const names = await readdir(dir);
  const jsonl = names.filter((n) => n.endsWith(JSONL_SUFFIX)).sort();
  const runs: RunFile[] = [];
  for (const file of jsonl) {
    const info = await stat(resolve(dir, file)).catch(() => null);
    if (!info?.isFile()) continue;
    runs.push({ file, path: resolve(dir, file), sizeBytes: info.size });
  }
  return runs;
}

/**
 * The first line of a run file and nothing more. Never reads the whole file:
 * reads at most MAX_HEADER_BYTES and stops at the first newline.
 */
export async function readHead(path: string): Promise<string> {
  const fh = await open(path, "r");
  try {
    const buf = Buffer.alloc(MAX_HEADER_BYTES);
    const { bytesRead } = await fh.read(buf, 0, MAX_HEADER_BYTES, 0);
    const chunk = buf.subarray(0, bytesRead);
    const nl = chunk.indexOf(0x0a);
    return (nl === -1 ? chunk : chunk.subarray(0, nl)).toString("utf8");
  } finally {
    await fh.close();
  }
}

/**
 * Open `[start, EOF)` of a run file as a lazy slice. Size is re-read here so an
 * append that landed since listing is visible, and so the 416 boundary and the
 * Content-Range we report describe the same snapshot.
 */
export function openRange(path: string, start: number): OpenedRange {
  const file = Bun.file(path);
  const size = file.size;
  if (start >= size) return { kind: "unsatisfiable", size };
  return { kind: "slice", body: file.slice(start), start, size };
}

/** The whole run file as a lazy body. */
export function openWhole(path: string): { readonly body: Blob; readonly size: number } {
  const file = Bun.file(path);
  return { body: file.slice(0), size: file.size };
}
