/**
 * The /runs index. Parsed at the boundary like everything else.
 *
 * Readers come from core/fields.ts so this boundary, the server's index writer
 * and the line parser agree on what a missing field means. RunsError stays the
 * error type callers catch; FieldError is rewrapped into it.
 */

import { FieldError, isRecord, optionalBoolean, optionalNumber, optionalString, requireString } from "../core/fields.ts";

export interface RunSummary {
  readonly file: string;
  readonly runId: string | null;
  readonly runName: string | null;
  /** null when the producer could not ask git — a real fact, not a default. */
  readonly gitSha: string | null;
  readonly gitDirty: boolean | null;
  readonly startedTs: number | null;
  readonly sizeBytes: number;
  /** Set when the server could not read this run's header. Row still listed. */
  readonly error: string | null;
}

export class RunsError extends Error {}

/**
 * Every field but `file` is optional here by design: the server omits what it
 * could not read, and an unreadable run still gets a row so it shows up in the
 * picker. `git_sha`/`git_dirty` may now also arrive as explicit JSON null from
 * a producer with no git — `optional*` reads absent and null the same way,
 * which is exactly right for a field that means "unavailable" either way.
 */
export function parseRuns(payload: unknown): RunSummary[] {
  if (!Array.isArray(payload)) {
    throw new RunsError("GET /runs did not return an array");
  }
  return payload.map((entry, index) => {
    const ctx = `/runs[${String(index)}]`;
    if (!isRecord(entry)) {
      throw new RunsError(`${ctx} is not an object`);
    }
    try {
      return {
        file: requireString(entry, "file", ctx),
        runId: optionalString(entry, "run_id", ctx),
        runName: optionalString(entry, "run_name", ctx),
        gitSha: optionalString(entry, "git_sha", ctx),
        gitDirty: optionalBoolean(entry, "git_dirty", ctx),
        startedTs: optionalNumber(entry, "started_ts", ctx),
        sizeBytes: optionalNumber(entry, "size_bytes", ctx) ?? 0,
        error: optionalString(entry, "error", ctx),
      };
    } catch (cause) {
      if (cause instanceof FieldError) throw new RunsError(cause.message);
      throw cause;
    }
  });
}

export async function fetchRuns(): Promise<RunSummary[]> {
  const res = await fetch("/runs", { headers: { "Cache-Control": "no-store" } });
  if (!res.ok) {
    throw new RunsError(`GET /runs failed: HTTP ${String(res.status)}`);
  }
  return parseRuns(await res.json());
}

/**
 * The first run worth opening: newest-started (the server sorts) with a
 * readable header.
 *
 * A run whose header would not parse carries `error` and is deliberately NOT
 * auto-selected — selecting it renders an empty dashboard and hides the reason.
 * It stays in the picker so it can be opened on purpose, and App shows the
 * error rows instead. `null` means every run is broken, which is a state the
 * UI must show rather than paper over.
 */
export function defaultRun(runs: readonly RunSummary[]): string | null {
  return runs.find((run) => run.error === null)?.file ?? null;
}

export function runLabel(run: RunSummary): string {
  const name = run.runName ?? run.runId ?? run.file;
  const sha = run.gitSha === null ? "" : ` · ${run.gitSha}${run.gitDirty === true ? "*" : ""}`;
  return `${name}${sha}`;
}
