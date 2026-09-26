/**
 * The CartPole surface: one env's geometry, and the SVG that draws it.
 *
 * Pure geometry (`cartpoleFrame`) is separated from the SVG so the mapping from
 * physics to pixels is testable without a DOM — θ=0 must be upright and x=±2.4
 * must land on the track ends, and those are arithmetic claims, not rendering
 * claims.
 *
 * Nothing here knows about artifacts, events, or playback. It takes an obs
 * 4-tuple and moves two shapes. A second env gets a second file beside this one.
 */

/**
 * CartPole-v1's own limits (gymnasium `cartpole.py`):
 *   x     ±2.4  — past this the episode terminates
 *   θ     ±12°  — likewise, but we draw well past it so a fall is visible
 *   dt    0.02s — hence the 50fps playback target
 */
export const CART_X_LIMIT = 2.4;
export const CARTPOLE_DT_S = 0.02;
/** The env id this surface is for. Anything else gets the unsupported state. */
export const CARTPOLE_ENV = "CartPole-v1";

/** The drawing surface, in SVG user units. A viewBox, not pixels. */
export const SURFACE = { width: 600, height: 300 } as const;

/** Where the track sits and how wide it is, in surface units. */
const TRACK = { y: 220, left: 60, right: 540 } as const;
const CART = { width: 70, height: 32 } as const;
/**
 * The pole is ~1 unit long in the env's own coordinates and is drawn at ~40% of
 * the surface height, which is the ratio gymnasium's own renderer uses closely
 * enough to look right next to a video of it.
 */
const POLE_LENGTH = SURFACE.height * 0.4;

/** One frame's geometry: where the cart is and which way the pole leans. */
export interface CartpoleFrame {
  /** Cart centre, in surface units along the track. */
  readonly cartX: number;
  /** Pole angle in radians, measured from vertical; positive leans right. */
  readonly poleAngle: number;
}

/**
 * Map one observation onto the surface.
 *
 * `x` is mapped linearly so ±CART_X_LIMIT lands exactly on the track ends — the
 * track IS the domain, so a cart at the edge of the drawing is a cart at the
 * edge of the state space, and there is no hidden margin to misread.
 *
 * `x` outside ±2.4 is NOT clamped: CartPole terminates there, so such an obs
 * means either a different env or a producer bug, and a cart drawn off the end
 * of the track says so. Clamping would draw a legal-looking frame instead.
 *
 * `theta` passes through untouched: the env already measures it from vertical,
 * which is what the SVG rotation wants, and converting units here would be a
 * second place for the sign convention to disagree with gymnasium's.
 */
export function cartpoleFrame(obs: readonly number[]): CartpoleFrame {
  const x = obs[0] ?? 0;
  const theta = obs[2] ?? 0;
  const mid = (TRACK.left + TRACK.right) / 2;
  const halfSpan = (TRACK.right - TRACK.left) / 2;
  return {
    cartX: mid + (x / CART_X_LIMIT) * halfSpan,
    poleAngle: theta,
  };
}

/** The surface's mutable handle: `draw` moves the shapes already on screen. */
export interface CartpoleSurface {
  readonly root: SVGSVGElement;
  draw(frame: CartpoleFrame): void;
}

/**
 * `createElementNS`, typed by tag name.
 *
 * Generic over `SVGElementTagNameMap` rather than returning `SVGElement`: the
 * root has to be an `SVGSVGElement` for the surface's type, and the honest way
 * to get one is for the helper to know the tag, not for the caller to assert
 * afterwards. `as SVGSVGElement` would have been a claim with nothing checking
 * it — the lint that rejected it was right.
 */
function svg<K extends keyof SVGElementTagNameMap>(
  tag: K,
  attrs: Readonly<Record<string, string>>,
): SVGElementTagNameMap[K] {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  return node;
}

/**
 * Build the CartPole SVG once and return a handle that only MOVES it.
 *
 * Built once, mutated per frame: at 50fps, rebuilding the subtree every frame
 * would be 50 layout invalidations a second for two shapes that never change
 * shape. The cart and pole live in one `<g>` whose transform carries the cart
 * position, so a frame is two attribute writes.
 */
export function createCartpoleSurface(): CartpoleSurface {
  const root = svg("svg", {
    class: "rollout-svg",
    viewBox: `0 0 ${String(SURFACE.width)} ${String(SURFACE.height)}`,
    preserveAspectRatio: "xMidYMid meet",
    role: "img",
    "aria-label": "CartPole rollout",
  });

  root.append(
    svg("line", {
      class: "rollout-track",
      x1: String(TRACK.left),
      y1: String(TRACK.y),
      x2: String(TRACK.right),
      y2: String(TRACK.y),
    }),
  );
  // The two termination bounds, drawn so "the cart ran out of track" reads as a
  // reason rather than a coincidence.
  for (const edge of [TRACK.left, TRACK.right]) {
    root.append(
      svg("line", {
        class: "rollout-limit",
        x1: String(edge),
        y1: String(TRACK.y - 14),
        x2: String(edge),
        y2: String(TRACK.y + 14),
      }),
    );
  }

  const group = svg("g", { class: "rollout-cart-group" });
  const cart = svg("rect", {
    class: "rollout-cart",
    x: String(-CART.width / 2),
    y: String(-CART.height / 2),
    width: String(CART.width),
    height: String(CART.height),
    rx: "3",
  });
  // The pole is drawn straight up from the origin and rotated, so its own
  // geometry never changes — only the rotation does.
  const pole = svg("line", {
    class: "rollout-pole",
    x1: "0",
    y1: "0",
    x2: "0",
    y2: String(-POLE_LENGTH),
  });
  const hinge = svg("circle", { class: "rollout-hinge", cx: "0", cy: "0", r: "4" });
  group.append(cart, pole, hinge);
  root.append(group);

  return {
    root,
    draw(frame) {
      group.setAttribute(
        "transform",
        `translate(${frame.cartX.toFixed(2)} ${String(TRACK.y - CART.height / 2)})`,
      );
      // SVG rotates clockwise for positive degrees and the y axis points down,
      // so a positive θ (leaning right in the env) is a positive rotation here.
      pole.setAttribute(
        "transform",
        `rotate(${((frame.poleAngle * 180) / Math.PI).toFixed(2)})`,
      );
    },
  };
}
