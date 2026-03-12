---
name: markdown-to-html
description: Use when converting an existing markdown file into a polished, scrollable HTML document with sidebar navigation. Trigger on requests to render, convert, or export a .md file to HTML, produce a shareable web-page version of a document, or generate a readable HTML report — not for slides, presentations, or pitch decks.
---

# Markdown to HTML

Converts a markdown document into a polished, self-contained single-page HTML document with sticky header, sidebar navigation, and Mermaid diagram support.

---

## Pre-Build Step: Analyse the Document First

Before writing any HTML, read the entire markdown file and produce a brief **structure report**:

1. List the top-level (`#`) and second-level (`##`) headings found
2. Identify the document type (e.g. technical reference, guide, report, specification, methodology)
3. Note any special content types present: tables, code blocks, Mermaid diagrams, ASCII diagrams, numbered/bulleted lists, callout patterns (e.g. bold lead-ins like `**Note:**`, `**Important:**`, `**Stop and Wait**`)
4. Propose:
    - A **sidebar navigation tree** (which headings become nav groups and nav links)
    - A **header title** and subtitle (derived from the `#` heading and document purpose)
    - **Accent colour** recommendation (navy `#0f1f3d` is the default; suggest an alternative if the document has a strong thematic identity — e.g. green for a sustainability report)
    - Whether the document warrants **tier/category colour-coding** (use when sections represent distinct phases, tiers, or categories; skip for uniform reference documents)

Present this report and **wait for approval** before building the HTML.

---

## Design Requirements

### Must-Have

- **Single `.html` file** — all CSS, JS, and fonts inlined; no external dependencies except the Mermaid CDN (see below)
- **Works offline** when opened by double-click (Mermaid diagrams require a one-time internet load; all other content is fully offline)
- **Self-contained** — safe to email or share; recipient needs only a browser

### Visual Design

- **Header:** Dark navy `#0f1f3d` background, white text, sticky (stays at top on scroll)
    - Left side: document title (bold) + subtitle in muted blue
    - Right side: flat anchor-link nav to major sections
- **Sidebar:** Fixed left sidebar (~220–240 px wide), white background, subtle right border
    - Grouped navigation with small-caps group labels
    - Nav links highlight the active section on scroll (IntersectionObserver)
    - Collapsible on mobile (hamburger toggle or auto-hide below 900 px)
- **Main content area:** Max-width ~960 px, generous padding, flows to the right of the sidebar
- **Font:** System sans-serif stack: `-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif`
- **Body text:** `#1e293b`, line-height `1.7`
- **Headings:**
    - `h1` in `#0f1f3d` (navy), `1.9rem`, `font-weight: 800`
    - `h2` in `#1a3a6b` (mid-navy), `1.35rem`, with a bottom border separator, `scroll-margin-top: 72px`
    - `h3` in `#3d5a80` (slate), `1.05rem`
    - `h4` in body colour, small-caps / uppercase, `0.9rem`
- **Background:** `#f8fafc` (off-white page), `#ffffff` sidebar and content cards

### Colour-Coded Categories (use only when appropriate — see Pre-Build Step)

When the document has distinct tiers, phases, or categories, assign each a colour trio (background / border / text) and apply it to section headers, phase cards, and sidebar indicators. Default palette:

- Category 1 / Tier 1: green family — `#e6f4ee` / `#a7d5be` / `#1e6b4f`
- Category 2 / Tier 2: amber family — `#fef3dc` / `#f5c97a` / `#7a4f00`
- Category 3 / Tier 3: purple family — `#f3e6f8` / `#d4a4e8` / `#5a1a6b`
- Category 4+: extend with teal, rose, blue families as needed

### Callout Boxes

Detect and render semantic callout patterns as styled boxes with a coloured left border:

|Pattern|Style|
|---|---|
|`**⏸ Stop and Wait**` or stop/checkpoint language|Amber left border (`#f59e0b`), warm background|
|`**🔴` or blocker/conflict language|Red left border (`#dc2626`), light red background|
|`**Note:**`, `**Important:**`, informational asides|Blue left border (`#4a90d9`), light blue background|
|`**Tip:**`, positive guidance|Green left border (`#16a34a`), light green background|
|`**Warning:**`|Orange left border, light orange background|

