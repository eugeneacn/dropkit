# Outlook MSG to Markdown Converter

Convert Outlook `.msg` email files to clean, structured Markdown preserving headers, body, and attachment metadata.

## Instructions

You are a document conversion agent. When the user provides a `.msg` file path via `$ARGUMENTS`, convert it to Markdown that captures the full email structure.

### Step 1: Verify the environment

Check if the required npm package is available. If not, install it:

```bash
npm list @nicecode/msg-reader || npm install @nicecode/msg-reader
```

If `@nicecode/msg-reader` fails to install, fall back to `msgreader`:

```bash
npm list msgreader || npm install msgreader
```

### Step 2: Extract the email data

Run this Node.js script, replacing `$ARGUMENTS` with the input file path:

```bash
node -e "
const fs = require('fs');
const path = require('path');

let MsgReader;
try {
  MsgReader = require('@nicecode/msg-reader').default || require('@nicecode/msg-reader');
} catch {
  MsgReader = require('msgreader').default || require('msgreader');
}

const filePath = '$ARGUMENTS';
const buf = fs.readFileSync(filePath);
const reader = new MsgReader(buf);
const msg = reader.getFileData();

// ── Helper: clean HTML body to Markdown ──

function htmlToMd(html) {
  if (!html) return '';
  let md = html;

  // Remove style/script blocks
  md = md.replace(/<style[^>]*>[\s\S]*?<\/style>/gi, '');
  md = md.replace(/<script[^>]*>[\s\S]*?<\/script>/gi, '');

  // Headers
  for (let i = 6; i >= 1; i--) {
    md = md.replace(new RegExp('<h' + i + '[^>]*>([\\\\s\\\\S]*?)<\\/h' + i + '>', 'gi'),
      (_, c) => '#'.repeat(i) + ' ' + c.replace(/<[^>]+>/g, '').trim() + '\\n\\n');
  }

  // Bold & italic
  md = md.replace(/<(strong|b)>([\s\S]*?)<\/\1>/gi, '**$2**');
  md = md.replace(/<(em|i)>([\s\S]*?)<\/\1>/gi, '*$2*');

  // Links
  md = md.replace(/<a\s+[^>]*href=\"([^\"]*)\"[^>]*>([\s\S]*?)<\/a>/gi, '[$2]($1)');

  // Unordered lists
  md = md.replace(/<ul[^>]*>([\s\S]*?)<\/ul>/gi, (_, inner) =>
    inner.replace(/<li[^>]*>([\s\S]*?)<\/li>/gi, (_, li) => '- ' + li.replace(/<[^>]+>/g, '').trim() + '\\n') + '\\n');

  // Ordered lists
  let counter = 0;
  md = md.replace(/<ol[^>]*>([\s\S]*?)<\/ol>/gi, (_, inner) => {
    counter = 0;
    return inner.replace(/<li[^>]*>([\s\S]*?)<\/li>/gi,
      (_, li) => (++counter) + '. ' + li.replace(/<[^>]+>/g, '').trim() + '\\n') + '\\n';
  });

  // Tables
  md = md.replace(/<table[^>]*>([\s\S]*?)<\/table>/gi, (_, tbl) => {
    const rows = [];
    let m, rm = /<tr[^>]*>([\s\S]*?)<\/tr>/gi;
    while (m = rm.exec(tbl)) {
      const cells = [];
      let cm, cr = /<(td|th)[^>]*>([\s\S]*?)<\/\1>/gi;
      while (cm = cr.exec(m[1])) cells.push(cm[2].replace(/<[^>]+>/g, '').trim());
      rows.push(cells);
    }
    if (!rows.length) return '';
    const hdr = '| ' + rows[0].join(' | ') + ' |';
    const sep = '| ' + rows[0].map(() => '---').join(' | ') + ' |';
    const body = rows.slice(1).map(r => '| ' + r.join(' | ') + ' |').join('\\n');
    return '\\n' + hdr + '\\n' + sep + '\\n' + body + '\\n\\n';
  });

  // Line breaks and paragraphs
  md = md.replace(/<br\s*\/?>/gi, '\\n');
  md = md.replace(/<p[^>]*>([\s\S]*?)<\/p>/gi, '$1\\n\\n');
  md = md.replace(/<div[^>]*>([\s\S]*?)<\/div>/gi, '$1\\n');

  // Strip remaining tags
  md = md.replace(/<[^>]+>/g, '');

  // Decode entities
  md = md.replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&quot;/g, '\"').replace(/&#39;/g, \"'\").replace(/&nbsp;/g, ' ')
    .replace(/&#\d+;/g, '');

  return md.replace(/\\n{3,}/g, '\\n\\n').trim();
}

// ── Build Markdown output ──

let md = '';

// Email metadata header block
md += '# ' + (msg.subject || 'No Subject') + '\\n\\n';

md += '| Field | Value |\\n';
md += '| --- | --- |\\n';
md += '| **From** | ' + (msg.senderName || '') + (msg.senderEmail ? ' <' + msg.senderEmail + '>' : '') + ' |\\n';

// Recipients
const toRecipients = (msg.recipients || []).filter(r => r.recipType === 'to' || r.recipType === 1 || !r.recipType);
const ccRecipients = (msg.recipients || []).filter(r => r.recipType === 'cc' || r.recipType === 2);
const bccRecipients = (msg.recipients || []).filter(r => r.recipType === 'bcc' || r.recipType === 3);

function formatRecipients(list) {
  return list.map(r => (r.name || '') + (r.email ? ' <' + r.email + '>' : '')).join('; ') || '—';
}

md += '| **To** | ' + formatRecipients(toRecipients.length ? toRecipients : msg.recipients || []) + ' |\\n';
if (ccRecipients.length) md += '| **CC** | ' + formatRecipients(ccRecipients) + ' |\\n';
if (bccRecipients.length) md += '| **BCC** | ' + formatRecipients(bccRecipients) + ' |\\n';

// Date
const dateStr = msg.messageDeliveryTime || msg.clientSubmitTime || msg.creationTime || '';
if (dateStr) md += '| **Date** | ' + dateStr + ' |\\n';

// Importance
if (msg.importance && msg.importance !== 'normal' && msg.importance !== 1) {
  md += '| **Importance** | ' + msg.importance + ' |\\n';
}

md += '\\n---\\n\\n';

// ── Email body ──

let body = '';
if (msg.htmlBody || msg.html) {
  body = htmlToMd(msg.htmlBody || msg.html);
} else if (msg.body) {
  body = msg.body;
}

if (body) {
  md += body + '\\n\\n';
} else {
  md += '*No message body found.*\\n\\n';
}

// ── Attachments ──

const attachments = msg.attachments || [];
if (attachments.length > 0) {
  md += '---\\n\\n';
  md += '## Attachments\\n\\n';
  md += '| # | Filename | Size | Type |\\n';
  md += '| --- | --- | --- | --- |\\n';
  attachments.forEach((att, i) => {
    const name = att.fileName || att.name || 'unnamed';
    const ext = path.extname(name).toLowerCase();
    const size = att.contentLength || att.dataSize || att.content?.length || '—';
    const sizeStr = typeof size === 'number'
      ? (size > 1048576 ? (size / 1048576).toFixed(1) + ' MB'
        : size > 1024 ? (size / 1024).toFixed(1) + ' KB'
        : size + ' B')
      : String(size);
    const isInline = att.contentId || att.isInline ? ' (inline)' : '';
    md += '| ' + (i + 1) + ' | ' + name + isInline + ' | ' + sizeStr + ' | ' + (ext || '—') + ' |\\n';
  });
  md += '\\n';
}

// ── Embedded MSG (forwarded/attached emails) ──

const embeddedMsgs = attachments.filter(a =>
  (a.fileName || a.name || '').toLowerCase().endsWith('.msg') || a.attachmentType === 'msg'
);
if (embeddedMsgs.length > 0) {
  md += '> **Note:** This email contains ' + embeddedMsgs.length + ' embedded message(s). ';
  md += 'Run this skill on the extracted .msg file(s) to convert them as well.\\n\\n';
}

// ── Write output ──

const outFile = path.basename(filePath).replace(/\.msg$/i, '') + '.md';
fs.writeFileSync(outFile, md);

// Summary for the agent
const summary = {
  subject: msg.subject || 'No Subject',
  from: msg.senderName || msg.senderEmail || 'Unknown',
  to: formatRecipients(toRecipients.length ? toRecipients : msg.recipients || []),
  date: dateStr || 'Unknown',
  hasHtmlBody: !!(msg.htmlBody || msg.html),
  hasPlainBody: !!msg.body,
  bodyLength: body.length,
  attachmentCount: attachments.length,
  embeddedMsgCount: embeddedMsgs.length,
  ccCount: ccRecipients.length,
  bccCount: bccRecipients.length
};

console.log('WROTE: ' + outFile);
console.log('SUMMARY: ' + JSON.stringify(summary));
"
```

