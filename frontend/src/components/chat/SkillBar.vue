<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { Sparkles } from 'lucide-vue-next'

import { useSkillStore } from '@/stores/skill'

const skillStore = useSkillStore()
const emit = defineEmits<{ select: [trigger: string] }>()

const enabled = computed(() => skillStore.skills.filter((s) => s.enabled))

onMounted(() => skillStore.list())
</script>

<template>
  <div v-if="enabled.length" class="flex flex-wrap items-center gap-1.5 px-4 pt-2">
    <Sparkles class="h-3.5 w-3.5 text-muted-foreground" />
    <button
      v-for="s in enabled"
      :key="s.name"
      type="button"
      class="rounded-full border border-border px-2.5 py-0.5 text-xs text-muted-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
      :title="s.description"
      @click="emit('select', s.triggers[0] || s.name)"
    >
      {{ s.name }}
    </button>
  </div>
</template>