Apply these by scanning for bold lead-ins and semantic keywords; do not require exact marker syntax.

### Tables

- Header row: `#1a3a6b` background, white text
- Alternating row shading (`#f8fafc` on even rows)
- Hover highlight with `#e8f0fb`
- `font-size: 0.82rem`, `overflow-x: auto` wrapper for wide tables

### Code and Pre-formatted Blocks

- Background: `#1e2d40` (dark navy)
- Text: `#c9d9ec` (light blue-grey)
- Font: `'Cascadia Code', 'Fira Code', 'Courier New', monospace`
- `font-size: 0.75rem`, `border-radius: 8px`, `overflow-x: auto`
- Apply to both fenced code blocks and ASCII diagram `<pre>` blocks

### Hero Banner (optional — use for documents with a strong title and purpose statement)

When the document has a clear title and purpose paragraph at the top, render these inside a dark navy gradient banner (`linear-gradient(135deg, #0f1f3d, #1a3a6b)`) with white text and optional badge pills (document version, key tags derived from frontmatter or opening metadata).

---

## Content Mapping: Markdown → HTML

|Markdown Element|HTML Treatment|
|---|---|
|`# Heading`|Page `<title>` + hero banner title (if used) + `<h1>`|
|`## Heading`|`<h2>` with `id` for anchor links; also appears in sidebar nav|
|`### Heading`|`<h3>`|
|`#### Heading`|`<h4>`|
|Paragraph|`<p>`|
|`**bold**`|`<strong>`|
|`*italic*` or `_italic_`|`<em>`|
|`` `inline code` ``|`<code>` styled with navy background, monospace font|
|Fenced code block|`<pre><code>` dark block|
|`- list` / `* list`|`<ul><li>`|
|`1. list`|`<ol><li>`|
|`> blockquote`|Styled blockquote with left accent bar|
|`---` horizontal rule|`<hr>` with subtle border|
|`[text](url)`|`<a>` (external links open in `_blank` with `rel="noopener"`)|
|Tables|Styled `<table>` with `overflow-x` wrapper|
|ASCII art in `` ``` `` blocks|`<pre>` with dark code styling|
|Mermaid diagrams|See Mermaid section below|

---

## Mermaid Diagram Handling

### Detection

Detect fenced code blocks with the language tag `mermaid`:

````
```mermaid
graph TD
    A --> B
```
````

### Rendering Approach

Use the **Mermaid CDN** for rendering. Place this script tag once, in the `<head>`:

```html
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
```

Initialise Mermaid once in the `<body>` before `</body>`:

```html
<script>
  mermaid.initialize({
    startOnLoad: true,
    theme: 'base',
    themeVariables: {
      primaryColor: '#1a3a6b',
      primaryTextColor: '#ffffff',
      primaryBorderColor: '#0f1f3d',
      lineColor: '#64748b',
      secondaryColor: '#e8f0fb',
      tertiaryColor: '#f8fafc',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      fontSize: '13px'
    }
  });
</script>
```

Replace each Mermaid fenced block with:

```html
<div class="mermaid-wrap">
  <div class="mermaid">
    [diagram source here]
  </div>
</div>
```

Style the wrapper:

```css
.mermaid-wrap {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 24px;
  margin: 16px 0 24px;
  overflow-x: auto;
  text-align: center;
}
```

### Offline / CDN Failure Fallback

If the Mermaid CDN fails to load (user is offline), show the raw diagram source in a styled `<pre>` block so content is never lost:

```html
<noscript>
  <pre class="mermaid-fallback">[diagram source]</pre>
