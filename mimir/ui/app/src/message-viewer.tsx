/**
 * MessageViewer — renders markdown with syntax highlighting.
 * Text selection triggers a floating "Comment" toolbar.
 */

import { useRef, useCallback, useState, useEffect, useMemo } from "preact/hooks";
import { marked } from "marked";
import hljs from "highlight.js/lib/core";
import { isDark } from "./theme-mode";

// Register common languages
import javascript from "highlight.js/lib/languages/javascript";
import typescript from "highlight.js/lib/languages/typescript";
import python from "highlight.js/lib/languages/python";
import bash from "highlight.js/lib/languages/bash";
import json from "highlight.js/lib/languages/json";
import css from "highlight.js/lib/languages/css";
import xml from "highlight.js/lib/languages/xml";
import markdown from "highlight.js/lib/languages/markdown";
import yaml from "highlight.js/lib/languages/yaml";
import sql from "highlight.js/lib/languages/sql";
import diff from "highlight.js/lib/languages/diff";
import rust from "highlight.js/lib/languages/rust";
import go from "highlight.js/lib/languages/go";

hljs.registerLanguage("javascript", javascript);
hljs.registerLanguage("js", javascript);
hljs.registerLanguage("typescript", typescript);
hljs.registerLanguage("ts", typescript);
hljs.registerLanguage("tsx", typescript);
hljs.registerLanguage("jsx", javascript);
hljs.registerLanguage("python", python);
hljs.registerLanguage("py", python);
hljs.registerLanguage("bash", bash);
hljs.registerLanguage("sh", bash);
hljs.registerLanguage("shell", bash);
hljs.registerLanguage("zsh", bash);
hljs.registerLanguage("json", json);
hljs.registerLanguage("css", css);
hljs.registerLanguage("html", xml);
hljs.registerLanguage("xml", xml);
hljs.registerLanguage("markdown", markdown);
hljs.registerLanguage("md", markdown);
hljs.registerLanguage("yaml", yaml);
hljs.registerLanguage("yml", yaml);
hljs.registerLanguage("sql", sql);
hljs.registerLanguage("diff", diff);
hljs.registerLanguage("rust", rust);
hljs.registerLanguage("rs", rust);
hljs.registerLanguage("go", go);

// Configure marked with syntax highlighting
marked.setOptions({
  gfm: true,
  breaks: false,
});

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

const renderer = new marked.Renderer();
renderer.code = function ({ text, lang }: { text: string; lang?: string }) {
  // ```mermaid blocks become a placeholder that renderMermaid() fills with an
  // SVG after mount. The source stays in the DOM (in a <pre>) until then, so a
  // failed render degrades to the plain code block.
  if (lang === "mermaid") {
    return `<div class="md-mermaid" data-mermaid-src="${escapeHtml(text)}"><pre class="md-code-block"><code class="hljs language-mermaid">${escapeHtml(text)}</code></pre></div>`;
  }
  let highlighted: string;
  if (lang && hljs.getLanguage(lang)) {
    highlighted = hljs.highlight(text, { language: lang }).value;
  } else {
    highlighted = hljs.highlightAuto(text).value;
  }
  return `<pre class="md-code-block"><code class="hljs${lang ? ` language-${lang}` : ""}">${highlighted}</code></pre>`;
};

/** Lazy-loaded mermaid — a large dep, only pulled in when a diagram appears. */
let mermaidPromise: Promise<typeof import("mermaid").default> | null = null;
function loadMermaid(dark: boolean) {
  if (!mermaidPromise) {
    mermaidPromise = import("mermaid").then((m) => {
      m.default.initialize({
        startOnLoad: false,
        theme: dark ? "dark" : "default",
        securityLevel: "strict",
        fontFamily: "inherit",
      });
      return m.default;
    });
  }
  return mermaidPromise;
}

let mermaidSeq = 0;
let mermaidDark: boolean | null = null;

async function renderMermaid(container: HTMLElement, dark: boolean) {
  const blocks = container.querySelectorAll<HTMLElement>("[data-mermaid-src]");
  if (!blocks.length) return;
  const mermaid = await loadMermaid(dark);
  if (mermaidDark !== dark) {
    // Theme flipped since the last render — re-theme and redraw everything.
    mermaid.initialize({
      startOnLoad: false,
      theme: dark ? "dark" : "default",
      securityLevel: "strict",
      fontFamily: "inherit",
    });
    mermaidDark = dark;
    for (const el of blocks) delete el.dataset.mermaidDone;
  }
  for (const el of blocks) {
    const src = el.dataset.mermaidSrc;
    if (!src || el.dataset.mermaidDone === "1") continue;
    try {
      const { svg } = await mermaid.render(`mmd-${mermaidSeq++}`, src);
      el.innerHTML = svg;
      el.dataset.mermaidDone = "1";
    } catch {
      // Leave the source code block in place — better a readable fence than
      // a broken diagram.
      el.dataset.mermaidDone = "1";
    }
  }
}

interface Props {
  text: string;
  messageIndex?: number;
  onTextSelect?: (
    file: string,
    originalText: string,
    top: number,
    left: number,
  ) => void;
}

export function MessageViewer({ text, messageIndex, onTextSelect }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [toolbar, setToolbar] = useState<{ top: number; left: number; text: string } | null>(null);

  // Parse markdown
  const html = useMemo(() => {
    return marked.parse(text, { renderer }) as string;
  }, [text]);

  // Render any ```mermaid blocks into SVG after the markdown lands in the DOM.
  const dark = isDark.value;
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    void renderMermaid(container, dark);
  }, [html, dark]);

  // Handle text selection for annotation
  const handleMouseUp = useCallback(() => {
    if (!onTextSelect) return;

    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.toString().trim()) {
      setToolbar(null);
      return;
    }

    // Check selection is within our container
    const container = containerRef.current;
    if (!container) return;
    const anchorNode = sel.anchorNode;
    const focusNode = sel.focusNode;
    if (!anchorNode || !focusNode) return;
    if (!container.contains(anchorNode) || !container.contains(focusNode)) {
      setToolbar(null);
      return;
    }

    const selectedText = sel.toString().trim();
    if (!selectedText) {
      setToolbar(null);
      return;
    }

    const range = sel.getRangeAt(0);
    const rect = range.getBoundingClientRect();

    setToolbar({
      top: rect.top - 36,
      left: rect.left + rect.width / 2 - 40,
      text: selectedText,
    });
  }, [onTextSelect]);

  // Dismiss toolbar on click outside
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (target.closest(".md-sel-toolbar")) return;
      // Small delay so the mouseup handler runs first
      setTimeout(() => {
        const sel = window.getSelection();
        if (!sel || sel.isCollapsed) setToolbar(null);
      }, 10);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const handleComment = useCallback(() => {
    if (!toolbar || !onTextSelect) return;
    const file = messageIndex != null ? `__message__:${messageIndex}` : "__message__";
    onTextSelect(file, toolbar.text, toolbar.top + 40, toolbar.left);
    setToolbar(null);
    window.getSelection()?.removeAllRanges();
  }, [toolbar, onTextSelect]);

  return (
    <div class="message-viewer-md" ref={containerRef} onMouseUp={handleMouseUp}>
      <div
        class="md-content"
        dangerouslySetInnerHTML={{ __html: html }}
      />
      {toolbar && (
        <div
          class="md-sel-toolbar"
          style={{
            position: "fixed",
            top: `${toolbar.top}px`,
            left: `${toolbar.left}px`,
          }}
        >
          <button class="md-sel-btn" onClick={handleComment}>
            comment
          </button>
        </div>
      )}
    </div>
  );
}
