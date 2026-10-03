<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import mermaid from 'mermaid'

import { renderMarkdown } from '@/lib/markdown'

import 'highlight.js/styles/github.css'

const props = defineProps<{ content: string }>()

const container = ref<HTMLElement>()

async function render() {
  if (!container.value) return
  container.value.innerHTML = renderMarkdown(props.content)
  const blocks = container.value.querySelectorAll<HTMLElement>('.mermaid')
  if (blocks.length > 0) {
    try {
      mermaid.initialize({ startOnLoad: false, theme: 'default' })
      await mermaid.run({ nodes: blocks })
    } catch {
      /* mermaid 渲染失败时保留原代码块 */
    }
  }
}

onMounted(render)
watch(
  () => props.content,
  () => nextTick(render),
)
</script>

<template>
  <div ref="container" class="markdown-body" />
</template>
