/**
 * Which attr keys are constant across a whole run.
 *
 * `setup_logging` stamps `static_fields` — run_id, run_name, git_sha, git_dirty —
 * onto every line (DESIGN.md), and the raw table wants them out of the way: they
 * are identical on every row, so they crowd out the attrs that actually differ.
 *
 * The raw table used to hide them by NAME, with a hardcoded
 * `new Set(["run_id", "run_name", "git_sha", "git_dirty"])`. That is the wrong
 * shape twice over. It hardcodes knowledge of the producer's static fields into
 * the UI, so a run stamped with a different set gets the wrong columns hidden;
 * and it is a lie the moment a "static" field is not static — a resumed run that
 * changes git_sha mid-file would still have it hidden, concealing the one fact
 * worth seeing.
 *
 * So the property is computed from the data instead: a key is run-constant when
 * every event that carries it carries the SAME value. No names appear anywhere
 * in this module.
 *
 * Monotonicity is the point. The set only ever shrinks as events arrive, so a
 * key that varies leaves and never returns — which is what makes the
 * incremental form below equal to the pure form over the same events, and what
 * makes it safe to fold a streaming log in batch by batch.
 */

import type { Attrs, AttrValue, Event } from "./events.ts";

/** The object case of `AttrValue`, named so the predicates can narrow to it. */
type AttrObject = Readonly<Record<string, AttrValue>>;

/**
 * A key's observed value, plus whether it has ever disagreed with itself.
 *
 * Keeping the first value is what lets a later event disqualify the key. Once
 * `varied` is true the value is dead weight, but dropping the entry entirely
 * would make the key look unseen and let it re-enter the set.
 */
interface Observed {
  readonly value: AttrValue;
  varied: boolean;
  /** How many events carried this key. Must equal `count` to be constant. */
  seenOn: number;
}

/**
 * Retained state for the incremental form. Opaque by intent: callers create it,
 * feed it, and read the set — they do not reach inside.
 */
export interface RunConstants {
  readonly seen: Map<string, Observed>;
  /** Events folded in so far. A key present on fewer events is not constant. */
  count: number;
}

export function createRunConstants(): RunConstants {
  return { seen: new Map<string, Observed>(), count: 0 };
}

/**
 * Structural equality over attr values.
 *
 * Attrs are JSON, so two values mean the same thing exactly when they serialise
 * the same way. Object key ORDER can differ between lines for the same logical
 * value, so the comparison is structural rather than a JSON.stringify of each
 * side — otherwise `{a:1,b:2}` and `{b:2,a:1}` would read as a variation and
 * silently unhide the key.
 */
/**
 * `Array.isArray` does not narrow a `readonly AttrValue[]` out of a union, so
 * the negative case needs its own predicate. Validate-then-narrow, no `as`.
 */
function isAttrArray(value: AttrValue): value is readonly AttrValue[] {
  return Array.isArray(value);
}

function isAttrObject(value: AttrValue): value is AttrObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function sameValue(a: AttrValue, b: AttrValue): boolean {
  if (a === b) return true;
  if (a === null || b === null) return false;
  // Narrow each side on its own: TS does not propagate a check on `a` to `b`,
  // and an array is never structurally equal to an object anyway.
  if (isAttrArray(a)) return isAttrArray(b) && sameArray(a, b);
  if (isAttrObject(a)) return isAttrObject(b) && sameObject(a, b);
  return false;
}

function sameArray(a: readonly AttrValue[], b: readonly AttrValue[]): boolean {
  if (a.length !== b.length) return false;
  return a.every((item, index) => sameValue(item, b[index] ?? null));
}

function sameObject(a: AttrObject, b: AttrObject): boolean {
  const aKeys = Object.keys(a);
  if (aKeys.length !== Object.keys(b).length) return false;
  return aKeys.every((key) => key in b && sameValue(a[key] ?? null, b[key] ?? null));
}

/** Fold one event's attrs into the retained state. */
function observe(state: RunConstants, attrs: Attrs): void {
  state.count += 1;
  for (const [key, value] of Object.entries(attrs)) {
    const prior = state.seen.get(key);
    if (prior === undefined) {
      // First sighting. A key that appears for the first time on a LATER event
      // cannot be run-constant — earlier events lacked it — and the
      // appears-on-every-event check in `constantKeys` is what catches that.
      state.seen.set(key, { value, varied: false, seenOn: 1 });
      continue;
    }
    prior.seenOn += 1;
    if (prior.varied) continue;
    if (!sameValue(prior.value, value)) prior.varied = true;
  }
}

/**
 * The keys that are constant across every event folded in so far.
 *
 * A key qualifies only if it never varied AND it appeared on every event: a key
 * present on half the lines is a distinguishing attr, not a run constant, even
 * though the half that carries it agrees.
 */
function constantKeys(state: RunConstants): Set<string> {
  const keys = new Set<string>();
  for (const [key, observed] of state.seen) {
    if (observed.varied) continue;
    if (observed.seenOn !== state.count) continue;
    keys.add(key);
  }
  return keys;
}

/**
 * Fold `events` into `state` and return the current run-constant key set.
 *
 * Incremental: the cost is proportional to the attrs in `events`, not to the
 * whole log, so the poll path can call it with each delivered batch.
 */
export function extendRunConstants(
  state: RunConstants,
  events: readonly Event[],
): Set<string> {
  for (const event of events) {
    observe(state, event.attrs);
  }
  return constantKeys(state);
}

/**
 * The run-constant attr keys of a whole event log.
 *
 * The pure, one-shot form — equal by construction to folding the same events in
 * any sequence of batches, which is the property the tests pin.
 */
export function runConstants(events: readonly Event[]): Set<string> {
  const state = createRunConstants();
  return extendRunConstants(state, events);
}
