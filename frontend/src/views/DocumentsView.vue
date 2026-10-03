<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowLeft, Trash2, Upload } from 'lucide-vue-next'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import { useDocumentStore } from '@/stores/document'

const store = useDocumentStore()
const router = useRouter()

const fileInput = ref<HTMLInputElement>()
const uploading = ref(false)

onMounted(() => store.list())

async function onFile(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  uploading.value = true
  try {
    await store.upload(file)
  } catch (err) {
    // eslint-disable-next-line no-alert
    alert((err as Error).message)
  } finally {
    uploading.value = false
    input.value = ''
  }
}

function fmtDate(iso: string) {
  return new Date(iso).toLocaleString('zh-CN')
}
</script>

<template>
  <div class="min-h-screen bg-muted/40 p-6">
    <div class="mx-auto max-w-3xl">
      <div class="mb-6 flex items-center gap-3">
        <Button variant="ghost" size="icon" title="返回工作区" @click="router.push('/')">
          <ArrowLeft class="h-4 w-4" />
        </Button>
        <h1 class="text-xl font-bold">文档管理</h1>
        <Button class="ml-auto" :disabled="uploading" @click="fileInput?.click()">
          <Upload class="h-4 w-4" />
          {{ uploading ? '上传中…' : '上传文档' }}
        </Button>
        <input
          ref="fileInput"
          type="file"
          accept=".pdf,.docx,.txt"
          class="hidden"
          @change="onFile"
        />
      </div>

      <Card v-if="!store.documents.length" class="p-12 text-center text-muted-foreground">
        <p>暂无文档，点击「上传文档」添加 PDF / DOCX / TXT</p>
      </Card>

      <div v-else class="space-y-2">
        <Card
          v-for="d in store.documents"
          :key="d.id"
          class="flex items-center gap-3 p-4"
        >
          <div class="flex-1">
            <p class="font-medium">{{ d.filename }}</p>
            <p class="text-xs text-muted-foreground">
              {{ d.file_type.toUpperCase() }} · {{ d.chunk_count }} 块 · {{ fmtDate(d.created_at) }}
            </p>
          </div>
          <Button variant="ghost" size="icon" title="删除" @click="store.remove(d.id)">
            <Trash2 class="h-4 w-4 text-destructive" />
          </Button>
        </Card>
      </div>
    </div>
  </div>
</template>
