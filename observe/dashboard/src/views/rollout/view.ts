/**
 * The rollout view — the first user-written view, and the first consumer of the
 * `artifact` signal.
 *
 * It plays back one episode as an animation: `artifact("rollout", {...},
 * mime="application/x-trajectory+json")` arrives on the event stream, this view
 * parses the payload at its own boundary and draws it.
 *
 * ## Why the payload is parsed HERE
 *
 * `Artifact.payload` is `unknown` in core (DESIGN.md "Artifacts"). Core does not
 * know what a trajectory is and must not: typing it there would make every new
 * artifact type a change to core, and would put this renderer's schema in front
 * of every other renderer's. So `parseTrajectory` lives in this folder, uses the
 * shared field readers, and returns a sum type rather than throwing — a
 * malformed artifact is this panel's problem to display, not the tailer's
 * problem to die on.
 *
 * ## Nothing is silently dropped
 *
 * Two things arrive that this view cannot draw, and both are COUNTED and shown:
 *
 *  - an artifact with a mime this view has no parser for -> "N artifacts with
 *    unsupported mime" in the header. The producer went to the trouble of
 *    emitting it; a blank panel is a lie about that.
 *  - a trajectory whose `env` has no surface -> a loud "no renderer for <env>"
 *    state naming the env and the raw obs shape, so you can see the data is
 *    fine and the renderer is what is missing.
 *
 * ## Switching artifacts mid-play
 *
 * A live run emits a new rollout every eval. Swapping the trajectory the instant
 * one arrives yanks the animation mid-stride, which reads as a glitch. So a
 * newer artifact is PARKED and adopted at the end of the current loop — the
 * frame you are watching always belongs to one episode.
 */

import type { Artifact, Event, View } from "../../core/events.ts";
import { FieldError, isRecord, requireString } from "../../core/fields.ts";
import type { CartpoleSurface } from "./cartpole.ts";
import {
  CARTPOLE_DT_S,
  CARTPOLE_ENV,
  createCartpoleSurface,
  cartpoleFrame,
} from "./cartpole.ts";
import "./rollout.css";

/** The mime this view renders. Anything else is counted, not drawn. */
export const TRAJECTORY_MIME = "application/x-trajectory+json";

/** CartPole's own dt, so playback runs at the speed the physics ran at. */
const FRAME_MS = CARTPOLE_DT_S * 1000;

/** The speeds offered. 1x is real time; 4x is for a 500-step episode. */
export const SPEEDS = [1, 4] as const;

/** One of the offered speeds. Typed so cycling needs no assertion. */
export type Speed = (typeof SPEEDS)[number];

/* ------------------------------------------------------------- the boundary */

/** One episode, column-oriented (DESIGN.md "Trajectory payload"). */
export interface Trajectory {
  readonly env: string;
  /** `obs.length === actions.length + 1`: the last entry is the terminal obs. */
  readonly obs: readonly (readonly number[])[];
  readonly actions: readonly number[];
  readonly rewards: readonly number[];
}

/** Why a payload is not a trajectory. Displayed, never thrown. */
export interface TrajectoryError {
  readonly kind: "error";
  readonly reason: string;
}

export type TrajectoryResult = Trajectory | TrajectoryError;

/**
 * `kind` is the discriminant, and a Trajectory has no `kind` field, so the `in`
 * check alone narrows. (An explicit `result.kind === "error"` afterwards is
 * provably true and the lint says so.)
 */
export function isTrajectoryError(result: TrajectoryResult): result is TrajectoryError {
  return "kind" in result;
}

function numbers(value: unknown, field: string): readonly number[] {
  if (!Array.isArray(value)) {
    throw new FieldError({ key: field, expected: "an array of numbers", got: value });
  }
  return value.map((item, index) => {
    if (typeof item !== "number" || !Number.isFinite(item)) {
      throw new FieldError({
        key: `${field}[${String(index)}]`,
        expected: "a finite number",
        got: item,
      });
    }
    return item;
  });
}

/**
 * `unknown` payload in, a Trajectory or a displayable reason out.
 *
 * Returns rather than throws: this is a panel's boundary, and DESIGN.md's
 * "failure is per panel, loud, in place" means a bad payload shows a reason in
 * the panel. The tailer already parsed the LINE successfully — the payload being
 * wrong is a different, narrower failure that must not take the run down.
 *
 * The length rule is checked, not assumed: `obs` is one longer than `actions`
 * and `rewards`, which are equal. A trajectory that violates it would draw a
 * frame for an action that was never taken.
 */
