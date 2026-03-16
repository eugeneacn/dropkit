---
name: pdf-to-markdown
description: Convert PDF files to clean, structured Markdown using positional text extraction and layout analysis to detect headings, paragraphs, lists, and tables. Use when the user wants to convert, read, or extract content from a .pdf file into Markdown format.
metadata:
  version: "1.0"
---

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

Run the extraction script, replacing `$ARGUMENTS` with the input file path. This extracts every text item with its font size, position, and font name — which you will use in Step 3 to infer structure.

```bash
node scripts/extract.js "$ARGUMENTS"
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
