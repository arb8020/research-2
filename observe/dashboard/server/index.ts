/**
 * The /runs index: one row per run, built from each run's first line only.
 *
 * A bad header is REPORTED, never skipped — a run you cannot parse is exactly
 * the run you need to see in the picker. The row shape is the wire contract
 * consumed by src/app/runs.ts (snake_case, fields omitted when absent).
 */

import {
  isRecord,
  optionalBoolean,
  optionalNumber,
  optionalString,
} from "../src/core/fields.ts";
import { listRuns, readHead, type RunFile } from "./store.ts";

/** One row of GET /runs. snake_case because it is the wire, not the model. */
export interface RunRow {
  readonly file: string;
  readonly size_bytes: number;
  readonly run_id?: string;
  readonly run_name?: string;
  /** null, not omitted, when the producer wrote null: "we could not ask git". */
  readonly git_sha?: string | null;
  readonly git_dirty?: boolean | null;
  readonly started_ts?: number;
  readonly error?: string;
}

/** Parse one run's header into an index row. Never throws. */
export async function readRunRow(run: RunFile): Promise<RunRow> {
  const raw = await readHead(run.path);
  if (raw.trim() === "") {
    return { file: run.file, size_bytes: run.sizeBytes, error: "empty file" };
  }

  let json: unknown;
  try {
    json = JSON.parse(raw);
  } catch (cause) {
    const detail = cause instanceof Error ? cause.message : String(cause);
    return {
      file: run.file,
      size_bytes: run.sizeBytes,
      error: `bad first line: ${detail}`,
    };
  }
  if (!isRecord(json)) {
    return {
      file: run.file,
      size_bytes: run.sizeBytes,
      error: `first line is ${Array.isArray(json) ? "list" : typeof json}, expected object`,
    };
  }

  // Deliberately NOT parsed as an Event. The index's job is the run's identity
  // (who, when, which commit); validating the line as a well-formed Event is
  // the tailer's job at src/core/parse.ts, on every line including this one.
  // A header that is valid JSON but a malformed Event still belongs in the
  // picker — that is the run you most need to open.
  // Readers are core/fields.ts's `optional*`: absent and null both read as
  // null. The header is a log line whose static_fields the producer chose, so
  // every one of these may legitimately be missing.
  const startedTs = optionalNumber(json, "started_ts") ?? optionalNumber(json, "ts");
  const runId = optionalString(json, "run_id");
  const runName = optionalString(json, "run_name");
  const gitDirty = optionalBoolean(json, "git_dirty");
  const gitSha = optionalString(json, "git_sha");
  // git_sha/git_dirty are forwarded as explicit null when the producer wrote
  // null, because "provenance unavailable" is a fact the picker should be able
  // to show. Everything else is omitted when absent, as before.
  const gitPresent = "git_sha" in json || "git_dirty" in json;
  return {
    file: run.file,
    size_bytes: run.sizeBytes,
    ...(startedTs === null ? {} : { started_ts: startedTs }),
    ...(runId === null ? {} : { run_id: runId }),
    ...(runName === null ? {} : { run_name: runName }),
    ...(gitPresent ? { git_sha: gitSha, git_dirty: gitDirty } : {}),
  };
}

/** The /runs payload: newest-started first, unparseable (no started_ts) last. */
export async function indexRuns(dir: string): Promise<RunRow[]> {
  const rows = await Promise.all((await listRuns(dir)).map(readRunRow));
  return rows.sort((a, b) => {
    const at = a.started_ts;
    const bt = b.started_ts;
    if (at === undefined && bt === undefined) return 0;
    if (at === undefined) return 1;
    if (bt === undefined) return -1;
    return bt - at;
  });
}
