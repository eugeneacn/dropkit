const fs = require('fs');
const path = require('path');
const pdfjsLib = require('pdfjs-dist/legacy/build/pdf.js');

const filePath = process.argv[2];
if (!filePath) { console.error('Usage: node extract.js <file.pdf>'); process.exit(1); }

async function extract(filePath) {
  const data = new Uint8Array(fs.readFileSync(filePath));
  const doc = await pdfjsLib.getDocument({ data, useSystemFonts: true }).promise;
  const numPages = doc.numPages;
  const pages = [];

  for (let p = 1; p <= numPages; p++) {
    const page = await doc.getPage(p);
    const content = await page.getTextContent();
    const viewport = page.getViewport({ scale: 1.0 });

    const items = content.items.map(item => ({
      text: item.str,
      x: Math.round(item.transform[4] * 100) / 100,
      y: Math.round((viewport.height - item.transform[5]) * 100) / 100,
      fontSize: Math.round(item.transform[0] * 100) / 100,
      fontName: item.fontName || '',
      width: Math.round(item.width * 100) / 100,
      height: Math.round(item.height * 100) / 100
    }));

    items.sort((a, b) => a.y - b.y || a.x - b.x);

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
        if (item.text.trim().length > 0) {
          currentLine.fontSize = Math.max(currentLine.fontSize, item.fontSize);
        }
      }
    }

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
        text,
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

  const allFontSizes = pages.flatMap(p => p.lines.map(l => l.fontSize)).filter(s => s > 0);
  const fontFreq = {};
  allFontSizes.forEach(s => { fontFreq[s] = (fontFreq[s] || 0) + 1; });
  const bodyFontSize = parseFloat(Object.entries(fontFreq).sort((a, b) => b[1] - a[1])[0]?.[0] || 12);

  const output = {
    file: path.basename(filePath),
    totalPages: numPages,
    bodyFontSize,
    fontSizeDistribution: fontFreq,
    pages
  };

  const jsonOut = filePath.replace(/\.pdf$/i, '') + '.extracted.json';
  fs.writeFileSync(jsonOut, JSON.stringify(output, null, 2));
  console.log('EXTRACTED: ' + jsonOut);
  console.log('PAGES: ' + numPages);
  console.log('BODY_FONT_SIZE: ' + bodyFontSize);
  console.log('FONT_SIZES: ' + JSON.stringify(fontFreq));
}

extract(filePath).catch(e => { console.error('ERROR:', e.message); process.exit(1); });
