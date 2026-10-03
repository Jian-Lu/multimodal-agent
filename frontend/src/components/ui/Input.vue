<script setup lang="ts">
import { useVModel } from '@vueuse/core'

import { cn } from '@/lib/utils'

const props = withDefaults(
  defineProps<{
    modelValue?: string
    type?: string
    placeholder?: string
    class?: string
  }>(),
  { modelValue: '', type: 'text' },
)

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const model = useVModel(props, 'modelValue', emit)
</script>

<template>
  <input
    v-model="model"
    :type="type"
    :placeholder="placeholder"
    :class="
      cn(
        'flex h-9 w-full rounded-md border border-border bg-background px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary disabled:cursor-not-allowed disabled:opacity-50',
        props.class,
      )
    "
  />
</template>
