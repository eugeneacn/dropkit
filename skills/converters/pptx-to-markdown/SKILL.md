---
name: pptx-to-markdown
description: Convert PowerPoint (.pptx) files to structured Markdown with slide headings, bullet points, tables, and speaker notes. Use when the user wants to convert, export, or process a .pptx or PowerPoint presentation into Markdown.
metadata:
  version: "1.0"
---

# PowerPoint to Markdown Converter

Convert a PowerPoint (.pptx) file to clean, structured Markdown.

## Instructions

You are a document conversion agent. When the user provides a `.pptx` file path via `$ARGUMENTS`, convert it to Markdown preserving slide structure, text, tables, speaker notes, and metadata.

### Step 1: Verify the environment

Check if the required npm packages are available. If not, install them:

```bash
npm list jszip || npm install jszip
npm list fast-xml-parser || npm install fast-xml-parser
```

### Step 2: Convert the file

Run the conversion script, replacing `$ARGUMENTS` with the input file path:

```bash
node scripts/convert.js "$ARGUMENTS"
```

### Step 3: Report the result

After conversion:

1. Read the generated `.md` file
2. Show the user a summary: total slides, how many had tables, how many had speaker notes, and how many images were detected (note: images are referenced but not extracted by default)
3. Ask if they'd like any adjustments, such as:
   - Extracting embedded images to a folder and linking them in the Markdown
   - Removing speaker notes
   - Flattening the slide separators for a continuous document
   - Converting to a different structure (e.g., one file per slide)

### Input format

The user provides the argument as a file path, e.g.:

- `slides/quarterly-review.pptx`
- `./presentation.pptx`

If the user provides a glob pattern like `slides/*.pptx`, loop through each file and convert them individually.

### Edge cases to handle

- **Images**: The script counts images but does not extract them by default. If the user wants images, extract them from `ppt/media/` in the zip and save to an `images/` directory, updating the Markdown with `![](images/filename.png)` references.
- **SmartArt / Charts**: These are complex embedded objects. Note to the user that SmartArt is extracted as best-effort text and charts are not converted — recommend exporting charts as images from PowerPoint first.
- **Grouped shapes**: Shapes inside `p:grpSp` may be nested. If the initial conversion misses content, recursively traverse group shapes.
- **Master/layout text**: Ignore text inherited from slide masters/layouts (e.g., footer placeholders, slide numbers) unless the user explicitly asks for it.
- **Empty slides**: Include them in the output as a heading with a note that the slide had no text content, so the user can see the full slide count.
