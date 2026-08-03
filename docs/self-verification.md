# Self-Verification for UI Development

How to visually verify frontend changes without requiring the user to check the browser.

## Setup

Playwright is installed as a dev dependency in `mimir/ui/app/`:

```bash
cd mimir/ui/app && npm install -D playwright
```

Chromium browser is bundled with Playwright — no separate install needed.

## Pattern: Headless Browser Verification

1. Start the mimir server in background with `--no-open`
2. Launch headless Chromium via Playwright
3. Navigate to the page, wait for elements
4. Inspect computed styles, class names, DOM structure
5. Take screenshots for visual verification
6. Clean up

```javascript
const { chromium } = require('playwright');

// Start server
// cd obol && git diff SHA1..SHA2 | mimir annotate --diff - --no-open &

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({
  viewport: { width: 1400, height: 900 },
  colorScheme: 'dark'  // or 'light'
});
await page.goto('http://127.0.0.1:PORT?annotate=1&mode=diff&diff=stdin');
await page.waitForSelector('.cm-line', { timeout: 5000 });
await page.waitForTimeout(1500);

// Inspect computed styles
const info = await page.evaluate(() => {
  const lines = document.querySelectorAll('.cm-line');
  return Array.from(lines).slice(0, 5).map(el => ({
    text: (el.textContent || '').slice(0, 40),
    classes: el.className,
    bg: getComputedStyle(el).backgroundColor,
  }));
});

// Interact (select text, click, etc.)
await page.click('.cm-content');
await page.keyboard.press('Meta+a');

// Screenshot
await page.screenshot({ path: '/tmp/verification.png' });

// Read screenshot with Read tool to see it inline
await browser.close();
```

## Why This Exists

CM6 (CodeMirror 6) owns its DOM — it generates scoped CSS class names, 
manages a virtual viewport, and recreates `.cm-line` elements on scroll. 
This makes it impossible to reason about CSS specificity from source alone.

We spent many cycles trying to fix diff line highlighting by guessing at
CSS selectors. The breakthrough: using headless Playwright to inspect
`getComputedStyle()` on actual rendered elements. This immediately showed:

- Classes WERE being applied (the StateField decorations worked all along)
- Colors were too subtle (nearly identical to the ground color)
- Selection layer was at z-index:-2, hidden behind opaque line backgrounds

All three issues were invisible from source code inspection.

## Key Discoveries

### CM6 Selection Layer
`drawSelection()` renders at `z-index: -2` (behind content). Opaque 
`background-color` on `.cm-line` covers it. Fix: use `rgba()` backgrounds 
with ~0.7 opacity so the selection shows through.

### CM6 Theme Scoping
`EditorView.theme()` generates scoped selectors like `.ͼ1 .cm-line`. 
Global CSS with `.cm-editor .cm-line.diff-line-add` can't compete.
Fix: use `EditorView.baseTheme()` for un-scoped rules, plus global CSS 
with `!important` as a belt-and-suspenders fallback.

### screencapture vs Headless
`screencapture -x` captures the actual screen — useful but interferes with 
the user's workflow (steals focus, captures wrong window). Headless 
Playwright runs independently in the background. Use `screencapture` only 
as a last resort when you need to see exactly what the user sees.

## Verification Checklist

When making visual changes to the diff viewer or annotation UI:

1. Build: `cd mimir/ui/app && npm run build`
2. Start server: `mimir annotate --diff - --no-open < diff_content`
3. Run Playwright script to inspect + screenshot
4. Read the screenshot with the `Read` tool
5. Check computed styles match expectations
6. Only then ask user to test