export function parseTrajectory(payload: unknown): TrajectoryResult {
  if (!isRecord(payload)) {
    const got = payload === null ? "null" : typeof payload;
    return { kind: "error", reason: `payload is ${got}, expected an object` };
  }
  try {
    const env = requireString(payload, "env", "trajectory");
    const rawObs = payload["obs"];
    if (!Array.isArray(rawObs)) {
      throw new FieldError({ key: "obs", expected: "an array of arrays", got: rawObs });
    }
    const obs = rawObs.map((row, index) => numbers(row, `obs[${String(index)}]`));
    const actions = numbers(payload["actions"], "actions");
    const rewards = numbers(payload["rewards"], "rewards");

    if (actions.length !== rewards.length) {
      return {
        kind: "error",
        reason:
          `actions and rewards must be the same length, got ` +
          `${String(actions.length)} and ${String(rewards.length)}`,
      };
    }
    if (obs.length !== actions.length + 1) {
      return {
        kind: "error",
        reason:
          `obs must be one longer than actions (it carries the terminal obs), got ` +
          `${String(obs.length)} obs for ${String(actions.length)} actions`,
      };
    }
    if (actions.length === 0) {
      return { kind: "error", reason: "trajectory has no steps" };
    }
    return { env, obs, actions, rewards };
  } catch (cause) {
    if (cause instanceof FieldError) return { kind: "error", reason: cause.message };
    throw cause;
  }
}

/** Total undiscounted return — what the header reports as R. */
export function trajectoryReturn(trajectory: Trajectory): number {
  return trajectory.rewards.reduce((sum, reward) => sum + reward, 0);
}

/* ------------------------------------------------------------------- the DOM */

type Timer = ReturnType<typeof globalThis.setInterval>;

/** The artifact currently loaded, plus everything derived from it once. */
interface Loaded {
  readonly artifact: Artifact;
  readonly result: TrajectoryResult;
  /** Present only when the trajectory parsed AND this env has a surface. */
  readonly surface: CartpoleSurface | null;
}

export interface RolloutState {
  readonly root: HTMLElement;
  readonly header: HTMLElement;
  readonly notice: HTMLElement;
  readonly stage: HTMLElement;
  readonly readout: HTMLElement;
  readonly playButton: HTMLButtonElement;
  readonly scrub: HTMLInputElement;
  readonly speedButton: HTMLButtonElement;
  readonly stepPicker: HTMLElement;
  /** Every trajectory artifact seen, keyed by step number. */
  artifacts: Map<number, Artifact>;
  /** The rollout on screen, by artifact name. */
  loaded: Loaded | null;
  /**
   * A newer artifact that arrived mid-loop. Adopted when the loop wraps, so a
   * frame is never yanked out from under the viewer.
   */
  pending: Artifact | null;
  /**
   * User-selected step, or null = follow latest (auto-advance).
   * Clicking a step pins it; clicking again or clicking "latest" unpins.
   */
  pinned: number | null;
  /** Artifacts this view has no parser for. Counted, shown, never dropped. */
  unsupported: number;
  frame: number;
  playing: boolean;
  speed: Speed;
  loops: number;
  timer: Timer | null;
  destroyed: boolean;
}

