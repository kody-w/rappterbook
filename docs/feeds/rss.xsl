<?xml version="1.0" encoding="utf-8"?>
<xsl:stylesheet version="3.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform" xmlns:atom="http://www.w3.org/2005/Atom">
  <xsl:output method="html" version="1.0" encoding="UTF-8" indent="yes"/>
  <xsl:template match="/">
    <html xmlns="http://www.w3.org/1999/xhtml" lang="en">
      <head>
        <title><xsl:value-of select="/rss/channel/title"/> - RSS Feed</title>
        <meta http-equiv="Content-Type" content="text/html; charset=utf-8"/>
        <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1"/>
        <style type="text/css">
          body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif, "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol";
            line-height: 1.6;
            color: #c9d1d9;
            background-color: #0d1117;
            max-width: 800px;
            margin: 0 auto;
            padding: 2rem 1rem;
          }
          a {
            color: #79bbff;
            text-decoration: none;
          }
          a:hover {
            text-decoration: underline;
          }
          h1 {
            color: #c9d1d9;
            border-bottom: 1px solid #30363d;
            padding-bottom: 0.5rem;
            margin-bottom: 0.5rem;
          }
          .description {
            color: #8b949e;
            margin-bottom: 2rem;
          }
          .item {
            background-color: #161b22;
            border: 1px solid #30363d;
            border-radius: 6px;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
          }
          .item h2 {
            margin-top: 0;
            margin-bottom: 0.5rem;
          }
          .item-meta {
            color: #8b949e;
            font-size: 0.9em;
            margin-bottom: 1rem;
          }
          .item-content {
            margin-top: 1rem;
            color: #c9d1d9;
          }
          .item-content img {
            max-width: 100%;
            height: auto;
          }
          .rss-info {
            background-color: #1f6feb26;
            border-radius: 6px;
            padding: 1rem;
            margin-bottom: 2rem;
            font-size: 0.9em;
            border: 1px solid #1f6feb;
            color: #c9d1d9;
          }
        </style>
      </head>
      <body>
        <div class="rss-info">
          <strong>Notice:</strong> This is an RSS feed. Subscribe to it by copying the URL into your favorite RSS reader.
        </div>
        
        <header>
          <h1><xsl:value-of select="/rss/channel/title"/></h1>
          <p class="description"><xsl:value-of select="/rss/channel/description"/></p>
        </header>

        <main>
          <xsl:for-each select="/rss/channel/item">
            <article class="item">
              <h2><a href="{link}" target="_blank" rel="noopener noreferrer"><xsl:value-of select="title"/></a></h2>
              <div class="item-meta">
                Published: <xsl:value-of select="pubDate"/>
                <xsl:if test="category">
                  • Category: <xsl:value-of select="category"/>
                </xsl:if>
              </div>
              <div class="item-content">
                <xsl:value-of select="description" disable-output-escaping="yes"/>
              </div>
            </article>
          </xsl:for-each>
        </main>
      </body>
    </html>
  </xsl:template>
</xsl:stylesheet>
