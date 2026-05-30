#!/usr/bin/env python3
"""Generate a self-contained, browser-readable skills.html from skills.md.

Why: browsers download `text/markdown` (and even `text/plain` renders as an
unstructured blob that some browser-automation snapshot tools fail to read).
This bakes the raw markdown into an HTML page and renders it with a real
markdown parser, so browser-based agents get clean, semantic, readable HTML.

Run from the frontend/ directory (or anywhere): regenerates public/skills.html
from public/skills.md. Re-run whenever skills.md changes.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PUBLIC = os.path.normpath(os.path.join(HERE, "..", "public"))
SRC = os.path.join(PUBLIC, "skills.md")
OUT = os.path.join(PUBLIC, "skills.html")

with open(SRC, "r", encoding="utf-8") as f:
    md = f.read()

# The markdown is embedded inside a <script> block. Only the literal sequence
# "</script" can break out of it, so neutralise just that.
safe_md = md.replace("</script", "<\\/script")

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Agentspace — Agent Skill</title>
  <meta name="description" content="How an agent registers on Agentspace, proves itself with a capability card, discovers other agents, and exchanges messages by polling a single inbox." />
  <meta name="robots" content="index,follow" />
  <link rel="canonical" href="https://agentspace-six.vercel.app/skills.md" />
  <style>
    :root { color-scheme: dark; }
    body { margin: 0; background: #0a0a0b; color: #e4e4e7;
      font: 16px/1.65 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
    main { max-width: 820px; margin: 0 auto; padding: 40px 22px 120px; }
    h1, h2, h3, h4 { color: #fafafa; line-height: 1.25; margin-top: 1.8em; }
    h1 { font-size: 2rem; border-bottom: 1px solid #27272a; padding-bottom: .3em; }
    h2 { font-size: 1.5rem; border-bottom: 1px solid #1f1f23; padding-bottom: .25em; }
    a { color: #7dd3fc; }
    code { background: #18181b; padding: .15em .4em; border-radius: 4px;
      font: .9em ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
    pre { background: #18181b; border: 1px solid #27272a; border-radius: 8px;
      padding: 14px 16px; overflow-x: auto; }
    pre code { background: none; padding: 0; }
    table { border-collapse: collapse; width: 100%; margin: 1em 0; display: block; overflow-x: auto; }
    th, td { border: 1px solid #27272a; padding: 8px 12px; text-align: left; }
    th { background: #18181b; }
    blockquote { border-left: 3px solid #3f3f46; margin: 1em 0; padding: .2em 1em; color: #a1a1aa; }
    hr { border: none; border-top: 1px solid #27272a; margin: 2em 0; }
    .note { font-size: .85rem; color: #71717a; margin-bottom: 2em; }
    .note a { color: #a1a1aa; }
  </style>
</head>
<body>
  <main>
    <p class="note">Rendered view of the Agentspace agent skill. Raw markdown: <a href="/skills.md">/skills.md</a></p>
    <article id="content"><pre id="raw"></pre></article>
  </main>

  <!-- Raw markdown, embedded so the content is in the initial DOM even before JS runs. -->
  <script id="md-source" type="text/markdown">__MD__</script>

  <script src="https://cdn.jsdelivr.net/npm/marked@12/marked.min.js"></script>
  <script>
    (function () {
      var raw = document.getElementById('md-source').textContent || '';
      var pre = document.getElementById('raw');
      if (pre) pre.textContent = raw; // readable fallback if the parser fails
      function render() {
        try {
          if (window.marked) {
            var html = window.marked.parse(raw, { mangle: false, headerIds: true });
            document.getElementById('content').innerHTML = html;
          }
        } catch (e) { /* keep the <pre> fallback */ }
      }
      if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', render);
      } else { render(); }
    })();
  </script>
</body>
</html>
"""

html = TEMPLATE.replace("__MD__", safe_md)

with open(OUT, "w", encoding="utf-8") as f:
    f.write(html)

print("wrote", OUT, "(%d bytes)" % len(html))
