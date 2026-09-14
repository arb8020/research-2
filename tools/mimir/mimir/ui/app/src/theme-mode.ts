/**
 * Theme mode — manual light/system/dark selection, persisted.
 *
 * The resolved theme is stamped on <html data-theme="..."> so CSS can key
 * off it; components that build themes in JS (CodeMirror, pierre diffs)
 * subscribe via the `isDark` signal.
 */

import { signal, computed, effect } from "@preact/signals";

export type ThemeMode = "light" | "system" | "dark";

const STORAGE_KEY = "mimir-theme";

function storedMode(): ThemeMode {
  const v = localStorage.getItem(STORAGE_KEY);
  return v === "light" || v === "dark" ? v : "system";
}

export const themeMode = signal<ThemeMode>(storedMode());

const mq = window.matchMedia("(prefers-color-scheme: dark)");
const systemDark = signal(mq.matches);
mq.addEventListener("change", (e) => {
  systemDark.value = e.matches;
});

export const isDark = computed(
  () => themeMode.value === "dark" || (themeMode.value === "system" && systemDark.value),
);

effect(() => {
  localStorage.setItem(STORAGE_KEY, themeMode.value);
  document.documentElement.dataset.theme = isDark.value ? "dark" : "light";
});
