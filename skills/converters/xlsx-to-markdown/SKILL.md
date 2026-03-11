# Excel to Markdown Converter

Convert an Excel (.xls/.xlsx) file to clean Markdown tables.

## Instructions

You are a document conversion agent. When the user provides an Excel file path via `$ARGUMENTS`, convert each sheet to a Markdown file with well-formatted tables.

### Step 1: Verify the environment

Check if the `xlsx` npm package (SheetJS) is available. If not, install it:

```bash
npm list xlsx || npm install xlsx
```

### Step 2: Convert the file

Run this Node.js script, replacing `$ARGUMENTS` with the input file path:

```bash
node -e "
const XLSX = require('xlsx');
const fs = require('fs');
const path = require('path');

const filePath = '$ARGUMENTS';
const wb = XLSX.readFile(filePath);
const baseName = path.basename(filePath).replace(/\.(xlsx?|csv)$/i, '');
const results = [];

wb.SheetNames.forEach(name => {
  const rows = XLSX.utils.sheet_to_json(wb.Sheets[name], { header: 1, defval: '' });
  if (!rows.length) { results.push({ sheet: name, status: 'empty' }); return; }

  // Find the header row (first row with content)
  let hdrIdx = rows.findIndex(r => r.some(c => String(c).trim() !== ''));
  if (hdrIdx === -1) { results.push({ sheet: name, status: 'empty' }); return; }

  const headers = rows[hdrIdx].map(c => String(c).trim() || '—');
  const dataRows = rows.slice(hdrIdx + 1).filter(r => r.some(c => String(c).trim() !== ''));
  const colCount = headers.length;

  // Build Markdown table
  let md = '# ' + name + '\n\n';
  md += '| ' + headers.join(' | ') + ' |\n';
  md += '| ' + headers.map(() => '---').join(' | ') + ' |\n';
  dataRows.forEach(r => {
    const cells = [];
    for (let i = 0; i < colCount; i++) {
      let v = r[i] !== undefined ? String(r[i]).trim() : '';
      v = v.replace(/\|/g, '\\\\|').replace(/\n/g, ' ');
      cells.push(v);
    }
    md += '| ' + cells.join(' | ') + ' |\n';
  });

  results.push({ sheet: name, rows: dataRows.length, cols: colCount, status: 'ok' });

  // Write one .md per sheet if multi-sheet, otherwise single file
  if (wb.SheetNames.length > 1) {
    const outFile = baseName + '_' + name.replace(/[^a-zA-Z0-9]/g, '_') + '.md';
    fs.writeFileSync(outFile, md);
    console.log('WROTE: ' + outFile);
  } else {
    const outFile = baseName + '.md';
    fs.writeFileSync(outFile, md);
    console.log('WROTE: ' + outFile);
  }
});

console.log('SUMMARY: ' + JSON.stringify(results));
"
```

### Step 3: Report the result

After conversion:

1. Read the generated `.md` file(s)
2. Show the user a summary for each sheet: name, row count, column count, and whether any sheets were empty or skipped
3. If any cells contained formulas, note that only the computed values were exported
4. Ask if they'd like any adjustments — for example:
   - Filtering out empty rows/columns
   - Splitting sheets into separate files (or combining into one)
   - Adding a table of contents for multi-sheet workbooks
   - Transposing a wide table into a vertical layout

### Input format

The user provides the argument as a file path, e.g.:

- `data/report.xlsx`
- `./budget.xls`
- `/absolute/path/to/financials.xlsx`

If the user provides a glob pattern like `data/*.xlsx`, loop through each file and convert them individually.

### Edge cases to handle

- **Merged cells**: SheetJS unmerges them — the value appears in the top-left cell only. Mention this to the user if the source had merged regions.
- **Multiple sheets**: Create one `.md` file per sheet, named `{basename}_{sheetname}.md`. Inform the user of all files created.
- **Dates**: SheetJS may return date serial numbers. If a column looks like dates, format them as `YYYY-MM-DD`.
- **Very wide tables** (>8 columns): Suggest the user consider whether a Markdown table is the right format, or offer to convert to a structured list instead.
- **Special characters**: Escape pipe characters (`|`) inside cell values so they don't break the Markdown table syntax.
