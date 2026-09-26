/**
 * The test that catches the gray screen.
 *
 * The bug had two halves. The server sorts /runs newest-started first and puts
 * runs whose header will not parse LAST; App then selected
 * `runs[runs.length - 1]`, so on any real runs/ directory it opened the OLDEST
 * run — and if anything unparseable was sitting in the directory, it opened
 * THAT, tailed a file it could not read, and rendered an empty page with the
 * reason invisible.
 *
 * Nothing caught it because there was no DOM test: vitest ran `src/**\/*.test.ts`
 * in a node environment, so no test had ever mounted <App/>. This one mounts it
 * against a stubbed /runs and a stubbed run file and asserts what a human would
 * have noticed immediately — the right run is selected, its name is in the
 * heading, its rows are on screen, the view slot exists, and the console is
 * clean.
 */

// @vitest-environment jsdom

import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App.tsx";

/**
 * Three golden lines: a log, a metric, a metric. Enough to fill the raw table
 * and give the metrics view a series to chart.
 */
const LINES = [
  '{"ts": 1789669021.9, "kind": "log", "level": "INFO", "event": "run_start", "logger": "robots.train", "run_id": "sliceproof", "run_name": "slice-proof", "git_sha": "0000000", "git_dirty": false}',
  '{"ts": 1789669022.5, "kind": "metric", "name": "wm_loss", "value": 1.5, "step": 1, "run_id": "sliceproof", "run_name": "slice-proof"}',
  '{"ts": 1789669023.5, "kind": "metric", "name": "wm_loss", "value": 1.1, "step": 2, "run_id": "sliceproof", "run_name": "slice-proof"}',
];
const BODY = `${LINES.join("\n")}\n`;

/** newest-first, exactly as server/index.ts sorts: newest, older, then broken. */
const RUNS = [
  {
    file: "slice-proof.jsonl",
    size_bytes: BODY.length,
    started_ts: 1789669021.9,
    run_id: "sliceproof",
    run_name: "slice-proof",
    git_sha: "0000000",
    git_dirty: false,
  },
  {
    file: "older.jsonl",
    size_bytes: 120,
    started_ts: 1689669021.9,
    run_id: "olderrun",
    run_name: "older-run",
    git_sha: "1111111",
    git_dirty: false,
  },
  {
    file: "truncated.jsonl",
    size_bytes: 9,
    error: "bad first line: Unexpected end of JSON input",
  },
];

/** The url a fetch argument names. App only ever passes a string, but the
 * signature admits Request and URL, and `Request.toString()` is useless. */
function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.href;
  return input.url;
}

let errors: unknown[][];

