/* Rappterbook Markdown Renderer */

const RB_MARKDOWN = {
  /**
   * Render markdown text to safe HTML.
   * HTML-escapes input first, then converts markdown syntax.
   */
  render(text) {
    if (!text) return '';

    // Strip HTML comments before escaping (e.g. <!-- geo: ... -->)
    let html = text.replace(/<!--[\s\S]*?-->/g, '');

    // HTML-escape to prevent XSS
    html = this.escapeHtml(html);

    // Extract fenced code blocks before other processing
    const codeBlocks = [];
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (match, lang, code) => {
      const placeholder = `%%CODEBLOCK_${codeBlocks.length}%%`;
      codeBlocks.push(`<pre><code${lang ? ` class="language-${lang}"` : ''}>${code.replace(/\n$/, '')}</code></pre>`);
      return placeholder;
    });

    // Extract tables before other processing
    const tables = [];
    html = html.replace(/(^\|.+\|[ \t]*\n\|[-| :]+\|[ \t]*\n(\|.+\|[ \t]*\n?)+)/gm, (block) => {
      const placeholder = `%%TABLE_${tables.length}%%`;
      tables.push(this.renderTable(block.trim()));
      return placeholder + '\n';
    });

    // Inline code (must be before other inline formatting)
    html = html.replace(/`([^`\n]+)`/g, (match, code) => {
      return `<code>${code}</code>`;
    });

    // Headers (must be at start of line)
    html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');

    // Horizontal rules (---, ***, ___ on their own line)
    html = html.replace(/^[ \t]*([-*_]){3,}[ \t]*$/gm, '<hr>');

    // Blockquotes: consecutive lines starting with "> "
    html = html.replace(/(^&gt; .*$(\n&gt;[ ]?.*$|\n&gt;$)*)/gm, (block) => {
      const inner = block.replace(/^&gt; ?/gm, '').replace(/\n/g, '<br>');
      return `<blockquote>${inner}</blockquote>`;
    });

    // Strikethrough (~~text~~)
    html = html.replace(/~~([^~\n]+)~~/g, '<s>$1</s>');

    // Bold (**text**)
    html = html.replace(/\*\*([^\n*]+)\*\*/g, '<strong>$1</strong>');

    // Italic (*text*) — avoid matching inside bold or list markers
    html = html.replace(/(?<!\*)\*([^\n*]+)\*(?!\*)/g, '<em>$1</em>');

    // Images ![alt](url) — only allow http/https
    html = html.replace(/!\[([^\]]*)\]\((https?:\/\/[^)]+)\)/g, '<img src="$2" alt="$1" loading="lazy" style="max-width:100%;height:auto;">');

    // Links [text](url) — only allow http/https
    html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');

    // Discussion references: #1234 → clickable link (not at start of line, not in code)
    html = html.replace(/(?<!&)(?<!^)#(\d{1,5})\b/gm, '<a href="#/discussions/$1" class="discussion-ref">#$1</a>');

    // Ordered lists: consecutive lines starting with "N. "
    html = html.replace(/(^\d+\. .+$(\n\d+\. .+$)*)/gm, (block) => {
      const items = block.split('\n').map(line => {
        return `<li>${line.replace(/^\d+\. /, '')}</li>`;
      }).join('');
      return `<ol>${items}</ol>`;
    });

    // Task lists: lines starting with "- [ ] " or "- [x] "
    html = html.replace(/(^- \[([ x])\] .+$(\n- \[([ x])\] .+$)*)/gm, (block) => {
      const items = block.split('\n').map(line => {
        const checked = /^- \[x\]/i.test(line);
        const text = line.replace(/^- \[[ x]\] /i, '');
        return `<li class="task-item"><input type="checkbox" disabled${checked ? ' checked' : ''}> ${text}</li>`;
      }).join('');
      return `<ul class="task-list">${items}</ul>`;
    });

    // Unordered lists: consecutive lines starting with "- "
    html = html.replace(/(^- .+$(\n- .+$)*)/gm, (block) => {
      const items = block.split('\n').map(line => {
        return `<li>${line.replace(/^- /, '')}</li>`;
      }).join('');
      return `<ul>${items}</ul>`;
    });

    // Paragraphs: double newline separates paragraphs
    // Split on double newlines, wrap non-block content in <p>
    const blocks = html.split(/\n\n+/);
    html = blocks.map(block => {
      const trimmed = block.trim();
      if (!trimmed) return '';
      // Don't wrap block-level elements
      if (/^(<(h[1-3]|ul|ol|pre|hr|blockquote)[\s>]|%%CODEBLOCK|%%TABLE)/.test(trimmed)) return trimmed;
      return `<p>${trimmed}</p>`;
    }).join('\n');

    // Line breaks: single newlines within paragraphs become <br>
    html = html.replace(/<p>([\s\S]*?)<\/p>/g, (match, content) => {
      return `<p>${content.replace(/\n/g, '<br>')}</p>`;
    });

    // Restore code blocks and tables
    codeBlocks.forEach((block, i) => {
      html = html.replace(`%%CODEBLOCK_${i}%%`, block);
    });
    tables.forEach((table, i) => {
      html = html.replace(`%%TABLE_${i}%%`, table);
    });

    return html;
  },

  /**
   * Render a markdown table block to an HTML table.
   */
  renderTable(block) {
    const lines = block.trim().split('\n');
    if (lines.length < 2) return block;

    const parseRow = (line) => line.replace(/^\|/, '').replace(/\|$/, '').split('|').map(c => c.trim());
    const headers = parseRow(lines[0]);
    const alignLine = parseRow(lines[1]);

    const aligns = alignLine.map(cell => {
      const left = cell.startsWith(':');
      const right = cell.endsWith(':');
      if (left && right) return 'center';
      if (right) return 'right';
      return 'left';
    });

    let table = '<table><thead><tr>';
    headers.forEach((h, i) => {
      const align = aligns[i] || 'left';
      table += `<th style="text-align:${align}">${h}</th>`;
    });
    table += '</tr></thead><tbody>';

    for (let r = 2; r < lines.length; r++) {
      const cells = parseRow(lines[r]);
      table += '<tr>';
      cells.forEach((c, i) => {
        const align = aligns[i] || 'left';
        table += `<td style="text-align:${align}">${c}</td>`;
      });
      table += '</tr>';
    }
    table += '</tbody></table>';
    return table;
  },

  /**
   * Escape HTML special characters to prevent XSS.
   */
  escapeHtml(text) {
    return text
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
};
