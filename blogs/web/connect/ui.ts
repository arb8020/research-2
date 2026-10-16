// <connect-pill>: the header's Connect control on opted-in pages (build_page.py puts it in the corner).
//
//   pill      disconnected "Connect" | connecting "connecting… (step)" | connected "● T4 · 1h 28m left"
//   panel     disconnected: provider, token (paste, or the saved one masked + Sign out), GPU, session length, Connect
//             otherwise:    summary, lease (ends, time left), Extend…, Details, Disconnect (Cancel while connecting), Sign out
//   drawer    Details: slides in from the right; the session's steps and machine log, follow + copy
//
// Anything may open the panel with document.dispatchEvent(new Event("connect:open")) (cells' "Connect to run").
import { must } from "../dom";
import { LEASE_MAX_S, LEASE_MIN_S } from "./gateway";
import { connect, currentPhase, disconnect, extend, logLines, onLog, onPhase, resume, savedToken, signOut } from "./session";
import type { LogLine, Phase } from "./session";

// [value sent as gpu, label]. Modal's ids; $/h from box/gpus.json (2026-10). CPU-only is the cheap way to try it.
const GPUS: readonly (readonly [gpu: string | null, label: string])[] = [
  ["T4", "T4 · 16 GB · $0.59/h"],
  ["L4", "L4 · 24 GB · $0.80/h"],
  ["A10G", "A10G · 24 GB · $1.10/h"],
  [null, "CPU only · no GPU"],
];
// Session length presets [seconds, label]; "custom" takes minutes. 90 min is the default (with the author, 2026-10-09).
const LENGTHS: readonly (readonly [seconds: number, label: string])[] = [
  [30 * 60, "30 min"], [60 * 60, "1 h"], [90 * 60, "90 min"], [2 * 3600, "2 h"], [4 * 3600, "4 h"], [8 * 3600, "8 h"], [LEASE_MAX_S, "12 h (most)"],
];
const DEFAULT_LENGTH_S = 90 * 60;
// Extend by [seconds, label]; 0 = all the way to the ceiling.
const EXTENDS: readonly (readonly [seconds: number, label: string])[] = [[30 * 60, "+30 min"], [3600, "+1 h"], [2 * 3600, "+2 h"], [4 * 3600, "+4 h"], [0, "to the 12 h limit"]];
const ENDING_SOON_S = 10 * 60; // the pill's dot turns red
const TICK_MS = 10_000;

const gpuName = (gpu: string | null): string => gpu ?? "CPU";
const mask = (id: string): string => (id.length > 8 ? `${id.slice(0, 3)}…${id.slice(-4)}` : "…");
const now = (): number => Date.now() / 1000;

function duration(seconds: number): string {
  const minutes = Math.max(0, Math.floor(seconds / 60));
  if (minutes < 1) return "<1m";
  return minutes < 60 ? `${String(minutes)}m` : `${String(Math.floor(minutes / 60))}h ${String(minutes % 60).padStart(2, "0")}m`;
}
const uptime = (startedAt: number): string => duration(now() - startedAt);
const left = (until: number): string => `${duration(until - now())} left`;
// "15:02", or "Sat 01:30" when it isn't today (12 h can cross midnight).
function endsAt(t: number): string {
  const d = new Date(t * 1000);
  const hm = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
  return d.toDateString() === new Date().toDateString() ? hm : `${d.toLocaleDateString([], { weekday: "short" })} ${hm}`;
}
const clock = (t: number): string => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
const logText = (l: LogLine): string => `${clock(l.t)}  ${l.source.padEnd(7)}  ${l.text}`;

