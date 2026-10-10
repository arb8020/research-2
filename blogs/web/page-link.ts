// <page-link>: a [[page#Heading]] link to another chapter, with an Alignment Forum style preview card.
//
// build_page.py writes, inline in the prose:
//   <page-link data-embeds="nn-fit"><a href="../neural-nets/#fitting-a-curve">…</a><template>card</template></page-link>
// The card (target title + that section, rendered at build time) sits in the <template>: nothing is fetched on hover.
// data-embeds names the embed kinds the card uses; their scripts are imported on the first open (dynamic import),
// so a page whose own prose has no nn-fit only loads it when a reader hovers a link that shows one.
//
// Hover or keyboard focus opens the card at once, below the link (above if it doesn't fit), kept on screen.
// For its first 200ms the card ignores the pointer (page.css, .link-card animation), so a pointer passing over it
// doesn't hold it open. Leaving link and card closes it after LEAVE_MS (long enough to cross the gap once the card
// accepts the pointer). Escape closes. On touch screens ((pointer: coarse)) there is no card: a tap just navigates.
// Placement is hand-rolled (one rect, a flip, a height cut, a horizontal shift), not @floating-ui/dom.
import { must } from "./dom";

const LEAVE_MS = 300; // > the 200ms grace in page.css, so a pointer heading for the card gets there
const GAP = 6;
const MARGIN = 8; // keep the card this far inside the viewport
const coarse = window.matchMedia("(pointer: coarse)");

type Preview =
  | { kind: "closed" }
  | { kind: "dismissed" } // closed by Escape; stays closed until the pointer or focus leaves the link
  | { kind: "open"; card: HTMLDivElement; untrack: () => void }
  | { kind: "leaving"; card: HTMLDivElement; untrack: () => void; timer: number };

// Embed kinds already imported. Re-importing is harmless (same URL, same module); this just skips the call.
const imported = new Set<string>();

function importEmbeds(kinds: string[]): void {
  for (const kind of kinds) {
    if (imported.has(kind)) continue;
    imported.add(kind);
    const url = new URL(`embeds/${kind}/element.js`, document.baseURI).href;
    import(url).catch((cause: unknown) => { imported.delete(kind); console.error(`preview: couldn't load the ${kind} embed`, cause); });
  }
}

// Below-start; flipped above when it only fits there; when it fits neither, the roomier side, with the card cut
// to that room (it is clipped with a fade anyway). Shifted left to stay on screen.
function place(card: HTMLDivElement, link: HTMLAnchorElement): void {
  const rect = link.getClientRects()[0] ?? link.getBoundingClientRect(); // first line box of a wrapped link
  card.style.maxHeight = ""; // measure at the stylesheet's max-height
  const { offsetWidth: w, offsetHeight: h } = card;
  const roomBelow = window.innerHeight - MARGIN - (rect.bottom + GAP);
  const roomAbove = rect.top - GAP - MARGIN;
  const above = h > roomBelow && (h <= roomAbove || roomAbove > roomBelow);
  const height = Math.min(h, above ? roomAbove : roomBelow);
  if (height < h) card.style.maxHeight = `${String(height)}px`;
  card.style.top = `${String(above ? rect.top - GAP - height : rect.bottom + GAP)}px`;
  card.style.left = `${String(Math.max(MARGIN, Math.min(rect.left, window.innerWidth - w - MARGIN)))}px`;
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
    // Keyboard focus inside the card keeps it open; the pointer wandering off doesn't override that.
    if (p.card.contains(document.activeElement)) return;
    this.#preview = { ...p, kind: "leaving", timer: window.setTimeout(() => { this.#close("closed"); }, LEAVE_MS) };
  }

  #close(to: "closed" | "dismissed"): void {
    const p = this.#preview;
    switch (p.kind) {
      case "closed":
      case "dismissed":
        this.#preview = { kind: to }; // focus or pointer leaving ends a dismissal
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

  // A fresh copy of the card each open, so embeds and read-only editors mount (and unmount) with it.
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

  // While open: follow scrolls and resizes (the card is position: fixed), re-place when the content grows
  // (an embed upgrading after its import), and close on Escape from anywhere. Returns the undo.
  #track(card: HTMLDivElement): () => void {
    const link = this.#link;
    const replace = (): void => { place(card, link); };
    const escape = (e: KeyboardEvent): void => {
      if (e.key !== "Escape") return;
      // Focus back on the link before the card goes, so focus never falls to <body> (that focusout would undo the dismissal).
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
