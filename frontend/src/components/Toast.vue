<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { CheckCircle2, XCircle } from 'lucide-vue-next'

import { useToastStore } from '@/stores/toast'

const toast = useToastStore()
const { list } = storeToRefs(toast)
</script>

<template>
  <div class="pointer-events-none fixed right-4 top-4 z-[100] flex flex-col gap-2">
    <div
      v-for="t in list"
      :key="t.id"
      class="pointer-events-auto flex items-center gap-2 rounded-md border border-border bg-card px-4 py-2 text-sm shadow-md"
    >
      <CheckCircle2 v-if="t.type === 'success'" class="h-4 w-4 shrink-0 text-primary" />
      <XCircle v-else class="h-4 w-4 shrink-0 text-destructive" />
      <span class="break-words">{{ t.message }}</span>
    </div>
  </div>
</template>
