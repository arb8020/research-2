/**
 * Every event, newest at the bottom. Lives in the logs drawer, never on the
 * landing surface (DESIGN.md "Register").
 *
 * Windowed by hand: the scroll container holds a fixed-height spacer and
 * renders only the visible slice, so 100k rows cost the same as 30. Row height
 * is a constant the CSS also asserts (.raw-row / .term-row height), which is
 * what makes the arithmetic — rather than measurement — sufficient.
 *
 * Two modes over the SAME events: `terminal` (one dense mono line) and `table`
 * (columns). Neither owns the filter — that is eventlines.ts, so the two modes
 * can never disagree about what is on screen.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Event, Kind } from "../core/events.ts";
import { KINDS, eventLabel } from "../core/events.ts";
import type { LogMode } from "./eventlines.ts";
import {
  formatTs,
  publishedConstants,
  summarizeAttrs,
  terminalLine,
  visibleEvents,
} from "./eventlines.ts";
import "./rawtable.css";

/** Row height per mode, in px. The CSS asserts the same numbers. */
const ROW_HEIGHT: Record<LogMode, number> = { table: 22, terminal: 18 };
const OVERSCAN = 8;

interface RawTableProps {
  /** The shared append-only log. Mutated in place upstream. */
  readonly events: readonly Event[];
  /** Number of published events — the signal that `events` has grown. */
  readonly revision: number;
  readonly mode: LogMode;
}

export function RawTable({
  events,
  revision,
  mode,
}: RawTableProps): React.JSX.Element {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [hidden, setHidden] = useState<ReadonlySet<Kind>>(new Set<Kind>());
  const [follow, setFollow] = useState(true);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(320);

  const rows = useMemo(
    () => visibleEvents(events, revision, hidden),
    [events, revision, hidden],
  );
  const constant = useMemo(
    () => publishedConstants(events, revision),
    [events, revision],
  );

  const onScroll = useCallback((): void => {
    const node = scrollRef.current;
    if (node === null) return;
    setScrollTop(node.scrollTop);
    setViewportHeight(node.clientHeight);
  }, []);

  // Follow-tail: pin to the bottom as rows arrive. This is a real DOM sync,
  // which is what useEffect is for. `mode` is a dependency because the row
  // height changed under the same scrollTop.
  useEffect(() => {
    const node = scrollRef.current;
    if (node === null || !follow) return;
    node.scrollTop = node.scrollHeight;
    setScrollTop(node.scrollTop);
    setViewportHeight(node.clientHeight);
  }, [rows.length, follow, mode]);

  const rowHeight = ROW_HEIGHT[mode];
  const total = rows.length;
  const first = Math.max(0, Math.floor(scrollTop / rowHeight) - OVERSCAN);
  const visibleCount = Math.ceil(viewportHeight / rowHeight) + OVERSCAN * 2;
  const last = Math.min(total, first + visibleCount);
  const window = rows.slice(first, last);

  function toggle(kind: Kind): void {
    setHidden((current) => {
      const next = new Set(current);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });
  }

  return (
    <section className="raw-table" data-mode={mode}>
      <header className="raw-header">
        <span className="raw-count tabular">
          {total} / {revision}
        </span>
        <div className="chips">
          {KINDS.map((kind) => (
            <button
              key={kind}
              type="button"
              className="chip"
              aria-pressed={!hidden.has(kind)}
              onClick={(): void => {
                toggle(kind);
              }}
            >
              {kind}
            </button>
          ))}
        </div>
        <label className="raw-follow">
          <input
            type="checkbox"
            checked={follow}
            onChange={(e): void => {
              setFollow(e.currentTarget.checked);
            }}
          />
          <span>follow tail</span>
        </label>
      </header>

      <div className="raw-scroll" ref={scrollRef} onScroll={onScroll}>
        {total === 0 ? (
          <p className="raw-empty">no events</p>
        ) : (
          <div
            className="raw-spacer"
            style={{ height: `${String(total * rowHeight)}px` }}
          >
            <div
              className="raw-window"
              style={{ transform: `translateY(${String(first * rowHeight)}px)` }}
            >
              {window.map((event, index) =>
                mode === "terminal" ? (
                  <div
                    className="raw-row"
                    data-kind={event.kind}
                    key={first + index}
                  >
                    {terminalLine(event, constant)}
                  </div>
                ) : (
                  <div className="raw-row" key={first + index}>
                    <span className="raw-kind" data-kind={event.kind}>
                      {event.kind}
                    </span>
                    <span className="raw-ts">{formatTs(event.ts)}</span>
                    <span className="raw-name">{eventLabel(event)}</span>
                    <span className="raw-attrs">
                      {summarizeAttrs(event, constant)}
                    </span>
                  </div>
                ),
              )}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
