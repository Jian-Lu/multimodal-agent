<script setup lang="ts">
import { useVModel } from '@vueuse/core'

import { cn } from '@/lib/utils'

const props = withDefaults(
  defineProps<{
    modelValue?: string
    placeholder?: string
    class?: string
    rows?: number
  }>(),
  { modelValue: '', rows: 3 },
)

const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const model = useVModel(props, 'modelValue', emit)
</script>

<template>
  <textarea
    v-model="model"
    :placeholder="placeholder"
    :rows="rows"
    :class="
      cn(
        'flex w-full rounded-md border border-border bg-background px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary disabled:cursor-not-allowed disabled:opacity-50',
        props.class,
      )
    "
  />
</template>
