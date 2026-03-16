---
name: xlsx-to-markdown
description: Convert Excel (.xls/.xlsx) spreadsheet files to Markdown tables, one table per sheet. Use when the user wants to convert, export, or read an Excel spreadsheet or .xlsx/.xls file into Markdown format.
metadata:
  version: "1.0"
---

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

Run the conversion script, replacing `$ARGUMENTS` with the input file path:

```bash
node scripts/convert.js "$ARGUMENTS"
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
