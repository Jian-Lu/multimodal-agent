import { defineStore } from 'pinia'
import { ref } from 'vue'

import { createSkill, listSkills, removeSkill, updateSkill } from '@/api/skills'
import type { Skill } from '@/types'

export const useSkillStore = defineStore('skill', () => {
  const skills = ref<Skill[]>([])
  const loading = ref(false)

  async function list() {
    loading.value = true
    try {
      skills.value = await listSkills()
    } finally {
      loading.value = false
    }
  }

  async function create(skill: Skill) {
    await createSkill(skill)
    await list()
  }

  async function toggle(name: string, enabled: boolean) {
    const skill = skills.value.find((s) => s.name === name)
    if (!skill) return
    await updateSkill(name, { ...skill, enabled })
    await list()
  }

  async function remove(name: string) {
    await removeSkill(name)
    await list()
  }

  return { skills, loading, list, create, toggle, remove }
})
