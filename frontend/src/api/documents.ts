import type { DocItem } from '@/types'

import client from './client'

export async function listDocuments(): Promise<DocItem[]> {
  const res = await client.get('/api/v1/documents')
  return res.data as DocItem[]
}

export async function uploadDocument(file: File): Promise<DocItem> {
  const form = new FormData()
  form.append('file', file)
  const res = await client.post('/api/v1/documents/upload', form)
  return res.data as DocItem
}

export async function removeDocument(id: string): Promise<void> {
  await client.delete(`/api/v1/documents/${id}`)
}
