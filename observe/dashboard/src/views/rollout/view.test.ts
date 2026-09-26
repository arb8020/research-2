/**
 * The rollout view's pure half: the payload boundary and the CartPole geometry.
 *
 * These run in the `core` (node) project — no DOM — which is what keeps the
 * physics-to-pixels mapping honest as arithmetic rather than as a screenshot.
 */

import { describe, expect, it } from "vitest";
import { CART_X_LIMIT, SURFACE, cartpoleFrame } from "./cartpole.ts";
import {
  actionGlyph,
  isTrajectoryError,
  parseTrajectory,
  trajectoryReturn,
} from "./view.ts";

/** A valid 3-step episode: 4 observations for 3 actions. */
const GOOD = {
  env: "CartPole-v1",
  obs: [
    [0, 0, 0, 0],
    [0.01, 0.15, -0.02, -0.21],
    [0.02, 0.34, -0.06, -0.52],
    [0.04, 0.53, -0.11, -0.84],
  ],
  actions: [1, 1, 0],
  rewards: [1, 1, 1],
};

function reasonOf(payload: unknown): string {
  const result = parseTrajectory(payload);
  if (!isTrajectoryError(result)) {
    throw new Error(`expected an error, got a trajectory for ${JSON.stringify(payload)}`);
  }
  return result.reason;
}

describe("parseTrajectory", () => {
  it("accepts a well-formed episode", () => {
    const result = parseTrajectory(GOOD);
    if (isTrajectoryError(result)) throw new Error(`unexpected error: ${result.reason}`);
    expect(result.env).toBe("CartPole-v1");
    expect(result.obs).toHaveLength(4);
    expect(result.actions).toEqual([1, 1, 0]);
    expect(trajectoryReturn(result)).toBe(3);
  });

  it("rejects a length mismatch, naming both lengths", () => {
    // obs must be actions.length + 1 — it carries the terminal observation.
    expect(reasonOf({ ...GOOD, obs: GOOD.obs.slice(0, 3) })).toMatch(
      /obs must be one longer than actions.*3 obs for 3 actions/,
    );
    expect(reasonOf({ ...GOOD, rewards: [1, 1] })).toMatch(
      /actions and rewards must be the same length, got 3 and 2/,
    );
  });

  it("rejects wrong types, naming the field and the index", () => {
    expect(reasonOf({ ...GOOD, env: 7 })).toMatch(/`env` expected a string/);
    expect(reasonOf({ ...GOOD, actions: "left" })).toMatch(
      /`actions` expected an array of numbers/,
    );
    expect(reasonOf({ ...GOOD, obs: "flat" })).toMatch(
      /`obs` expected an array of arrays/,
    );
    // The index is in the message: which observation is bad, not just "an obs".
    expect(
      reasonOf({
        ...GOOD,
        obs: [GOOD.obs[0], ["x", 0, 0, 0], GOOD.obs[2], GOOD.obs[3]],
      }),
    ).toMatch(/`obs\[1\]\[0\]` expected a finite number/);
    // NaN/Infinity do not survive a JSON round trip honestly.
    expect(reasonOf({ ...GOOD, rewards: [1, 1, Number.POSITIVE_INFINITY] })).toMatch(
      /`rewards\[2\]` expected a finite number/,
    );
  });

  it("rejects a non-object payload, saying what it got", () => {
    expect(reasonOf(null)).toBe("payload is null, expected an object");
    expect(reasonOf(7)).toBe("payload is number, expected an object");
    expect(reasonOf("x")).toBe("payload is string, expected an object");
    expect(reasonOf([1, 2])).toMatch(/expected an object/);
  });

  it("rejects an empty episode rather than drawing nothing", () => {
    expect(reasonOf({ env: "CartPole-v1", obs: [[0, 0, 0, 0]], actions: [], rewards: [] })).toBe(
      "trajectory has no steps",
    );
  });

  it("accepts a non-CartPole env — the ENV is the renderer's problem, not the parser's", () => {
    const result = parseTrajectory({
      env: "Pendulum-v1",
      obs: [
        [0, 0, 0],
        [0.1, 0.2, 0.3],
      ],
      actions: [0],
      rewards: [-1.5],
    });
    if (isTrajectoryError(result)) throw new Error(`unexpected error: ${result.reason}`);
    expect(result.env).toBe("Pendulum-v1");
  });
});

describe("cartpoleFrame", () => {
  const mid = SURFACE.width / 2;

  it("puts an upright pole at exactly zero radians", () => {
    const frame = cartpoleFrame([0, 0, 0, 0]);
    expect(frame.poleAngle).toBe(0);
    expect(frame.cartX).toBe(mid);
  });

  it("maps x = ±2.4 onto the track ends", () => {
    // The track IS the domain: the edge of the drawing is the edge of the state
    // space, so there is no hidden margin to misread.
    const left = cartpoleFrame([-CART_X_LIMIT, 0, 0, 0]).cartX;
    const right = cartpoleFrame([CART_X_LIMIT, 0, 0, 0]).cartX;
    expect(left).toBeLessThan(mid);
    expect(right).toBeGreaterThan(mid);
    // Symmetric about the middle, and spanning the full inset track.
    expect(mid - left).toBeCloseTo(right - mid, 6);
    expect(right - left).toBeCloseTo(480, 6);
  });

  it("is linear and monotonic in x", () => {
    const at = (x: number): number => cartpoleFrame([x, 0, 0, 0]).cartX;
    expect(at(1.2)).toBeCloseTo((at(0) + at(2.4)) / 2, 6);
    expect(at(-1)).toBeLessThan(at(0));
    expect(at(0)).toBeLessThan(at(1));
  });

  it("does NOT clamp x past the limit — an off-track cart is the signal", () => {
    // CartPole terminates at ±2.4, so a larger x means a different env or a
    // producer bug. Clamping would draw a legal-looking frame instead.
    expect(cartpoleFrame([5, 0, 0, 0]).cartX).toBeGreaterThan(
      cartpoleFrame([CART_X_LIMIT, 0, 0, 0]).cartX,
    );
  });

  it("passes theta through with the env's own sign convention", () => {
    expect(cartpoleFrame([0, 0, 0.2, 0]).poleAngle).toBe(0.2);
    expect(cartpoleFrame([0, 0, -0.2, 0]).poleAngle).toBe(-0.2);
  });
});

describe("actionGlyph", () => {
  it("shows CartPole's two actions as arrows and anything else as itself", () => {
    expect(actionGlyph(0)).toBe("◀");
    expect(actionGlyph(1)).toBe("▶");
    expect(actionGlyph(3)).toBe("3");
  });
});
