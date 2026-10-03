import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { login as apiLogin, register as apiRegister } from '@/api/auth'
import { TOKEN_KEY, USER_KEY } from '@/api/client'
import type { User } from '@/types'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string>(localStorage.getItem(TOKEN_KEY) ?? '')
  const user = ref<User | null>(
    JSON.parse(localStorage.getItem(USER_KEY) ?? 'null') as User | null,
  )

  const isAuthenticated = computed(() => !!token.value)

  async function login(email: string, password: string) {
    const data = await apiLogin(email, password)
    token.value = data.access_token
    user.value = data.user
    localStorage.setItem(TOKEN_KEY, data.access_token)
    localStorage.setItem(USER_KEY, JSON.stringify(data.user))
  }

  async function register(email: string, username: string, password: string) {
    await apiRegister(email, username, password)
  }

  function logout() {
    token.value = ''
    user.value = null
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
  }

  return { token, user, isAuthenticated, login, register, logout }
})
