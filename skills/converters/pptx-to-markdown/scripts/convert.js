const JSZip = require('jszip');
const { XMLParser } = require('fast-xml-parser');
const fs = require('fs');
const path = require('path');

const filePath = process.argv[2];
if (!filePath) { console.error('Usage: node convert.js <file.pptx>'); process.exit(1); }

const parser = new XMLParser({ ignoreAttributes: false, attributeNamePrefix: '@_' });

function extractText(node) {
  if (!node) return '';
  if (typeof node === 'string') return node;
  if (Array.isArray(node)) return node.map(extractText).join('');
  if (node['#text'] !== undefined) return String(node['#text']);
  if (node['a:t'] !== undefined) {
    const t = node['a:t'];
    if (typeof t === 'string') return t;
    if (typeof t === 'object' && t['#text'] !== undefined) return String(t['#text']);
    return String(t);
  }
  if (node['a:br'] !== undefined) return '\n';
  let text = '';
  for (const key of Object.keys(node)) {
    if (key.startsWith('@_')) continue;
    text += extractText(node[key]);
  }
  return text;
}

function extractParagraphs(txBody) {
  if (!txBody || !txBody['a:p']) return [];
  const paras = Array.isArray(txBody['a:p']) ? txBody['a:p'] : [txBody['a:p']];
  return paras.map(p => {
    const text = extractText(p).trim();
    const lvl = p['a:pPr'] && p['a:pPr']['@_lvl'] ? parseInt(p['a:pPr']['@_lvl'], 10) : 0;
    const isBullet = p['a:pPr'] && p['a:pPr']['a:buChar'] !== undefined
      || p['a:pPr'] && p['a:pPr']['a:buAutoNum'] !== undefined
      || p['a:pPr'] && p['a:pPr']['a:buNone'] === undefined && lvl > 0;
    return { text, lvl, isBullet };
  }).filter(p => p.text.length > 0);
}

function extractShapes(spTree) {
  if (!spTree) return [];
  const shapes = [];
  const spList = spTree['p:sp'] ? (Array.isArray(spTree['p:sp']) ? spTree['p:sp'] : [spTree['p:sp']]) : [];
  for (const sp of spList) {
    const txBody = sp['p:txBody'];
    if (!txBody) continue;
    let phType = '';
    if (sp['p:nvSpPr'] && sp['p:nvSpPr']['p:nvPr'] && sp['p:nvSpPr']['p:nvPr']['p:ph']) {
      phType = sp['p:nvSpPr']['p:nvPr']['p:ph']['@_type'] || '';
    }
    const paragraphs = extractParagraphs(txBody);
    if (paragraphs.length > 0) shapes.push({ phType, paragraphs });
  }
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

function tableToMd(tableData) {
  if (!tableData.length) return '';
  const colCount = Math.max(...tableData.map(r => r.length));
  const hdr = tableData[0].map(c => c.replace(/\|/g, '\\|'));
  while (hdr.length < colCount) hdr.push('');
  let md = '| ' + hdr.join(' | ') + ' |\n';
  md += '| ' + hdr.map(() => '---').join(' | ') + ' |\n';
  for (const row of tableData.slice(1)) {
    const cells = row.map(c => c.replace(/\|/g, '\\|'));
    while (cells.length < colCount) cells.push('');
    md += '| ' + cells.join(' | ') + ' |\n';
  }
  return md;
}

async function convert() {
  const buf = fs.readFileSync(filePath);
  const zip = await JSZip.loadAsync(buf);

  const slideFiles = Object.keys(zip.files)
    .filter(f => /^ppt\/slides\/slide\d+\.xml$/.test(f))
    .sort((a, b) => {
      const na = parseInt(a.match(/slide(\d+)/)[1]);
      const nb = parseInt(b.match(/slide(\d+)/)[1]);
      return na - nb;
    });

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

    const picList = spTree?.['p:pic'];
    if (picList) {
      const pics = Array.isArray(picList) ? picList : [picList];
      summary.images += pics.length;
    }

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

  const outFile = path.basename(filePath).replace(/\.pptx?$/i, '') + '.md';
  fs.writeFileSync(outFile, markdown.trim() + '\n');
  console.log('WROTE: ' + outFile);
  console.log('SUMMARY: ' + JSON.stringify(summary));
}

convert().catch(e => { console.error('ERROR:', e.message); process.exit(1); });
