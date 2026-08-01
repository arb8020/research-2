/**
 * Syntax palette derived from design tokens via OKLCH color mixing.
 *
 * Instead of picking syntax colors by hand, we derive them from the
 * design system: take the ink color, shift its hue to a target angle,
 * and set a controlled chroma (saturation). This guarantees every
 * syntax color "belongs" to the palette — same lightness family,
 * just tinted.
 *
 * OKLCH is perceptually uniform, so equal chroma values look equally
 * saturated regardless of hue.
 */

// ── OKLCH utilities ───────────────────────────────────────────────

/** sRGB hex → OKLCH {L, C, h} */
function hexToOklch(hex: string): { L: number; C: number; h: number } {
  const rgb = hexToLinearRgb(hex);
  const [l, a, b] = linearRgbToOklab(rgb);
  const C = Math.sqrt(a * a + b * b);
  const h = (Math.atan2(b, a) * 180) / Math.PI;
  return { L: l, C, h: h < 0 ? h + 360 : h };
}

/** OKLCH {L, C, h} → sRGB hex */
function oklchToHex(L: number, C: number, h: number): string {
  const hRad = (h * Math.PI) / 180;
  const a = C * Math.cos(hRad);
  const b = C * Math.sin(hRad);
  const rgb = oklabToLinearRgb(L, a, b);
  return linearRgbToHex(rgb);
}

function hexToLinearRgb(hex: string): [number, number, number] {
  const n = parseInt(hex.slice(1), 16);
  const r = ((n >> 16) & 0xff) / 255;
  const g = ((n >> 8) & 0xff) / 255;
  const b = (n & 0xff) / 255;
  return [srgbToLinear(r), srgbToLinear(g), srgbToLinear(b)];
}

function srgbToLinear(c: number): number {
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}

function linearToSrgb(c: number): number {
  c = Math.max(0, Math.min(1, c));
  return c <= 0.0031308 ? c * 12.92 : 1.055 * Math.pow(c, 1 / 2.4) - 0.055;
}

function linearRgbToOklab(rgb: [number, number, number]): [number, number, number] {
  const [r, g, b] = rgb;
  const l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b;
  const m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b;
  const s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b;
  const l_ = Math.cbrt(l), m_ = Math.cbrt(m), s_ = Math.cbrt(s);
  return [
    0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
    1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
    0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
  ];
}

function oklabToLinearRgb(L: number, a: number, b: number): [number, number, number] {
  const l_ = L + 0.3963377774 * a + 0.2158037573 * b;
  const m_ = L - 0.1055613458 * a - 0.0638541728 * b;
  const s_ = L - 0.0894841775 * a - 1.2914855480 * b;
  const l = l_ * l_ * l_, m = m_ * m_ * m_, s = s_ * s_ * s_;
  return [
    +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
  ];
}

function linearRgbToHex(rgb: [number, number, number]): string {
  const [r, g, b] = rgb.map(linearToSrgb);
  const toHex = (c: number) =>
    Math.round(Math.max(0, Math.min(255, c * 255)))
      .toString(16)
      .padStart(2, "0");
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
}

// ── Syntax color derivation ───────────────────────────────────────

/**
 * Derive a syntax color from a base ink color by shifting to a target
 * hue and applying a controlled chroma (saturation).
 *
 * - Lightness comes from the base ink (keeps it in the same visual tier)
 * - Hue is the "meaning" color for this syntax role
 * - Chroma controls how much color shows through (low = muted, subtle)
 */
function deriveSyntaxColor(
  baseInk: string,
  targetHue: number,
  chroma: number,
  lightnessOffset: number = 0,
): string {
  const base = hexToOklch(baseInk);
  return oklchToHex(
    Math.max(0, Math.min(1, base.L + lightnessOffset)),
    chroma,
    targetHue,
  );
}

/** Hue angles for syntax roles (OKLCH degrees) */
const HUES = {
  string: 145,    // olive-green
  number: 70,     // warm amber (near accent)
  function: 230,  // cool blue
  type: 300,      // mauve/purple
  decorator: 70,  // same as accent
} as const;

export interface SyntaxColors {
  keyword: string;
  string: string;
  comment: string;
  number: string;
  function: string;
  type: string;
  decorator: string;
}

/**
 * Generate syntax colors from design tokens.
 *
 * Light mode: ink-based, low chroma (0.04-0.06) for muted tints
 * Dark mode: lifted lightness, slightly more chroma for readability
 */
export function deriveSyntaxPalette(
  ink: string,
  ink3: string,
  accent: string,
  isDark: boolean,
): SyntaxColors {
  const chroma = isDark ? 0.06 : 0.045;
  const lOffset = isDark ? 0.05 : -0.03;

  return {
    keyword: ink, // bold weight carries it, no color needed
    string: deriveSyntaxColor(ink, HUES.string, chroma, lOffset),
    comment: ink3, // already in the palette
    number: deriveSyntaxColor(ink, HUES.number, chroma * 0.8, lOffset),
    function: deriveSyntaxColor(ink, HUES.function, chroma * 0.7, lOffset),
    type: deriveSyntaxColor(ink, HUES.type, chroma * 0.6, lOffset),
    decorator: accent, // accent itself
  };
}