### Step 3: Extract attachments (if requested)

If the user asks to extract attachments, run a follow-up script:

```bash
node -e "
const fs = require('fs');
const path = require('path');

let MsgReader;
try {
  MsgReader = require('@nicecode/msg-reader').default || require('@nicecode/msg-reader');
} catch {
  MsgReader = require('msgreader').default || require('msgreader');
}

const filePath = '$ARGUMENTS';
const buf = fs.readFileSync(filePath);
const reader = new MsgReader(buf);
const msg = reader.getFileData();
const attachments = msg.attachments || [];

if (attachments.length === 0) {
  console.log('No attachments to extract.');
  process.exit(0);
}

const outDir = path.basename(filePath, '.msg') + '_attachments';
if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });

attachments.forEach((att, i) => {
  const name = att.fileName || att.name || ('attachment_' + (i + 1));
  const content = reader.getAttachment(i);
  if (content && content.content) {
    fs.writeFileSync(path.join(outDir, name), Buffer.from(content.content));
    console.log('EXTRACTED: ' + path.join(outDir, name));
  } else {
    console.log('SKIPPED (no content): ' + name);
  }
});
"
```

### Step 4: Report the result

After conversion:

1. Show the user a summary: subject, sender, date, recipient count, body type (HTML vs plain text), and attachment count
2. If the email had an HTML body, mention that it was converted from HTML and some complex formatting (e.g., embedded CSS styles, conditional Outlook markup) may have been simplified
3. If there are attachments, list them and ask if the user wants them extracted to a folder
4. If there are embedded `.msg` files (forwarded emails), offer to recursively convert those too
5. Ask if they'd like adjustments:
   - Including or stripping email signature blocks
   - Extracting inline images
   - Converting the email into a more structured format (e.g., meeting notes template)
   - Batch-converting a folder of `.msg` files

