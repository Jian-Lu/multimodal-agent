<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowLeft, Plus, Trash2 } from 'lucide-vue-next'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import Input from '@/components/ui/Input.vue'
import Textarea from '@/components/ui/Textarea.vue'
import { useSkillStore } from '@/stores/skill'
import type { Skill } from '@/types'

const store = useSkillStore()
const router = useRouter()

const showForm = ref(false)
const name = ref('')
const description = ref('')
const triggersText = ref('')
const targetAgent = ref('rag')
const promptTemplate = ref('')

onMounted(() => store.list())

function resetForm() {
  showForm.value = false
  name.value = ''
  description.value = ''
  triggersText.value = ''
  targetAgent.value = 'rag'
  promptTemplate.value = ''
}

async function submit() {
  if (!name.value.trim()) return
  const skill: Skill = {
    name: name.value.trim(),
    description: description.value,
    triggers: triggersText.value
      .split(/[,，]/)
      .map((t) => t.trim())
      .filter(Boolean),
    tools: [],
    system_prompt_template: promptTemplate.value,
    config_schema: {},
    target_agent: targetAgent.value || 'rag',
    enabled: true,
    builtin: false,
  }
  await store.create(skill)
  resetForm()
}
</script>

<template>
  <div class="min-h-screen bg-muted/40 p-6">
    <div class="mx-auto max-w-3xl">
      <div class="mb-6 flex items-center gap-3">
        <Button variant="ghost" size="icon" title="返回" @click="router.push('/')">
          <ArrowLeft class="h-4 w-4" />
        </Button>
        <h1 class="text-xl font-bold">技能管理</h1>
        <Button class="ml-auto" @click="showForm = !showForm">
          <Plus class="h-4 w-4" />
          新增技能
        </Button>
      </div>

      <Card v-if="showForm" class="mb-4 space-y-3 p-4">
        <Input v-model="name" placeholder="技能名(英文唯一)" />
        <Input v-model="description" placeholder="描述" />
        <Input v-model="triggersText" placeholder="触发词(逗号分隔)" />
        <Input v-model="targetAgent" placeholder="目标 agent (rag/coder/...)" />
        <Textarea v-model="promptTemplate" :rows="4" placeholder="System Prompt 模板(Jinja2)" />
        <div class="flex justify-end gap-2">
          <Button variant="ghost" @click="resetForm">取消</Button>
          <Button @click="submit">保存</Button>
        </div>
      </Card>

      <Card v-if="!store.skills.length" class="p-12 text-center text-muted-foreground">
        <p>暂无技能</p>
      </Card>

      <div v-else class="space-y-2">
        <Card v-for="s in store.skills" :key="s.name" class="flex items-center gap-3 p-4">
          <div class="flex-1">
            <p class="font-medium">
              {{ s.name }}
              <span class="ml-1 rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                {{ s.builtin ? '内置' : '自定义' }}
              </span>
            </p>
            <p class="text-xs text-muted-foreground">{{ s.description }}</p>
          </div>
          <button
            type="button"
            :class="[
              'h-5 w-9 shrink-0 rounded-full p-0.5 transition-colors',
              s.enabled ? 'bg-primary' : 'bg-muted',
            ]"
            :title="s.enabled ? '禁用' : '启用'"
            @click="store.toggle(s.name, !s.enabled)"
          >
            <span
              :class="[
                'block h-4 w-4 rounded-full bg-white transition-transform',
                s.enabled ? 'translate-x-4' : '',
              ]"
            />
          </button>
          <Button
            v-if="!s.builtin"
            variant="ghost"
            size="icon"
            title="删除"
            @click="store.remove(s.name)"
          >
            <Trash2 class="h-4 w-4 text-destructive" />
          </Button>
        </Card>
      </div>
    </div>
  </div>
</template>
