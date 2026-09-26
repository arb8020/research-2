/**
 * The rollout view as a mounted surface, fed the REAL golden artifact.
 *
 * The fixture is not hand-written here: it is parsed out of
 * core/__fixtures__/golden.jsonl, so this test fails if the Python emitter's
 * artifact shape drifts from what this renderer reads. That is the whole point
 * of the golden file being cross-language.
 *
 * Runs under jsdom (`*.dom.test.ts`) because a surface owns DOM. jsdom has no
 * SVG layout, so the assertions are about elements and attributes, never about
 * measured geometry — the geometry is asserted as arithmetic in view.test.ts.
 */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Artifact } from "../../core/events.ts";
import { parseLine } from "../../core/parse.ts";
import { must } from "../../core/test-utils.ts";
import { view } from "./view.ts";

/**
 * Resolved from the vitest root, not from `import.meta.url`: under jsdom
 * `import.meta.url` is an `http://localhost/` URL, so `fileURLToPath` throws
 * "The URL must be of scheme file". The node-project tests can use the URL
 * form; a DOM test cannot.
 */
const goldenPath = resolve(
  process.cwd(),
  "src/core/__fixtures__/golden.jsonl",
);

/** The one artifact line in the golden fixture, parsed the way the app does. */
function goldenArtifact(): Artifact {
  const lines = readFileSync(goldenPath, "utf8").split("\n").filter((l) => l.trim() !== "");
  for (const line of lines) {
    const event = parseLine(line);
    if (event.kind === "artifact") return event;
  }
  throw new Error("golden.jsonl has no artifact line — regenerate it");
}

function otherMime(mime: string): Artifact {
  return {
    kind: "artifact",
    ts: 1_700_000_000,
    name: "attention",
    mime,
    payload: { anything: [1, 2, 3] },
    attrs: { step: 1 },
  };
}

function pendulum(): Artifact {
  return {
    kind: "artifact",
    ts: 1_700_000_001,
    name: "rollout",
    mime: "application/x-trajectory+json",
    payload: {
      env: "Pendulum-v1",
      obs: [
        [0, 0, 0],
        [0.1, 0.2, 0.3],
        [0.2, 0.3, 0.4],
      ],
      actions: [0, 1],
      rewards: [-1.5, -0.5],
    },
    attrs: { step: 20 },
  };
}

let host: HTMLElement;

beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
});

afterEach(() => {
  host.remove();
  vi.useRealTimers();
});

function mountView(): { state: ReturnType<typeof view.mount> } {
  return { state: view.mount(host, { file: "golden.jsonl" }) };
}

function text(selector: string): string {
  return must(must(host.querySelector(selector), selector).textContent, `${selector} text`);
}

