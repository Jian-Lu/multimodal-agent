import { defineStore } from 'pinia'
import { ref } from 'vue'

import { genId } from '@/lib/utils'

export interface Toast {
  id: string
  type: 'success' | 'error'
  message: string
}

export const useToastStore = defineStore('toast', () => {
  const list = ref<Toast[]>([])

  function push(type: Toast['type'], message: string) {
    const id = genId()
    list.value.push({ id, type, message })
    setTimeout(() => remove(id), 3000)
  }

  function remove(id: string) {
    list.value = list.value.filter((t) => t.id !== id)
  }

  return { list, push, remove }
})