### Input format

The user provides the argument as a file path, e.g.:

- `emails/important-update.msg`
- `./meeting-invite.msg`
- `/absolute/path/to/forwarded-chain.msg`

If the user provides a glob pattern like `emails/*.msg`, loop through each file and convert them individually.

### Edge cases to handle

- **RTF body**: Some older Outlook messages store the body only in RTF format (no HTML or plain text). If both `htmlBody` and `body` are empty, note that the email likely uses RTF-only encoding and suggest the user open it in Outlook to re-save as HTML, or install an RTF parser.
- **Winmail.dat / TNEF**: Some `.msg` files contain TNEF-encoded content. If the reader fails to parse, suggest the `node-tnef` package as an alternative.
- **Inline images**: Images referenced via `cid:` URLs in the HTML body are stored as attachments with a `contentId`. Flag these separately from regular attachments and note that the Markdown will show broken image references unless attachments are extracted.
- **Email chains / conversation threads**: The body may contain quoted replies. Look for patterns like `From:` headers mid-body, `>` prefixed lines, or `-----Original Message-----` dividers. Preserve these as nested blockquotes in the Markdown.
- **Calendar invites (.ics)**: If an attachment is a `.ics` file, mention it's a calendar invite and offer to parse the event details (date, time, location, attendees) into a structured Markdown section.
- **Character encoding**: `.msg` files may use various encodings. If the output contains garbled text, try reading string properties with different encodings (UTF-8, UTF-16LE, Windows-1252).
- **Distribution lists**: The To/CC fields may reference Outlook distribution lists rather than individual addresses. These may appear as display names without email addresses — preserve them as-is.
- **Sensitivity / classification labels**: Some corporate emails have sensitivity labels (Confidential, Internal, etc.). If present in the message properties, include them in the metadata table.
- **Read receipts / delivery receipts**: These are special message types. If the message class indicates a receipt rather than a normal email, format the output accordingly with the receipt metadata.