</noscript>
```

Additionally, add a JS error handler:

```javascript
window.addEventListener('error', function(e) {
  if (e.target && e.target.src && e.target.src.includes('mermaid')) {
    document.querySelectorAll('.mermaid').forEach(el => {
      const pre = document.createElement('pre');
      pre.className = 'mermaid-fallback';
      pre.textContent = el.textContent;
      el.parentNode.replaceChild(pre, el);
    });
  }
}, true);
```

### Diagram Types: Special Handling

|Mermaid Type|Notes|
|---|---|
|`flowchart` / `graph`|Renders as-is; ensure left-to-right (`LR`) or top-down (`TD`) is explicit|
|`sequenceDiagram`|Renders as-is; increase wrapper padding to `32px`|
|`gantt`|Use `overflow-x: auto` on wrapper; gantt charts are often wide|
|`classDiagram`|Renders as-is|
|`erDiagram`|Renders as-is|
|`stateDiagram-v2`|Use `stateDiagram-v2` tag (not `stateDiagram`) for best results|
|`mindmap`|Supported in Mermaid v10+; test rendering|
|`journey`|User journey diagrams; renders as-is|

### ASCII Diagrams (non-Mermaid)

For plain ASCII art in `` ``` `` blocks that are **not** tagged as `mermaid` — render as a dark `<pre>` code block (same styling as code). Do not attempt to convert ASCII art to Mermaid.

---

## JavaScript Behaviour

### Active Sidebar Navigation

Use `IntersectionObserver` to track which `<section>` or heading is in the viewport and apply an `.active` class to the matching sidebar nav link:

```javascript
const links = document.querySelectorAll('.nav-link');
const observer = new IntersectionObserver(entries => {
  entries.forEach(e => {
    if (e.isIntersecting) {
      links.forEach(l => l.classList.remove('active'));
      const match = document.querySelector(`.nav-link[href="#${e.target.id}"]`);
      if (match) match.classList.add('active');
    }
  });
}, { rootMargin: '-60px 0px -70% 0px' });
document.querySelectorAll('section[id], h2[id]').forEach(s => observer.observe(s));
```

### Smooth Scroll

Add `html { scroll-behavior: smooth; }` in CSS.

### Mobile Sidebar Toggle

Below 900 px, hide the sidebar and show a hamburger button in the header. Clicking it toggles a `.sidebar-open` class on `<body>` that slides in the sidebar as an overlay.

---

## Structural HTML Template

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>[DOCUMENT TITLE]</title>
  <!-- Mermaid CDN (only external dependency) -->
  <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
  <style>
    /* All CSS inlined here */

    /* Print TOC: hidden on screen, revealed in print */
    .print-toc { display: none; }

    /* Print stylesheet — see Print / PDF Export section */
    @media print { /* ... */ }
  </style>
</head>
<body>
  <header>
    <!-- Sticky dark navy header: title + subtitle + anchor nav -->
  </header>

  <!-- Print-only TOC: populated by JS, hidden on screen -->
  <nav class="print-toc" aria-hidden="true">
    <h2>Table of Contents</h2>
    <!-- JS inserts <ul> here at init time -->
  </nav>

  <div class="layout">
    <aside>
      <!-- Fixed sidebar: grouped nav links, active state on scroll -->
    </aside>
    <main>
      <!-- Document content: hero (optional), sections, all markdown rendered to HTML -->
    </main>
  </div>
  <footer>
    <!-- Document name and key tags -->
  </footer>
  <script>
    /* Active nav observer + mobile toggle + Mermaid init */
    mermaid.initialize({ ... });

    /* Build print-only TOC from headings — see Print / PDF Export section */
  </script>
