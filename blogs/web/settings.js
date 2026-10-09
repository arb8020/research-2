// Reader settings: light/dark toggle, theme, typography. A classic (non-module) script loaded in <head>,
// so the saved settings land on <html> before first paint. The controls mount once the body exists.
//
// Light/dark follows Lea Verou's two-state toggle (docs/raw/frontend/raw/lea_verou_dark_mode_toggles.md):
// the model has three states (light, dark, follow the OS), the button shows two. Clicking goes to the opposite
// of what you see; if that equals the OS preference, the override is cleared instead of stored.
// The OS is only consulted at click time, never watched to clean up an override.
(() => {
  const SCHEME_KEY = "blogs.scheme";
  const SETTINGS_KEY = "blogs.settings";
  const root = document.documentElement;

  const FONTS = {
    body: [
      ["Charter", 'Charter, "Iowan Old Style", Georgia, serif', null],
      ["Source Serif 4", '"Source Serif 4", Georgia, serif', "Source+Serif+4:wght@400..700"],
      ["Literata", "Literata, Georgia, serif", "Literata:wght@400..700"],
      ["Lora", "Lora, Georgia, serif", "Lora:wght@400..700"],
      ["Newsreader", "Newsreader, Georgia, serif", "Newsreader:wght@400..700"],
      ["Inter", "Inter, system-ui, sans-serif", "Inter:wght@400..700"],
      ["IBM Plex Sans", '"IBM Plex Sans", system-ui, sans-serif', "IBM+Plex+Sans:wght@400;600"],
      ["Source Sans 3", '"Source Sans 3", system-ui, sans-serif', "Source+Sans+3:wght@400..700"],
      ["Geist", "Geist, system-ui, sans-serif", "Geist:wght@400..700"],
    ],
    mono: [
      ["System mono", 'ui-monospace, "SF Mono", Menlo, monospace', null],
      ["DM Mono", '"DM Mono", ui-monospace, monospace', "DM+Mono:wght@400;500"],
      ["JetBrains Mono", '"JetBrains Mono", ui-monospace, monospace', "JetBrains+Mono:wght@400..700"],
      ["IBM Plex Mono", '"IBM Plex Mono", ui-monospace, monospace', "IBM+Plex+Mono:wght@400;600"],
      ["Geist Mono", '"Geist Mono", ui-monospace, monospace', "Geist+Mono:wght@400..700"],
    ],
  };
  // [setting, label, options as [label, value]]. Fixed lists, as shadcn's typeset does.
  const CONTROLS = [
    ["theme", "Theme", [["Classic", "classic"], ["Paper", "paper"]]],
    ["body", "Body", FONTS.body.map(([name]) => [name, name])],
    ["mono", "Mono", FONTS.mono.map(([name]) => [name, name])],
    ["size", "Size", [14, 15, 16, 18, 20].map((px) => [`${px}px`, `${px}px`])],
    ["leading", "Leading", [["Tight 1.6", "1.6"], ["Regular 1.75", "1.75"], ["Loose 1.9", "1.9"]]],
    ["flow", "Flow", [["Compact 1em", "1em"], ["Regular 1.25em", "1.25em"], ["Airy 2em", "2em"]]],
    ["measure", "Measure", [60, 70, 80, 90].map((ch) => [`${ch}ch`, `${ch}ch`])],
  ];
  const DEFAULTS = { theme: "classic", body: "Charter", mono: "System mono", size: "18px", leading: "1.75", flow: "1.25em", measure: "80ch" };

  const read = (key) => { try { return localStorage.getItem(key); } catch { return null; } };
  const write = (key, value) => {
    try { value === null ? localStorage.removeItem(key) : localStorage.setItem(key, value); } catch {}
  };

  let settings = { ...DEFAULTS };
  try { Object.assign(settings, JSON.parse(read(SETTINGS_KEY) || "{}")); } catch {}

  const loaded = new Set();
  function loadFont(spec) {
    if (!spec || loaded.has(spec)) return;
    loaded.add(spec);
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = `https://fonts.googleapis.com/css2?family=${spec}&display=swap`;
    document.head.append(link);
  }
  const font = (kind, name) => FONTS[kind].find(([n]) => n === name) ?? FONTS[kind][0];

  // The only writer of <html> attributes and typography variables.
  function apply() {
    const [, bodyStack, bodySpec] = font("body", settings.body);
    const [, monoStack, monoSpec] = font("mono", settings.mono);
    loadFont(bodySpec);
    loadFont(monoSpec);
    root.dataset.theme = settings.theme;
    root.style.setProperty("--font-body", bodyStack);
    root.style.setProperty("--font-mono", monoStack);
    for (const key of ["size", "leading", "flow", "measure"]) root.style.setProperty(`--${key}`, settings[key]);
    const scheme = read(SCHEME_KEY);
    if (scheme === "light" || scheme === "dark") root.dataset.scheme = scheme;
    else delete root.dataset.scheme;
  }

  const osScheme = () => (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const resolvedScheme = () => root.dataset.scheme ?? osScheme();
  function toggleScheme() {
    const target = resolvedScheme() === "dark" ? "light" : "dark";
    write(SCHEME_KEY, target === osScheme() ? null : target);
    apply();
  }

  function save() {
    write(SETTINGS_KEY, JSON.stringify(settings));
    apply();
  }

  apply();

  const SUN = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4.5"/><path d="M12 2v2.5M12 19.5V22M2 12h2.5M19.5 12H22M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8"/></svg>';
  const MOON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/></svg>';

  class PageSettings extends HTMLElement {
    connectedCallback() {
      const selects = CONTROLS.map(([key, label, options]) => `
        <label><span>${label}</span><select data-key="${key}">
          ${options.map(([text, value]) => `<option value="${value}">${text}</option>`).join("")}
        </select></label>`).join("");
      this.innerHTML = `
        <button class="corner-button scheme" type="button"></button>
        <button class="corner-button aa" type="button" aria-expanded="false" aria-controls="settings-panel">Aa</button>
        <div class="settings-panel" id="settings-panel" role="dialog" aria-label="Reading settings" hidden>
          ${selects}
          <div class="settings-actions">
            <button type="button" class="shuffle">Shuffle</button>
            <button type="button" class="reset">Reset</button>
          </div>
        </div>`;
      this.panel = this.querySelector(".settings-panel");
      this.aa = this.querySelector(".aa");
      this.scheme = this.querySelector(".scheme");
      this.scheme.onclick = () => { toggleScheme(); this.render(); };
      this.aa.onclick = () => this.open(this.panel.hidden);
      for (const select of this.querySelectorAll("select")) {
        select.onchange = () => { settings[select.dataset.key] = select.value; save(); };
      }
      this.querySelector(".shuffle").onclick = () => {
        for (const [key, , options] of CONTROLS) {
          if (key !== "theme") settings[key] = options[Math.floor(Math.random() * options.length)][1];
        }
        save();
        this.render();
      };
      this.querySelector(".reset").onclick = () => { settings = { ...DEFAULTS }; save(); this.render(); };
      document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !this.panel.hidden) { this.open(false); this.aa.focus(); } });
      document.addEventListener("pointerdown", (e) => { if (!this.panel.hidden && !this.contains(e.target)) this.open(false); });
      addEventListener("blur", () => this.open(false));  // clicks inside the play iframe never reach this document
      this.render();
    }

    open(on) {
      this.panel.hidden = !on;
      this.aa.setAttribute("aria-expanded", String(on));
    }

    render() {
      const dark = resolvedScheme() === "dark";
      const pinned = root.dataset.scheme !== undefined;
      this.scheme.innerHTML = dark ? MOON : SUN;
      this.scheme.setAttribute("aria-label", `${dark ? "Dark" : "Light"} mode (${pinned ? "your choice" : "following your system"}). Switch to ${dark ? "light" : "dark"}`);
      this.scheme.title = this.scheme.getAttribute("aria-label");
      for (const select of this.querySelectorAll("select")) select.value = settings[select.dataset.key];
    }
  }

  customElements.define("page-settings", PageSettings);
  const mount = () => document.body.prepend(document.createElement("page-settings"));
  document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", mount) : mount();
})();
