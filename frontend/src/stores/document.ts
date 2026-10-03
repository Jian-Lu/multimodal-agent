import { defineStore } from 'pinia'
import { ref } from 'vue'

import { listDocuments, removeDocument, uploadDocument } from '@/api/documents'
import type { DocItem } from '@/types'

export const useDocumentStore = defineStore('document', () => {
  const documents = ref<DocItem[]>([])
  const loading = ref(false)

  async function list() {
    loading.value = true
    try {
      documents.value = await listDocuments()
    } finally {
      loading.value = false
    }
  }

  async function upload(file: File) {
    await uploadDocument(file)
    await list()
  }

  async function remove(id: string) {
    await removeDocument(id)
    await list()
  }

  return { documents, loading, list, upload, remove }
})
