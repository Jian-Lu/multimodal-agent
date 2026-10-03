<script setup lang="ts">
import { MessageSquare, Plus, Trash2 } from 'lucide-vue-next'

import Button from '@/components/ui/Button.vue'
import { cn } from '@/lib/utils'
import type { Session } from '@/types'

defineProps<{ sessions: Session[]; currentId: string }>()
const emit = defineEmits<{ create: []; select: [id: string]; remove: [id: string] }>()
</script>

<template>
  <aside class="flex h-full w-64 shrink-0 flex-col border-r border-border bg-card">
    <div class="flex items-center justify-between border-b border-border p-4">
      <span class="font-semibold">会话</span>
      <Button size="icon" variant="ghost" title="新建会话" @click="emit('create')">
        <Plus class="h-4 w-4" />
      </Button>
    </div>
    <div class="flex-1 overflow-y-auto p-2">
      <div
        v-for="s in sessions"
        :key="s.id"
        :class="
          cn(
            'group flex cursor-pointer items-center gap-2 rounded-md px-3 py-2 text-sm hover:bg-accent',
            s.id === currentId && 'bg-accent',
          )
        "
        @click="emit('select', s.id)"
      >
        <MessageSquare class="h-4 w-4 shrink-0 text-muted-foreground" />
        <span class="flex-1 truncate">{{ s.title }}</span>
        <button
          type="button"
          class="hidden text-muted-foreground hover:text-destructive group-hover:block"
          title="删除会话"
          @click.stop="emit('remove', s.id)"
        >
          <Trash2 class="h-4 w-4" />
        </button>
      </div>
      <p v-if="!sessions.length" class="p-4 text-center text-sm text-muted-foreground">
        暂无会话，点击 + 新建
      </p>
    </div>
  </aside>
</template>
