/**
 * Narrowing helpers for tests.
 *
 * Tests reach into arrays and DOM queries constantly, and every such lookup is
 * typed as possibly-absent. The old answer was `!`, with an eslint exemption
 * turning `no-non-null-assertion` off for test files. That exemption is gone:
 * `!` erases the check at compile time and gives nothing at runtime, so an
 * assumption that quietly breaks surfaces as "cannot read property of
 * undefined" three lines later, pointing at the wrong thing.
 *
 * `must` is the honest version — a real runtime check that names what was
 * missing. `as` is not an option either: it lies in exactly the same way `!`
 * does, without even the syntax to flag it.
 */

/** The value, or a throw naming what was absent. Validate, then narrow. */
export function must<T>(value: T | undefined | null, what: string): T {
  if (value === undefined || value === null) {
    throw new Error(`expected ${what} to be present, got ${String(value)}`);
  }
  return value;
}

/** `must` for an array index, with the index in the message. */
export function at<T>(items: readonly T[], index: number, what: string): T {
  return must(items[index], `${what}[${String(index)}]`);
}
