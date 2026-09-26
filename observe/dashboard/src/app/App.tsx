/**
 * Layout and orchestration. Core owns the column; views do not see each other.
 *
 * The landing surface is a figure, not a console (DESIGN.md "Register"): a slim
 * top bar of chrome — run picker, status, event count, logs, theme — and then
 * the discovered view slots in one column. Nothing else. The raw event log is
 * in the drawer; everything loud is a toast.
 *
 * The event log is a growing array published into state once per delivered
 * batch, not once per event: the tailer already coalesces lines into an
 * animation frame, so one network burst of 10k lines is one render. The array
 * is mutated in place and re-published by identity, which is what lets
 * ViewSlot diff against a cursor instead of re-reading the whole log.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Event } from "../core/events.ts";
import { RUN_END_EVENT } from "../core/events.ts";
import { ParseError, parseLine } from "../core/parse.ts";
import type { TailBatch, TailState } from "../core/tail.ts";
import { createTailer } from "../core/tail.ts";
import { discoverViews } from "../core/views.ts";
import type { LogMode } from "./eventlines.ts";
import { formatAttrValue } from "./eventlines.ts";
import { LogsDrawer } from "./LogsDrawer.tsx";
import type { NotifyKind } from "./notify.ts";
import { onNotify } from "./notify.ts";
import type { Toast } from "./Toasts.tsx";
import { Toasts, addToast } from "./Toasts.tsx";
import { ViewSlot } from "./ViewSlot.tsx";
import type { RunSummary } from "./runs.ts";
import { defaultRun, fetchRuns, runLabel } from "./runs.ts";
import "./app.css";

type RunsState =
  | { readonly status: "loading" }
  | { readonly status: "ready"; readonly runs: readonly RunSummary[] }
  | { readonly status: "error"; readonly reason: string };

/**
 * The theme the user asked for. `system` follows the OS; the others are the
 * named `[data-theme]` blocks in theme.css.
 *
 * `THEMES` is the picker's contents and the parse gate for the stored value, in
 * one place — a localStorage string the app no longer ships is not a theme.
 */
const THEMES = ["paper", "paper-dark"] as const;
type ThemeName = (typeof THEMES)[number];
type ThemeChoice = "system" | ThemeName;

const THEME_CHOICES: readonly ThemeChoice[] = ["system", ...THEMES];

/** Human labels for the picker. */
const THEME_LABELS: Readonly<Record<ThemeChoice, string>> = {
  system: "System",
  paper: "Paper",
  "paper-dark": "Paper dark",
};

const THEME_KEY = "observe:theme";

function isThemeChoice(value: unknown): value is ThemeChoice {
  return THEME_CHOICES.some((candidate) => candidate === value);
}

/**
 * The stored choice, or `system`.
 *
 * Wrapped because `localStorage` THROWS on access in a private window or with
 * site data blocked — not just returns null — and a dashboard that will not
 * render because it could not remember a color is worse than one that forgets.
 */
function storedTheme(): ThemeChoice {
  try {
    const raw = window.localStorage.getItem(THEME_KEY);
    return isThemeChoice(raw) ? raw : "system";
  } catch {
    return "system";
  }
}

function storeTheme(choice: ThemeChoice): void {
  try {
    window.localStorage.setItem(THEME_KEY, choice);
  } catch {
    // Render fine without persistence.
  }
}

/** The system's current preference, as one of the named themes. */
function systemTheme(): ThemeName {
  // `matchMedia` is absent in some non-browser DOMs; light is the base theme.
  if (typeof window.matchMedia !== "function") return "paper";
  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "paper-dark"
    : "paper";
}

/** Log levels that earn a toast. Anything quieter stays in the drawer. */
const LOUD_LEVELS: Readonly<Record<string, NotifyKind>> = {
  WARNING: "warning",
  ERROR: "error",
  CRITICAL: "error",
};

