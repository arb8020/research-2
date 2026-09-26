/**
 * The logs drawer. Right-side slide-in; the raw event log lives here and
 * nowhere else (DESIGN.md "Register": logs are never on the landing surface).
 *
 * Opened by the top-bar "logs" button or the `l` key, closed by Esc or a click
 * outside. The panel is kept mounted so RawTable's scroll position, kind chips
 * and follow-tail survive a close/open — remounting would also throw away its
 * window arithmetic mid-stream.
 *
 * Motion (animations.md): transform/opacity only, ease-out, 300ms in and 240ms
 * out (exits ~20% faster). Transitions, not keyframes, so a fast l-Esc-l
 * retargets instead of restarting.
 *
 * Focus moves INTO the drawer on open and back out on close. The panel is a
 * `role="dialog"` and stays mounted while closed (so RawTable keeps its
 * scroll), which means without this the keyboard user pressing `l` gets a
 * dialog they cannot reach and a Tab order that still walks the page behind it.
 * The element that opened it is remembered and restored, so `l`-Esc leaves the
 * caret where it was.
 */

import { useEffect, useRef } from "react";
import type { Event } from "../core/events.ts";
import type { LogMode } from "./eventlines.ts";
import { LOG_MODES } from "./eventlines.ts";
import { RawTable } from "./RawTable.tsx";
import "./logsdrawer.css";

interface LogsDrawerProps {
  readonly open: boolean;
  readonly onClose: () => void;
  readonly mode: LogMode;
  readonly onMode: (mode: LogMode) => void;
  readonly events: readonly Event[];
  readonly revision: number;
}

export function LogsDrawer({
  open,
  onClose,
  mode,
  onMode,
  events,
  revision,
}: LogsDrawerProps): React.JSX.Element {
  const panelRef = useRef<HTMLDivElement | null>(null);
  /** What had focus when the drawer opened, so closing can give it back. */
  const restoreRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const panel = panelRef.current;
    if (panel === null) return;
    if (!open) {
      const restore = restoreRef.current;
      restoreRef.current = null;
      // Only take focus back if the drawer still holds it: a close triggered by
      // clicking something else must not yank focus off what was clicked.
      if (restore !== null && panel.contains(document.activeElement)) {
        restore.focus();
      }
      return;
    }
    const active = document.activeElement;
    restoreRef.current = active instanceof HTMLElement ? active : null;
    // The first focusable INSIDE the drawer. `inert` was just lifted by the
    // render, so these are reachable now.
    const first = panel.querySelector<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    );
    (first ?? panel).focus();
  }, [open]);

  // Esc and click-outside. Both only exist while open, so a closed drawer
  // costs no listeners and does not swallow Esc from anything else.
  useEffect(() => {
    if (!open) return;
    function onKey(event: KeyboardEvent): void {
      if (event.key === "Escape") onClose();
    }
    function onPointerDown(event: MouseEvent): void {
      const panel = panelRef.current;
      if (panel === null) return;
      if (event.target instanceof Node && panel.contains(event.target)) return;
      onClose();
    }
    window.addEventListener("keydown", onKey);
    // Capture: a click-outside must win before any app handler re-focuses.
    window.addEventListener("mousedown", onPointerDown, true);
    return (): void => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onPointerDown, true);
    };
  }, [open, onClose]);

  return (
    <aside
      className="logs-drawer"
      data-open={open ? "true" : "false"}
      aria-hidden={open ? undefined : "true"}
      // Inert while closed: the offscreen panel must not be tabbable, and the
      // hidden RawTable's chips must not be clickable through the page.
      inert={!open}
    >
      {/* `tabIndex={-1}` so the panel itself can take focus when it contains
          nothing focusable — programmatic focus only, never in the Tab order. */}
      <div
        className="logs-panel"
        ref={panelRef}
        role="dialog"
        aria-label="logs"
        tabIndex={-1}
      >
        <header className="logs-panel-header">
          <h2 className="logs-title">logs</h2>
          <div className="mode-toggle" role="group" aria-label="log mode">
            {LOG_MODES.map((candidate) => (
              <button
                key={candidate}
                type="button"
                className="mode-button"
                aria-pressed={mode === candidate}
                onClick={(): void => {
                  onMode(candidate);
                }}
              >
                {candidate}
              </button>
            ))}
          </div>
          <button
            type="button"
            className="logs-close"
            aria-label="close logs"
            onClick={onClose}
          >
            esc
          </button>
        </header>
        <RawTable events={events} revision={revision} mode={mode} />
      </div>
    </aside>
  );
}