describe("the rollout view, mounted", () => {
  it("says it is waiting before any artifact arrives", () => {
    mountView();
    expect(text(".rollout-title")).toBe("rollout · waiting for an artifact");
    // The controls are dead until there is something to play — a play button
    // that does nothing is worse than a disabled one.
    expect(must(host.querySelector<HTMLButtonElement>(".rollout-button"), "play").disabled).toBe(
      true,
    );
  });

  it("draws a cart and a pole from the golden artifact", () => {
    const { state } = mountView();
    view.append(state, [goldenArtifact()]);

    const svg = must(host.querySelector("svg.rollout-svg"), "the svg surface");
    expect(must(svg.querySelector(".rollout-cart"), "cart").tagName.toLowerCase()).toBe("rect");
    expect(must(svg.querySelector(".rollout-pole"), "pole").tagName.toLowerCase()).toBe("line");
    expect(svg.querySelector(".rollout-track")).not.toBeNull();
    // The cart is positioned, i.e. a frame was actually drawn and not just built.
    expect(
      must(svg.querySelector(".rollout-cart-group"), "cart group").getAttribute("transform"),
    ).toMatch(/^translate\(/);
  });

  it("puts the name, step and return in the header", () => {
    const { state } = mountView();
    view.append(state, [goldenArtifact()]);
    // golden.py emits 3 rewards of 1.0 at step 3.
    expect(text(".rollout-title")).toBe("rollout · step 3 · return 3");
  });

  it("scrubbing seeks the frame and moves the cart", () => {
    const { state } = mountView();
    view.append(state, [goldenArtifact()]);
    const group = must(host.querySelector(".rollout-cart-group"), "cart group");
    const first = group.getAttribute("transform");

    const scrub = must(host.querySelector<HTMLInputElement>(".rollout-scrub"), "scrub");
    expect(scrub.max).toBe("3");
    scrub.value = "3";
    scrub.dispatchEvent(new Event("input"));

    expect(group.getAttribute("transform")).not.toBe(first);
    expect(text(".rollout-readout")).toContain("step 3 / 3");
  });

  it("plays: the frame advances on the timer and the cart moves", () => {
    vi.useFakeTimers();
    const { state } = mountView();
    view.append(state, [goldenArtifact()]);
    const group = must(host.querySelector(".rollout-cart-group"), "cart group");
    const before = group.getAttribute("transform");

    must(host.querySelector<HTMLButtonElement>(".rollout-button"), "play").click();
    expect(text(".rollout-button")).toBe("pause");
    // CartPole dt is 0.02s, so one frame is 20ms at 1x.
    vi.advanceTimersByTime(20);

    expect(group.getAttribute("transform")).not.toBe(before);
    expect(text(".rollout-readout")).toContain("step 1 / 3");
  });

  it("counts an unsupported mime in the header instead of dropping it", () => {
    const { state } = mountView();
    view.append(state, [otherMime("application/x-attention+json")]);
    expect(text(".rollout-notice")).toBe("1 artifact with unsupported mime");
    // Still nothing drawable — but the panel SAYS so rather than looking idle.
    expect(host.querySelector("svg.rollout-svg")).toBeNull();
    expect(text(".rollout-title")).toBe("rollout · waiting for an artifact");

    view.append(state, [otherMime("image/png"), otherMime("application/json")]);
    expect(text(".rollout-notice")).toBe("3 artifacts with unsupported mime");
  });

  it("keeps counting unsupported mimes alongside a drawable rollout", () => {
    const { state } = mountView();
    view.append(state, [goldenArtifact(), otherMime("image/png")]);
    expect(host.querySelector("svg.rollout-svg")).not.toBeNull();
    expect(text(".rollout-notice")).toBe("1 artifact with unsupported mime");
  });

  it("is loud, not blank, for an env it has no renderer for", () => {
    const { state } = mountView();
    view.append(state, [pendulum()]);
    expect(host.querySelector("svg.rollout-svg")).toBeNull();
    expect(text(".rollout-fault")).toBe("no renderer for Pendulum-v1");
    // The obs shape is what you need to write the next renderer.
    expect(text(".rollout-fault-detail")).toContain("3 observations of 3 dims");
    expect(text(".rollout-fault-detail")).toContain("2 actions");
  });

  it("is loud, not blank, for an unparseable payload", () => {
    const { state } = mountView();
    view.append(state, [
      {
        kind: "artifact",
        ts: 1,
        name: "rollout",
        mime: "application/x-trajectory+json",
        payload: { env: "CartPole-v1", obs: [[0, 0, 0, 0]], actions: [1], rewards: [1] },
        attrs: {},
      },
    ]);
    expect(text(".rollout-fault")).toMatch(/cannot render rollout: obs must be one longer/);
    expect(text(".rollout-title")).toBe("rollout · unparseable");
  });

  it("finishes the current loop before adopting a newer artifact", () => {
    vi.useFakeTimers();
    const { state } = mountView();
    const golden = goldenArtifact();
    view.append(state, [golden]);
    must(host.querySelector<HTMLButtonElement>(".rollout-button"), "play").click();

    // A newer rollout arrives one frame in. Yanking it here would cut the
    // animation mid-stride, so it is parked.
    vi.advanceTimersByTime(20);
    const newer: Artifact = { ...golden, ts: golden.ts + 10, attrs: { step: 13 } };
    view.append(state, [newer]);
    expect(text(".rollout-title")).toBe("rollout · step 3 · return 3");

    // 3 frames to reach the terminal obs (index 3) from frame 1, then the wrap
    // tick adopts the pending artifact.
    vi.advanceTimersByTime(20 * 3);
    expect(text(".rollout-title")).toBe("rollout · step 13 · return 3");
    // And it kept playing across the switch.
    expect(text(".rollout-button")).toBe("pause");
  });

  it("switches immediately when it is NOT playing — nothing to yank", () => {
    const { state } = mountView();
    const golden = goldenArtifact();
    view.append(state, [golden]);
    view.append(state, [{ ...golden, attrs: { step: 99 } }]);
    expect(text(".rollout-title")).toBe("rollout · step 99 · return 3");
  });

  it("cycles the speed control through the offered speeds", () => {
    const { state } = mountView();
    view.append(state, [goldenArtifact()]);
    const speed = must(host.querySelector<HTMLButtonElement>(".rollout-speed"), "speed");
    expect(speed.textContent).toBe("1×");
    speed.click();
    expect(speed.textContent).toBe("4×");
    speed.click();
    expect(speed.textContent).toBe("1×");
  });

  it("accepts only artifacts, so core never hands it anything else", () => {
    expect(view.accepts).toEqual(["artifact"]);
    expect(view.name).toBe("rollout");
  });
});
