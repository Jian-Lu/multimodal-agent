import { TOKEN_KEY } from './client'

export interface StreamHandlers {
  onMeta?: (meta: { session_id: string; mode: string; user: string }) => void
  onToken?: (delta: string) => void
  onError?: (message: string) => void
  onDone?: () => void
}

export interface StreamPayload {
  message: string
  mode: 'chat' | 'document'
  images?: string[]
  session_id?: string
}

/** 连接中断异常(区别于后端优雅返回的 error 事件)。 */
export class StreamConnectionError extends Error {
  constructor() {
    super('连接中断')
    this.name = 'StreamConnectionError'
  }
}

/**
 * 以 POST + fetch 流式读取后端 SSE(text/event-stream)。
 * 后端为 POST 接口, 原生 EventSource 不支持, 故手动解析。
 * 区分「正常 [DONE] 结束」与「网络中断/未收尾」: 后者抛 StreamConnectionError。
 */
export async function streamChat(
  payload: StreamPayload,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const token = localStorage.getItem(TOKEN_KEY) ?? ''

  let res: Response
  try {
    res = await fetch('/api/v1/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(payload),
      signal,
    })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e
    throw new StreamConnectionError()
  }

  if (!res.ok || !res.body) {
    let msg = `HTTP ${res.status}`
    try {
      const j = await res.json()
      msg = j.detail ?? j.message ?? msg
    } catch {
      /* ignore */
    }
    handlers.onError?.(msg)
    handlers.onDone?.()
    return
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let completed = false

  const handleFrame = (frame: string) => {
    let event = 'message'
    let data = ''
    for (const line of frame.split('\n')) {
      const t = line.trim()
      if (t.startsWith('event:')) event = t.slice(6).trim()
      else if (t.startsWith('data:')) data += t.slice(5).trim()
    }
    if (data === '[DONE]') {
      completed = true
      return
    }
    if (!data) return
    try {
      const parsed = JSON.parse(data)
      if (event === 'meta') handlers.onMeta?.(parsed)
      else if (event === 'error') handlers.onError?.(parsed.message ?? '未知错误')
      else if (event === 'message') handlers.onToken?.(parsed.delta ?? '')
    } catch {
      /* ignore malformed frame */
    }
  }

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let idx: number
      while ((idx = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, idx)
        buffer = buffer.slice(idx + 2)
        if (frame.trim()) handleFrame(frame)
      }
    }
    if (buffer.trim()) handleFrame(buffer)
  } catch (e) {
    if ((e as Error).name === 'AbortError') {
      handlers.onDone?.()
      throw e
    }
    handlers.onDone?.()
    throw new StreamConnectionError()
  }

  handlers.onDone?.()
  if (!completed) throw new StreamConnectionError()
}
