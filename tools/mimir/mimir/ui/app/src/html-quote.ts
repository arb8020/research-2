/**
 * Text-quote selectors for rendered HTML.
 *
 * The durable handle is the selected string plus a short prefix/suffix
 * (Hypothes.is / W3C Web Annotation). Line numbers are a best-effort
 * map back into the source file so the agent still gets start_line.
 */

export function htmlEscape(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function locateQuote(
  source: string,
  quote: string,
): { startLine: number; endLine: number } | null {
  if (!quote) return null;
  const needles = [quote, htmlEscape(quote), quote.replace(/\s+/g, " ")];
  for (const candidate of needles) {
    if (!candidate) continue;
    const idx = source.indexOf(candidate);
    if (idx < 0) continue;
    const startLine = source.slice(0, idx).split("\n").length;
    const endLine = source.slice(0, idx + candidate.length).split("\n").length;
    return { startLine, endLine };
  }
  return null;
}

export function contextAround(
  text: string,
  start: number,
  end: number,
  radius = 32,
): { prefix: string; suffix: string } {
  return {
    prefix: text.slice(Math.max(0, start - radius), start),
    suffix: text.slice(end, Math.min(text.length, end + radius)),
  };
}

const SKIP = new Set(["SCRIPT", "STYLE", "NOSCRIPT"]);

export function collectTextNodes(root: Node): Text[] {
  const out: Text[] = [];
  const walk = (n: Node) => {
    if (n.nodeType === Node.ELEMENT_NODE && SKIP.has((n as Element).tagName)) {
      return;
    }
    if (n.nodeType === Node.TEXT_NODE) {
      if (n.nodeValue) out.push(n as Text);
      return;
    }
    for (let i = 0; i < n.childNodes.length; i++) {
      walk(n.childNodes[i]!);
    }
  };
  walk(root);
  return out;
}

export function unwrapMarks(root: Element, selector = "mark.mimir-ann"): void {
  const marks = Array.from(root.querySelectorAll(selector));
  for (const mark of marks) {
    const parent = mark.parentNode;
    if (!parent) continue;
    while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
    parent.removeChild(mark);
    (parent as Element).normalize?.();
  }
}

/** Wrap the first match of `quote` (preferring prefix+quote) in a <mark>. */
export function wrapQuote(
  root: Element,
  quote: string,
  id: string,
  prefix?: string,
): Element | null {
  const doc = root.ownerDocument;
  if (!doc || !quote) return null;
  const nodes = collectTextNodes(root);
  if (!nodes.length) return null;

  const full = nodes.map((n) => n.nodeValue ?? "").join("");
  let start = -1;
  let matched = quote;
  if (prefix) {
    const i = full.indexOf(prefix + quote);
    if (i >= 0) start = i + prefix.length;
  }
  if (start < 0) {
    // Selection.toString() inserts \n across blocks; text nodes do not.
    for (const needle of [quote, quote.replace(/\s+/g, " "), quote.replace(/\s+/g, "")]) {
      if (!needle) continue;
      const i = full.indexOf(needle);
      if (i >= 0) {
        start = i;
        matched = needle;
        break;
      }
    }
  }
  if (start < 0) return null;
  const end = start + matched.length;

  let acc = 0;
  let startNode: Text | null = null;
  let startOff = 0;
  let endNode: Text | null = null;
  let endOff = 0;
  for (const n of nodes) {
    const len = n.nodeValue?.length ?? 0;
    if (!startNode && acc + len > start) {
      startNode = n;
      startOff = start - acc;
    }
    if (acc + len >= end) {
      endNode = n;
      endOff = end - acc;
      break;
    }
    acc += len;
  }
  if (!startNode || !endNode) return null;

  const range = doc.createRange();
  range.setStart(startNode, startOff);
  range.setEnd(endNode, endOff);

  const mark = doc.createElement("mark");
  mark.className = "mimir-ann";
  mark.dataset.annId = id;
  try {
    range.surroundContents(mark);
  } catch {
    const frag = range.extractContents();
    mark.appendChild(frag);
    range.insertNode(mark);
  }
  return mark;
}
