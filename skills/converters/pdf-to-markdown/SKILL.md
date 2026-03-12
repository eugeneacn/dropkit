# PDF to Markdown Converter

Convert a PDF file to clean, structured Markdown using text extraction with positional analysis.

## Instructions

You are a document conversion agent. When the user provides a PDF file path via `$ARGUMENTS`, convert it to well-structured Markdown by extracting text with layout data and intelligently reconstructing the document structure.

### Step 1: Verify the environment

Check if the required npm package is available. If not, install it:

```bash
npm list pdfjs-dist || npm install pdfjs-dist@4.7.76
```

### Step 2: Extract text with positional data

Run this Node.js script, replacing `$ARGUMENTS` with the input file path. This extracts every text item with its font size, position, and font name — which you will use in Step 3 to infer structure.

```bash
node -e "
const fs = require('fs');
const path = require('path');
const pdfjsLib = require('pdfjs-dist/legacy/build/pdf.js');

async function extract(filePath) {
  const data = new Uint8Array(fs.readFileSync(filePath));
  const doc = await pdfjsLib.getDocument({ data, useSystemFonts: true }).promise;
  const numPages = doc.numPages;
  const pages = [];

  for (let p = 1; p <= numPages; p++) {
    const page = await doc.getPage(p);
    const content = await page.getTextContent();
    const viewport = page.getViewport({ scale: 1.0 });

    // Group text items into lines by Y position
    const items = content.items.map(item => ({
      text: item.str,
      x: Math.round(item.transform[4] * 100) / 100,
      y: Math.round((viewport.height - item.transform[5]) * 100) / 100,
      fontSize: Math.round(item.transform[0] * 100) / 100,
      fontName: item.fontName || '',
      width: Math.round(item.width * 100) / 100,
      height: Math.round(item.height * 100) / 100
    }));

    // Sort by Y (top to bottom), then X (left to right)
    items.sort((a, b) => a.y - b.y || a.x - b.x);

    // Merge items into lines (items within 3pt Y tolerance = same line)
    const lines = [];
    let currentLine = null;

    for (const item of items) {
      if (!item.text.trim() && !item.text.includes(' ')) continue;
      if (!currentLine || Math.abs(item.y - currentLine.y) > 3) {
        currentLine = {
          y: item.y,
          x: item.x,
          fontSize: item.fontSize,
          fontName: item.fontName,
          segments: [item]
        };
        lines.push(currentLine);
      } else {
        currentLine.segments.push(item);
        // Track the dominant font size for the line
        if (item.text.trim().length > 0) {
          currentLine.fontSize = Math.max(currentLine.fontSize, item.fontSize);
        }
      }
    }

    // Build line objects with gap detection (for table columns)
    const processedLines = lines.map(line => {
      const segs = line.segments.sort((a, b) => a.x - b.x);
      const gaps = [];
      for (let i = 1; i < segs.length; i++) {
        const gapStart = segs[i - 1].x + segs[i - 1].width;
        const gapSize = segs[i].x - gapStart;
        if (gapSize > 15) gaps.push({ pos: gapStart, size: Math.round(gapSize) });
      }
      const text = segs.map(s => s.text).join('');
      return {
        text: text,
        x: Math.round(line.x),
        fontSize: line.fontSize,
        fontName: line.fontName,
        hasLargeGaps: gaps.length > 0,
        gapCount: gaps.length,
        segments: gaps.length > 0 ? segs.map(s => ({ text: s.text, x: Math.round(s.x) })) : undefined
      };
    });

    pages.push({
      page: p,
      width: Math.round(viewport.width),
      height: Math.round(viewport.height),
      lines: processedLines
    });
  }

  // Compute font size statistics for structure detection
  const allFontSizes = pages.flatMap(p => p.lines.map(l => l.fontSize)).filter(s => s > 0);
  const fontFreq = {};
  allFontSizes.forEach(s => { fontFreq[s] = (fontFreq[s] || 0) + 1; });
  const bodyFontSize = parseFloat(Object.entries(fontFreq).sort((a, b) => b[1] - a[1])[0]?.[0] || 12);

  const output = {
    file: path.basename(filePath),
    totalPages: numPages,
    bodyFontSize: bodyFontSize,
    fontSizeDistribution: fontFreq,
    pages: pages
  };

  // Write structured extraction to a temp JSON for the agent to process
  const jsonOut = filePath.replace(/\.pdf$/i, '') + '.extracted.json';
  fs.writeFileSync(jsonOut, JSON.stringify(output, null, 2));
  console.log('EXTRACTED: ' + jsonOut);
  console.log('PAGES: ' + numPages);
  console.log('BODY_FONT_SIZE: ' + bodyFontSize);
  console.log('FONT_SIZES: ' + JSON.stringify(fontFreq));
}

extract('$ARGUMENTS').catch(e => { console.error('ERROR:', e.message); process.exit(1); });
"
```

