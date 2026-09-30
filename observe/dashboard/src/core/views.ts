/**
 * View discovery.
 *
 * Views are found on disk, not registered in a shared inventory: adding a view
 * is adding a folder. Core validates the contract shape at load time and throws
 * loudly rather than skipping a module that half-implements it.
 *
 * Note the direction of the dependency: this file reads view modules through
 * the bundler's glob, but never imports a view by name. Lint forbids
 * `core/** -> views/**` static imports.
 */

import type { Kind, View } from "./events.ts";
import { KINDS } from "./events.ts";
import { isRecord } from "./fields.ts";

export class ViewContractError extends Error {
  constructor(path: string, reason: string) {
    super(`view module ${path}: ${reason}`);
    this.name = "ViewContractError";
  }
}

function isKind(value: unknown): value is Kind {
  return typeof value === "string" && KINDS.some((k) => k === value);
}

/** Verifies every claim in the View interface before narrowing to it. */
function isView(value: unknown): value is View {
  if (!isRecord(value)) return false;
  if (typeof value["name"] !== "string" || value["name"].length === 0) {
    return false;
  }
  const accepts = value["accepts"];
  if (!Array.isArray(accepts) || accepts.length === 0) return false;
  if (!accepts.every(isKind)) return false;
  // Arity is deliberately not checked: `mount(el, ctx)` — a view that ignores
  // the ViewContext declares `mount(el)` and is still a valid View.
  if (typeof value["mount"] !== "function") return false;
  if (typeof value["append"] !== "function") return false;
  return true;
}

export interface DiscoveredView {
  readonly path: string;
  readonly view: View;
}

/**
 * Validate a path -> module map into views, in stable path-sorted order.
 * Exported separately from `discoverViews` so tests can drive it without a bundler.
 */
export function validateViewModules(
  modules: Readonly<Record<string, unknown>>,
): DiscoveredView[] {
  const paths = Object.keys(modules).sort();
  return paths.map((path) => {
    const mod = modules[path];
    if (!isRecord(mod)) {
      throw new ViewContractError(path, "module is not an object");
    }
    if (!("view" in mod)) {
      throw new ViewContractError(path, "has no `view` export");
    }
    const candidate = mod["view"];
    if (!isView(candidate)) {
      throw new ViewContractError(
        path,
        "`view` export does not match the View contract " +
          "(needs name: string, accepts: non-empty Kind[], mount(el, ctx), append(state, events))",
      );
    }
    return { path, view: candidate };
  });
}

/** Every view under src/views/, discovered at build time. */
export function discoverViews(): DiscoveredView[] {
  const modules: Readonly<Record<string, unknown>> = import.meta.glob(
    "../views/*/view.ts",
    { eager: true },
  );
  return validateViewModules(modules);
}