</body>
</html>
```

---

## Print / PDF Export

Every generated document must support **Ctrl+P → Save as PDF** cleanly. The print output replaces the screen sidebar with a table of contents page, collapses the layout to full-width, and preserves all colors and backgrounds.

### Print-Only Table of Contents

The sidebar nav is a screen affordance — scrolling and active-link highlighting have no meaning in print. Replace it with a static TOC that:

- Appears as its **own page** before the document body (`break-after: page`)
- Is **hidden on screen** (`display: none`) and shown only in print
- Is **built by JS** from all `h2[id]` and `h3[id]` elements at init time
- Uses indentation to distinguish `h2` (top-level) from `h3` (sub-item)

```javascript
// Build print-only TOC — run once at page load
(function buildPrintToc() {
  const toc = document.querySelector('.print-toc');
  if (!toc) return;
  const ul = document.createElement('ul');
  document.querySelectorAll('h2[id], h3[id]').forEach(h => {
    const li = document.createElement('li');
    li.className = h.tagName.toLowerCase(); // 'h2' or 'h3'
    const a = document.createElement('a');
    a.href = '#' + h.id;
    a.textContent = h.textContent;
    li.appendChild(a);
    ul.appendChild(li);
  });
  toc.appendChild(ul);
})();
```

Style the TOC for print legibility:

```css
/* Screen: hidden */
.print-toc { display: none; }

/* Print: full-page TOC before content */
@media print {
  .print-toc {
    display: block !important;
    page-break-after: always;
    break-after: page;
  }
  .print-toc h2 {
    font-size: 1.4rem;
    margin-bottom: 1rem;
    border-bottom: 2px solid #0f1f3d;
    padding-bottom: 0.5rem;
  }
  .print-toc ul {
    list-style: none;
    padding: 0;
    margin: 0;
  }
  .print-toc li.h2 {
    margin-top: 0.6rem;
    font-weight: 600;
  }
  .print-toc li.h3 {
    margin-left: 1.5rem;
    font-weight: 400;
    font-size: 0.9rem;
  }
  .print-toc a {
    color: #0f1f3d;
    text-decoration: none;
  }
}
```

### Required `@media print` block

Add this block in the `<style>` tag, after all screen styles:

```css
@media print {
  @page {
    size: portrait;
    margin: 1.5cm 2cm;
  }

  /* Hide screen-only chrome */
  header,
  aside,
  footer,
  .hamburger {
    display: none !important;
  }

  /* Collapse sidebar layout to full-width single column */
  .layout {
    display: block !important;
  }

  main {
    max-width: 100% !important;
    margin: 0 !important;
    padding: 0 !important;
  }

  /* Force background colors, gradients, and borders to print */
  * {
    -webkit-print-color-adjust: exact !important;
    print-color-adjust: exact !important;
  }

  /* Keep callouts, tables, code blocks, and diagrams intact */
  pre,
  blockquote,
  .callout,
  table,
  .mermaid-wrap {
    page-break-inside: avoid;
    break-inside: avoid;
  }

  /* Prevent headings from orphaning at page bottom */
  h2, h3, h4 {
    page-break-after: avoid;
    break-after: avoid;
  }
}
```

---

## Quality Checklist

Before delivering the HTML, verify:

- [ ] All `##` headings have an `id` attribute and appear in the sidebar
- [ ] All `scroll-margin-top` values account for sticky header height
- [ ] Every table has an `overflow-x: auto` wrapper div
- [ ] All Mermaid blocks are replaced with `<div class="mermaid">` + fallback
- [ ] No external resources except the Mermaid CDN script
- [ ] No `localStorage` or `sessionStorage` calls
- [ ] File opens correctly by double-click (tested mentally: no relative imports, no fetch calls, no server-side dependencies)
- [ ] Callout boxes applied to all detected stop/wait, blocker, note, and tip patterns
- [ ] Mobile: sidebar hidden below 900 px, toggle button present
- [ ] Footer credits the source file name
- [ ] Output written with correct filename
- [ ] `@media print` block present: portrait page with margins, `header`/`aside`/`footer` hidden, `.layout` collapsed to single column, `print-color-adjust: exact` on `*`, `break-inside: avoid` on `pre`/`.callout`/`table`/`.mermaid-wrap`, headings use `break-after: avoid`
- [ ] `<nav class="print-toc">` present, hidden on screen (`display: none`), JS builds TOC from all `h2[id]` and `h3[id]` at load time, TOC occupies its own page in print (`break-after: page`)

---

## Output

Deliver the complete HTML as a single file. Do not truncate. The file must be copy-pasteable into a `.html` file and immediately usable.