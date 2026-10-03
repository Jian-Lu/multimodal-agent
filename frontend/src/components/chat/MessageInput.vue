<script setup lang="ts">
import { ref } from 'vue'
import { Send } from 'lucide-vue-next'

import ImageUpload from '@/components/chat/ImageUpload.vue'
import Button from '@/components/ui/Button.vue'
import Textarea from '@/components/ui/Textarea.vue'

const props = defineProps<{ mode: 'chat' | 'document'; streaming: boolean }>()
const emit = defineEmits<{ send: [text: string, images: string[]] }>()

const text = ref('')
const images = ref<string[]>([])

function submit() {
  if (!text.value.trim() || props.streaming) return
  emit('send', text.value.trim(), images.value)
  text.value = ''
  images.value = []
}

function insertText(t: string) {
  text.value += t
}

defineExpose({ insertText })
</script>

<template>
  <div class="border-t border-border bg-background p-4">
    <ImageUpload v-model="images" />
    <div class="flex items-end gap-2">
      <Textarea
        v-model="text"
        :rows="1"
        class="min-h-[44px] resize-none"
        :placeholder="mode === 'document' ? '输入文档主题，生成 Markdown 文档…' : '输入消息，Enter 发送，Shift+Enter 换行'"
        @keydown.enter.exact.prevent="submit"
      />
      <Button size="icon" :disabled="streaming || !text.trim()" title="发送" @click="submit">
        <Send class="h-4 w-4" />
      </Button>
    </div>
  </div>
</template>