### Step 3: Convert extracted data to Markdown

This is the critical step. Read the `.extracted.json` file and use the positional data to intelligently reconstruct the Markdown. Apply these rules:

#### Heading detection
- Lines with `fontSize > bodyFontSize * 1.4` → `# H1`
- Lines with `fontSize > bodyFontSize * 1.2` → `## H2`
- Lines with `fontSize > bodyFontSize * 1.05` → `### H3`
- Lines with bold font names (containing "Bold" but not larger) → `**bold text**`
- Adjust thresholds if the document uses unusual sizing — inspect the `fontSizeDistribution` to calibrate

#### Paragraph assembly
- Consecutive lines at body font size with similar X positions → merge into a single paragraph
- A line that ends without punctuation and the next line starts lowercase → continuation of the same paragraph
- A blank gap (Y distance between lines > 1.5× line height) → paragraph break
- Lines with significantly larger X indentation (>30pt more than body) → blockquote or indented content

#### List detection
- Lines starting with `•`, `–`, `-`, `*`, `○` → unordered list items
- Lines starting with `1.`, `2.`, `a)`, `(i)` etc → ordered list items
- Indented lines following a list item → sub-items, use nested list syntax
- Consistent X indentation shift from parent → nesting level

#### Table detection
- Lines where `hasLargeGaps: true` AND 2+ consecutive lines have the same `gapCount` → likely a table
- Use the `segments` array to reconstruct columns — items with similar X positions across rows belong to the same column
- Align columns by X-coordinate clustering: group segment X values that are within 10pt of each other
- Output as Markdown table with `|` delimiters and `---` separator row
- If column alignment is ambiguous, prefer wider columns and note the uncertainty

#### Header/footer removal
- Lines appearing at the same Y position on multiple pages (within 5pt) with the same or incrementing text (page numbers) → headers/footers, remove them
- Common patterns: page numbers, document titles repeated on every page, dates in margins

#### Special content
- Lines that are just a horizontal sequence of `_`, `-`, or `=` → `---` horizontal rule
- Superscript-sized text immediately after a word → footnote reference, convert to `[^N]`
- Text blocks at bottom of page with small font matching footnote refs → footnote definitions

### Step 4: Write the final Markdown

- Write the result to `{basename}.md`
- Delete the intermediate `.extracted.json` file

### Step 5: Report the result

After conversion:

1. Show the user a summary: page count, detected headings, tables found, any footnotes
2. Flag any areas of uncertainty (e.g., "Pages 3-4 had complex multi-column layout — please review")
3. Ask if they'd like adjustments:
   - Keeping or removing headers/footers
   - Handling multi-column layouts differently (merge vs. separate sections)
   - Extracting images (requires additional tooling)
   - Splitting into one file per page/chapter

### Input format

The user provides the argument as a file path, e.g.:

- `docs/whitepaper.pdf`
- `./invoice.pdf`
- `/absolute/path/to/report.pdf`

If the user provides a glob pattern like `docs/*.pdf`, loop through each file and convert them individually.

### Edge cases to handle

- **Scanned PDFs (image-only)**: If extraction yields zero or near-zero text items, inform the user the PDF appears to be scanned/image-based and suggest OCR tools like `tesseract` or cloud OCR APIs. Do not attempt to process further without OCR.
- **Multi-column layouts**: Detect when a page has two distinct clusters of X positions (e.g., 50-280 and 310-540). Process left column fully before right column, separated by a clear break.
- **Mixed orientation pages**: Some pages may be landscape in a portrait doc. The width/height values per page will reveal this — adjust column detection accordingly.
- **Embedded links**: pdfjs-dist does not extract hyperlinks from annotations by default. If the user needs links, note this limitation and suggest using a tool that reads PDF annotations.
- **Mathematical notation**: PDF math is often custom-positioned symbols. Flag any lines with unusual font names (e.g., Symbol, CMSY, CMMI) and recommend the user review those sections manually.
- **CJK / RTL text**: May require different line-merging logic. If detected, note this to the user and adjust paragraph assembly direction.
- **Password-protected PDFs**: pdfjs-dist will throw an error. Catch it and ask the user for the password, then retry with `{ data, password }`.
