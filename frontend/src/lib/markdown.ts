import hljs from 'highlight.js'
import MarkdownIt from 'markdown-it'

const md = new MarkdownIt({
  html: false,
  linkify: true,
})

// 自定义 fence 渲染: mermaid 块输出占位 div, 其余交给 highlight.js
md.renderer.rules.fence = (tokens, idx) => {
  const token = tokens[idx]
  const lang = (token.info ?? '').trim().toLowerCase()
  const code = token.content

  if (lang === 'mermaid') {
    return `<div class="mermaid">${md.utils.escapeHtml(code)}</div>`
  }

  if (lang && hljs.getLanguage(lang)) {
    try {
      const highlighted = hljs.highlight(code, { language: lang, ignoreIllegals: true }).value
      return `<pre class="hljs"><code class="language-${lang}">${highlighted}</code></pre>`
    } catch {
      /* fallthrough */
    }
  }
  return `<pre class="hljs"><code>${md.utils.escapeHtml(code)}</code></pre>`
}

export function renderMarkdown(text: string): string {
  return md.render(text)
}
