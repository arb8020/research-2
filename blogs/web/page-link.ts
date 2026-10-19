import { must } from "./dom";

const LEAVE_MS = 300;
const GAP = 6;
const VIEWPORT_MARGIN = 8;
const coarse = window.matchMedia("(pointer: coarse)");

type Preview =
  | { kind: "closed" }
  | { kind: "dismissed" }
  | { kind: "open"; card: HTMLDivElement; untrack: () => void }
  | { kind: "leaving"; card: HTMLDivElement; untrack: () => void; timer: number };

const imported = new Set<string>();

function importEmbeds(kinds: string[]): void {
  for (const kind of kinds) {
    if (imported.has(kind)) continue;
    imported.add(kind);
    const url = new URL(`embeds/${kind}/element.js`, document.baseURI).href;
    import(url).catch((cause: unknown) => { imported.delete(kind); console.error(`preview: couldn't load the ${kind} embed`, cause); });
  }
}

function place(card: HTMLDivElement, link: HTMLAnchorElement): void {
  const firstLineBox = link.getClientRects()[0];
  const rect = firstLineBox ?? link.getBoundingClientRect();
  card.style.maxHeight = "";
  const { offsetWidth: w, offsetHeight: h } = card;
  const roomBelow = window.innerHeight - VIEWPORT_MARGIN - (rect.bottom + GAP);
  const roomAbove = rect.top - GAP - VIEWPORT_MARGIN;
  const above = h > roomBelow && (h <= roomAbove || roomAbove > roomBelow);
  const height = Math.min(h, above ? roomAbove : roomBelow);
  if (height < h) card.style.maxHeight = `${String(height)}px`;
  card.style.top = `${String(above ? rect.top - GAP - height : rect.bottom + GAP)}px`;
  card.style.left = `${String(Math.max(VIEWPORT_MARGIN, Math.min(rect.left, window.innerWidth - w - VIEWPORT_MARGIN)))}px`;
  card.dataset["side"] = above ? "above" : "below";
  card.toggleAttribute("data-clipped", card.scrollHeight > card.clientHeight);
}

class PageLink extends HTMLElement {
  #preview: Preview = { kind: "closed" };

  get #link(): HTMLAnchorElement {
    return must(this, ":scope > a", HTMLAnchorElement);
  }

  connectedCallback(): void {
    this.addEventListener("pointerenter", (e) => { if (e.pointerType !== "touch") this.#show(); });
    this.addEventListener("pointerleave", (e) => { if (e.pointerType !== "touch") this.#leave(); });
    this.addEventListener("focusin", () => { this.#show(); });
    this.addEventListener("focusout", (e) => {
      if (!(e.relatedTarget instanceof Node && this.contains(e.relatedTarget))) this.#close("closed");
    });
  }

  disconnectedCallback(): void {
    this.#close("closed");
  }

  #show(): void {
    if (coarse.matches) return;
    const p = this.#preview;
    switch (p.kind) {
      case "closed": {
        const card = this.#open();
        this.#preview = { kind: "open", card, untrack: this.#track(card) };
        return;
      }
      case "leaving":
        window.clearTimeout(p.timer);
        this.#preview = { kind: "open", card: p.card, untrack: p.untrack };
        return;
      case "open":
      case "dismissed":
        return;
    }
  }

  #leave(): void {
    const p = this.#preview;
    if (p.kind === "dismissed") this.#preview = { kind: "closed" };
    if (p.kind !== "open") return;
    const keyboardFocusInCard = p.card.contains(document.activeElement);
    if (keyboardFocusInCard) return;
    this.#preview = { ...p, kind: "leaving", timer: window.setTimeout(() => { this.#close("closed"); }, LEAVE_MS) };
  }

  #close(to: "closed" | "dismissed"): void {
    const p = this.#preview;
    switch (p.kind) {
      case "closed":
      case "dismissed":
        this.#preview = { kind: to };
        return;
      case "leaving":
        window.clearTimeout(p.timer);
        break;
      case "open":
        break;
    }
    p.untrack();
    p.card.remove();
    this.#preview = { kind: to };
  }

  #open(): HTMLDivElement {
    const link = this.#link;
    const template = must(this, ":scope > template", HTMLTemplateElement);
    const card = document.createElement("div");
    card.className = "link-card";
    card.setAttribute("role", "group");
    card.setAttribute("aria-label", `preview of ${link.textContent}`);
    card.append(template.content.cloneNode(true));
    link.after(card);
    importEmbeds((this.dataset["embeds"] ?? "").split(" ").filter((k) => k !== ""));
    place(card, link);
    return card;
  }

  #track(card: HTMLDivElement): () => void {
    const link = this.#link;
    const replace = (): void => { place(card, link); };
    const escape = (e: KeyboardEvent): void => {
      if (e.key !== "Escape") return;
      if (card.contains(document.activeElement)) link.focus();
      this.#close("dismissed");
    };
    const resized = new ResizeObserver(replace);
    resized.observe(card);
    window.addEventListener("scroll", replace, { passive: true, capture: true });
    window.addEventListener("resize", replace);
    document.addEventListener("keydown", escape);
    return () => {
      resized.disconnect();
      window.removeEventListener("scroll", replace, { capture: true });
      window.removeEventListener("resize", replace);
      document.removeEventListener("keydown", escape);
    };
  }
}
customElements.define("page-link", PageLink);
