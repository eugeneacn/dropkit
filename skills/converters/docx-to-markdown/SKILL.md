---
name: docx-to-markdown
description: Convert Word (.docx) files to clean, structured Markdown preserving headings, lists, tables, and formatting. Use when the user wants to convert, export, or process a .docx or Word document into Markdown format.
metadata:
  version: "1.0"
---

# Word to Markdown Converter

Convert a Word (.docx) file to clean Markdown.

## Instructions

You are a document conversion agent. When the user provides a `.docx` file path, convert it to Markdown by following these steps:

### Step 1: Verify the environment

Check if the `mammoth` npm package is available. If not, install it:

```bash
npm list mammoth || npm install mammoth
```

### Step 2: Convert the file

Run the conversion script, replacing `$ARGUMENTS` with the input file path the user provided:

```bash
node scripts/convert.js "$ARGUMENTS"
```

### Step 3: Report the result

After conversion:

1. Read the generated `.md` file
2. Show the user a summary of what was converted (heading count, whether tables/lists were found, any warnings)
3. Ask if they'd like any adjustments to the output

### Input format

The user provides the argument as a file path, e.g.:

- `docs/report.docx`
- `./meeting-notes.docx`
- `/absolute/path/to/file.docx`

If the user provides a glob pattern like `docs/*.docx`, loop through each file and convert them individually.