beforeEach(() => {
  errors = [];
  vi.spyOn(console, "error").mockImplementation((...args: unknown[]) => {
    errors.push(args);
  });

  // The run file is served whole (a 200, no Range honoured), which is the
  // simplest honest server: the tailer's first poll has no cursor anyway.
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL): Promise<Response> => {
      const url = requestUrl(input);
      if (url.startsWith("/runs/")) {
        return Promise.resolve(
          new Response(BODY, {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      if (url.startsWith("/runs")) {
        return Promise.resolve(Response.json(RUNS));
      }
      throw new Error(`unexpected fetch: ${url}`);
    }),
  );

  // jsdom implements neither of these. They are pure environment gaps, not
  // product behaviour: the chart only needs the observer to exist, and every
  // element in jsdom measures 0x0 so no geometry is asserted here anyway.
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe(): void {
        // no layout in jsdom, so nothing ever fires
      }
      unobserve(): void {
        /* no-op */
      }
      disconnect(): void {
        /* no-op */
      }
    },
  );

  // jsdom has no rAF worth waiting on here; flush the tailer's batch immediately.
  vi.stubGlobal("requestAnimationFrame", (cb: () => void): number => {
    cb();
    return 0;
  });

  // jsdom has no matchMedia. "system" must resolve to something, and light is
  // the base theme, so a stub that reports "not dark" is the honest default.
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: false,
      media: query,
      addEventListener: (): void => undefined,
      removeEventListener: (): void => undefined,
    })),
  );

  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("App", () => {
  it("opens the newest readable run and renders its events", async () => {
    render(<App />);

    // The picker landed on the NEWEST run, not the last row of the array and
    // not the unparseable one. This assertion alone is the regression test.
    const picker = await waitFor(() => {
      const el = document.querySelector("select.run-picker");
      if (el === null) throw new Error("run picker not rendered");
      return el;
    });
    expect(picker).toBeInstanceOf(HTMLSelectElement);
    if (!(picker instanceof HTMLSelectElement)) return;
    expect(picker.value).toBe("slice-proof.jsonl");

    // The heading names that run, so a human can see which one is open.
    await waitFor(() => {
      const h1 = document.querySelector("h1");
      expect(h1?.textContent).toContain("slice-proof");
    });

    // The landing surface is a figure: the raw log is in the drawer, which is
    // closed, so nothing on screen is a table of events.
    expect(document.querySelector(".logs-drawer")?.getAttribute("data-open")).toBe(
      "false",
    );

    // Open it — the button, then the rows. All three lines parsed and reached
    // the table, which is the half of the bug that produced a blank page.
    const logsButton = screen.getByRole("button", { name: "logs" });
    act(() => {
      logsButton.click();
    });
    expect(document.querySelector(".logs-drawer")?.getAttribute("data-open")).toBe(
      "true",
    );
    await waitFor(() => {
      expect(document.querySelectorAll(".raw-row")).toHaveLength(LINES.length);
    });

    // Every discovered view was mounted exactly once, in its own slot. The
    // slot count is asserted rather than a view name: which views exist is
    // views/' business, and the landing surface is "the discovered views".
    const slots = document.querySelectorAll(".view-slot");
    expect(slots.length).toBeGreaterThan(0);
    for (const slot of slots) {
      expect(slot.getAttribute("data-view")).not.toBeNull();
    }

    // And nothing complained on the way. A React key warning or an unhandled
    // parse error here would mean the page only LOOKS right.
    expect(errors).toEqual([]);
  });

  it("renders NO view slots when nothing is selected", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL): Promise<Response> => {
        const url = requestUrl(input);
        if (url.startsWith("/runs/")) {
          throw new Error(`must not tail an unreadable run: ${url}`);
        }
        return Promise.resolve(Response.json([RUNS[2]]));
      }),
    );

    render(<App />);

    await waitFor(() => {
      expect(document.querySelector("select.run-picker")).not.toBeNull();
    });
    // A view is mounted to look at a run. With nothing open there is no slot at
    // all, rather than a slot holding a view's "no run selected" empty state —
    // which is why `mount(el, ctx)` can require its ctx.
    expect(document.querySelectorAll(".view-slot")).toHaveLength(0);
    expect(document.querySelector(".surface")).toBeNull();
    expect(errors).toEqual([]);
  });

  it("selects nothing and shows the error rows when every run is broken", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL): Promise<Response> => {
        const url = requestUrl(input);
        if (url.startsWith("/runs/")) {
          throw new Error(`must not tail an unreadable run: ${url}`);
        }
        return Promise.resolve(Response.json([RUNS[2]]));
      }),
    );

    render(<App />);

    // The picker exists (the broken run is still listed, on purpose) but
    // nothing is selected, so no unreadable file is tailed.
    const picker = await waitFor(() => {
      const el = document.querySelector("select.run-picker");
      if (el === null) throw new Error("run picker not rendered");
      return el;
    });
    if (!(picker instanceof HTMLSelectElement)) throw new Error("not a select");
    expect(picker.value).toBe("");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("observe");
    // And the page says WHY nothing is open, instead of going quietly gray —
    // as a toast, not a banner on the figure.
    const shown = await waitFor(() => {
      const toast = document.querySelector(".toast");
      if (toast === null) throw new Error("no toast");
      return toast;
    });
    expect(shown.getAttribute("data-kind")).toBe("error");
    expect(shown.textContent).toContain("truncated.jsonl");
    expect(shown.textContent).toContain("Unexpected end of JSON input");
    expect(errors).toEqual([]);
  });
});

