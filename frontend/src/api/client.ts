import axios from 'axios'

import { useToastStore } from '@/stores/toast'
import type { ApiResponse } from '@/types'

export const TOKEN_KEY = 'agent_harness_token'
export const USER_KEY = 'agent_harness_user'

const client = axios.create({ baseURL: '' })

client.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

client.interceptors.response.use(
  (response) => {
    const body = response.data as ApiResponse | undefined
    // 统一解包后端 { code, message, data }
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code !== 0) {
        return Promise.reject(new Error(body.message || '请求失败'))
      }
      response.data = body.data
    }
    return response
  },
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
      return Promise.reject(new Error('未登录或凭证过期'))
    }
    const msg =
      error.response?.data?.detail ??
      error.response?.data?.message ??
      error.message ??
      '网络错误'
    try {
      useToastStore().push('error', msg)
    } catch {
      /* pinia 未就绪时忽略 */
    }
    return Promise.reject(new Error(msg))
  },
)

export default client
