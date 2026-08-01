/**
 * CodeMirror extension: --at gutter marks + popover with branch list + peek.
 *
 * Flow:
 * 1. Gold pip in gutter for lines touched by other branches
 * 2. Click pip → popover anchored to line listing branches
 * 3. Click a branch → peek panel slides out showing that branch's code
 * 4. Click "enter" → main editor swaps to that branch, peek shows old branch
 */

import {
  EditorView,
  GutterMarker,
  gutter,
  showTooltip,
  type Tooltip,
} from "@codemirror/view";
import { StateField, StateEffect, RangeSetBuilder } from "@codemirror/state";
import type { AtHit } from "./api";

/* ── types ─────────────────────────────────────────────────────── */

export interface AtLineData {
  line: number; // 1-indexed
  hits: AtHit[];
}

/* ── callbacks for peek/enter (wired by the app shell) ─────────── */

export interface AtCallbacks {
  onPeek: (branch: string, line: number) => void;
  onEnter: (branch: string) => void;
}

let _callbacks: AtCallbacks | null = null;

export function setAtCallbacks(cb: AtCallbacks) {
  _callbacks = cb;
}

/* ── state ─────────────────────────────────────────────────────── */

export const setAtData = StateEffect.define<AtLineData[]>();
export const openPopover = StateEffect.define<number | null>(); // 1-indexed line, null to close
export const setPeekBranch = StateEffect.define<string | null>();

interface AtState {
  lineData: Map<number, AtHit[]>;
  popoverLine: number | null;
  peekBranch: string | null;
}

const atState = StateField.define<AtState>({
  create: () => ({ lineData: new Map(), popoverLine: null, peekBranch: null }),
  update(state, tr) {
    let { lineData, popoverLine, peekBranch } = state;
    for (const e of tr.effects) {
      if (e.is(setAtData)) {
        lineData = new Map();
        for (const d of e.value) lineData.set(d.line, d.hits);
        popoverLine = null;
        peekBranch = null;
      }
      if (e.is(openPopover)) {
        popoverLine = popoverLine === e.value ? null : e.value;
        peekBranch = null; // reset peek when switching lines
      }
      if (e.is(setPeekBranch)) {
        peekBranch = e.value;
      }
    }
    return { lineData, popoverLine, peekBranch };
  },
});

/* ── gutter marker ─────────────────────────────────────────────── */

class AtMarker extends GutterMarker {
  constructor(readonly count: number) { super(); }
  toDOM() {
    const el = document.createElement("div");
    el.className = "cm-at-mark";
    el.title = `${this.count} branch${this.count > 1 ? "es" : ""}`;
    return el;
  }
}

const atGutter = gutter({
  class: "cm-at-gutter",
  markers(view) {
    const state = view.state.field(atState);
    const builder = new RangeSetBuilder<GutterMarker>();
    const lines = [...state.lineData.entries()]
      .filter(([ln]) => ln >= 1 && ln <= view.state.doc.lines)
      .sort((a, b) => a[0] - b[0]);
    for (const [ln, hits] of lines) {
      const line = view.state.doc.line(ln);
      builder.add(line.from, line.from, new AtMarker(hits.length));
    }
    return builder.finish();
  },
  domEventHandlers: {
    click(view, line) {
      const lineNo = view.state.doc.lineAt(line.from).number;
      view.dispatch({ effects: openPopover.of(lineNo) });
      return true;
    },
  },
});

/* ── popover tooltip ───────────────────────────────────────────── */

function createPopoverDom(
  view: EditorView,
  lineNo: number,
  hits: AtHit[],
  peekBranch: string | null,
): HTMLElement {
  const container = document.createElement("div");
  container.className = "mimir-popover";

  if (hits.length === 0) {
    container.innerHTML = `<div class="mimir-popover-empty">nobody here</div>`;
    return container;
  }

  const list = document.createElement("div");
  list.className = "mimir-popover-list";

  for (const hit of hits) {
    const row = document.createElement("div");
    row.className = "mimir-popover-row" + (peekBranch === hit.branch ? " active" : "");

    const rangeStr = hit.ranges
      .map(([a, b]) => (a === b ? String(a) : `${a}–${b}`))
      .join(", ");
    const ageStr =
      hit.age_hours < 1 ? `${Math.round(hit.age_hours * 60)}m` :
      hit.age_hours < 24 ? `${Math.round(hit.age_hours)}h` :
      `${Math.round(hit.age_hours / 24)}d`;

    row.innerHTML = `
      <span class="mimir-popover-branch">${hit.branch}</span>
      <span class="mimir-popover-meta">L${rangeStr} · ${ageStr}</span>
    `;

    row.addEventListener("click", (e) => {
      e.stopPropagation();
      view.dispatch({ effects: setPeekBranch.of(hit.branch) });
      _callbacks?.onPeek(hit.branch, hit.ranges[0][0]);
    });

    list.appendChild(row);
  }

  container.appendChild(list);

  return container;
}

const popoverTooltip = StateField.define<readonly Tooltip[]>({
  create: () => [],
  update(_, tr) {
    const state = tr.state.field(atState);
    if (state.popoverLine == null) return [];

    const ln = state.popoverLine;
    if (ln < 1 || ln > tr.state.doc.lines) return [];

    const line = tr.state.doc.line(ln);
    const hits = state.lineData.get(ln) ?? [];

    return [{
      pos: line.from,
      above: false,
      strictSide: true,
      arrow: false,
      create(view: EditorView) {
        const dom = createPopoverDom(view, ln, hits, state.peekBranch);
        return { dom, offset: { x: 0, y: 4 } };
      },
    }];
  },
  provide: (field) => showTooltip.computeN([field], (state) => state.field(field)),
});

/* ── click-away to dismiss ─────────────────────────────────────── */

const clickAwayHandler = EditorView.domEventHandlers({
  click(event, view) {
    const state = view.state.field(atState);
    if (state.popoverLine == null) return false;

    // Don't dismiss if clicking inside the popover
    const target = event.target as HTMLElement;
    if (target.closest(".mimir-popover")) return false;

    // Don't dismiss if clicking a gutter mark (that handler toggles)
    if (target.closest(".cm-at-mark")) return false;

    view.dispatch({ effects: openPopover.of(null) });
    return false;
  },
});

/* ── export ────────────────────────────────────────────────────── */

export function atExtension() {
  return [atState, atGutter, popoverTooltip, clickAwayHandler];
}