function el(tag: string, className: string, text?: string): HTMLElement {
  const node = document.createElement(tag);
  node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function button(className: string, text: string): HTMLButtonElement {
  const node = document.createElement("button");
  node.type = "button";
  node.className = className;
  node.textContent = text;
  return node;
}

/** `◀`/`▶` for CartPole's two actions; the number itself for anything else. */
export function actionGlyph(action: number): string {
  if (action === 0) return "◀";
  if (action === 1) return "▶";
  return String(action);
}

/** Load a specific step, or null to follow latest. */
function selectStep(state: RolloutState, step: number | null): void {
  if (step === state.pinned) {
    // Clicking the active step unpins → follow latest.
    state.pinned = null;
  } else {
    state.pinned = step;
  }
  if (state.pinned !== null) {
    const artifact = state.artifacts.get(state.pinned);
    if (artifact) load(state, artifact);
  } else {
    // Unpin → load the latest artifact.
    const latest = latestArtifact(state);
    if (latest) load(state, latest);
  }
  renderStepPicker(state);
}

function latestArtifact(state: RolloutState): Artifact | null {
  let best: Artifact | null = null;
  let bestStep = -1;
  for (const [step, artifact] of state.artifacts) {
    if (step > bestStep) {
      bestStep = step;
      best = artifact;
    }
  }
  return best;
}

function renderStepPicker(state: RolloutState): void {
  state.stepPicker.replaceChildren();
  const steps = [...state.artifacts.keys()].sort((a, b) => a - b);
  if (steps.length <= 1) return;

  for (const step of steps) {
    const btn = button("rollout-step-button", String(step));
    const isActive =
      state.pinned === step ||
      (state.pinned === null && step === steps[steps.length - 1]);
    if (isActive) btn.classList.add("rollout-step-active");
    btn.addEventListener("click", () => selectStep(state, step));
    state.stepPicker.append(btn);
  }
}

function headerText(state: RolloutState): string {
  const loaded = state.loaded;
  if (loaded === null) return "rollout · waiting for an artifact";
  const step = loaded.artifact.attrs["step"];
  const stepPart = typeof step === "number" ? ` · step ${String(step)}` : "";
  const pinPart = state.pinned !== null ? " · pinned" : "";
  const result = loaded.result;
  if (isTrajectoryError(result)) return `${loaded.artifact.name}${stepPart} · unparseable`;
  const total = trajectoryReturn(result);
  return `${loaded.artifact.name}${stepPart} · return ${String(total)}${pinPart}`;
}

function noticeText(state: RolloutState): string {
  const parts: string[] = [];
  if (state.unsupported > 0) {
    const plural = state.unsupported === 1 ? "artifact" : "artifacts";
    parts.push(`${String(state.unsupported)} ${plural} with unsupported mime`);
  }
  if (state.loops > 0) parts.push(`${String(state.loops)} loops`);
  return parts.join(" · ");
}

function renderChrome(state: RolloutState): void {
  state.header.textContent = headerText(state);
  state.notice.textContent = noticeText(state);
  state.playButton.textContent = state.playing ? "pause" : "play";
  state.speedButton.textContent = `${String(state.speed)}×`;
}

/** The trajectory on screen, or null if there is nothing drawable. */
function drawable(state: RolloutState): Trajectory | null {
  const loaded = state.loaded;
  if (loaded?.surface == null) return null;
  if (isTrajectoryError(loaded.result)) return null;
  return loaded.result;
}

function renderFrame(state: RolloutState): void {
  const loaded = state.loaded;
  const trajectory = drawable(state);
  if (loaded?.surface == null || trajectory === null) return;

  const frame = Math.min(state.frame, trajectory.obs.length - 1);
  const obs = trajectory.obs[frame] ?? [];
  loaded.surface.draw(cartpoleFrame(obs));

  // Rewards/actions are indexed by TRANSITION, so the terminal obs (the last
  // frame) has neither. Showing the cumulative reward up to here rather than a
  // blank keeps the counter monotonic all the way to the end.
  const reward = trajectory.rewards
    .slice(0, frame)
    .reduce((sum, value) => sum + value, 0);
  const action = trajectory.actions[frame];
  const glyph = action === undefined ? "—" : actionGlyph(action);
  state.readout.textContent =
    `step ${String(frame)} / ${String(trajectory.actions.length)}` +
    `   R ${String(reward)}   ${glyph}`;
  state.scrub.value = String(frame);
}

/** Load an artifact onto the stage, replacing whatever was there. */
function load(state: RolloutState, artifact: Artifact): void {
  const result = parseTrajectory(artifact.payload);
  state.stage.replaceChildren();

  let surface: CartpoleSurface | null = null;
  if (isTrajectoryError(result)) {
    state.stage.append(
      el("p", "rollout-fault", `cannot render ${artifact.name}: ${result.reason}`),
    );
  } else if (result.env !== CARTPOLE_ENV) {
    // Loud, not blank. The data is fine; the renderer is what is missing, and
    // the obs shape is the thing you need to write the next one.
    const width = result.obs[0]?.length ?? 0;
    state.stage.append(
      el("p", "rollout-fault", `no renderer for ${result.env}`),
      el(
        "p",
        "rollout-fault-detail",
        `${String(result.obs.length)} observations of ${String(width)} dims, ` +
          `${String(result.actions.length)} actions, ` +
          `return ${String(trajectoryReturn(result))}`,
      ),
    );
  } else {
    surface = createCartpoleSurface();
    state.stage.append(surface.root);
  }

  state.loaded = { artifact, result, surface };
  state.pending = null;
  state.frame = 0;
  state.loops = 0;
  const steps = isTrajectoryError(result) ? 0 : result.actions.length;
  state.scrub.max = String(steps);
  state.scrub.disabled = surface === null;
  state.playButton.disabled = surface === null;
  renderChrome(state);
  renderFrame(state);
}

function tick(state: RolloutState): void {
  if (state.destroyed || !state.playing) return;
  const trajectory = drawable(state);
  if (trajectory === null) return;

  const last = trajectory.obs.length - 1;
  if (state.frame >= last) {
    // End of the loop: the one safe moment to adopt a newer artifact.
    state.loops += 1;
    const pending = state.pending;
    if (pending !== null) {
      const wasPlaying = state.playing;
      load(state, pending);
      state.playing = wasPlaying;
      renderChrome(state);
      return;
    }
    state.frame = 0;
  } else {
    state.frame += 1;
  }
  renderFrame(state);
  renderChrome(state);
}

function setPlaying(state: RolloutState, playing: boolean): void {
  state.playing = playing;
  if (state.timer !== null) globalThis.clearInterval(state.timer);
  state.timer = null;
  if (playing) {
    // Speed is the interval, not a frame skip: every frame is still drawn, so
    // 4x is a faster movie and not a choppier one.
    state.timer = globalThis.setInterval(() => {
      tick(state);
    }, FRAME_MS / state.speed);
  }
  renderChrome(state);
}

/**
 * `mount(el)` — no `ViewContext`.
 *
 * Everything this view draws arrives on the event stream, so it has no use for
 * the run's file name. core/views.ts deliberately does not check arity for
 * exactly this case: "a view that ignores the ViewContext declares `mount(el)`
 * and is still a valid View."
 */
function mount(host: HTMLElement): RolloutState {
  const root = el("section", "rollout");
  const headerRow = el("header", "rollout-header");
  const header = el("h2", "rollout-title", "rollout · waiting for an artifact");
  const notice = el("span", "rollout-notice");
  headerRow.append(header, notice);

  const stepPicker = el("div", "rollout-step-picker");

  const stage = el("div", "rollout-stage");
  const readout = el("div", "rollout-readout tabular", "step 0 / 0   R 0   —");

  const controls = el("div", "rollout-controls");
  const playButton = button("rollout-button", "play");
  playButton.disabled = true;
  const scrub = document.createElement("input");
  scrub.type = "range";
  scrub.className = "rollout-scrub";
  scrub.min = "0";
  scrub.max = "0";
  scrub.value = "0";
  scrub.disabled = true;
  scrub.setAttribute("aria-label", "rollout step");
  const speedButton = button("rollout-button rollout-speed", "1×");
  controls.append(playButton, scrub, speedButton);

  root.append(headerRow, stepPicker, stage, readout, controls);
  host.append(root);

  const state: RolloutState = {
    root,
    header,
    notice,
    stage,
    readout,
    playButton,
    scrub,
    speedButton,
    stepPicker,
    artifacts: new Map(),
    loaded: null,
    pending: null,
    pinned: null,
    unsupported: 0,
    frame: 0,
    playing: false,
    speed: SPEEDS[0],
    loops: 0,
    timer: null,
    destroyed: false,
  };

  playButton.addEventListener("click", () => {
    setPlaying(state, !state.playing);
  });
  scrub.addEventListener("input", () => {
    // Scrubbing is a seek, so it stops playback: otherwise the timer fights the
    // pointer for the frame index and the slider jitters.
    setPlaying(state, false);
    const value = Number(scrub.value);
    state.frame = Number.isFinite(value) ? value : 0;
    renderFrame(state);
  });
  speedButton.addEventListener("click", () => {
    const index = SPEEDS.indexOf(state.speed);
    state.speed = SPEEDS[(index + 1) % SPEEDS.length] ?? SPEEDS[0];
    // Re-arm at the new cadence if we are running.
    setPlaying(state, state.playing);
  });

  return state;
}

function append(state: RolloutState, events: readonly Event[]): void {
  if (state.destroyed) return;
  let changed = false;
  let newTrajectory = false;
  for (const event of events) {
    if (event.kind !== "artifact") continue;
    if (event.mime !== TRAJECTORY_MIME) {
      state.unsupported += 1;
      changed = true;
      continue;
    }
    // Accumulate every trajectory keyed by step.
    const step = event.attrs["step"];
    if (typeof step === "number") {
      state.artifacts.set(step, event);
      newTrajectory = true;
    }
    // If pinned, don't auto-advance — just update the picker.
    if (state.pinned !== null) {
      changed = true;
      continue;
    }
    // Auto-advance: load or park the latest artifact.
    if (state.loaded === null) {
      load(state, event);
      continue;
    }
    if (state.playing && drawable(state) !== null) {
      state.pending = event;
      changed = true;
      continue;
    }
    load(state, event);
  }
  if (newTrajectory) renderStepPicker(state);
  if (changed) renderChrome(state);
}

export const view: View<RolloutState> = {
  name: "rollout",
  accepts: ["artifact"],
  mount,
  append,
};
