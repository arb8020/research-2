/**
 * The event vocabulary. One JSONL line == one Event.
 *
 * Discriminated on `kind`. Fixed fields per kind are lifted to named
 * properties; everything else on the line lands in `attrs`.
 *
 * Decision (see report): `static_fields` (run_id, run_name, git_sha,
 * git_dirty, logger) stay in `attrs`. They are stamped on every line by
 * `setup_logging` and are not part of any kind's required shape, so
 * lifting them would mean inventing optional fields on all three kinds
 * and make `exactOptionalPropertyTypes` painful for no gain. Consumers
 * that want them read `attrs.run_id`. `logger` is the one exception the
 * contract names as a log field, and DESIGN.md lists it inside the log
 * shape, so it is lifted on Log only.
 */

export const KINDS = ["log", "span", "metric", "artifact"] as const;

/**
 * The log event that means the run is over (DESIGN.md: "`run_end` is a `log`
 * event"). Named here because two independent places act on it — App stops the
 * tailer, the panels view stops its live poll — and two string literals of the
 * same protocol word is one rename away from a dashboard that polls forever.
 */
export const RUN_END_EVENT = "run_end";

export type Kind = (typeof KINDS)[number];

/** Any JSON value that can appear as an attr. */
export type AttrValue =
  | string
  | number
  | boolean
  | null
  | readonly AttrValue[]
  | { readonly [key: string]: AttrValue };

export type Attrs = Readonly<Record<string, AttrValue>>;

export type SpanStatus = "ok" | "error";

export interface Log {
  readonly kind: "log";
  readonly ts: number;
  readonly level: string;
  readonly event: string;
  readonly logger: string;
  readonly attrs: Attrs;
}

export interface Span {
  readonly kind: "span";
  readonly ts: number;
  readonly spanName: string;
  readonly traceId: string;
  readonly spanId: string;
  readonly parentSpanId: string | null;
  readonly startTimeUnixNano: number;
  readonly endTimeUnixNano: number;
  readonly durationMs: number;
  readonly status: SpanStatus;
  readonly attrs: Attrs;
}

export interface Metric {
  readonly kind: "metric";
  readonly ts: number;
  readonly name: string;
  readonly value: number;
  readonly attrs: Attrs;
}

/**
 * One named, typed structure a renderer draws (DESIGN.md "Artifacts").
 *
 * `payload` is `unknown` ON PURPOSE. Core does not know what a trajectory is,
 * and it must not: a renderer parses the payload at its own boundary and
 * reports its own shape errors. Typing it here would make every new artifact
 * type a change to core, and would put one renderer's schema in front of every
 * other renderer's.
 *
 * `mime` is the renderer's selector. A renderer that does not recognise a mime
 * leaves the artifact alone — and says so on screen, because silently dropping
 * data the producer went to the trouble of emitting is the failure mode this
 * whole signal exists to avoid.
 */
export interface Artifact {
  readonly kind: "artifact";
  readonly ts: number;
  readonly name: string;
  readonly mime: string;
  readonly payload: unknown;
  readonly attrs: Attrs;
}

export type Event = Log | Span | Metric | Artifact;

/**
 * Human label for an event in a table row: the log's event name, the span's
 * name, the metric's name, the artifact's name.
 */
export function eventLabel(event: Event): string {
  switch (event.kind) {
    case "log":
      return event.event;
    case "span":
      return event.spanName;
    case "metric":
      return event.name;
    case "artifact":
      return event.name;
    default: {
      const exhaustive: never = event;
      return exhaustive;
    }
  }
}

/**
 * A view is an imperative surface. Core mounts it once and feeds it
 * appended events. `State` is the view's own business; core only carries it
 * from `mount` back into `append`.
 */
export interface View<State = unknown> {
  readonly name: string;
  readonly accepts: readonly Kind[];
  mount(el: HTMLElement, ctx: ViewContext): State;
  append(state: State, events: readonly Event[]): void;
}

/**
 * What a view needs to know about the run it is looking at, beyond the events.
 *
 * Added for the panels view: a panel's SQL is `... WHERE file = '<file>'`, and
 * the file name is not derivable from any Event — the events carry `run_id` in
 * attrs, the store keys on the file name, and `/query` exposes `file`. Rather
 * than have a view guess, the mounter passes it.
 *
 * `ctx` is REQUIRED. A view is mounted to look at a run, so "mounted with no
 * run" is not a state a view has to model: when nothing is selected, the app
 * renders no slots at all. That is what killed the panels view's "no run
 * selected" branch — an empty state that only existed because the contract
 * allowed a meaningless mount.
 */
export interface ViewContext {
  /** The run's store file name, e.g. "run-1k.jsonl". */
  readonly file: string;
}
