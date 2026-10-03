<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import Input from '@/components/ui/Input.vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()

const isRegister = ref(false)
const email = ref('')
const username = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

async function submit() {
  error.value = ''
  loading.value = true
  try {
    if (isRegister.value) {
      await auth.register(email.value, username.value, password.value)
      isRegister.value = false
      password.value = ''
    } else {
      await auth.login(email.value, password.value)
      router.push('/')
    }
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="flex min-h-screen items-center justify-center bg-muted/40 p-4">
    <Card class="w-full max-w-sm p-6">
      <h1 class="text-2xl font-bold">Agent-Harness</h1>
      <p class="mb-6 mt-1 text-sm text-muted-foreground">多模态智能体平台</p>

      <form class="space-y-4" @submit.prevent="submit">
        <Input v-model="email" type="email" placeholder="邮箱" required />
        <Input v-if="isRegister" v-model="username" placeholder="用户名" required />
        <Input v-model="password" type="password" placeholder="密码" required />
        <p v-if="error" class="text-sm text-destructive">{{ error }}</p>
        <Button type="submit" class="w-full" :disabled="loading">
          {{ loading ? '请稍候…' : isRegister ? '注册' : '登录' }}
        </Button>
      </form>

      <p class="mt-4 text-center text-sm text-muted-foreground">
        {{ isRegister ? '已有账号？' : '没有账号？' }}
        <button
          type="button"
          class="text-primary hover:underline"
          @click="isRegister = !isRegister"
        >
          {{ isRegister ? '去登录' : '去注册' }}
        </button>
      </p>
    </Card>
  </div>
</template>