const PANEL = `
  <form class="connect-form">
    <p class="connect-failure" role="alert" hidden></p>
    <fieldset class="connect-providers"><legend>Provider</legend>
      <label><input type="radio" name="provider" value="modal" checked> Modal</label>
      <label class="connect-soon"><input type="radio" name="provider" value="runpod" disabled> RunPod <span>soon</span></label>
    </fieldset>
    <div class="connect-token-saved" hidden>
      <span>Modal token <code class="connect-token-mask"></code></span>
      <button type="button" class="connect-forget">Sign out</button>
    </div>
    <fieldset class="connect-token-new"><legend>Modal token</legend>
      <label><span>Token ID</span><input name="token-id" autocomplete="off" spellcheck="false" placeholder="ak-…" required></label>
      <label><span>Token secret</span><input name="token-secret" type="password" autocomplete="off" spellcheck="false" placeholder="as-…" required></label>
      <p class="connect-hint">Already use Modal? Your <code>token_id</code> and <code>token_secret</code> are in
        <code>~/.modal.toml</code>. Otherwise create one at
        <a href="https://modal.com/settings/tokens" target="_blank" rel="noopener">modal.com/settings/tokens</a>.
        Stored only in this browser.</p>
    </fieldset>
    <label class="connect-gpu"><span>GPU</span><select name="gpu">
      ${GPUS.map(([gpu, label]) => `<option value="${gpu ?? ""}">${label}</option>`).join("")}
    </select></label>
    <label class="connect-length"><span>Session length</span><select name="length">
      ${LENGTHS.map(([s, label]) => `<option value="${String(s)}"${s === DEFAULT_LENGTH_S ? " selected" : ""}>${label}</option>`).join("")}
      <option value="custom">Custom…</option>
    </select></label>
    <label class="connect-custom" hidden><span>Minutes</span><input name="length-min" type="number" inputmode="numeric"
      min="${String(LEASE_MIN_S / 60)}" max="${String(LEASE_MAX_S / 60)}" step="1" required disabled></label>
    <p class="connect-hint connect-ends"></p>
    <p class="connect-hint">Runs in your Modal workspace, billed to it while connected.
      Closing the tab ends it after about 5 min, whatever the length.</p>
    <div class="connect-actions">
      <button type="button" class="connect-details">Details</button>
      <button type="submit" class="connect-go">Connect</button>
    </div>
  </form>
  <div class="connect-menu" hidden>
    <p class="connect-summary"></p>
    <p class="connect-lease"></p>
    <button type="button" class="connect-extend-open" aria-expanded="false" aria-controls="connect-extend">Extend…</button>
    <div class="connect-extend" id="connect-extend" hidden>
      <label><span>Extend</span><select name="extend-by">
        ${EXTENDS.map(([s, label]) => `<option value="${String(s)}">${label}</option>`).join("")}
      </select></label>
      <button type="button" class="connect-extend-go">Extend</button>
    </div>
    <p class="connect-extend-result" role="status"></p>
    <button type="button" class="connect-details">Details</button>
    <button type="button" class="connect-end">Disconnect</button>
    <button type="button" class="connect-signout">Sign out</button>
  </div>`;

const DRAWER = `
  <div class="drawer-head">
    <h2 tabindex="-1">Connection details</h2>
    <button type="button" class="drawer-close" aria-label="Close connection details">×</button>
  </div>
  <p class="drawer-status"></p>
  <div class="drawer-tools">
    <label><input type="checkbox" class="drawer-follow" checked> follow</label>
    <button type="button" class="drawer-copy">Copy log</button>
  </div>
  <ol class="drawer-log" tabindex="0" aria-label="Session log"></ol>`;

class ConnectPill extends HTMLElement {
  private readonly drawer = document.createElement("aside");
  private tick: ReturnType<typeof setInterval> | undefined;
  private autoTop = 0; // where following last scrolled the log to
  private announced: Phase["kind"] | undefined; // a lease update re-renders "connected"; say it once

  connectedCallback(): void {
    this.innerHTML = `
      <button type="button" class="connect-pill" aria-expanded="false" aria-controls="connect-panel"><span class="connect-dot" aria-hidden="true"></span><span class="connect-label">Connect</span></button>
      <span class="connect-announce" role="status"></span>
      <div class="connect-panel" id="connect-panel" role="dialog" aria-label="Connect to a GPU" hidden>${PANEL}</div>`;
    this.drawer.className = "connect-drawer";
    this.drawer.id = "connect-drawer";
    this.drawer.setAttribute("aria-label", "Connection details");
    this.drawer.hidden = true;
    this.drawer.innerHTML = DRAWER;
    document.body.append(this.drawer);
    this.wirePanel();
    this.wireDrawer();
    onPhase((p) => { this.render(p); this.announce(p); });
    onLog((line) => { this.appendLog(line); });
    document.addEventListener("connect:open", () => { this.open(true); });
    this.render(currentPhase());
    void resume();
  }

  private get pill(): HTMLButtonElement { return must(this, ".connect-pill", HTMLButtonElement); }
  private get panel(): HTMLDivElement { return must(this, ".connect-panel", HTMLDivElement); }

