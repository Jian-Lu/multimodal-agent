<script setup lang="ts">
import { ref } from 'vue'
import imageCompression from 'browser-image-compression'
import { ImagePlus, X } from 'lucide-vue-next'

const props = defineProps<{ modelValue: string[] }>()
const emit = defineEmits<{ 'update:modelValue': [value: string[]] }>()

const previews = ref<{ id: string; url: string }[]>([])

function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result as string)
    reader.onerror = reject
    reader.readAsDataURL(file)
  })
}

async function onFiles(e: Event) {
  const input = e.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  const added: string[] = []
  for (const file of files) {
    try {
      const compressed = await imageCompression(file, { maxSizeMB: 3, useWebWorker: true })
      const dataUrl = await fileToDataUrl(compressed)
      added.push(dataUrl)
      previews.value.push({ id: Math.random().toString(36).slice(2), url: dataUrl })
    } catch {
      /* 忽略无法处理的图片 */
    }
  }
  if (added.length) emit('update:modelValue', [...props.modelValue, ...added])
  input.value = ''
}

function remove(idx: number) {
  previews.value.splice(idx, 1)
  const next = [...props.modelValue]
  next.splice(idx, 1)
  emit('update:modelValue', next)
}
</script>

<template>
  <div>
    <div v-if="previews.length" class="mb-2 flex flex-wrap gap-2">
      <div v-for="(p, i) in previews" :key="p.id" class="group relative">
        <img :src="p.url" class="h-16 w-16 rounded-md object-cover" />
        <button
          type="button"
          class="absolute -right-1 -top-1 rounded-full bg-destructive p-0.5 text-destructive-foreground opacity-0 transition-opacity group-hover:opacity-100"
          title="移除"
          @click="remove(i)"
        >
          <X class="h-3 w-3" />
        </button>
      </div>
    </div>
    <label
      class="inline-flex cursor-pointer items-center gap-1 rounded-md p-1.5 text-muted-foreground hover:bg-accent hover:text-accent-foreground"
      title="上传图片(自动压缩至 3MB)"
    >
      <ImagePlus class="h-5 w-5" />
      <input type="file" accept="image/*" multiple class="hidden" @change="onFiles" />
    </label>
  </div>
</template>
