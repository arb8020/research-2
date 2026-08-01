/**
 * CodeMirror extension: --at gutter marks + fan-out widgets.
 *
 * Shows a small accent pip in the gutter for lines touched by other branches.
 * Click or hover a pip → fan-out widget appears below the line showing
 * which branches touch it, age, worktree links.
 */

import {
  EditorView,
  GutterMarker,
  gutter,
  Decoration,
  WidgetType,
  type DecorationSet,
} from "@codemirror/view";
import { StateField, StateEffect, RangeSetBuilder } from "@codemirror/state";
import type { AtHit } from "./api";

/* ── types ─────────────────────────────────────────────────────── */

export interface AtLineData {
  line: number; // 1-indexed
  hits: AtHit[];
}

/* ── state: which lines have --at data ─────────────────────────── */

export const setAtData = StateEffect.define<AtLineData[]>();
export const toggleFanOut = StateEffect.define<number>(); // 1-indexed line

interface AtState {
  lineData: Map<number, AtHit[]>; // line → hits
  openFan: number | null; // which line's fan-out is open
}

const atState = StateField.define<AtState>({
  create: () => ({ lineData: new Map(), openFan: null }),
  update(state, tr) {
    let { lineData, openFan } = state;
    for (const e of tr.effects) {
      if (e.is(setAtData)) {
        lineData = new Map();
        for (const d of e.value) {
          lineData.set(d.line, d.hits);
        }
        openFan = null; // close fan when data changes
      }
      if (e.is(toggleFanOut)) {
        openFan = openFan === e.value ? null : e.value;
      }
    }
    return { lineData, openFan };
  },
});

/* ── gutter marker (the small accent pip) ──────────────────────── */

class AtMarker extends GutterMarker {
  constructor(readonly count: number) {
    super();
  }
  toDOM() {
    const el = document.createElement("div");
    el.className = "cm-at-mark";
    el.title = `${this.count} branch${this.count > 1 ? "es" : ""} touch this line`;
    return el;
  }
}

const atGutter = gutter({
  class: "cm-at-gutter",
  markers(view) {
    const state = view.state.field(atState);
    const builder = new RangeSetBuilder<GutterMarker>();
    // Must add markers in document order
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
      view.dispatch({ effects: toggleFanOut.of(lineNo) });
      return true;
    },
  },
});

/* ── fan-out widget ────────────────────────────────────────────── */

class FanOutWidget extends WidgetType {
  constructor(
    readonly lineNo: number,
    readonly hits: AtHit[],
    readonly branchesScanned: number
  ) {
    super();
  }

  eq(other: FanOutWidget) {
    return this.lineNo === other.lineNo;
  }

  toDOM() {
    if (this.hits.length === 0) {
      const el = document.createElement("div");
      el.className = "mimir-fan-empty";
      el.textContent = `line ${this.lineNo} — nobody here · ${this.branchesScanned} branches scanned`;
      return el;
    }

    const fan = document.createElement("div");
    fan.className = "mimir-fan";

    const header = document.createElement("div");
    header.className = "mimir-fan-header";
    header.textContent = `line ${this.lineNo} · ${this.hits.length} branch${this.hits.length > 1 ? "es" : ""}`;
    fan.appendChild(header);

    for (const hit of this.hits) {
      const entry = document.createElement("div");
      entry.className = "mimir-fan-entry";

      const branch = document.createElement("span");
      branch.className = "mimir-fan-branch";
      branch.textContent = hit.branch;

      const rangeStr = hit.ranges
        .map(([a, b]) => (a === b ? String(a) : `${a}–${b}`))
        .join(", ");
      const ageStr =
        hit.age_hours < 1
          ? `${Math.round(hit.age_hours * 60)}m`
          : hit.age_hours < 24
            ? `${Math.round(hit.age_hours)}h`
            : `${Math.round(hit.age_hours / 24)}d`;

      const detail = document.createElement("span");
      detail.className = "mimir-fan-detail";
      detail.textContent = `lines ${rangeStr} · ${ageStr} ago`;

      entry.appendChild(branch);
      entry.appendChild(detail);

      if (hit.worktree) {
        const action = document.createElement("a");
        action.className = "mimir-fan-action";
        action.textContent = `open → line ${hit.line_in_branch ?? hit.ranges[0][0]}`;
        action.href = "#";
        action.onclick = (e) => e.preventDefault();
        entry.appendChild(action);
      } else {
        const noWt = document.createElement("span");
        noWt.className = "mimir-fan-detail";
        noWt.textContent = "no worktree";
        entry.appendChild(noWt);
      }

      fan.appendChild(entry);
    }

    return fan;
  }

  ignoreEvent() {
    return false;
  }
}

/* ── decoration field (fan-out widgets) ─────────────────────────── */

const fanOutDecorations = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(_, tr) {
    const state = tr.state.field(atState);
    if (state.openFan == null) return Decoration.none;

    const ln = state.openFan;
    const hits = state.lineData.get(ln) ?? [];
    if (ln < 1 || ln > tr.state.doc.lines) return Decoration.none;

    const line = tr.state.doc.line(ln);
    const widget = Decoration.widget({
      widget: new FanOutWidget(
        ln,
        hits,
        // Sum total branches from all line data as rough "scanned" count
        state.lineData.size > 0
          ? Math.max(
              ...Array.from(state.lineData.values()).map((h) => h.length)
            )
          : 0
      ),
      side: 1, // after the line
      block: true,
    });
    return Decoration.set([widget.range(line.to)]);
  },
  provide: (field) => EditorView.decorations.from(field),
});

/* ── CSS animation ─────────────────────────────────────────────── */

const fanOutAnimation = EditorView.theme({
  "@keyframes mimir-fan-enter": {
    from: { opacity: "0", transform: "translateY(-4px)" },
    to: { opacity: "1", transform: "translateY(0)" },
  },
});

/* ── export: the full extension ────────────────────────────────── */

export function atExtension() {
  return [atState, atGutter, fanOutDecorations, fanOutAnimation];
}