  open(on: boolean): void {
    this.panel.hidden = !on;
    this.pill.setAttribute("aria-expanded", String(on));
    if (!on) return;
    this.render(currentPhase());
    const form = must(this, ".connect-form", HTMLFormElement);
    const fresh = must(form, ".connect-token-new", HTMLFieldSetElement);
    const first = !form.hidden ? (fresh.disabled ? must(form, ".connect-go", HTMLButtonElement) : must(fresh, "input", HTMLInputElement))
      : must(this, ".connect-menu button", HTMLButtonElement);
    first.focus();
  }

  private wirePanel(): void {
    const form = must(this, ".connect-form", HTMLFormElement);
    this.pill.onclick = () => { this.open(this.panel.hidden !== false); }; // hidden is boolean | "until-found"
    form.onsubmit = (e) => {
      e.preventDefault();
      const id = must(form, "input[name=token-id]", HTMLInputElement).value.trim();
      const secret = must(form, "input[name=token-secret]", HTMLInputElement).value.trim();
      const token = savedToken() ?? { id, secret };
      const choice = must(form, "select[name=gpu]", HTMLSelectElement).value;
      const leaseS = this.lengthS(); // the form's min/max/required blocked submit unless this is in range
      if (leaseS === undefined) throw new Error("connect form submitted with an invalid session length");
      this.open(false);
      this.pill.focus();
      void connect(token, choice === "" ? null : choice, leaseS);
    };
    const length = must(form, "select[name=length]", HTMLSelectElement);
    const custom = must(form, ".connect-custom", HTMLLabelElement);
    const minutes = must(custom, "input", HTMLInputElement);
    length.onchange = () => {
      custom.hidden = length.value !== "custom";
      minutes.disabled = custom.hidden; // a hidden required input would block submit
      if (!custom.hidden) { if (minutes.value === "") minutes.value = String(DEFAULT_LENGTH_S / 60); minutes.focus(); }
      this.renderEnds();
    };
    minutes.oninput = () => { this.renderEnds(); };
    this.wireExtend();
    must(this, ".connect-forget", HTMLButtonElement).onclick = () => {
      void signOut().then(() => { this.render(currentPhase()); must(form, "input[name=token-id]", HTMLInputElement).focus(); });
    };
    for (const b of this.querySelectorAll<HTMLButtonElement>(".connect-details")) b.onclick = () => { this.open(false); this.showDrawer(true); };
    must(this, ".connect-end", HTMLButtonElement).onclick = () => { this.open(false); this.pill.focus(); void disconnect(); };
    must(this, ".connect-signout", HTMLButtonElement).onclick = () => { this.open(false); this.pill.focus(); void signOut(); };
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      if (!this.panel.hidden) { this.open(false); this.pill.focus(); } else if (!this.drawer.hidden) { this.showDrawer(false); this.pill.focus(); }
    });
    document.addEventListener("pointerdown", (e) => { if (!this.panel.hidden && !(e.target instanceof Node && this.contains(e.target))) this.open(false); });
  }

  // The session length the form asks for, in seconds; undefined if the custom minutes are out of range.
  private lengthS(): number | undefined {
    const choice = must(this, "select[name=length]", HTMLSelectElement).value;
    if (choice !== "custom") return Number(choice);
    const minutes = must(this, "input[name=length-min]", HTMLInputElement);
    const seconds = Number(minutes.value) * 60;
    return minutes.value !== "" && minutes.checkValidity() && seconds >= LEASE_MIN_S && seconds <= LEASE_MAX_S ? seconds : undefined;
  }

  private renderEnds(): void {
    const seconds = this.lengthS();
    must(this, ".connect-ends", HTMLParagraphElement).textContent = seconds === undefined
      ? `Pick ${String(LEASE_MIN_S / 60)} to ${String(LEASE_MAX_S / 60)} minutes (12 h at most).`
      : `Ends at ${endsAt(now() + seconds)} if you connect now. You can extend it later, up to 12 h.`;
  }

  private wireExtend(): void {
    const menu = must(this, ".connect-menu", HTMLDivElement);
    const opener = must(menu, ".connect-extend-open", HTMLButtonElement);
    const row = must(menu, ".connect-extend", HTMLDivElement);
    const by = must(row, "select", HTMLSelectElement);
    const go = must(row, ".connect-extend-go", HTMLButtonElement);
    const result = must(menu, ".connect-extend-result", HTMLParagraphElement);
    opener.onclick = () => {
      row.hidden = !row.hidden;
      opener.setAttribute("aria-expanded", String(!row.hidden));
      result.textContent = "";
      if (!row.hidden) by.focus();
    };
    go.onclick = () => {
      const p = currentPhase();
      if (p.kind !== "connected") return; // the button is hidden then
      const add = Number(by.value);
      // Ask for what the reader picked, uncapped: the gateway clamps to the ceiling and we show where it landed.
      const until = add === 0 ? p.ceiling : Math.max(p.leaseUntil, now()) + add;
      go.disabled = true;
      result.textContent = "Extending…";
      extend(until).then(() => {
        const q = currentPhase();
        if (q.kind !== "connected") return;
        const capped = q.leaseUntil >= q.ceiling;
        result.textContent = `Now ends ${endsAt(q.leaseUntil)}${capped ? ", the 12 h limit" : ""}.`;
        row.hidden = true;
        opener.setAttribute("aria-expanded", "false");
      }, (cause: unknown) => {
        result.textContent = `Extend failed: ${cause instanceof Error ? cause.message : String(cause)}`;
      }).finally(() => { go.disabled = false; this.render(currentPhase()); });
    };
  }

  private wireDrawer(): void {
    const list = must(this.drawer, ".drawer-log", HTMLOListElement);
    const follow = must(this.drawer, ".drawer-follow", HTMLInputElement);
    must(this.drawer, ".drawer-close", HTMLButtonElement).onclick = () => { this.showDrawer(false); this.pill.focus(); };
    // Following only scrolls down, so a scroll up from where it left the list is the reader's: stop following.
    // Back at the bottom: follow again.
    list.onscroll = () => {
      if (list.scrollTop < this.autoTop - 8) follow.checked = false;
      else if (list.scrollHeight - list.scrollTop - list.clientHeight < 8) follow.checked = true;
    };
    follow.onchange = () => { if (follow.checked) { list.scrollTop = list.scrollHeight; this.autoTop = list.scrollTop; } };
    const copy = must(this.drawer, ".drawer-copy", HTMLButtonElement);
    copy.onclick = () => {
      const { lines, dropped } = logLines();
      const text = (dropped > 0 ? `(${String(dropped)} earlier lines dropped)\n` : "") + lines.map(logText).join("\n");
      navigator.clipboard.writeText(text).then(() => { copy.textContent = "Copied"; }, () => { copy.textContent = "Copy failed"; });
      setTimeout(() => { copy.textContent = "Copy log"; }, 1500);
    };
    for (const line of logLines().lines) this.appendLog(line);
  }

  private showDrawer(on: boolean): void {
    this.drawer.hidden = !on;
    if (!on) return;
    this.render(currentPhase());
    const list = must(this.drawer, ".drawer-log", HTMLOListElement);
    if (must(this.drawer, ".drawer-follow", HTMLInputElement).checked) { list.scrollTop = list.scrollHeight; this.autoTop = list.scrollTop; }
    must(this.drawer, "h2", HTMLHeadingElement).focus();
  }

  private appendLog(line: LogLine): void {
    const list = must(this.drawer, ".drawer-log", HTMLOListElement);
    const item = document.createElement("li");
    item.className = `log-${line.kind}`;
    const time = document.createElement("time");
    time.textContent = clock(line.t);
    const source = document.createElement("span");
    source.className = "log-source";
    source.textContent = line.source;
    const body = document.createElement("span");
    body.textContent = line.text;
    item.append(time, source, body);
    list.append(item);
    const { dropped } = logLines();
    while (list.children.length > logLines().lines.length) list.firstElementChild?.remove();
    list.dataset["dropped"] = String(dropped);
    if (must(this.drawer, ".drawer-follow", HTMLInputElement).checked) { list.scrollTop = list.scrollHeight; this.autoTop = list.scrollTop; }
  }

  private announce(p: Phase): void {
    if (p.kind === this.announced) return;
    this.announced = p.kind;
    const text = p.kind === "connected" ? `Connected to ${gpuName(p.gpu)}` : p.kind === "disconnected" ? `Disconnected${p.failure ? `: ${p.failure}` : ""}` : "";
    if (text) must(this, ".connect-announce", HTMLSpanElement).textContent = text;
  }

  private render(p: Phase): void {
    clearInterval(this.tick);
    if (p.kind === "connected" || !this.panel.hidden) this.tick = setInterval(() => { this.render(currentPhase()); }, TICK_MS);
    this.dataset["phase"] = p.kind;
    this.toggleAttribute("data-failed", p.kind === "disconnected" && p.failure !== undefined);
    this.toggleAttribute("data-ending", p.kind === "connected" && p.leaseUntil - now() <= ENDING_SOON_S);
    const label = p.kind === "connected" ? `${gpuName(p.gpu)} · ${left(p.leaseUntil)}` : p.kind === "connecting" ? `connecting… (${p.step})` : "Connect";
    must(this, ".connect-label", HTMLSpanElement).textContent = label;
    this.pill.title = p.kind === "connected" ? `Connected: ${gpuName(p.gpu)} on Modal, up ${uptime(p.startedAt)}, ends ${endsAt(p.leaseUntil)}`
      : p.kind === "connecting" ? `Connecting: ${p.step}` : p.failure ?? "Connect a GPU to run remote cells";
    this.renderPanel(p);
    must(this.drawer, ".drawer-status", HTMLParagraphElement).textContent = p.kind === "connected"
      ? `${p.id} · ${gpuName(p.gpu)} on Modal · running, up ${uptime(p.startedAt)} · ends ${clock(p.leaseUntil)} (extendable to ${clock(p.ceiling)})`
      : p.kind === "connecting" ? `connecting: ${p.step}` : `disconnected${p.failure ? `: ${p.failure}` : ""}`;
  }

  private renderPanel(p: Phase): void {
    const form = must(this, ".connect-form", HTMLFormElement);
    const menu = must(this, ".connect-menu", HTMLDivElement);
    form.hidden = p.kind !== "disconnected";
    menu.hidden = p.kind === "disconnected";
    const failure = must(form, ".connect-failure", HTMLParagraphElement);
    failure.hidden = p.kind !== "disconnected" || p.failure === undefined;
    failure.textContent = p.kind === "disconnected" && p.failure !== undefined ? `Last attempt: ${p.failure}` : "";
    const token = savedToken();
    must(form, ".connect-token-saved", HTMLDivElement).hidden = token === undefined;
    const fresh = must(form, ".connect-token-new", HTMLFieldSetElement);
    fresh.hidden = token !== undefined;
    fresh.disabled = token !== undefined; // a hidden required input would block submit
    must(form, ".connect-token-mask", HTMLElement).textContent = token === undefined ? "" : mask(token.id);
    must(menu, ".connect-summary", HTMLParagraphElement).textContent = p.kind === "connected"
      ? `${gpuName(p.gpu)} on Modal · up ${uptime(p.startedAt)}` : p.kind === "connecting" ? `Connecting: ${p.step}` : "";
    must(menu, ".connect-end", HTMLButtonElement).textContent = p.kind === "connecting" ? "Cancel" : "Disconnect";
    this.renderEnds();
    this.renderLease(menu, p);
  }

  // The menu's lease line and Extend…: hidden until connected; Extend… disabled at the ceiling.
  private renderLease(menu: HTMLDivElement, p: Phase): void {
    const line = must(menu, ".connect-lease", HTMLParagraphElement);
    const opener = must(menu, ".connect-extend-open", HTMLButtonElement);
    const row = must(menu, ".connect-extend", HTMLDivElement);
    if (p.kind !== "connected") {
      line.hidden = opener.hidden = row.hidden = true;
      must(menu, ".connect-extend-result", HTMLParagraphElement).textContent = "";
      return;
    }
    const atCeiling = p.leaseUntil >= p.ceiling;
    line.hidden = false;
    line.textContent = `Ends ${endsAt(p.leaseUntil)} · ${left(p.leaseUntil)}${atCeiling ? " · at the 12 h limit" : ""}`;
    opener.hidden = false;
    opener.disabled = atCeiling;
    if (atCeiling) row.hidden = true;
    opener.setAttribute("aria-expanded", String(!row.hidden));
    const ceiling = p.ceiling;
    const options = must(row, "select", HTMLSelectElement).options;
    EXTENDS.forEach(([add, label], i) => {
      const until = add === 0 ? ceiling : Math.max(p.leaseUntil, now()) + add;
      const capped = add !== 0 && until > ceiling ? " (capped)" : "";
      const option = options[i];
      if (option !== undefined) option.textContent = `${label}${capped}, ends ${endsAt(Math.min(until, ceiling))}`;
    });
  }
}

customElements.define("connect-pill", ConnectPill);