describe("the register", () => {
  it("keeps the raw log off the landing surface until the drawer opens", async () => {
    render(<App />);

    await waitFor(() => {
      expect(document.querySelector("select.run-picker")).not.toBeNull();
    });

    // Closed by default, and no event row anywhere reachable.
    const drawer = document.querySelector(".logs-drawer");
    expect(drawer?.getAttribute("data-open")).toBe("false");
    expect(drawer?.getAttribute("aria-hidden")).toBe("true");

    // `l` is the shortcut. No transition is asserted — jsdom has no layout and
    // the open state is a data attribute, which is the honest thing to test.
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "l" }));
    });
    expect(document.querySelector(".logs-drawer")?.getAttribute("data-open")).toBe(
      "true",
    );
    await waitFor(() => {
      expect(document.querySelectorAll(".raw-row").length).toBeGreaterThan(0);
    });

    // Esc closes it.
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    expect(document.querySelector(".logs-drawer")?.getAttribute("data-open")).toBe(
      "false",
    );
    expect(errors).toEqual([]);
  });

  it("toasts a WARNING log event, naming it", async () => {
    const runStart: string = LINES[0] ?? "";
    const withWarning = [
      runStart,
      '{"ts": 1789669024.0, "kind": "log", "level": "WARNING", "event": "grad_clip_hit", "logger": "robots.train", "norm": 42.5, "run_id": "sliceproof", "run_name": "slice-proof"}',
    ].join("\n");
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL): Promise<Response> => {
        const url = requestUrl(input);
        if (url.startsWith("/runs/")) {
          return Promise.resolve(new Response(`${withWarning}\n`, { status: 200 }));
        }
        return Promise.resolve(Response.json([RUNS[0]]));
      }),
    );

    render(<App />);

    const toast = await waitFor(() => {
      const el = document.querySelector(".toast");
      if (el === null) throw new Error("no toast");
      return el;
    });
    // level, event name, and the attr that made it interesting.
    expect(toast.textContent).toContain("WARNING");
    expect(toast.textContent).toContain("grad_clip_hit");
    expect(toast.textContent).toContain("norm=42.5");
    expect(toast.getAttribute("data-kind")).toBe("warning");
    expect(errors).toEqual([]);
  });

  it("toasts a parse error instead of rendering a banner", async () => {
    const runStartLine: string = LINES[0] ?? "";
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL): Promise<Response> => {
        const url = requestUrl(input);
        if (url.startsWith("/runs/")) {
          // Valid JSON, unknown kind: parse must throw, not skip.
          return Promise.resolve(
            new Response(`${runStartLine}\n{"ts": 1.0, "kind": "nope"}\n`, {
              status: 200,
            }),
          );
        }
        return Promise.resolve(Response.json([RUNS[0]]));
      }),
    );

    render(<App />);

    const toast = await waitFor(() => {
      const el = document.querySelector(".toast[data-kind=\"error\"]");
      if (el === null) throw new Error("no error toast");
      return el;
    });
    expect(toast.textContent).toContain("nope");
    // The banner it replaced is gone for good.
    expect(document.querySelector(".app-error")).toBeNull();
    expect(errors).toEqual([]);
  });
});

