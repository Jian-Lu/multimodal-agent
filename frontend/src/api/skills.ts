import type { Skill } from '@/types'

import client from './client'

export async function listSkills(): Promise<Skill[]> {
  const res = await client.get('/api/v1/skills')
  return res.data as Skill[]
}

export async function createSkill(skill: Skill): Promise<Skill> {
  const res = await client.post('/api/v1/skills', skill)
  return res.data as Skill
}

export async function updateSkill(name: string, skill: Skill): Promise<Skill> {
  const res = await client.put(`/api/v1/skills/${name}`, skill)
  return res.data as Skill
}

export async function removeSkill(name: string): Promise<void> {
  await client.delete(`/api/v1/skills/${name}`)
}
