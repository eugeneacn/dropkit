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

Run this Node.js script, replacing `$ARGUMENTS` with the input file path the user provided:

```bash
node -e "
const mammoth = require('mammoth');
const fs = require('fs');

function htmlToMd(html) {
  let md = html;
  for (let i = 6; i >= 1; i--) {
    md = md.replace(new RegExp('<h'+i+'[^>]*>([\\\\s\\\\S]*?)</h'+i+'>', 'gi'), (_, c) => '#'.repeat(i) + ' ' + c.replace(/<[^>]+>/g,'').trim() + '\n\n');
  }
  md = md.replace(/<(strong|b)>([\s\S]*?)<\/\1>/gi, '**\$2**');
  md = md.replace(/<(em|i)>([\s\S]*?)<\/\1>/gi, '*\$2*');
  md = md.replace(/<a\s+href=\"([^\"]*)\"[^>]*>([\s\S]*?)<\/a>/gi, '[\$2](\$1)');
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
  md = md.replace(/<pre[^>]*><code[^>]*>([\s\S]*?)<\/code><\/pre>/gi, '\n\`\`\`\n\$1\n\`\`\`\n');
  md = md.replace(/<code>([\s\S]*?)<\/code>/gi, '\`\$1\`');
  md = md.replace(/<hr\s*\/?>/gi, '\n---\n\n');
  md = md.replace(/<br\s*\/?>/gi, '\n');
  md = md.replace(/<p[^>]*>([\s\S]*?)<\/p>/gi, '\$1\n\n');
  md = md.replace(/<[^>]+>/g, '');
  md = md.replace(/&amp;/g,'&').replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&quot;/g,'\"').replace(/&#39;/g,\"'\").replace(/&nbsp;/g,' ');
  return md.replace(/\n{3,}/g, '\n\n').trim();
}

mammoth.convertToHtml({ path: '$ARGUMENTS' })
  .then(r => {
    const md = htmlToMd(r.value);
    const out = '$ARGUMENTS'.replace(/\.docx$/i, '.md');
    fs.writeFileSync(out, md);
    console.log('CONVERTED: ' + out);
    if (r.messages.length) console.log('WARNINGS:', JSON.stringify(r.messages));
  })
  .catch(e => { console.error('ERROR:', e.message); process.exit(1); });
"
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