/** `?file=` pins a run; `?url=` tails an arbitrary static file (dev convenience). */
function initialTarget(): { file: string | null; url: string | null } {
  const params = new URLSearchParams(window.location.search);
  return { file: params.get("file"), url: params.get("url") };
}

function statusText(state: TailState): string {
  switch (state.status) {
    case "connecting":
      return "connecting";
    case "live":
      return `live · ${String(state.cursor)}B`;
    case "ended":
      return "run complete";
    case "error":
      return `error: ${state.reason}`;
    default: {
      const exhaustive: never = state;
      return exhaustive;
    }
  }
}

/** A loud log event, rendered as `level · event · key attrs`. */
function loudLogMessage(event: Extract<Event, { kind: "log" }>): string {
  const attrs = Object.entries(event.attrs)
    // run_id/run_name/git_* are stamped on EVERY line; in a toast they are
    // pure noise, so the toast carries the attrs specific to this event.
    .filter(([key]) => !key.startsWith("git_") && !key.startsWith("run_"))
    .slice(0, 4)
    .map(([key, value]) => `${key}=${formatAttrValue(value)}`)
    .join(" ");
  const head = `${event.level} · ${event.event}`;
  return attrs === "" ? head : `${head} · ${attrs}`;
}

export function App(): React.JSX.Element {
  const target = useMemo(() => initialTarget(), []);
  const views = useMemo(() => discoverViews(), []);

  const [runsState, setRunsState] = useState<RunsState>({ status: "loading" });
  const [selected, setSelected] = useState<string | null>(target.file);
  const [tailState, setTailState] = useState<TailState>({
    status: "connecting",
  });
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [logMode, setLogMode] = useState<LogMode>("terminal");
  const [theme, setTheme] = useState<ThemeChoice>(() => storedTheme());
  const [systemIsDark, setSystemIsDark] = useState<ThemeName>(() => systemTheme());
  const [toasts, setToasts] = useState<readonly Toast[]>([]);
  const toastId = useRef(0);

  const pushToast = useCallback((kind: NotifyKind, message: string): void => {
    toastId.current += 1;
    // `addToast` may not use the id (a duplicate is counted, not added); the
    // counter is monotonic either way, which is all an id has to be.
    setToasts((current) => addToast(current, { kind, message }, toastId.current));
  }, []);

  const dismissToast = useCallback((id: number): void => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  /**
   * The append-only log for one url. `events` is the live array (mutated in
   * place on the hot path) and `revision` is how many events have been
   * published, so a render is triggered by a number changing rather than by a
   * new array. `url` identifies which run the array belongs to: switching runs
   * is a fresh Log object, so nothing has to be imperatively cleared.
   */
  interface Log {
    readonly url: string;
    readonly events: Event[];
    readonly revision: number;
    /** Bumped when the tailer reset. Part of the view slots' remount key. */
    readonly generation: number;
  }
  const [log, setLog] = useState<Log | null>(null);

  // The views -> app notify channel. See notify.ts for why it is a DOM event.
  useEffect(() => onNotify(({ kind, message }) => {
    pushToast(kind, message);
  }), [pushToast]);

  // `l` opens the drawer. Not a shortcut for closing — Esc owns that, and the
  // drawer swallows keys while open (see LogsDrawer).
  useEffect(() => {
    function onKey(event: KeyboardEvent): void {
      if (event.key !== "l" || event.metaKey || event.ctrlKey || event.altKey) {
        return;
      }
      const active = document.activeElement;
      // Never steal a keystroke from a field.
      if (
        active instanceof HTMLInputElement ||
        active instanceof HTMLTextAreaElement ||
        active instanceof HTMLSelectElement
      ) {
        return;
      }
      setDrawerOpen(true);
    }
    window.addEventListener("keydown", onKey);
    return (): void => {
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  /**
   * The theme actually on screen. Never "system": that is a question, and this
   * is the answer — which is what ViewSlot needs to key its remount on.
   */
  const resolvedTheme: ThemeName = theme === "system" ? systemIsDark : theme;

  // Stamped on <html> so theme.css's `[data-theme="..."]` block wins, and
  // ALWAYS stamped (even for "system"), so the resolved theme is one attribute
  // read away for a test and for the Vega config.
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", resolvedTheme);
  }, [resolvedTheme]);

  useEffect(() => {
    storeTheme(theme);
  }, [theme]);

  // Follow the OS while the choice is "system". Subscribed unconditionally:
  // the listener is one callback, and unsubscribing on every choice change is
  // more moving parts than keeping a number up to date.
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    function onChange(): void {
      setSystemIsDark(query.matches ? "paper-dark" : "paper");
    }
    onChange();
    query.addEventListener("change", onChange);
    return (): void => {
      query.removeEventListener("change", onChange);
    };
  }, []);

  useEffect(() => {
    let live = true;
    fetchRuns()
      .then((runs) => {
        if (!live) return;
        setRunsState({ status: "ready", runs });
        // The server sorts newest-started first, so the newest READABLE run is
        // the first one without an error. `runs[runs.length - 1]` picked the
        // oldest — or, worse, an unparseable run sorted last, which rendered a
        // gray screen with the reason hidden. `null` leaves nothing selected
        // and lets the toasts below explain why.
        setSelected((current) => current ?? defaultRun(runs));
      })
      .catch((cause: unknown) => {
        if (!live) return;
        setRunsState({
          status: "error",
          reason: cause instanceof Error ? cause.message : String(cause),
        });
      });
    return (): void => {
      live = false;
    };
  }, []);

  const url =
    target.url ?? (selected === null ? null : `/runs/${encodeURIComponent(selected)}`);

  useEffect(() => {
    if (url === null) return;
    const runUrl: string = url;

    // A new run is a new log object, published on its first batch. Nothing is
    // cleared here, so the effect does no synchronous setState.
    //
    // `events` is mutated in place on the hot path, so a tailer reset truncates
    // it rather than rebinding: ViewSlot holds this same array identity and
    // diffs against a cursor. `generation` is published so the slots remount
    // (their surfaces cannot rewind) and their cursors restart at zero.
    const events: Event[] = [];
    let generation = 0;

    /** Publish this run's log. Ignored if the url has already moved on. */
    function publish(): void {
      setLog((prev) =>
        prev !== null && prev.url === runUrl && prev.events !== events
          ? prev
          : { url: runUrl, events, revision: events.length, generation },
      );
    }

    const tailer = createTailer({
      url: runUrl,
      onState: setTailState,
      onLines: (batch: TailBatch): void => {
        // The server ignored Range and resent the file from zero. Everything in
        // `events` is about to arrive again, so drop it first — appending would
        // duplicate the whole prefix.
        if (batch.kind === "reset") {
          events.length = 0;
          generation = batch.generation;
        }
        let sawRunEnd = false;
        for (const line of batch.lines) {
          try {
            const event = parseLine(line);
            events.push(event);
            if (event.kind === "log" && event.event === RUN_END_EVENT) {
              sawRunEnd = true;
            }
            // Loud log lines are the second toast feed. The event itself is
            // still in the drawer; the toast is the thing you cannot miss.
            if (event.kind === "log") {
              const kind = LOUD_LEVELS[event.level];
              if (kind !== undefined) pushToast(kind, loudLogMessage(event));
            }
          } catch (cause) {
            // A bad line is loud but not fatal to the session: the run is
            // still worth watching, so toast the error and keep tailing. This
            // replaced an inline banner, which scrolled the figure.
            pushToast(
              "error",
              cause instanceof ParseError ? cause.message : String(cause),
            );
          }
        }
        publish();
        // The tailer does not interpret events — the caller decides to stop.
        if (sawRunEnd) tailer.stop();
      },
    });
    tailer.start();
    return (): void => {
      tailer.stop();
    };
  }, [url, pushToast]);

  const onPick = useCallback((file: string): void => {
    setSelected(file);
  }, []);

  const closeDrawer = useCallback((): void => {
    setDrawerOpen(false);
  }, []);

  /** The log for the url on screen; empty until its first batch lands. */
  const current_log: Log =
    log !== null && log.url === url
      ? log
      : { url: url ?? "", events: [], revision: 0, generation: 0 };

  const current =
    runsState.status === "ready"
      ? (runsState.runs.find((run) => run.file === selected) ?? null)
      : null;

  // Runs the server could not read, and a dead /runs, are toasts too: the
  // landing surface stays a figure even when there is nothing to draw.
  useEffect(() => {
    if (runsState.status === "error") {
      pushToast("error", `/runs unavailable: ${runsState.reason}`);
    }
  }, [runsState, pushToast]);

  useEffect(() => {
    if (runsState.status !== "ready" || selected !== null) return;
    for (const run of runsState.runs) {
      if (run.error !== null) {
        pushToast("error", `${run.file}: ${run.error}`);
      }
    }
  }, [runsState, selected, pushToast]);

  return (
    <>
      <main className="app">
        {/* Top bar: chrome only. Every element here is a run picker, a status,
            or a control — see DESIGN.md's enforcement test. */}
        <header className="topbar">
          <h1 className="topbar-title">
            {current === null ? "observe" : runLabel(current)}
          </h1>
          {runsState.status === "ready" && runsState.runs.length > 0 && (
            <select
              className="run-picker"
              aria-label="run"
              value={selected ?? ""}
              onChange={(e): void => {
                onPick(e.currentTarget.value);
              }}
            >
              {/*
                A select whose `value` matches no option displays its FIRST
                option, so with nothing selected the picker would claim to be
                showing a run it is not. An explicit empty option keeps the
                control honest about "nothing open".
              */}
              {selected === null && <option value="">— no run selected —</option>}
              {runsState.runs.map((run) => (
                <option key={run.file} value={run.file}>
                  {runLabel(run)}
                </option>
              ))}
            </select>
          )}
          <span className="status-pill" data-status={tailState.status}>
            {statusText(tailState)}
          </span>
          <span className="topbar-count tabular">
            {current_log.revision} events
          </span>
          <span className="topbar-spacer" />
          <button
            type="button"
            className="topbar-button"
            aria-expanded={drawerOpen}
            title="logs (l)"
            onClick={(): void => {
              setDrawerOpen(true);
            }}
          >
            logs
          </button>
          {/* A picker, not a cycle: three states behind one button means
              reaching "paper dark" from "paper" costs two clicks and a guess
              about the order. */}
          <select
            className="theme-picker"
            aria-label="theme"
            value={theme}
            onChange={(e): void => {
              const next: unknown = e.currentTarget.value;
              if (isThemeChoice(next)) setTheme(next);
            }}
          >
            {THEME_CHOICES.map((choice) => (
              <option key={choice} value={choice}>
                {THEME_LABELS[choice]}
              </option>
            ))}
          </select>
        </header>

        {/* No run, no slots. A view is mounted to look at a run, so mounting
            one with nothing selected means every view has to carry an empty
            state that exists only because the contract allowed it (the panels
            view had exactly that). The run picker already says nothing is
            open, and the toasts say why. */}
        {selected !== null && (
          <div className="surface">
            {views.map(({ path, view }) => (
              <ViewSlot
                key={path}
                view={view}
                events={current_log.events}
                revision={current_log.revision}
                resetKey={`${current_log.url}#${String(current_log.generation)}`}
                file={selected}
                theme={resolvedTheme}
              />
            ))}
          </div>
        )}
      </main>

      <LogsDrawer
        open={drawerOpen}
        onClose={closeDrawer}
        mode={logMode}
        onMode={setLogMode}
        events={current_log.events}
        revision={current_log.revision}
      />
      <Toasts toasts={toasts} onDismiss={dismissToast} />
    </>
  );
}