describe("theming", () => {
  /** The theme <select> in the top bar. */
  async function picker(): Promise<HTMLSelectElement> {
    return waitFor(() => {
      const el = document.querySelector("select.theme-picker");
      if (!(el instanceof HTMLSelectElement)) throw new Error("no theme picker");
      return el;
    });
  }

  it("offers System, Paper and Paper dark, and stamps the resolved name", async () => {
    render(<App />);
    const select = await picker();
    expect([...select.options].map((o) => o.value)).toEqual([
      "system",
      "paper",
      "paper-dark",
    ]);
    // Always stamped, even for "system": the resolved theme is one attribute
    // read away, for a test and for the Vega config.
    expect(select.value).toBe("system");
    await waitFor(() => {
      expect(document.documentElement.getAttribute("data-theme")).toBe("paper");
    });
  });

  it("re-mounts the view slots when the theme changes, so the charts re-embed", async () => {
    render(<App />);
    // Wait for a slot to exist (a run is open).
    const before = await waitFor(() => {
      const slot = document.querySelector(".view-slot");
      if (slot === null) throw new Error("no view slot");
      return slot;
    });
    const viewNode = await waitFor(() => {
      const node = before.querySelector(".panels-view");
      if (node === null) throw new Error("panels view not mounted");
      return node;
    });
    const select = await picker();

    act(() => {
      select.value = "paper-dark";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });

    await waitFor(() => {
      expect(document.documentElement.getAttribute("data-theme")).toBe("paper-dark");
    });
    // The remount itself: the host element is React's and survives, but the
    // view's own subtree is torn down and rebuilt, so the node the view created
    // is a DIFFERENT node afterwards. (The mount-count form of this assertion
    // is in ViewSlot.test.tsx, against a spy view.)
    await waitFor(() => {
      const after = before.querySelector(".panels-view");
      expect(after).not.toBeNull();
      expect(after).not.toBe(viewNode);
    });
    // And exactly one: a remount that forgot to clean up leaves two.
    expect(before.querySelectorAll(".panels-view")).toHaveLength(1);
    expect(errors).toEqual([]);
  });

  it("remembers the choice across a remount", async () => {
    const first = render(<App />);
    const select = await picker();
    act(() => {
      select.value = "paper-dark";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await waitFor(() => {
      expect(window.localStorage.getItem("observe:theme")).toBe("paper-dark");
    });
    first.unmount();

    render(<App />);
    const again = await picker();
    expect(again.value).toBe("paper-dark");
    await waitFor(() => {
      expect(document.documentElement.getAttribute("data-theme")).toBe("paper-dark");
    });
  });

  it("renders fine when localStorage throws (private window)", async () => {
    // A Storage whose accessors throw, which is what a private window or
    // "block site data" actually does — it does not merely return null.
    const throwing: Storage = {
      length: 0,
      clear: (): void => {
        throw new Error("blocked");
      },
      getItem: (): string => {
        throw new Error("blocked");
      },
      key: (): string => {
        throw new Error("blocked");
      },
      removeItem: (): void => {
        throw new Error("blocked");
      },
      setItem: (): void => {
        throw new Error("blocked");
      },
    };
    vi.spyOn(window, "localStorage", "get").mockReturnValue(throwing);

    render(<App />);
    const select = await picker();
    expect(select.value).toBe("system");
    act(() => {
      select.value = "paper-dark";
      select.dispatchEvent(new Event("change", { bubbles: true }));
    });
    // The theme still applies; only the memory of it is lost.
    await waitFor(() => {
      expect(document.documentElement.getAttribute("data-theme")).toBe("paper-dark");
    });
    expect(errors).toEqual([]);
  });
});

describe("the drawer's focus", () => {
  it("moves focus into the drawer on open and restores it on close", async () => {
    render(<App />);

    const logsButton = await waitFor(() => screen.getByRole("button", { name: "logs" }));
    act(() => {
      logsButton.focus();
      logsButton.click();
    });

    const panel = document.querySelector(".logs-panel");
    if (panel === null) throw new Error("no drawer panel");
    // Focus is INSIDE the drawer: without this, `l` opens a dialog a keyboard
    // user cannot reach and Tab keeps walking the page behind it.
    await waitFor(() => {
      expect(panel.contains(document.activeElement)).toBe(true);
    });

    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    // And it comes back to the button that opened it.
    await waitFor(() => {
      expect(document.activeElement).toBe(logsButton);
    });
    expect(errors).toEqual([]);
  });
});
