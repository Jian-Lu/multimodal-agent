import { defineStore } from 'pinia'
import { ref } from 'vue'

import { streamChat } from '@/api/chat'
import { fetchSessionMessages, fetchSessions, removeSession } from '@/api/sessions'
import { USER_KEY } from '@/api/client'
import { genId } from '@/lib/utils'
import type { ChatMessage, MessageDto, Session, SessionDto, User } from '@/types'

function currentUserId(): string {
  try {
    const u = JSON.parse(localStorage.getItem(USER_KEY) ?? 'null') as User | null
    return u?.id ?? 'anonymous'
  } catch {
    return 'anonymous'
  }
}

// 按 user_id 分桶, 切换账号后会话互不可见
function sessionsKey() {
  return `agent_harness_sessions_${currentUserId()}`
}

function loadSessions(): Session[] {
  try {
    return JSON.parse(localStorage.getItem(sessionsKey()) ?? '[]') as Session[]
  } catch {
    return []
  }
}

function saveSessions(sessions: Session[]) {
  localStorage.setItem(sessionsKey(), JSON.stringify(sessions))
}

function toSession(dto: SessionDto): Session {
  return { id: dto.id, title: dto.title, mode: dto.mode, updatedAt: Date.parse(dto.updated_at) }
}

function toMessage(dto: MessageDto): ChatMessage | null {
  if (dto.role === 'system') return null // 系统提示不展示
  return {
    id: dto.id,
    role: dto.role as 'user' | 'assistant',
    content: dto.content,
    createdAt: Date.parse(dto.created_at),
  }
}

export const useChatStore = defineStore('chat', () => {
  const sessions = ref<Session[]>(loadSessions())
  const currentSessionId = ref<string>('')
  const messages = ref<ChatMessage[]>([])
  const mode = ref<'chat' | 'document'>('chat')
  const streaming = ref(false)
  const loadingMessages = ref(false)
  const lastInput = ref<{ text: string; images: string[] } | null>(null)

  function newSession() {
    const id = genId()
    const s: Session = { id, title: '新对话', mode: mode.value, updatedAt: Date.now() }
    sessions.value.unshift(s)
    saveSessions(sessions.value)
    currentSessionId.value = id
    messages.value = []
  }

  async function selectSession(id: string) {
    if (id === currentSessionId.value && messages.value.length) {
      currentSessionId.value = id
      return
    }
    currentSessionId.value = id
    messages.value = []
    loadingMessages.value = true
    try {
      const list = await fetchSessionMessages(id)
      messages.value = list.map(toMessage).filter((m): m is ChatMessage => m !== null)
    } catch {
      /* axios 拦截器已 toast */
    } finally {
      loadingMessages.value = false
    }
  }

  async function deleteSession(id: string) {
    try {
      await removeSession(id)
    } catch {
      /* 服务端删除失败时仍移除本地(拦截器已 toast) */
    }
    sessions.value = sessions.value.filter((s) => s.id !== id)
    saveSessions(sessions.value)
    if (currentSessionId.value === id) {
      currentSessionId.value = ''
      messages.value = []
    }
  }

  /** 以服务端会话为准刷新列表; 失败时保留本地兜底。 */
  async function refreshSessions() {
    try {
      const list = await fetchSessions()
      sessions.value = list.map(toSession)
      saveSessions(sessions.value)
      if (!currentSessionId.value && sessions.value.length) {
        // 自动恢复最近一次会话
        currentSessionId.value = sessions.value[0].id
        await selectSession(currentSessionId.value)
      }
    } catch {
      /* 未登录/网络异常: 保留 localStorage */
    }
  }

  async function send(text: string, images: string[] = []) {
    if (!text.trim() || streaming.value) return
    if (!currentSessionId.value) newSession()

    lastInput.value = { text, images }

    messages.value.push({
      id: genId(),
      role: 'user',
      content: text,
      images,
      createdAt: Date.now(),
    })
    const assistantIdx = messages.value.length
    messages.value.push({
      id: genId(),
      role: 'assistant',
      content: '',
      createdAt: Date.now(),
    })

    streaming.value = true
    try {
      await streamChat(
        { message: text, mode: mode.value, images, session_id: currentSessionId.value },
        {
          onToken: (delta) => {
            const m = messages.value[assistantIdx]
            if (m) m.content += delta
          },
          onError: (msg) => {
            const m = messages.value[assistantIdx]
            if (m) {
              m.error = true
              if (!m.content) m.content = msg
            }
          },
        },
      )

      const s = sessions.value.find((x) => x.id === currentSessionId.value)
      if (s && s.title === '新对话') {
        s.title = text.slice(0, 20)
        s.updatedAt = Date.now()
        saveSessions(sessions.value)
      }
    } catch {
      // 网络中断: 标记可重试
      const m = messages.value[assistantIdx]
      if (m) {
        m.error = true
        if (!m.content) m.content = '连接中断，请点击重试'
      }
    } finally {
      streaming.value = false
    }
  }

  async function retryLast() {
    if (!lastInput.value || streaming.value) return
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === 'assistant' && last.error) {
      messages.value.pop()
    }
    await send(lastInput.value.text, lastInput.value.images)
  }

  void refreshSessions()

  return {
    sessions,
    currentSessionId,
    messages,
    mode,
    streaming,
    loadingMessages,
    lastInput,
    newSession,
    selectSession,
    deleteSession,
    send,
    retryLast,
    refreshSessions,
  }
})
