<script setup lang="ts">
import { ref } from 'vue'

import MarkdownRenderer from '@/components/markdown/MarkdownRenderer.vue'
import MarkdownToolbar from '@/components/markdown/MarkdownToolbar.vue'
import { cn } from '@/lib/utils'
import type { ChatMessage } from '@/types'

defineProps<{ message: ChatMessage }>()
const emit = defineEmits<{ retry: [] }>()

const fullscreen = ref(false)
</script>

<template>
  <div :class="cn('animate-fade-in flex', message.role === 'user' ? 'justify-end' : 'justify-start')">
    <div
      :class="
        cn(
          'max-w-[80%] rounded-lg px-4 py-3',
          message.role === 'user'
            ? 'bg-primary text-primary-foreground'
            : 'border border-border bg-card',
        )
      "
    >
      <div v-if="message.images?.length" class="mb-2 flex flex-wrap gap-2">
        <img
          v-for="(img, i) in message.images"
          :key="i"
          :src="img"
          class="h-20 w-20 rounded-md object-cover"
        />
      </div>

      <p v-if="message.role === 'user'" class="whitespace-pre-wrap break-words text-sm">
        {{ message.content }}
      </p>

      <template v-else>
        <template v-if="message.error">
          <p class="text-sm text-destructive">{{ message.content }}</p>
          <button
            type="button"
            class="mt-2 text-sm text-primary hover:underline"
            @click="emit('retry')"
          >
            重试
          </button>
        </template>
        <template v-else>
          <MarkdownRenderer v-if="message.content" :content="message.content" />
          <div v-if="message.content" class="mt-2 flex justify-end">
            <MarkdownToolbar :content="message.content" @fullscreen="fullscreen = true" />
          </div>
        </template>
      </template>
    </div>
  </div>

  <div
    v-if="fullscreen"
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-8"
    @click.self="fullscreen = false"
  >
    <div class="flex h-full w-full max-w-4xl flex-col overflow-hidden rounded-lg bg-card">
      <div class="flex justify-end border-b border-border p-3">
        <MarkdownToolbar :content="message.content" @fullscreen="fullscreen = false" />
      </div>
      <div class="flex-1 overflow-y-auto p-6">
        <MarkdownRenderer :content="message.content" />
      </div>
    </div>
  </div>
</template>
