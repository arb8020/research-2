import { must } from "../../dom";

const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");

class EmbedCarousel extends HTMLElement {
  private track = document.createElement("div");
  private slides: HTMLElement[] = [];
  private current = 0;
  private scrollingTo: number | undefined;
  private counter = document.createElement("span");
  private prev = document.createElement("button");
  private next = document.createElement("button");
  private facadeByFrame = new Map<HTMLIFrameElement, HTMLAnchorElement>();

  connectedCallback(): void {
    this.track = must(this, ".carousel-track", HTMLDivElement);
    this.slides = [...this.track.querySelectorAll(".slide")].filter((el) => el instanceof HTMLElement);
    this.counter.className = "carousel-count";
    this.counter.setAttribute("aria-live", "polite");
    const nav = document.createElement("div");
    nav.className = "carousel-nav";
    for (const [button, label, step] of [[this.prev, "Previous slide", -1], [this.next, "Next slide", 1]] as const) {
      button.type = "button";
      button.className = `carousel-${step < 0 ? "prev" : "next"}`;
      button.setAttribute("aria-label", label);
      button.onclick = () => { this.go(this.current + step); };
    }
    nav.append(this.prev, this.counter, this.next);
    must(this, ".carousel", HTMLElement).append(nav);

    this.addEventListener("keydown", (e) => { this.key(e); });
    for (const facade of [...this.track.querySelectorAll("a.facade")].filter((el) => el instanceof HTMLAnchorElement)) {
      facade.addEventListener("click", (e) => { e.preventDefault(); this.play(facade); });
    }
    const mostlyInView = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        const i = entry.target instanceof HTMLElement ? this.slides.indexOf(entry.target) : -1;
        if (!entry.isIntersecting || i < 0 || (this.scrollingTo !== undefined && i !== this.scrollingTo)) continue;
        this.scrollingTo = undefined;
        this.settle(i);
      }
    }, { root: this.track, threshold: 0.6 });
    for (const grab of ["pointerdown", "wheel", "touchstart"]) {
      this.track.addEventListener(grab, () => { this.scrollingTo = undefined; }, { passive: true });
    }
    for (const slide of this.slides) mostlyInView.observe(slide);
    this.settle(0);
  }

  private key(e: KeyboardEvent): void {
    const to = new Map([["ArrowLeft", this.current - 1], ["ArrowRight", this.current + 1], ["Home", 0], ["End", this.slides.length - 1]]).get(e.key);
    if (to === undefined) return;
    e.preventDefault();
    this.go(to);
  }

  go(index: number): void {
    const i = Math.max(0, Math.min(this.slides.length - 1, index));
    const slide = this.slides[i];
    if (slide === undefined) return;
    if (i !== this.current) this.scrollingTo = i;
    this.track.scrollTo({ left: slide.offsetLeft, behavior: reducedMotion.matches ? "instant" : "smooth" });
    this.settle(i);
  }

  private settle(i: number): void {
    this.current = i;
    const n = this.slides.length;
    this.counter.textContent = `${String(i + 1)} / ${String(n)}`;
    this.prev.setAttribute("aria-disabled", String(i === 0));
    this.next.setAttribute("aria-disabled", String(i === n - 1));
    this.slides.forEach((slide, j) => {
      slide.inert = j !== i;
      if (j !== i) for (const frame of slide.querySelectorAll("iframe")) this.unplay(frame);
    });
  }

  private play(facade: HTMLAnchorElement): void {
    const id = facade.dataset.youtube ?? "";
    const start = facade.dataset.start ?? "";
    const frame = document.createElement("iframe");
    frame.src = `https://www.youtube-nocookie.com/embed/${encodeURIComponent(id)}?autoplay=1&rel=0${start === "" ? "" : `&start=${start}`}`;
    frame.title = facade.dataset.title ?? "video";
    frame.allow = "autoplay; encrypted-media; picture-in-picture; fullscreen";
    frame.allowFullscreen = true;
    this.facadeByFrame.set(frame, facade);
    facade.replaceWith(frame);
    frame.focus();
  }

  private unplay(frame: HTMLIFrameElement): void {
    const facade = this.facadeByFrame.get(frame);
    if (facade === undefined) throw new Error("carousel: an iframe with no facade to restore");
    this.facadeByFrame.delete(frame);
    frame.replaceWith(facade);
  }
}
customElements.define("embed-carousel", EmbedCarousel);
