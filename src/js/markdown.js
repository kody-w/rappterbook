/* Rappterbook Markdown Renderer */

const RB_MARKDOWN = {
  /**
   * Render markdown text to safe HTML.
   * HTML-escapes input first, then converts markdown syntax.
   */
  render(text) {
    if (!text) return '';

    // HTML-escape to prevent XSS
    let html = this.escapeHtml(text);

    // Extract fenced code blocks before other processing
    const codeBlocks = [];
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (match, lang, code) => {
      const placeholder = `%%CODEBLOCK_${codeBlocks.length}%%`;
      codeBlocks.push(`<pre><code${lang ? ` class="language-${lang}"` : ''}>${code.replace(/\n$/, '')}</code></pre>`);
      return placeholder;
    });

    // Inline code (must be before other inline formatting)
    html = html.replace(/`([^`\n]+)`/g, (match, code) => {
      return `<code>${code}</code>`;
    });

    // Headers (must be at start of line)
    html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');

    // Bold (**text**)
    html = html.replace(/\*\*([^\n*]+)\*\*/g, '<strong>$1</strong>');

    // Italic (*text*) — avoid matching inside bold or list markers
    html = html.replace(/(?<!\*)\*([^\n*]+)\*(?!\*)/g, '<em>$1</em>');

    // Links [text](url) — only allow http/https
    html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');

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
      if (/^<(h[1-3]|ul|pre|%%CODEBLOCK)/.test(trimmed)) return trimmed;
      return `<p>${trimmed}</p>`;
    }).join('\n');

    // Line breaks: single newlines within paragraphs become <br>
    html = html.replace(/<p>([\s\S]*?)<\/p>/g, (match, content) => {
      return `<p>${content.replace(/\n/g, '<br>')}</p>`;
    });

    // Restore code blocks
    codeBlocks.forEach((block, i) => {
      html = html.replace(`%%CODEBLOCK_${i}%%`, block);
    });

    return html;
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
