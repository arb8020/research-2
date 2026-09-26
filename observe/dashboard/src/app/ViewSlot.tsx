/**
 * The component <-> surface bridge. The ONLY place React touches a view.
 *
 * React owns the slot element and nothing inside it: `mount` runs exactly once
 * and the view owns its subtree from then on. Events are pushed in imperatively
 * via a cursor, so point arrays never enter React state and a 100k-event stream
 * causes no re-renders here.
 *
 * Everything the mount depends on is in the mount effect's dependency list, and
 * `exhaustive-deps` is on to keep it that way. Two of those deps earned their
 * place by being bugs:
 *
 *  - `file` — the view gets it as its `ViewContext`, and it used to be read
 *    without being depended on, on the theory that `resetKey` (the log url)
 *    encodes it. With `?url=` it does not: the url is pinned while `file`
 *    follows the run picker, so the panels view kept querying the first run
 *    forever while the chrome said otherwise.
 *  - `theme` — a Vega config is baked at embed time from the computed CSS
 *    variables (core/vega-theme.ts), so a theme flip has to re-embed. Naming
 *    the resolved theme here is what makes that a remount.
 */

import { useEffect, useRef } from "react";
import type { Event, View } from "../core/events.ts";

interface ViewSlotProps {
  readonly view: View;
  /** Append-only event log. This component reads past its own cursor. */
  readonly events: readonly Event[];
  /** Bumped by the owner whenever `events` has grown. */
  readonly revision: number;
  /** Changes when the log was replaced (e.g. a new run) — remount, don't rewind. */
  readonly resetKey: string;
  /**
   * The store file name of the run on screen, passed through as the view's
   * `ViewContext` (core/events.ts). Always a real run: when nothing is
   * selected, the owner renders no slots at all.
   */
  readonly file: string;
  /**
   * The RESOLVED theme name (never "system"). Part of the mount key: the charts
   * read their palette from CSS at embed time, so they must be rebuilt when it
   * changes.
   */
  readonly theme: string;
}

export function ViewSlot({
  view,
  events,
  revision,
  resetKey,
  file,
  theme,
}: ViewSlotProps): React.JSX.Element {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const stateRef = useRef<unknown>(null);
  const cursorRef = useRef(0);
  const accepts = view.accepts;

  /**
   * What makes this a fresh surface. One string, so the mount effect and the
   * append effect below agree on when the cursor went back to zero.
   */
  const mountKey = `${resetKey}\u0000${file}\u0000${theme}`;

  // Mount once per (view, log, file, theme). Each of those is a reason the
  // surface cannot be rewound in place, so each is a remount.
  useEffect(() => {
    const host = hostRef.current;
    if (host === null) return;
    host.replaceChildren();
    stateRef.current = view.mount(host, { file });
    cursorRef.current = 0;
    return (): void => {
      stateRef.current = null;
      host.replaceChildren();
    };
  }, [view, mountKey, file]);

  /**
   * Feed the surface everything past its cursor.
   *
   * `mountKey` is a dependency, not just `revision`: a remount resets the
   * cursor to zero, and the log it is reading did NOT change, so without this
   * the fresh surface is handed nothing at all. A finished run makes that
   * visible — no further batch ever arrives to bump `revision`, so flipping the
   * theme left every panel permanently empty. The replay is the whole log,
   * which is exactly what a surface that cannot rewind needs.
   */
  useEffect(() => {
    const state = stateRef.current;
    if (state === null) return;
    const from = cursorRef.current;
    if (events.length <= from) return;
    const fresh = events.slice(from);
    cursorRef.current = events.length;
    const filtered = fresh.filter((event) => accepts.includes(event.kind));
    if (filtered.length === 0) return;
    view.append(state, filtered);
    // `revision` is the trigger; `events` is read through it by design.
  }, [view, accepts, events, revision, mountKey]);

  return <div className="view-slot" data-view={view.name} ref={hostRef} />;
}
