const XLSX = require('xlsx');
const fs = require('fs');
const path = require('path');

const filePath = process.argv[2];
if (!filePath) { console.error('Usage: node convert.js <file.xlsx>'); process.exit(1); }

const wb = XLSX.readFile(filePath);
const baseName = path.basename(filePath).replace(/\.(xlsx?|csv)$/i, '');
const results = [];

wb.SheetNames.forEach(name => {
  const rows = XLSX.utils.sheet_to_json(wb.Sheets[name], { header: 1, defval: '' });
  if (!rows.length) { results.push({ sheet: name, status: 'empty' }); return; }

  let hdrIdx = rows.findIndex(r => r.some(c => String(c).trim() !== ''));
  if (hdrIdx === -1) { results.push({ sheet: name, status: 'empty' }); return; }

  const headers = rows[hdrIdx].map(c => String(c).trim() || '—');
  const dataRows = rows.slice(hdrIdx + 1).filter(r => r.some(c => String(c).trim() !== ''));
  const colCount = headers.length;

  let md = '# ' + name + '\n\n';
  md += '| ' + headers.join(' | ') + ' |\n';
  md += '| ' + headers.map(() => '---').join(' | ') + ' |\n';
  dataRows.forEach(r => {
    const cells = [];
    for (let i = 0; i < colCount; i++) {
      let v = r[i] !== undefined ? String(r[i]).trim() : '';
      v = v.replace(/\|/g, '\\|').replace(/\n/g, ' ');
      cells.push(v);
    }
    md += '| ' + cells.join(' | ') + ' |\n';
  });

  results.push({ sheet: name, rows: dataRows.length, cols: colCount, status: 'ok' });

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
