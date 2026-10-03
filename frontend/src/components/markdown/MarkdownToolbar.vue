<script setup lang="ts">
import { ref } from 'vue'
import { Check, Copy, Download, Maximize2 } from 'lucide-vue-next'

const props = defineProps<{ content: string; filename?: string }>()
const emit = defineEmits<{ fullscreen: [] }>()

const copied = ref(false)

async function copy() {
  try {
    await navigator.clipboard.writeText(props.content)
    copied.value = true
    setTimeout(() => (copied.value = false), 1500)
  } catch {
    /* ignore */
  }
}

function download() {
  const blob = new Blob([props.content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = props.filename || 'document.md'
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <div class="flex items-center gap-1">
    <button
      type="button"
      class="rounded p-1.5 text-muted-foreground hover:bg-accent hover:text-accent-foreground"
      title="复制 Markdown"
      @click="copy"
    >
      <Check v-if="copied" class="h-4 w-4" />
      <Copy v-else class="h-4 w-4" />
    </button>
    <button
      type="button"
      class="rounded p-1.5 text-muted-foreground hover:bg-accent hover:text-accent-foreground"
      title="下载 .md"
      @click="download"
    >
      <Download class="h-4 w-4" />
    </button>
    <button
      type="button"
      class="rounded p-1.5 text-muted-foreground hover:bg-accent hover:text-accent-foreground"
      title="全屏预览"
      @click="emit('fullscreen')"
    >
      <Maximize2 class="h-4 w-4" />
    </button>
  </div>
</template>
