const mammoth = require('mammoth');
const fs = require('fs');

const filePath = process.argv[2];
if (!filePath) { console.error('Usage: node convert.js <file.docx>'); process.exit(1); }

function htmlToMd(html) {
  let md = html;
  for (let i = 6; i >= 1; i--) {
    md = md.replace(new RegExp('<h'+i+'[^>]*>([\\s\\S]*?)</h'+i+'>', 'gi'), (_, c) => '#'.repeat(i) + ' ' + c.replace(/<[^>]+>/g,'').trim() + '\n\n');
  }
  md = md.replace(/<(strong|b)>([\s\S]*?)<\/\1>/gi, '**$2**');
  md = md.replace(/<(em|i)>([\s\S]*?)<\/\1>/gi, '*$2*');
  md = md.replace(/<a\s+href="([^"]*)"[^>]*>([\s\S]*?)<\/a>/gi, '[$2]($1)');
  md = md.replace(/<ul[^>]*>([\s\S]*?)<\/ul>/gi, (_, inner) =>
    inner.replace(/<li[^>]*>([\s\S]*?)<\/li>/gi, (_, li) => '- ' + li.replace(/<[^>]+>/g,'').trim() + '\n') + '\n');
  let c = 0;
  md = md.replace(/<ol[^>]*>([\s\S]*?)<\/ol>/gi, (_, inner) => {
    c = 0;
    return inner.replace(/<li[^>]*>([\s\S]*?)<\/li>/gi, (_, li) => (++c) + '. ' + li.replace(/<[^>]+>/g,'').trim() + '\n') + '\n';
  });
  md = md.replace(/<blockquote[^>]*>([\s\S]*?)<\/blockquote>/gi, (_, q) =>
    q.replace(/<[^>]+>/g,'').trim().split('\n').map(l => '> ' + l.trim()).join('\n') + '\n\n');
  md = md.replace(/<table[^>]*>([\s\S]*?)<\/table>/gi, (_, tbl) => {
    const rows = [];
    let m, rm = /<tr[^>]*>([\s\S]*?)<\/tr>/gi;
    while (m = rm.exec(tbl)) {
      const cells = []; let cm, cr = /<(td|th)[^>]*>([\s\S]*?)<\/\1>/gi;
      while (cm = cr.exec(m[1])) cells.push(cm[2].replace(/<[^>]+>/g,'').trim());
      rows.push(cells);
    }
    if (!rows.length) return '';
    return '\n| ' + rows[0].join(' | ') + ' |\n| ' + rows[0].map(() => '---').join(' | ') + ' |\n' +
      rows.slice(1).map(r => '| ' + r.join(' | ') + ' |').join('\n') + '\n\n';
  });
  md = md.replace(/<pre[^>]*><code[^>]*>([\s\S]*?)<\/code><\/pre>/gi, '\n```\n$1\n```\n');
  md = md.replace(/<code>([\s\S]*?)<\/code>/gi, '`$1`');
  md = md.replace(/<hr\s*\/?>/gi, '\n---\n\n');
  md = md.replace(/<br\s*\/?>/gi, '\n');
  md = md.replace(/<p[^>]*>([\s\S]*?)<\/p>/gi, '$1\n\n');
  md = md.replace(/<[^>]+>/g, '');
  md = md.replace(/&amp;/g,'&').replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&nbsp;/g,' ');
  return md.replace(/\n{3,}/g, '\n\n').trim();
}

mammoth.convertToHtml({ path: filePath })
  .then(r => {
    const md = htmlToMd(r.value);
    const out = filePath.replace(/\.docx$/i, '.md');
    fs.writeFileSync(out, md);
    console.log('CONVERTED: ' + out);
    if (r.messages.length) console.log('WARNINGS:', JSON.stringify(r.messages));
  })
  .catch(e => { console.error('ERROR:', e.message); process.exit(1); });
