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

Run this Node.js script, replacing `$ARGUMENTS` with the input file path:

```bash
node -e "
const JSZip = require('jszip');
const { XMLParser } = require('fast-xml-parser');
const fs = require('fs');
const path = require('path');

const filePath = '$ARGUMENTS';
const parser = new XMLParser({ ignoreAttributes: false, attributeNamePrefix: '@_' });

// Recursively extract text from parsed XML nodes
function extractText(node) {
  if (!node) return '';
  if (typeof node === 'string') return node;
  if (Array.isArray(node)) return node.map(extractText).join('');

  // Direct text content
  if (node['#text'] !== undefined) return String(node['#text']);

  // a:t = text run in OOXML
  if (node['a:t'] !== undefined) {
    const t = node['a:t'];
    if (typeof t === 'string') return t;
    if (typeof t === 'object' && t['#text'] !== undefined) return String(t['#text']);
    return String(t);
  }

  // a:br = line break
  if (node['a:br'] !== undefined) return '\n';

  let text = '';
  for (const key of Object.keys(node)) {
    if (key.startsWith('@_')) continue;
    text += extractText(node[key]);
  }
  return text;
}

// Extract paragraphs from a text body (a:txBody)
function extractParagraphs(txBody) {
  if (!txBody || !txBody['a:p']) return [];
  const paras = Array.isArray(txBody['a:p']) ? txBody['a:p'] : [txBody['a:p']];
  return paras.map(p => {
    const text = extractText(p).trim();
    // Detect bullet level from pPr
    const lvl = p['a:pPr'] && p['a:pPr']['@_lvl'] ? parseInt(p['a:pPr']['@_lvl'], 10) : 0;
    const isBullet = p['a:pPr'] && p['a:pPr']['a:buChar'] !== undefined
      || p['a:pPr'] && p['a:pPr']['a:buAutoNum'] !== undefined
      || p['a:pPr'] && p['a:pPr']['a:buNone'] === undefined && lvl > 0;
    return { text, lvl, isBullet };
  }).filter(p => p.text.length > 0);
}

// Extract shapes from a slide's spTree
function extractShapes(spTree) {
  if (!spTree) return [];
  const shapes = [];
  const spList = spTree['p:sp'] ? (Array.isArray(spTree['p:sp']) ? spTree['p:sp'] : [spTree['p:sp']]) : [];

  for (const sp of spList) {
    const txBody = sp['p:txBody'];
    if (!txBody) continue;

    // Detect shape type from placeholder
    let phType = '';
    if (sp['p:nvSpPr'] && sp['p:nvSpPr']['p:nvPr'] && sp['p:nvSpPr']['p:nvPr']['p:ph']) {
      phType = sp['p:nvSpPr']['p:nvPr']['p:ph']['@_type'] || '';
    }

    const paragraphs = extractParagraphs(txBody);
    if (paragraphs.length > 0) {
      shapes.push({ phType, paragraphs });
    }
  }

  // Handle tables in graphicFrame
  const gfList = spTree['p:graphicFrame']
    ? (Array.isArray(spTree['p:graphicFrame']) ? spTree['p:graphicFrame'] : [spTree['p:graphicFrame']])
    : [];
  for (const gf of gfList) {
    const tbl = gf?.['a:graphic']?.['a:graphicData']?.['a:tbl'];
    if (!tbl) continue;
    const tblRows = tbl['a:tr'] ? (Array.isArray(tbl['a:tr']) ? tbl['a:tr'] : [tbl['a:tr']]) : [];
    const tableData = tblRows.map(tr => {
      const cells = tr['a:tc'] ? (Array.isArray(tr['a:tc']) ? tr['a:tc'] : [tr['a:tc']]) : [];
      return cells.map(tc => {
        const paras = extractParagraphs(tc['a:txBody']);
        return paras.map(p => p.text).join(' ');
      });
    });
    if (tableData.length > 0) shapes.push({ phType: 'table', tableData });
  }

  return shapes;
}

// Format a table as Markdown
function tableToMd(tableData) {
  if (!tableData.length) return '';
  const colCount = Math.max(...tableData.map(r => r.length));
  const hdr = tableData[0].map(c => c.replace(/\|/g, '\\\\|'));
  while (hdr.length < colCount) hdr.push('');
  let md = '| ' + hdr.join(' | ') + ' |\n';
  md += '| ' + hdr.map(() => '---').join(' | ') + ' |\n';
  for (const row of tableData.slice(1)) {
    const cells = row.map(c => c.replace(/\|/g, '\\\\|'));
    while (cells.length < colCount) cells.push('');
    md += '| ' + cells.join(' | ') + ' |\n';
  }
  return md;
}

async function convert() {
  const buf = fs.readFileSync(filePath);
  const zip = await JSZip.loadAsync(buf);

  // Find all slide XML files and sort numerically
  const slideFiles = Object.keys(zip.files)
    .filter(f => /^ppt\/slides\/slide\d+\.xml$/.test(f))
    .sort((a, b) => {
      const na = parseInt(a.match(/slide(\d+)/)[1]);
      const nb = parseInt(b.match(/slide(\d+)/)[1]);
      return na - nb;
    });

  // Find corresponding notes files
  const noteFiles = Object.keys(zip.files)
    .filter(f => /^ppt\/notesSlides\/notesSlide\d+\.xml$/.test(f));

  let markdown = '';
  const summary = { slides: slideFiles.length, tables: 0, notes: 0, images: 0 };

  for (let i = 0; i < slideFiles.length; i++) {
    const slideXml = await zip.file(slideFiles[i]).async('string');
    const slide = parser.parse(slideXml);
    const spTree = slide['p:sld']?.['p:cSld']?.['p:spTree'];
    const shapes = extractShapes(spTree);

    markdown += '---\n\n';
    markdown += '## Slide ' + (i + 1) + '\n\n';

    let titleWritten = false;

    for (const shape of shapes) {
      if (shape.phType === 'table' && shape.tableData) {
        markdown += tableToMd(shape.tableData) + '\n';
        summary.tables++;
        continue;
      }

      // Title placeholder → use ### heading
      if ((shape.phType === 'title' || shape.phType === 'ctrTitle') && !titleWritten) {
        markdown += '### ' + shape.paragraphs.map(p => p.text).join(' ') + '\n\n';
        titleWritten = true;
        continue;
      }

      for (const p of shape.paragraphs) {
        if (p.isBullet || p.lvl > 0) {
          const indent = '  '.repeat(p.lvl);
          markdown += indent + '- ' + p.text + '\n';
        } else {
          markdown += p.text + '\n\n';
        }
      }
    }

    // Count images (for summary)
    const picList = spTree?.['p:pic'];
    if (picList) {
      const pics = Array.isArray(picList) ? picList : [picList];
      summary.images += pics.length;
    }

    // Speaker notes
    const noteFile = noteFiles.find(f => f.includes('notesSlide' + (i + 1) + '.xml'));
    if (noteFile) {
      const noteXml = await zip.file(noteFile).async('string');
      const note = parser.parse(noteXml);
      const noteTree = note['p:notes']?.['p:cSld']?.['p:spTree'];
      const noteShapes = extractShapes(noteTree);
      const noteTexts = noteShapes
        .filter(s => s.phType === 'body')
        .flatMap(s => s.paragraphs.map(p => p.text))
        .filter(t => t && !t.match(/^\d+$/));

      if (noteTexts.length > 0) {
        markdown += '\n> **Speaker Notes**\n';
        noteTexts.forEach(t => { markdown += '> ' + t + '\n'; });
        markdown += '\n';
        summary.notes++;
      }
    }

    markdown += '\n';
  }

  // Write output
  const outFile = path.basename(filePath).replace(/\.pptx?$/i, '') + '.md';
  fs.writeFileSync(outFile, markdown.trim() + '\n');
  console.log('WROTE: ' + outFile);
  console.log('SUMMARY: ' + JSON.stringify(summary));
}

convert().catch(e => { console.error('ERROR:', e.message); process.exit(1); });
"
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
